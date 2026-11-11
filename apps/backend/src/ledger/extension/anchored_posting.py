"""The sole command boundary for decision-authorized ledger facts."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import String, bindparam, func, select, text, tuple_
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    DeclarativeTracePolicy,
    JournalEntrySourceType,
    TraceAuthorityProfile,
    TraceDecisionPolicyRegistry,
    TraceLineage,
    TraceRecord,
    TraceRecordType,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
    current_authoritative_trace_decision_projection,
    text_digest,
    trace_decision_projection,
)
from src.audit.base.trace_repository import TraceRecordRepository
from src.audit.extension.trace_emitter import TraceEmitter
from src.audit.extension.trace_repository import SqlTraceRecordRepository
from src.ledger.base.decision_anchor import DecisionAnchor, DecisionAnchorError, journal_command_target
from src.ledger.base.validators import ValidationError
from src.ledger.extension.repository import (
    AnchoredEntryDraft,
    _create_anchored_journal_entries,
    _create_anchored_journal_entry,
    post_journal_entries,
    post_journal_entry,
    void_journal_entry,
)
from src.ledger.orm.journal import (
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalEntryStatus,
    JournalLine,
)

__all__ = [
    "AnchoredJournalCommand",
    "current_anchored_journal_entries",
    "ledger_trace_policy_registry",
    "submit_anchored_journal_entries",
    "submit_anchored_journal_entry",
    "submit_manual_journal_entry",
    "submit_system_journal_entry",
    "validate_manual_journal_entry_for_post",
    "void_journal_entry",
]

_TARGET_READ_CHUNK_SIZE = 1000


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
    ) -> AnchoredJournalCommand:
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
    """Compose a trusted-ledger query from audit-owned current authority."""
    projection = current_authoritative_trace_decision_projection(TraceScope.tenant(user_id)).subquery(
        "journal_authority_decisions"
    )
    query = (
        select(JournalEntry)
        .join(projection, projection.c.decision_id == JournalEntry.decision_anchor_id)
        .where(
            JournalEntry.user_id == user_id,
            JournalEntry.decision_authority_state == JournalEntryAuthorityState.ANCHORED,
        )
    )
    if target_kind is not None:
        query = query.where(projection.c.target_kind == target_kind)
    if target_id is not None:
        query = query.where(projection.c.target_id == target_id)
    if target_ids is not None:
        query = query.where(projection.c.target_id.in_(target_ids))
    return query


@dataclass(frozen=True, slots=True)
class ManualJournalAttestationPolicy(DeclarativeTracePolicy):
    assertion: VersionedTraceRef = field(
        default_factory=lambda: VersionedTraceRef("manual_journal_attestation", "human-reviewed-entry", "1")
    )
    authority: TraceAuthorityProfile = field(
        default_factory=lambda: TraceAuthorityProfile(
            package="ledger",
            tier="CODE-LED",
            proof_kind="property",
            provenance="manual",
            execution_stage="manual.adjudication",
            assertion_owner_digest=text_digest("ledger:manual-journal-attestation:v1"),
            producer_version="1",
        )
    )
    pass_reason: str = "manual_journal_attested"
    fail_reason: str = "manual_journal_attestation_invalid"


@dataclass(frozen=True, slots=True)
class SystemJournalCommandPolicy(DeclarativeTracePolicy):
    assertion: VersionedTraceRef = field(
        default_factory=lambda: VersionedTraceRef("ledger_system_command", "balanced-command", "1")
    )
    authority: TraceAuthorityProfile = field(
        default_factory=lambda: TraceAuthorityProfile(
            package="ledger",
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage="product.runtime",
            assertion_owner_digest=text_digest("ledger:system-journal-command:v1"),
            producer_version="1",
        )
    )
    pass_reason: str = "ledger_system_command_authorized"
    fail_reason: str = "ledger_system_command_invalid"


def ledger_trace_policy_registry() -> TraceDecisionPolicyRegistry:
    """Return the complete decoder for ledger-owned authority decisions."""
    from src.ledger.extension.opening_positions import OpeningPositionPolicy

    return TraceDecisionPolicyRegistry(
        (ManualJournalAttestationPolicy(), SystemJournalCommandPolicy(), OpeningPositionPolicy())
    )


def _normalized_lines_data(lines_data: list[dict], *, base_currency: str) -> list[dict]:
    return [{**line, "currency": str(line.get("currency") or base_currency).upper()} for line in lines_data]


def _at_column_scale(value: Decimal, column: object) -> Decimal:
    """Return ``value`` quantized to column scale without rounding, or raise (#2539)."""
    scale = column.type.scale  # type: ignore[attr-defined]
    stored = value.quantize(Decimal(1).scaleb(-scale))
    if stored != value:
        raise ValidationError(f"{column.key} {value} has more than {scale} decimal places")  # type: ignore[attr-defined]
    return stored


def _at_stored_scale(lines_data: list[dict]) -> list[dict]:
    scaled = []
    for line in lines_data:
        stored = {**line, "amount": _at_column_scale(line["amount"], JournalLine.amount)}
        if line.get("fx_rate") is not None:
            stored["fx_rate"] = _at_column_scale(line["fx_rate"], JournalLine.fx_rate)
        scaled.append(stored)
    return scaled


def _versioned_command_target(
    *,
    entry_date: date,
    memo: str,
    normalized_lines: list[dict],
    base_currency: str,
    prefix: str,
    explicit_suffix: UUID | None = None,
) -> tuple[str, VersionedTraceRef]:
    provisional = journal_command_target(
        entry_date=entry_date,
        memo=memo,
        lines_data=normalized_lines,
        base_currency=base_currency,
        source_identity=prefix,
    )
    source_identity = f"{prefix}:{explicit_suffix or provisional.version}"
    target = journal_command_target(
        entry_date=entry_date,
        memo=memo,
        lines_data=normalized_lines,
        base_currency=base_currency,
        source_identity=source_identity,
    )
    return source_identity, target


async def _emit_financial_decision_anchor(
    repository: SqlTraceRecordRepository,
    *,
    scope: TraceScope,
    target: VersionedTraceRef,
    policy: DeclarativeTracePolicy,
    input_assertion: VersionedTraceRef,
    execution_id: str,
    evidence_manifest_digest: str,
    reason_code: str,
) -> DecisionAnchor:
    occurred_at = datetime.now(UTC)
    observation = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=input_assertion,
        authority=policy.authority,
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=evidence_manifest_digest,
        occurred_at=occurred_at,
        score=None,
        reason_code=reason_code,
    )
    decision = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=policy,
        execution_id=execution_id,
        occurred_at=occurred_at,
        parents=(observation,),
    )
    emitted = await TraceEmitter(repository).emit_many((observation, decision))
    return DecisionAnchor.from_record(emitted[-1])


def manual_journal_target(
    *,
    entry_date: date,
    memo: str,
    lines_data: list[dict],
    base_currency: str,
) -> VersionedTraceRef:
    """Hash the precise manual payload so edits require a new attestation decision."""
    normalized_lines = _normalized_lines_data(lines_data, base_currency=base_currency)
    _, target = _versioned_command_target(
        entry_date=entry_date,
        memo=memo,
        normalized_lines=normalized_lines,
        base_currency=base_currency,
        prefix="manual-journal",
    )
    return target


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
    rationale_digest = text_digest(rationale)
    current = await repository.current_decision(scope, TraceLineage.from_refs(target, policy.assertion))
    if current is not None:
        parent_records = [await repository.get(scope, parent_id) for parent_id in current.parent_ids]
        if any(parent is not None and parent.evidence_manifest_digest == rationale_digest for parent in parent_records):
            return DecisionAnchor.from_record(current)
        raise DecisionAnchorError("a different manual attestation already owns this immutable journal payload")

    return await _emit_financial_decision_anchor(
        repository,
        scope=scope,
        target=target,
        policy=policy,
        input_assertion=VersionedTraceRef("manual_journal_input", "operator-attestation", "1"),
        execution_id=f"manual-journal:{target.id}",
        evidence_manifest_digest=rationale_digest,
        reason_code="manual_journal_input_attested",
    )


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
    """Create a manual draft through the decision-anchored command port (#2539)."""
    normalized_lines = _at_stored_scale(_normalized_lines_data(lines_data, base_currency=base_currency))
    anchor = await manual_journal_decision_anchor(
        db,
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        rationale=rationale,
        lines_data=normalized_lines,
        base_currency=base_currency,
    )
    return await submit_anchored_journal_entry(
        db,
        user_id=user_id,
        command=AnchoredJournalCommand.from_mappings(
            entry_date=entry_date,
            memo=memo,
            lines_data=normalized_lines,
            base_currency=base_currency,
            source_type=JournalEntrySourceType.MANUAL,
            source_id=None,
            source_identity=anchor.target.id,
            decision_anchor=anchor,
            post_immediately=False,
        ),
        base_currency=base_currency,
        trace_repository=SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((ManualJournalAttestationPolicy(),))),
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
    """Post a deterministic system command through the anchored command port."""
    normalized_lines = _normalized_lines_data(lines_data, base_currency=base_currency)
    source_identity, target = _versioned_command_target(
        entry_date=entry_date,
        memo=memo,
        normalized_lines=normalized_lines,
        base_currency=base_currency,
        prefix=f"ledger-system:{operation}",
        explicit_suffix=source_id,
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
        anchor = await _emit_financial_decision_anchor(
            repository,
            scope=scope,
            target=target,
            policy=policy,
            input_assertion=VersionedTraceRef("ledger_system_input", operation, "1"),
            execution_id=f"ledger-system:{target.id}:{target.version}",
            evidence_manifest_digest=target.version,
            reason_code="ledger_system_command_materialized",
        )

    return await submit_anchored_journal_entry(
        db,
        user_id=user_id,
        command=AnchoredJournalCommand.from_mappings(
            entry_date=entry_date,
            memo=memo,
            lines_data=normalized_lines,
            base_currency=base_currency,
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
    """Re-verify an editable manual draft against its decision anchor before posting (#2539)."""
    if entry.source_type is not JournalEntrySourceType.MANUAL:
        return
    if entry.decision_authority_state is JournalEntryAuthorityState.LEGACY_UNPROVEN:
        raise DecisionAnchorError("legacy-unproven journal entries cannot be posted")
    if entry.decision_anchor_id is None:
        raise DecisionAnchorError("manual journal entry is missing its decision anchor")
    if not entry.lines:
        raise DecisionAnchorError("manual journal entry has no lines to verify")
    line_fields = ("account_id", "direction", "amount", "currency", "fx_rate", "event_type", "tags")
    target = manual_journal_target(
        entry_date=entry.entry_date,
        memo=entry.memo,
        lines_data=[{f: getattr(line, f) for f in line_fields} for line in entry.lines],
        base_currency=entry.stored_base_currency(base_currency),
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


def _target_lock_key(user_id: UUID, target: VersionedTraceRef) -> str:
    return f"ledger-target\x1f{user_id}\x1f{target.kind}\x1f{target.id}"


def _active_anchored_entries_query(user_id: UUID):
    decisions = trace_decision_projection(TraceScope.tenant(user_id)).subquery("ledger_target_decisions")
    query = (
        select(JournalEntry, decisions.c.target_kind, decisions.c.target_id)
        .join(decisions, decisions.c.decision_id == JournalEntry.decision_anchor_id)
        .where(
            JournalEntry.user_id == user_id,
            JournalEntry.decision_authority_state == JournalEntryAuthorityState.ANCHORED,
            JournalEntry.status != JournalEntryStatus.VOID,
        )
    )
    return query, decisions


async def _existing_for_target(
    db: AsyncSession,
    *,
    user_id: UUID,
    target: VersionedTraceRef,
) -> JournalEntry | None:
    await db.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(_target_lock_key(user_id, target), 0)))
    )
    query, decisions = _active_anchored_entries_query(user_id)
    row = (
        await db.execute(
            query.where(decisions.c.target_kind == target.kind, decisions.c.target_id == target.id).with_for_update()
        )
    ).one_or_none()
    return row[0] if row is not None else None


async def _existing_for_targets(
    db: AsyncSession,
    *,
    user_id: UUID,
    targets: Sequence[VersionedTraceRef],
) -> dict[tuple[str, str], JournalEntry]:
    """Acquire advisory locks in key order and return active entries owning ``targets``."""
    keys = sorted({_target_lock_key(user_id, target) for target in targets})
    await db.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended(lock_key, 0)) "
            "FROM (SELECT lock_key FROM unnest(CAST(:keys AS text[])) AS locks(lock_key) "
            "ORDER BY lock_key OFFSET 0) AS ordered_keys"
        ).bindparams(bindparam("keys", keys, type_=ARRAY(String)))
    )
    query, decisions = _active_anchored_entries_query(user_id)
    owners: dict[tuple[str, str], JournalEntry] = {}
    pairs = sorted({(target.kind, target.id) for target in targets})
    for start in range(0, len(pairs), _TARGET_READ_CHUNK_SIZE):
        rows = (
            await db.execute(
                query.where(
                    tuple_(decisions.c.target_kind, decisions.c.target_id).in_(
                        pairs[start : start + _TARGET_READ_CHUNK_SIZE]
                    )
                ).with_for_update()
            )
        ).all()
        for entry, target_kind, target_id in rows:
            if (target_kind, target_id) in owners:
                raise MultipleResultsFound(f"more than one journal entry owns the target {target_kind}:{target_id}")
            owners[(target_kind, target_id)] = entry
    return owners


async def submit_anchored_journal_entry(
    db: AsyncSession,
    *,
    user_id: UUID,
    command: AnchoredJournalCommand,
    base_currency: str,
    trace_repository: TraceRecordRepository | None = None,
) -> JournalEntry:
    """Verify one decision and persist its journal fact idempotently by target identity."""
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
        return await post_journal_entry(db, entry, user_id, base_currency=base_currency)
    return entry


async def submit_anchored_journal_entries(
    db: AsyncSession,
    *,
    user_id: UUID,
    commands: Sequence[AnchoredJournalCommand],
    base_currency: str,
    trace_repository: TraceRecordRepository | None = None,
) -> list[JournalEntry]:
    """Verify many decisions and persist their journal facts in bulk unless targets overlap."""
    repository = trace_repository or SqlTraceRecordRepository(db)
    targets = [
        journal_command_target(
            entry_date=cmd.entry_date,
            memo=cmd.memo,
            lines_data=cmd.lines_data,
            base_currency=base_currency,
            source_identity=cmd.source_identity,
        )
        for cmd in commands
    ]
    if len({target.id for target in targets}) != len(targets):
        return [
            await submit_anchored_journal_entry(
                db, user_id=user_id, command=cmd, base_currency=base_currency, trace_repository=repository
            )
            for cmd in commands
        ]
    for cmd, target in zip(commands, targets, strict=True):
        await validate_decision_anchor(repository, user_id=user_id, anchor=cmd.decision_anchor, expected_target=target)
    existing = await _existing_for_targets(db, user_id=user_id, targets=targets) if commands else {}

    results: dict[int, JournalEntry] = {}
    fresh: list[int] = []
    for index, (cmd, target) in enumerate(zip(commands, targets, strict=True)):
        owner = existing.get((target.kind, target.id))
        if owner is None:
            fresh.append(index)
        elif owner.decision_anchor_id == cmd.decision_anchor.decision_id:
            results[index] = owner
        else:
            raise DecisionAnchorError("a different decision already owns this immutable source target")

    created = await _create_anchored_journal_entries(
        db,
        user_id,
        [
            AnchoredEntryDraft(
                entry_date=commands[i].entry_date,
                memo=commands[i].memo,
                lines_data=commands[i].lines_data,
                source_type=commands[i].source_type,
                source_id=commands[i].source_id,
                decision_anchor=commands[i].decision_anchor,
            )
            for i in fresh
        ],
        base_currency=base_currency,
    )
    await post_journal_entries(
        db,
        [entry for entry, i in zip(created, fresh, strict=True) if commands[i].post_immediately],
        user_id,
        base_currency=base_currency,
    )
    for entry, i in zip(created, fresh, strict=True):
        results[i] = entry
    return [results[i] for i in range(len(commands))]
