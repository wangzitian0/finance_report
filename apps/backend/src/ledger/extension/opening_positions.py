"""Persist and project starting stock under exact ledger authority."""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.audit import (
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceDecisionPolicyRegistry,
    TraceDecisionRef,
    TraceEmitter,
    TraceLineage,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
    current_authoritative_trace_decision_projection,
)
from src.audit.extension.trace_repository import SqlTraceRecordRepository
from src.ledger.base.opening import OpeningPosition
from src.ledger.orm.account import AccountType
from src.ledger.orm.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.ledger.orm.opening_position import OpeningPositionRecord


@dataclass(frozen=True, slots=True)
class OpeningPositionPolicy:
    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef("ledger_opening_position", "initialized", "1")

    @property
    def authority(self) -> TraceAuthorityProfile:
        return TraceAuthorityProfile(
            package="ledger",
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage="product.runtime",
            assertion_owner_digest=hashlib.sha256(b"ledger-opening-position-v1").hexdigest(),
            producer_version="1",
        )

    @property
    def causality(self) -> TraceCausality:
        return TraceCausality.DIRECT

    @property
    def target_class(self) -> TraceTargetClass:
        return TraceTargetClass.FINANCIAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        valid = (
            len(parents) == 1
            and parents[0].result is TraceResult.PASS
            and parents[0].assertion == VersionedTraceRef("ledger_opening_input", "starting-stock", "1")
        )
        return TraceDecisionOutcome(
            TraceResult.AUTHORITATIVE if valid else TraceResult.REJECTED,
            "opening_position_initialized" if valid else "opening_position_invalid",
        )


def position_digest(
    *,
    account_id: UUID,
    effective_date: date,
    amount: Decimal,
    currency: str,
    fx_rate: Decimal | None,
    journal_entry_id: UUID | None,
    source_decision_id: UUID | None,
) -> str:
    payload = {
        "account_id": str(account_id),
        "effective_date": effective_date.isoformat(),
        "amount": str(amount.normalize()),
        "currency": currency,
        "fx_rate": str(fx_rate.normalize()) if fx_rate is not None else None,
        "journal_entry_id": str(journal_entry_id) if journal_entry_id else None,
        "source_decision_id": str(source_decision_id) if source_decision_id else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def record_opening_position(
    db: AsyncSession,
    *,
    user_id: UUID,
    account_id: UUID,
    effective_date: date,
    amount: Decimal,
    currency: str,
    fx_rate: Decimal | None,
    journal_entry_id: UUID | None,
    source_decision_id: UUID | None = None,
) -> OpeningPositionRecord:
    digest = position_digest(
        account_id=account_id,
        effective_date=effective_date,
        amount=amount,
        currency=currency,
        fx_rate=fx_rate,
        journal_entry_id=journal_entry_id,
        source_decision_id=source_decision_id,
    )
    policy = OpeningPositionPolicy()
    target = VersionedTraceRef("opening_position", str(account_id), digest)
    scope = TraceScope.tenant(user_id)
    now = datetime.now(UTC)
    observation = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("ledger_opening_input", "starting-stock", "1"),
        authority=policy.authority,
        result=TraceResult.PASS,
        execution_id=f"opening-position:{account_id}:{digest}",
        evidence_manifest_digest=digest,
        occurred_at=now,
        reason_code="opening_position_materialized",
        score=None,
    )
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,)))
    previous = await repository.decision_head(scope, TraceLineage.from_refs(target, policy.assertion))
    decision = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=policy,
        execution_id=observation.execution_id,
        occurred_at=now,
        parents=(observation,),
        supersedes_id=previous.record.record_id if previous else None,
    )
    await TraceEmitter(repository).emit_many((observation, decision))
    versions = (
        (await db.execute(select(OpeningPositionRecord.version).where(OpeningPositionRecord.account_id == account_id)))
        .scalars()
        .all()
    )
    record = OpeningPositionRecord(
        user_id=user_id,
        account_id=account_id,
        version=max(versions, default=0) + 1,
        effective_date=effective_date,
        amount=amount,
        currency=currency,
        fx_rate=fx_rate,
        journal_entry_id=journal_entry_id,
        decision_id=decision.record_id,
        source_decision_id=source_decision_id,
        content_digest=digest,
    )
    db.add(record)
    await db.flush()
    return record


async def list_opening_positions(db: AsyncSession, *, user_id: UUID, as_of: date) -> tuple[OpeningPosition, ...]:
    """Read exact current starting-stock evidence, including historical anchored commands.

    Facts with stale source authority are returned as unproven, never silently
    accepted as a trustworthy starting balance. Voided entries are not positions.
    """
    from src.ledger.extension.anchored_posting import current_anchored_journal_entries

    authority = current_authoritative_trace_decision_projection(TraceScope.tenant(user_id)).subquery()
    authorities = {row.decision_id: row for row in (await db.execute(select(authority))).all()}
    records = (
        (
            await db.execute(
                select(OpeningPositionRecord)
                .where(OpeningPositionRecord.user_id == user_id, OpeningPositionRecord.effective_date <= as_of)
                .order_by(OpeningPositionRecord.version.desc())
            )
        )
        .scalars()
        .all()
    )
    positions = []
    seen = set()
    entry_ids = set()
    for row in records:
        if row.account_id in seen:
            continue
        # A voided latest version ends that account's initialized position. Do
        # not resurrect an older version or an older legacy journal fallback.
        seen.add(row.account_id)
        journal_current = True
        if row.journal_entry_id:
            entry = await db.get(JournalEntry, row.journal_entry_id)
            entry_ids.add(row.journal_entry_id)
            if entry is not None and entry.status == JournalEntryStatus.VOID:
                continue
            journal_current = (
                entry is not None
                and entry.user_id == user_id
                and entry.status in (JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED)
                and entry.decision_anchor_id in authorities
            )
        evidence = authorities.get(row.decision_id)
        digest = position_digest(
            account_id=row.account_id,
            effective_date=row.effective_date,
            amount=row.amount,
            currency=row.currency,
            fx_rate=row.fx_rate,
            journal_entry_id=row.journal_entry_id,
            source_decision_id=row.source_decision_id,
        )
        valid = (
            journal_current
            and evidence is not None
            and evidence.assertion_kind == "ledger_opening_position"
            and evidence.assertion_id == "initialized"
            and evidence.assertion_version == "1"
            and evidence.target_kind == "opening_position"
            and evidence.target_id == str(row.account_id)
            and evidence.target_version == digest == row.content_digest
        )
        if row.source_decision_id is not None and row.source_decision_id not in authorities:
            valid = False
        decision = (
            TraceDecisionRef(
                row.decision_id,
                VersionedTraceRef("opening_position", str(row.account_id), digest),
                OpeningPositionPolicy().assertion,
            )
            if valid
            else None
        )
        positions.append(
            OpeningPosition(
                row.account_id,
                row.effective_date,
                row.amount,
                row.currency,
                row.fx_rate,
                row.journal_entry_id,
                decision,
                "authoritative" if valid else "unproven",
                None if valid else "opening_authority_not_current",
            )
        )
    # Existing system opening operations are already immutable evidence. Project
    # them without modifying old facts or trusting a user-editable memo/tag.
    entries = (
        (
            await db.execute(
                current_anchored_journal_entries(user_id=user_id)
                .where(
                    JournalEntry.entry_date <= as_of,
                    JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]),
                )
                .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
            )
        )
        .scalars()
        .all()
    )
    for entry in entries:
        if entry.id in entry_ids:
            continue
        evidence = authorities.get(entry.decision_anchor_id)
        if (
            evidence is None
            or not evidence.target_id.startswith("ledger-system:opening-balance:")
            or evidence.assertion_kind != "ledger_system_command"
        ):
            continue
        for line in entry.lines:
            acct = line.account
            if acct.user_id != user_id or acct.is_system or acct.id in seen:
                continue
            normal = Direction.DEBIT if acct.type in (AccountType.ASSET, AccountType.EXPENSE) else Direction.CREDIT
            amount = line.amount if line.direction == normal else -line.amount
            decision = TraceDecisionRef(
                entry.decision_anchor_id,
                VersionedTraceRef(evidence.target_kind, evidence.target_id, evidence.target_version),
                VersionedTraceRef(evidence.assertion_kind, evidence.assertion_id, evidence.assertion_version),
            )
            positions.append(
                OpeningPosition(acct.id, entry.entry_date, amount, line.currency, line.fx_rate, entry.id, decision)
            )
            seen.add(acct.id)
    return tuple(positions)
