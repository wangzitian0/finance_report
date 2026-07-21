"""The sole command boundary for decision-authorized ledger facts."""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    JournalEntrySourceType,
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceDecisionPolicyRegistry,
    TraceLineage,
    TraceRecord,
    TraceRecordType,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
    current_authoritative_trace_decision_projection,
    trace_decision_projection,
)
from src.audit.base.trace_repository import TraceRecordRepository
from src.audit.extension.trace_emitter import TraceEmitter
from src.audit.extension.trace_repository import SqlTraceRecordRepository
from src.ledger.base.decision_anchor import DecisionAnchor, DecisionAnchorError, journal_command_target
from src.ledger.extension.repository import _create_anchored_journal_entry, post_journal_entry
from src.ledger.orm.journal import Direction, JournalEntry, JournalEntryAuthorityState


@dataclass(frozen=True, slots=True)
class JournalCommandLine:
    """One typed persistence-neutral line carried by an anchored command."""

    account_id: UUID
    direction: Direction
    amount: Decimal
    currency: str
    fx_rate: Decimal | None = None
    event_type: str | None = None
    tags: Mapping[str, object] | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, object], *, base_currency: str) -> JournalCommandLine:
        account_id = value.get("account_id")
        amount = value.get("amount")
        if not isinstance(account_id, UUID):
            raise TypeError("journal command line account_id must be a UUID")
        if not isinstance(amount, Decimal):
            raise TypeError("journal command line amount must be a Decimal")
        raw_direction = value.get("direction")
        direction = raw_direction if isinstance(raw_direction, Direction) else Direction(str(raw_direction))
        fx_rate = value.get("fx_rate")
        if fx_rate is not None and not isinstance(fx_rate, Decimal):
            raise TypeError("journal command line fx_rate must be a Decimal")
        tags = value.get("tags")
        if tags is not None and not isinstance(tags, Mapping):
            raise TypeError("journal command line tags must be a mapping")
        event_type = value.get("event_type")
        return cls(
            account_id=account_id,
            direction=direction,
            amount=amount,
            currency=str(value.get("currency") or base_currency).upper(),
            fx_rate=fx_rate,
            event_type=str(event_type) if event_type is not None else None,
            tags=tags,
        )

    def as_mapping(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "direction": self.direction,
            "amount": self.amount,
            "currency": self.currency,
            "fx_rate": self.fx_rate,
            "event_type": self.event_type,
            "tags": dict(self.tags) if self.tags is not None else None,
        }


@dataclass(frozen=True, slots=True)
class AnchoredJournalCommand:
    """Legacy v1 command retained for source-compatible evolution."""

    entry_date: date
    memo: str
    lines_data: list[dict]
    source_type: JournalEntrySourceType
    source_id: UUID | None
    source_identity: str
    decision_anchor: DecisionAnchor
    post_immediately: bool


@dataclass(frozen=True, slots=True)
class AnchoredJournalCommandV2:
    """A balanced journal payload plus the exact decision that authorizes it."""

    entry_date: date
    memo: str
    lines: tuple[JournalCommandLine, ...]
    source_type: JournalEntrySourceType
    source_id: UUID | None
    source_identity: str
    decision_anchor: DecisionAnchor
    post_immediately: bool

    @classmethod
    def from_mappings(
        cls,
        *,
        entry_date: date,
        memo: str,
        lines_data: Sequence[Mapping[str, object]],
        base_currency: str,
        source_type: JournalEntrySourceType,
        source_id: UUID | None,
        source_identity: str,
        decision_anchor: DecisionAnchor,
        post_immediately: bool,
    ) -> AnchoredJournalCommandV2:
        """Validate legacy mappings once when they enter the typed command port."""
        return cls(
            entry_date=entry_date,
            memo=memo,
            lines=tuple(JournalCommandLine.from_mapping(line, base_currency=base_currency) for line in lines_data),
            source_type=source_type,
            source_id=source_id,
            source_identity=source_identity,
            decision_anchor=decision_anchor,
            post_immediately=post_immediately,
        )

    @property
    def lines_data(self) -> list[dict[str, object]]:
        return [line.as_mapping() for line in self.lines]


def current_anchored_journal_entries(
    *,
    user_id: UUID,
    target_kind: str | None = None,
    target_id=None,
    target_ids: Collection[str] | None = None,
):
    """Compose a trusted-ledger query from audit-owned current authority.

    Provenance fields never establish authority, and a decision whose own or
    causal parent record was superseded is excluded.
    """
    scope = TraceScope.tenant(user_id)
    projection = current_authoritative_trace_decision_projection(scope).subquery("journal_authority_decisions")
    query = (
        select(JournalEntry)
        .join(projection, projection.c.decision_id == JournalEntry.decision_anchor_id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.decision_authority_state == JournalEntryAuthorityState.ANCHORED)
    )
    if target_kind is not None:
        query = query.where(projection.c.target_kind == target_kind)
    if target_id is not None:
        query = query.where(projection.c.target_id == target_id)
    if target_ids is not None:
        query = query.where(projection.c.target_id.in_(target_ids))
    return query


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ManualJournalAttestationPolicy:
    """A human attestation is an explicit financial decision, not a source label."""

    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef("manual_journal_attestation", "human-reviewed-entry", "1")

    @property
    def authority(self) -> TraceAuthorityProfile:
        return TraceAuthorityProfile(
            package="ledger",
            tier="CODE-LED",
            proof_kind="property",
            provenance="manual",
            execution_stage="manual.adjudication",
            assertion_owner_digest=_sha256("ledger:manual-journal-attestation:v1"),
            producer_version="1",
        )

    @property
    def causality(self) -> TraceCausality:
        return TraceCausality.DIRECT

    @property
    def target_class(self) -> TraceTargetClass:
        return TraceTargetClass.FINANCIAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        valid = len(parents) == 1 and parents[0].result is TraceResult.PASS
        return TraceDecisionOutcome(
            TraceResult.AUTHORITATIVE if valid else TraceResult.REJECTED,
            "manual_journal_attested" if valid else "manual_journal_attestation_invalid",
        )


@dataclass(frozen=True, slots=True)
class SystemJournalCommandPolicy:
    """Authorizes a deterministic ledger-owned command without classifying it."""

    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef("ledger_system_command", "balanced-command", "1")

    @property
    def authority(self) -> TraceAuthorityProfile:
        return TraceAuthorityProfile(
            package="ledger",
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage="product.runtime",
            assertion_owner_digest=_sha256("ledger:system-journal-command:v1"),
            producer_version="1",
        )

    @property
    def causality(self) -> TraceCausality:
        return TraceCausality.DIRECT

    @property
    def target_class(self) -> TraceTargetClass:
        return TraceTargetClass.FINANCIAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        valid = len(parents) == 1 and parents[0].result is TraceResult.PASS
        return TraceDecisionOutcome(
            TraceResult.AUTHORITATIVE if valid else TraceResult.REJECTED,
            "ledger_system_command_authorized" if valid else "ledger_system_command_invalid",
        )


def ledger_trace_policy_registry() -> TraceDecisionPolicyRegistry:
    """Return the complete decoder for ledger-owned authority decisions."""
    return TraceDecisionPolicyRegistry((ManualJournalAttestationPolicy(), SystemJournalCommandPolicy()))


def _normalized_lines_data(lines_data: list[dict], *, base_currency: str) -> list[dict]:
    """Materialize defaults before both target hashing and persistence."""
    return [
        {
            **line,
            "currency": str(line.get("currency") or base_currency).upper(),
        }
        for line in lines_data
    ]


def manual_journal_target(
    *,
    entry_date: date,
    memo: str,
    lines_data: list[dict],
    base_currency: str,
) -> VersionedTraceRef:
    """Hash the precise manual payload so edits need a new attestation decision."""
    normalized_lines = _normalized_lines_data(lines_data, base_currency=base_currency)
    provisional = journal_command_target(
        entry_date=entry_date,
        memo=memo,
        lines_data=normalized_lines,
        base_currency=base_currency,
        source_identity="manual-journal",
    )
    return journal_command_target(
        entry_date=entry_date,
        memo=memo,
        lines_data=normalized_lines,
        base_currency=base_currency,
        source_identity=f"manual-journal:{provisional.version}",
    )


async def manual_journal_decision_anchor(
    db: AsyncSession,
    *,
    user_id: UUID,
    entry_date: date,
    memo: str,
    rationale: str,
    lines_data: list[dict],
    base_currency: str,
) -> DecisionAnchor:
    """Return the current manual decision or append one in this unit of work."""
    target = manual_journal_target(
        entry_date=entry_date,
        memo=memo,
        lines_data=lines_data,
        base_currency=base_currency,
    )
    policy = ManualJournalAttestationPolicy()
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,)))
    scope = TraceScope.tenant(user_id)
    current = await repository.current_decision(scope, TraceLineage.from_refs(target, policy.assertion))
    if current is not None:
        parent_records = [await repository.get(scope, parent_id) for parent_id in current.parent_ids]
        if any(
            parent is not None and parent.evidence_manifest_digest == _sha256(rationale) for parent in parent_records
        ):
            return DecisionAnchor.from_record(current)
        raise DecisionAnchorError("a different manual attestation already owns this immutable journal payload")

    occurred_at = datetime.now(UTC)
    rationale_digest = _sha256(rationale)
    observation = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("manual_journal_input", "operator-attestation", "1"),
        authority=policy.authority,
        result=TraceResult.PASS,
        execution_id=f"manual-journal:{target.id}",
        evidence_manifest_digest=rationale_digest,
        occurred_at=occurred_at,
        score=None,
        reason_code="manual_journal_input_attested",
    )
    decision = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=policy,
        execution_id=f"manual-journal:{target.id}",
        occurred_at=occurred_at,
        parents=(observation,),
    )
    emitted = await TraceEmitter(repository).emit_many((observation, decision))
    return DecisionAnchor.from_record(emitted[-1])


async def submit_manual_journal_entry(
    db: AsyncSession,
    *,
    user_id: UUID,
    entry_date: date,
    memo: str,
    rationale: str,
    lines_data: list[dict],
    base_currency: str,
) -> JournalEntry:
    """Create a manual draft through the same decision-anchored command port."""
    normalized_lines = _normalized_lines_data(lines_data, base_currency=base_currency)
    anchor = await manual_journal_decision_anchor(
        db,
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        rationale=rationale,
        lines_data=normalized_lines,
        base_currency=base_currency,
    )
    command = AnchoredJournalCommand(
        entry_date=entry_date,
        memo=memo,
        lines_data=normalized_lines,
        source_type=JournalEntrySourceType.MANUAL,
        source_id=None,
        source_identity=anchor.target.id,
        decision_anchor=anchor,
        post_immediately=False,
    )
    return await submit_anchored_journal_entry(
        db,
        user_id=user_id,
        command=command,
        base_currency=base_currency,
        trace_repository=SqlTraceRecordRepository(
            db,
            TraceDecisionPolicyRegistry((ManualJournalAttestationPolicy(),)),
        ),
    )


async def submit_system_journal_entry(
    db: AsyncSession,
    *,
    user_id: UUID,
    entry_date: date,
    memo: str,
    lines_data: list[dict],
    base_currency: str,
    operation: str,
    source_id: UUID | None = None,
    source_type: JournalEntrySourceType = JournalEntrySourceType.SYSTEM,
    post_immediately: bool = True,
) -> JournalEntry:
    """Post a deterministic system command through the same anchored port.

    This policy asserts only that ledger received this exact validated command;
    its callers retain ownership of account selection and economic semantics.
    """
    normalized_lines = _normalized_lines_data(lines_data, base_currency=base_currency)
    provisional = journal_command_target(
        entry_date=entry_date,
        memo=memo,
        lines_data=normalized_lines,
        base_currency=base_currency,
        source_identity=f"ledger-system:{operation}",
    )
    source_identity = f"ledger-system:{operation}:{source_id or provisional.version}"
    target = journal_command_target(
        entry_date=entry_date,
        memo=memo,
        lines_data=normalized_lines,
        base_currency=base_currency,
        source_identity=source_identity,
    )
    policy = SystemJournalCommandPolicy()
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((policy,)))
    scope = TraceScope.tenant(user_id)
    current = await repository.current_decision(scope, TraceLineage.from_refs(target, policy.assertion))
    if current is not None:
        if current.target != target:
            raise DecisionAnchorError("a different system command already owns this immutable source")
        anchor = DecisionAnchor.from_record(current)
    else:
        occurred_at = datetime.now(UTC)
        observation = TraceRecord.observation(
            scope=scope,
            target=target,
            target_class=TraceTargetClass.FINANCIAL,
            assertion=VersionedTraceRef("ledger_system_input", operation, "1"),
            authority=policy.authority,
            result=TraceResult.PASS,
            execution_id=f"ledger-system:{target.id}:{target.version}",
            evidence_manifest_digest=target.version,
            occurred_at=occurred_at,
            score=None,
            reason_code="ledger_system_command_materialized",
        )
        decision = TraceRecord.decision(
            scope=scope,
            target=target,
            policy=policy,
            execution_id=observation.execution_id,
            occurred_at=occurred_at,
            parents=(observation,),
        )
        anchor = DecisionAnchor.from_record((await TraceEmitter(repository).emit_many((observation, decision)))[-1])

    return await submit_anchored_journal_entry(
        db,
        user_id=user_id,
        command=AnchoredJournalCommand(
            entry_date=entry_date,
            memo=memo,
            lines_data=normalized_lines,
            source_type=source_type,
            source_id=source_id,
            source_identity=source_identity,
            decision_anchor=anchor,
            post_immediately=post_immediately,
        ),
        base_currency=base_currency,
        trace_repository=repository,
    )


async def validate_manual_journal_entry_for_post(
    db: AsyncSession,
    *,
    user_id: UUID,
    entry: JournalEntry,
    base_currency: str,
) -> None:
    """Re-check an editable draft against its manual decision before posting it."""
    if entry.source_type is not JournalEntrySourceType.MANUAL:
        return
    if entry.decision_authority_state is JournalEntryAuthorityState.LEGACY_UNPROVEN:
        raise DecisionAnchorError("legacy-unproven journal entries cannot be posted")
    if entry.decision_anchor_id is None:
        raise DecisionAnchorError("manual journal entry is missing its decision anchor")
    if not entry.lines:
        raise DecisionAnchorError("manual journal entry has no lines to verify")
    target = manual_journal_target(
        entry_date=entry.entry_date,
        memo=entry.memo,
        lines_data=[
            {
                "account_id": line.account_id,
                "direction": line.direction,
                "amount": line.amount,
                "currency": line.currency,
                "fx_rate": line.fx_rate,
                "event_type": line.event_type,
                "tags": line.tags,
            }
            for line in entry.lines
        ],
        base_currency=base_currency,
    )
    repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((ManualJournalAttestationPolicy(),)))
    record = await repository.get(TraceScope.tenant(user_id), entry.decision_anchor_id)
    if record is None:
        raise DecisionAnchorError("manual journal decision anchor is unavailable")
    await validate_decision_anchor(
        repository,
        user_id=user_id,
        anchor=DecisionAnchor.from_record(record),
        expected_target=target,
    )


async def validate_decision_anchor(
    repository: TraceRecordRepository,
    *,
    user_id: UUID,
    anchor: DecisionAnchor,
    expected_target: VersionedTraceRef | None = None,
) -> None:
    """Fail closed unless the persisted decision is current for this tenant and target."""
    scope = TraceScope.tenant(user_id)
    record = await repository.get(scope, anchor.decision_id)
    if record is None:
        raise DecisionAnchorError("decision anchor does not belong to the requested tenant")
    if record.record_type is not TraceRecordType.DECISION or record.result is not TraceResult.AUTHORITATIVE:
        raise DecisionAnchorError("decision anchor is not authoritative")
    if record.target_class is not TraceTargetClass.FINANCIAL:
        raise DecisionAnchorError("decision anchor does not authorize a financial target")
    if record.target != anchor.target:
        raise DecisionAnchorError("decision anchor target does not match the persisted decision")
    if record.assertion != anchor.policy_assertion:
        raise DecisionAnchorError("decision anchor policy version does not match the persisted decision")
    if expected_target is not None and anchor.target != expected_target:
        raise DecisionAnchorError("decision anchor target does not match the command source target")
    current = await repository.current_decision(scope, record.lineage)
    if current is None or current.record_id != record.record_id:
        raise DecisionAnchorError("decision anchor is no longer the current authority decision")


async def _existing_for_target(
    db: AsyncSession,
    *,
    user_id: UUID,
    target: VersionedTraceRef,
) -> JournalEntry | None:
    lock_key = f"ledger-target\x1f{user_id}\x1f{target.kind}\x1f{target.id}"
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))
    decisions = trace_decision_projection(TraceScope.tenant(user_id)).subquery("ledger_target_decisions")
    result = await db.execute(
        select(JournalEntry)
        .join(decisions, decisions.c.decision_id == JournalEntry.decision_anchor_id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.decision_authority_state == JournalEntryAuthorityState.ANCHORED)
        .where(decisions.c.target_kind == target.kind)
        .where(decisions.c.target_id == target.id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def submit_anchored_journal_entry(
    db: AsyncSession,
    *,
    user_id: UUID,
    command: AnchoredJournalCommand,
    base_currency: str,
    trace_repository: TraceRecordRepository | None = None,
) -> JournalEntry:
    """Submit the source-compatible v1 command."""
    return await _submit_anchored_journal_entry(
        db,
        user_id=user_id,
        command=command,
        base_currency=base_currency,
        trace_repository=trace_repository,
    )


async def submit_anchored_journal_entry_v2(
    db: AsyncSession,
    *,
    user_id: UUID,
    command: AnchoredJournalCommandV2,
    base_currency: str,
    trace_repository: TraceRecordRepository | None = None,
) -> JournalEntry:
    """Submit a typed v2 command without changing the v1 public contract."""
    return await _submit_anchored_journal_entry(
        db,
        user_id=user_id,
        command=command,
        base_currency=base_currency,
        trace_repository=trace_repository,
    )


async def _submit_anchored_journal_entry(
    db: AsyncSession,
    *,
    user_id: UUID,
    command: AnchoredJournalCommand | AnchoredJournalCommandV2,
    base_currency: str,
    trace_repository: TraceRecordRepository | None = None,
) -> JournalEntry:
    """Verify one decision and persist its journal fact exactly once.

    The target identity, rather than caller-selected source metadata, is the
    idempotency boundary. A changed decision for the same source must produce a
    correction/void workflow, never a second competing journal fact.
    """
    repository = trace_repository or SqlTraceRecordRepository(db)
    expected_target = journal_command_target(
        entry_date=command.entry_date,
        memo=command.memo,
        lines_data=command.lines_data,
        base_currency=base_currency,
        source_identity=command.source_identity,
    )
    await validate_decision_anchor(
        repository,
        user_id=user_id,
        anchor=command.decision_anchor,
        expected_target=expected_target,
    )
    existing = await _existing_for_target(db, user_id=user_id, target=expected_target)
    if existing is not None:
        if existing.decision_anchor_id == command.decision_anchor.decision_id:
            return existing
        raise DecisionAnchorError("a different decision already owns this immutable source target")

    entry = await _create_anchored_journal_entry(
        db,
        user_id,
        entry_date=command.entry_date,
        memo=command.memo,
        lines_data=command.lines_data,
        source_type=command.source_type,
        source_id=command.source_id,
        base_currency=base_currency,
        decision_anchor=command.decision_anchor,
    )
    if command.post_immediately:
        return await post_journal_entry(db, entry.id, user_id, base_currency=base_currency)
    return entry
