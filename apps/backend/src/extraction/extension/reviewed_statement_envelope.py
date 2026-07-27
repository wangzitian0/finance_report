"""Version-bound human confirmation for incomplete statement source envelopes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    Ratio,
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceEmitter,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.extraction.base.result import StatementEvidenceType, StatementExtractionResult
from src.extraction.base.reviewed_statement_envelope import (
    ReviewedStatementEnvelopeCommand,
    supports_reviewed_statement_envelope,
)
from src.extraction.orm.reviewed_statement_envelope import (
    ReviewedStatementEnvelope,
    StatementExtractionResultRecord,
)
from src.extraction.orm.statement_enums import BankStatementStatus, Stage1Status
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType


class ReviewedStatementEnvelopeConflict(ValueError):
    """A different review command targets an already-confirmed source version."""


def _digest(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()


def _authority(*, tier: str, proof_kind: str, provenance: str, execution_stage: str) -> TraceAuthorityProfile:
    return TraceAuthorityProfile(
        package="extraction",
        tier=tier,
        proof_kind=proof_kind,
        provenance=provenance,
        execution_stage=execution_stage,
        assertion_owner_digest=_digest(f"reviewed-statement-envelope:{tier}:{proof_kind}:v1"),
        producer_version="1",
    )


@dataclass(frozen=True, slots=True)
class ReviewedEnvelopeInvariantTracePolicy:
    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef(kind="invariant", id="reviewed-statement-envelope-integrity", version="1")

    @property
    def authority(self) -> TraceAuthorityProfile:
        return _authority(
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage="product.runtime",
        )

    @property
    def causality(self) -> TraceCausality:
        return TraceCausality.DIRECT

    @property
    def target_class(self) -> TraceTargetClass:
        return TraceTargetClass.FINANCIAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        valid = len(parents) == 1 and parents[0].reason_code == "reviewed_envelope_invariants_satisfied"
        return TraceDecisionOutcome(
            result=TraceResult.AUTHORITATIVE if valid else TraceResult.REJECTED,
            reason_code="reviewed_envelope_integrity_satisfied" if valid else "reviewed_envelope_integrity_failed",
            score=Ratio(Decimal("1" if valid else "0")),
        )


@dataclass(frozen=True, slots=True)
class ReviewedEnvelopeDecisionTracePolicy:
    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef(kind="review", id="reviewed-statement-envelope", version="1")

    @property
    def authority(self) -> TraceAuthorityProfile:
        # The operator provides evidence, but only the typed code guard grants
        # promotion authority over that evidence.
        return _authority(
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="manual",
            execution_stage="manual.adjudication",
        )

    @property
    def causality(self) -> TraceCausality:
        return TraceCausality.MANIFEST

    @property
    def target_class(self) -> TraceTargetClass:
        return TraceTargetClass.FINANCIAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        has_source = any(parent.target.kind == "statement_extraction_result" for parent in parents)
        has_operator = any(parent.reason_code == "reviewed_envelope_operator_confirmed" for parent in parents)
        has_guard = any(parent.reason_code == "reviewed_envelope_integrity_satisfied" for parent in parents)
        valid = has_source and has_operator and has_guard
        return TraceDecisionOutcome(
            result=TraceResult.AUTHORITATIVE if valid else TraceResult.REJECTED,
            reason_code="reviewed_envelope_confirmed" if valid else "reviewed_envelope_parents_invalid",
            score=Ratio(Decimal("1" if valid else "0")),
        )


def reviewed_envelope_trace_policies() -> tuple[
    ReviewedEnvelopeInvariantTracePolicy, ReviewedEnvelopeDecisionTracePolicy
]:
    """Policies registered by extraction's single trace composition root."""
    return ReviewedEnvelopeInvariantTracePolicy(), ReviewedEnvelopeDecisionTracePolicy()


async def persist_statement_extraction_result(
    db: AsyncSession,
    *,
    statement: StatementSummary,
    result: StatementExtractionResult,
    source_trace_record_id: UUID,
) -> StatementExtractionResultRecord:
    """Append or reuse an exact typed source result and advance only the summary pointer."""
    payload = result.to_payload()
    if StatementExtractionResult.from_payload(payload) != result:
        raise ValueError("statement extraction result failed typed persistence validation")

    candidate = StatementExtractionResultRecord(
        user_id=statement.user_id,
        statement_id=statement.id,
        content_digest=result.content_digest,
        source_content_digest=result.source_content_digest,
        schema_version=result.schema_version,
        producer_version=result.producer_version,
        payload=payload,
        source_trace_record_id=source_trace_record_id,
        created_at=datetime.now(UTC),
    )
    try:
        async with db.begin_nested():
            db.add(candidate)
            await db.flush()
        source_record = candidate
    except IntegrityError:
        source_record = (
            await db.execute(
                select(StatementExtractionResultRecord)
                .where(StatementExtractionResultRecord.user_id == statement.user_id)
                .where(StatementExtractionResultRecord.statement_id == statement.id)
                .where(StatementExtractionResultRecord.content_digest == result.content_digest)
            )
        ).scalar_one_or_none()
        if source_record is None:
            raise RuntimeError("source-result conflict did not expose a canonical winner") from None
    if source_record.payload != payload:
        raise ValueError("statement extraction result digest collision")

    previous_source_result_id = statement.current_extraction_result_id
    if previous_source_result_id != source_record.id:
        # A reparse changes source identity. Do not let a previous reviewed
        # envelope remain materially approvable while the new source is pending.
        statement.current_extraction_result_id = source_record.id
        if previous_source_result_id is not None and result.requires_review:
            statement.account_id = None
            statement.currency = result.statement_currency
            statement.period_start = result.period_start
            statement.period_end = result.period_end
            if len(result.balances) == 1:
                balance = result.balances[0]
                statement.currency = statement.currency or balance.currency
                statement.opening_balance = balance.opening
                statement.closing_balance = balance.closing
            else:
                statement.opening_balance = None
                statement.closing_balance = None
            statement.manual_opening_balance = None
            statement.status = BankStatementStatus.PARSED
            statement.stage1_status = Stage1Status.PENDING_REVIEW
            statement.balance_validated = result.balance_validated
            statement.validation_error = "Source facts require reviewer confirmation: " + ", ".join(
                result.missing_required_facts
            )
    await db.flush()
    return source_record


async def current_reviewed_statement_envelope(
    db: AsyncSession,
    *,
    user_id: UUID,
    statement_id: UUID,
) -> ReviewedStatementEnvelope | None:
    """Return the review head only when it pins the summary's current source result."""
    statement = await db.get(StatementSummary, statement_id)
    if statement is None or statement.user_id != user_id or statement.current_extraction_result_id is None:
        return None
    return (
        await db.execute(
            select(ReviewedStatementEnvelope)
            .where(ReviewedStatementEnvelope.user_id == user_id)
            .where(ReviewedStatementEnvelope.statement_id == statement.id)
            .where(ReviewedStatementEnvelope.source_result_id == statement.current_extraction_result_id)
            .order_by(desc(ReviewedStatementEnvelope.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_current_statement_extraction_result(
    db: AsyncSession,
    *,
    user_id: UUID,
    statement_id: UUID,
) -> StatementExtractionResult | None:
    """Read the typed current source result without exposing extraction ORM internals."""
    statement = await db.get(StatementSummary, statement_id)
    if statement is None or statement.user_id != user_id or statement.current_extraction_result_id is None:
        return None
    source_record = await db.get(StatementExtractionResultRecord, statement.current_extraction_result_id)
    if source_record is None or source_record.user_id != user_id or source_record.statement_id != statement.id:
        return None
    return StatementExtractionResult.from_payload(source_record.payload)


async def require_current_statement_envelope_trust(
    db: AsyncSession,
    *,
    statement: StatementSummary,
) -> None:
    """Reject a mutable projection that cannot be traced to its current source head.

    Pre-migration statements have no typed raw-result pointer and retain their
    existing Stage-1 migration path. Every newly parsed statement has a pointer:
    complete sources must still agree with their raw envelope, while incomplete
    transaction-ledger sources require the exact current reviewed envelope.
    """
    if statement.current_extraction_result_id is None:
        return

    source_record = await db.get(StatementExtractionResultRecord, statement.current_extraction_result_id)
    if (
        source_record is None
        or source_record.user_id != statement.user_id
        or source_record.statement_id != statement.id
    ):
        raise ValueError("Statement current source result is unavailable")
    source_result = StatementExtractionResult.from_payload(source_record.payload)

    if not source_result.requires_review:
        _require_projection_matches_source(statement, source_result)
        return

    if not supports_reviewed_statement_envelope(source_result):
        raise ValueError(
            "Current source result has facts that this statement-envelope review cannot confirm: "
            + ", ".join(source_result.missing_required_facts)
        )

    envelope = await current_reviewed_statement_envelope(
        db,
        user_id=statement.user_id,
        statement_id=statement.id,
    )
    if envelope is None:
        raise ValueError(
            "Current source facts require an explicit reviewed envelope before posting: "
            + ", ".join(source_result.missing_required_facts)
        )
    if statement.manual_opening_balance is not None:
        raise ValueError("Manual opening-balance override cannot replace a reviewed statement envelope")
    projection = (
        statement.account_id,
        statement.currency,
        statement.period_start,
        statement.period_end,
        statement.opening_balance,
        statement.closing_balance,
    )
    reviewed = (
        envelope.account_id,
        envelope.currency,
        envelope.period_start,
        envelope.period_end,
        envelope.opening_balance,
        envelope.closing_balance,
    )
    if projection != reviewed:
        raise ValueError("Statement projection diverges from its current reviewed envelope")


def _require_projection_matches_source(
    statement: StatementSummary,
    source_result: StatementExtractionResult,
) -> None:
    """Guard scalar Stage-1 facts against a complete single-currency raw source."""
    if len(source_result.balances) != 1:
        # Multi-currency statements use their existing per-currency projection.
        # Their scalar approval path remains guarded by the normal completeness
        # and balance-chain checks rather than inventing one canonical currency.
        return
    balance = source_result.balances[0]
    source_currency = source_result.statement_currency or balance.currency
    source_projection = (
        source_currency,
        source_result.period_start,
        source_result.period_end,
        balance.opening,
        balance.closing,
    )
    statement_projection = (
        statement.currency,
        statement.period_start,
        statement.period_end,
        statement.opening_balance,
        statement.closing_balance,
    )
    if statement_projection != source_projection:
        raise ValueError("Statement projection diverges from its current source result")


async def confirm_reviewed_statement_envelope(
    db: AsyncSession,
    *,
    user_id: UUID,
    statement_id: UUID,
    command: ReviewedStatementEnvelopeCommand,
    trace_emitter: TraceEmitter,
) -> ReviewedStatementEnvelope:
    """Confirm one complete envelope without editing the result it reviews."""
    statement = (
        await db.execute(
            select(StatementSummary)
            .where(StatementSummary.id == statement_id)
            .where(StatementSummary.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if statement is None:
        raise ValueError("Statement not found or access denied")
    if statement.current_extraction_result_id is None:
        raise ValueError("Statement has no current source result; reparse before confirming its envelope")

    source_record = await db.get(StatementExtractionResultRecord, statement.current_extraction_result_id)
    if source_record is None or source_record.user_id != user_id or source_record.statement_id != statement.id:
        raise ValueError("Statement current source result is unavailable")
    if command.source_result_digest != source_record.content_digest:
        raise ValueError("Command does not match the current source result digest")
    source_result = StatementExtractionResult.from_payload(source_record.payload)
    if source_result.content_digest != command.source_result_digest:
        raise ValueError("Current source result identity is invalid")
    if not supports_reviewed_statement_envelope(source_result):
        raise ValueError("Current source result cannot be confirmed with a cash statement envelope")
    _validate_command_against_source(command, source_result)

    account = (
        await db.execute(select(Account).where(Account.id == command.account_id).where(Account.user_id == user_id))
    ).scalar_one_or_none()
    if account is None or not account.is_active or account.type is not AccountType.ASSET:
        raise ValueError("A user-owned active asset custody account is required")
    if account.currency.strip().upper() != command.currency:
        raise ValueError("Custody account currency must match the confirmed statement currency")

    existing = (
        await db.execute(
            select(ReviewedStatementEnvelope)
            .where(ReviewedStatementEnvelope.user_id == user_id)
            .where(ReviewedStatementEnvelope.statement_id == statement.id)
            .where(ReviewedStatementEnvelope.command_digest == command.digest)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    current_for_source = await current_reviewed_statement_envelope(
        db,
        user_id=user_id,
        statement_id=statement.id,
    )
    if current_for_source is not None:
        raise ReviewedStatementEnvelopeConflict(
            "A different reviewed envelope already confirms this source result; reparse before replacing it"
        )
    previous = (
        await db.execute(
            select(ReviewedStatementEnvelope)
            .where(ReviewedStatementEnvelope.user_id == user_id)
            .where(ReviewedStatementEnvelope.statement_id == statement.id)
            .order_by(desc(ReviewedStatementEnvelope.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()

    source_parent = await trace_emitter.repository.get(TraceScope.tenant(user_id), source_record.source_trace_record_id)
    if source_parent is None:
        raise ValueError("Current source result audit anchor is unavailable")
    trace_records = _build_review_trace_records(
        user_id=user_id,
        statement_id=statement.id,
        source_result=source_result,
        command=command,
        source_parent=source_parent,
    )
    await trace_emitter.emit_many(trace_records)

    envelope = ReviewedStatementEnvelope(
        user_id=user_id,
        statement_id=statement.id,
        source_result_id=source_record.id,
        account_id=account.id,
        currency=command.currency,
        period_start=command.period_start,
        period_end=command.period_end,
        opening_balance=command.opening_balance,
        closing_balance=command.closing_balance,
        rationale=command.rationale,
        command_digest=command.digest,
        review_trace_record_id=trace_records[-1].record_id,
        supersedes_id=previous.id if previous is not None else None,
        created_at=datetime.now(UTC),
    )
    db.add(envelope)

    # This is a DWD conform projection, not source evidence. The immutable
    # source-result record/payload above remains unchanged and is the audit parent.
    statement.account_id = account.id
    statement.currency = command.currency
    statement.period_start = command.period_start
    statement.period_end = command.period_end
    statement.opening_balance = command.opening_balance
    statement.closing_balance = command.closing_balance
    statement.manual_opening_balance = None
    statement.status = BankStatementStatus.PARSED
    statement.stage1_status = Stage1Status.PENDING_REVIEW
    statement.balance_validated = True
    statement.validation_error = None
    await db.flush()
    return envelope


def _validate_command_against_source(
    command: ReviewedStatementEnvelopeCommand,
    source_result: StatementExtractionResult,
) -> None:
    if source_result.evidence_type is not StatementEvidenceType.TRANSACTION_LEDGER:
        raise ValueError("Only transaction-ledger sources accept a cash statement envelope confirmation")
    currencies = {txn.currency for txn in source_result.transactions}
    if None in currencies or any(currency != command.currency for currency in currencies):
        raise ValueError("Every transaction currency must match the confirmed statement currency")
    net = sum(
        (txn.amount if txn.direction == "IN" else -txn.amount for txn in source_result.transactions),
        start=Decimal("0"),
    )
    if command.opening_balance + net != command.closing_balance:
        raise ValueError("Confirmed opening balance plus source transactions must equal closing balance")


def _build_review_trace_records(
    *,
    user_id: UUID,
    statement_id: UUID,
    source_result: StatementExtractionResult,
    command: ReviewedStatementEnvelopeCommand,
    source_parent: TraceRecord,
) -> tuple[TraceRecord, ...]:
    execution_id = f"statement:{statement_id}:reviewed-envelope:{command.digest}"
    occurred_at = datetime.now(UTC)
    target = VersionedTraceRef(
        kind="reviewed_statement_envelope",
        # The source-result identity, not the mutable statement aggregate, is
        # the review lineage. A reparse therefore starts a new explicit chain.
        id=str(source_result.result_id),
        version=command.digest,
    )
    scope = TraceScope.tenant(user_id)
    operator = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef(kind="review", id="operator-envelope-confirmation", version="1"),
        authority=_authority(
            tier="CODE-LED",
            proof_kind="exact",
            provenance="manual",
            execution_stage="manual.adjudication",
        ),
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=source_result.content_digest,
        occurred_at=occurred_at,
        score=Ratio(Decimal("1")),
        reason_code="reviewed_envelope_operator_confirmed",
    )
    invariant = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef(kind="invariant", id="reviewed-envelope-command-validation", version="1"),
        authority=_authority(
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage="product.runtime",
        ),
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=command.digest,
        occurred_at=occurred_at,
        score=Ratio(Decimal("1")),
        reason_code="reviewed_envelope_invariants_satisfied",
    )
    guard = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=ReviewedEnvelopeInvariantTracePolicy(),
        execution_id=execution_id,
        occurred_at=occurred_at,
        parents=(invariant,),
    )
    decision = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=ReviewedEnvelopeDecisionTracePolicy(),
        execution_id=execution_id,
        occurred_at=occurred_at,
        parents=(source_parent, operator, guard),
    )
    return operator, invariant, guard, decision
