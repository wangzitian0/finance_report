"""Version-bound human confirmation for reviewable statement source envelopes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    DeclarativeTracePolicy,
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
    canonical_json_digest,
)
from src.extraction.base.result import StatementEvidenceType, StatementExtractionResult, StatementSourceType
from src.extraction.base.reviewed_statement_envelope import (
    ReviewedStatementEnvelopeCommand,
    supports_reviewed_statement_envelope,
)
from src.extraction.base.source_vocabulary import BankStatementStatus, Stage1Status
from src.extraction.extension.custody_binding import resolve_bank_custody_account
from src.extraction.extension.statement_runs import get_active_run
from src.extraction.orm.reviewed_statement_envelope import (
    ReviewedStatementEnvelope,
    StatementExtractionResultRecord,
)
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType


class ReviewedStatementEnvelopeConflict(ValueError):
    """A different review command targets an already-confirmed source version."""


def _authority(*, tier: str, proof_kind: str, provenance: str, execution_stage: str) -> TraceAuthorityProfile:
    return TraceAuthorityProfile(
        package="extraction",
        tier=tier,
        proof_kind=proof_kind,
        provenance=provenance,
        execution_stage=execution_stage,
        assertion_owner_digest=canonical_json_digest(
            f"reviewed-statement-envelope:{tier}:{proof_kind}:v1", default=str
        ),
        producer_version="1",
    )


@dataclass(frozen=True, slots=True)
class ReviewedEnvelopeInvariantTracePolicy(DeclarativeTracePolicy):
    assertion: VersionedTraceRef = field(
        default_factory=lambda: VersionedTraceRef("invariant", "reviewed-statement-envelope-integrity", "1")
    )
    authority: TraceAuthorityProfile = field(
        default_factory=lambda: _authority(
            tier="CODE-ONLY", proof_kind="exact", provenance="deterministic", execution_stage="product.runtime"
        )
    )

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        valid = len(parents) == 1 and parents[0].reason_code == "reviewed_envelope_invariants_satisfied"
        return TraceDecisionOutcome(
            result=TraceResult.AUTHORITATIVE if valid else TraceResult.REJECTED,
            reason_code="reviewed_envelope_integrity_satisfied" if valid else "reviewed_envelope_integrity_failed",
            score=Ratio(Decimal("1" if valid else "0")),
        )


@dataclass(frozen=True, slots=True)
class ReviewedEnvelopeDecisionTracePolicy(DeclarativeTracePolicy):
    assertion: VersionedTraceRef = field(
        default_factory=lambda: VersionedTraceRef("review", "reviewed-statement-envelope", "1")
    )
    authority: TraceAuthorityProfile = field(
        default_factory=lambda: _authority(
            tier="CODE-ONLY", proof_kind="exact", provenance="manual", execution_stage="manual.adjudication"
        )
    )
    causality: TraceCausality = TraceCausality.MANIFEST

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        valid = (
            any(p.target.kind == "statement_extraction_result" for p in parents)
            and any(p.reason_code == "reviewed_envelope_operator_confirmed" for p in parents)
            and any(p.reason_code == "reviewed_envelope_integrity_satisfied" for p in parents)
        )
        return TraceDecisionOutcome(
            result=TraceResult.AUTHORITATIVE if valid else TraceResult.REJECTED,
            reason_code="reviewed_envelope_confirmed" if valid else "reviewed_envelope_parents_invalid",
            score=Ratio(Decimal("1" if valid else "0")),
        )


def reviewed_envelope_trace_policies() -> tuple[
    ReviewedEnvelopeInvariantTracePolicy, ReviewedEnvelopeDecisionTracePolicy
]:
    return ReviewedEnvelopeInvariantTracePolicy(), ReviewedEnvelopeDecisionTracePolicy()


async def _load_owned_source_record(
    db: AsyncSession, statement: StatementSummary
) -> StatementExtractionResultRecord | None:
    if statement.current_extraction_result_id is None:
        return None
    rec = await db.get(StatementExtractionResultRecord, statement.current_extraction_result_id)
    if rec is None or rec.user_id != statement.user_id or rec.statement_id != statement.id:
        return None
    return rec


async def persist_statement_extraction_result(
    db: AsyncSession,
    *,
    statement: StatementSummary,
    result: StatementExtractionResult,
    source_trace_record_id: UUID,
) -> StatementExtractionResultRecord:
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
        found = (
            await db.execute(
                select(StatementExtractionResultRecord).where(
                    StatementExtractionResultRecord.user_id == statement.user_id,
                    StatementExtractionResultRecord.statement_id == statement.id,
                    StatementExtractionResultRecord.content_digest == result.content_digest,
                )
            )
        ).scalar_one_or_none()
        if found is None:
            raise RuntimeError("source-result conflict did not expose a canonical winner") from None
        source_record = found
    if source_record.payload != payload:
        raise ValueError("statement extraction result digest collision")

    previous_id = statement.current_extraction_result_id
    if previous_id != source_record.id:
        statement.current_extraction_result_id = source_record.id
        if previous_id is not None and result.requires_review:
            statement.account_id = None
            statement.currency = result.statement_currency
            statement.period_start, statement.period_end = result.period_start, result.period_end
            if len(result.balances) == 1:
                bal = result.balances[0]
                statement.currency = statement.currency or bal.currency
                statement.opening_balance, statement.closing_balance = bal.opening, bal.closing
            else:
                statement.opening_balance = statement.closing_balance = None
            statement.manual_opening_balance = None
            statement.status = BankStatementStatus.PARSED
            statement.stage1_status = Stage1Status.PENDING_REVIEW
            statement.balance_validated = result.balance_validated
            statement.validation_error = "Source facts require reviewer confirmation: " + ", ".join(
                result.missing_required_facts
            )
    elif (
        cur_env := await current_reviewed_statement_envelope(db, user_id=statement.user_id, statement_id=statement.id)
    ) is not None:
        _apply_envelope_to_statement(statement, cur_env)
    await db.flush()
    return source_record


async def current_reviewed_statement_envelope(
    db: AsyncSession, *, user_id: UUID, statement_id: UUID
) -> ReviewedStatementEnvelope | None:
    statement = await db.get(StatementSummary, statement_id)
    if statement is None or statement.user_id != user_id or statement.current_extraction_result_id is None:
        return None
    return (
        await db.execute(
            select(ReviewedStatementEnvelope)
            .where(
                ReviewedStatementEnvelope.user_id == user_id,
                ReviewedStatementEnvelope.statement_id == statement.id,
                ReviewedStatementEnvelope.source_result_id == statement.current_extraction_result_id,
            )
            .order_by(desc(ReviewedStatementEnvelope.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_current_statement_extraction_result(
    db: AsyncSession, *, user_id: UUID, statement_id: UUID
) -> StatementExtractionResult | None:
    statement = await db.get(StatementSummary, statement_id)
    if statement is None or statement.user_id != user_id:
        return None
    source_record = await _load_owned_source_record(db, statement)
    return None if source_record is None else StatementExtractionResult.from_payload(source_record.payload)


async def require_current_statement_envelope_trust(db: AsyncSession, *, statement: StatementSummary) -> None:
    if statement.current_extraction_result_id is None:
        return
    source_record = await _load_owned_source_record(db, statement)
    if source_record is None:
        raise ValueError("Statement current source result is unavailable")
    source_result = StatementExtractionResult.from_payload(source_record.payload)
    envelope = await current_reviewed_statement_envelope(db, user_id=statement.user_id, statement_id=statement.id)

    if not source_result.requires_review and envelope is None:
        _require_projection_matches_source(statement, source_result)
        if supports_reviewed_statement_envelope(source_result):
            raise ValueError("Current source requires explicit human confirmation before posting")
        return
    if not supports_reviewed_statement_envelope(source_result):
        raise ValueError(
            "Current source result has facts that this statement-envelope review cannot confirm: "
            + ", ".join(source_result.missing_required_facts)
        )
    if envelope is None:
        raise ValueError(
            "Current source facts require an explicit reviewed envelope before posting: "
            + ", ".join(source_result.missing_required_facts)
        )
    if statement.manual_opening_balance is not None:
        raise ValueError("Manual opening-balance override cannot replace a reviewed statement envelope")
    attrs = ("account_id", "currency", "period_start", "period_end", "opening_balance", "closing_balance")
    if tuple(getattr(statement, a) for a in attrs) != tuple(getattr(envelope, a) for a in attrs):
        raise ValueError("Statement projection diverges from its current reviewed envelope")
    from src.extraction.extension.statement_contribution import resolve_statement_contribution

    contribution = await resolve_statement_contribution(db, user_id=statement.user_id, statement_id=statement.id)
    if contribution.state != "authoritative" or contribution.decision is None:
        raise ValueError("Current human source confirmation is no longer authoritative")


def _require_projection_matches_source(statement: StatementSummary, source_result: StatementExtractionResult) -> None:
    if len(source_result.balances) != 1:
        return
    bal = source_result.balances[0]
    src = (
        source_result.statement_currency or bal.currency,
        source_result.period_start,
        source_result.period_end,
        bal.opening,
        bal.closing,
    )
    proj = (
        statement.currency,
        statement.period_start,
        statement.period_end,
        statement.opening_balance,
        statement.closing_balance,
    )
    if proj != src:
        raise ValueError("Statement projection diverges from its current source result")


def _apply_envelope_to_statement(statement: StatementSummary, envelope: ReviewedStatementEnvelope) -> None:
    statement.account_id = envelope.account_id
    statement.currency = envelope.currency
    statement.period_start, statement.period_end = envelope.period_start, envelope.period_end
    statement.opening_balance, statement.closing_balance = envelope.opening_balance, envelope.closing_balance
    statement.manual_opening_balance = None
    statement.status = BankStatementStatus.PARSED
    statement.stage1_status = Stage1Status.PENDING_REVIEW
    statement.balance_validated = True
    statement.validation_error = None


async def confirm_reviewed_statement_envelope(
    db: AsyncSession,
    *,
    user_id: UUID,
    statement_id: UUID,
    command: ReviewedStatementEnvelopeCommand,
    trace_emitter: TraceEmitter,
) -> ReviewedStatementEnvelope:
    statement = (
        await db.execute(
            select(StatementSummary)
            .where(StatementSummary.id == statement_id, StatementSummary.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if statement is None:
        raise ValueError("Statement not found or access denied")
    if statement.status is BankStatementStatus.RETIRED:
        raise ValueError("Retired statement cannot receive a new source confirmation")
    # One guard before both branches below, the first confirmation and the replay of the same command: each
    # writes PARSED. A rerun leaves the current extraction result in place, so the old digest still matches.
    # A confirmation that wrote PARSED over a run would let an approve post entries that the finalize of the
    # run then overwrites.
    if statement.status is BankStatementStatus.PARSING or await get_active_run(db, statement.id) is not None:
        raise ValueError("Statement is parsing again. Reload the statement before confirming its envelope.")
    if statement.current_extraction_result_id is None:
        raise ValueError("Statement has no current source result; reparse before confirming its envelope")

    source_record = await _load_owned_source_record(db, statement)
    if source_record is None:
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
        await db.execute(select(Account).where(Account.id == command.account_id, Account.user_id == user_id))
    ).scalar_one_or_none()
    if account is None or not account.is_active or account.type is not AccountType.ASSET:
        raise ValueError("A user-owned active asset custody account is required")
    if account.currency.strip().upper() != command.currency:
        raise ValueError("Custody account currency must match the confirmed statement currency")
    if (
        source_result.source_type is StatementSourceType.BANK
        and source_result.institution
        and source_result.account_last4
    ):
        await resolve_bank_custody_account(
            db,
            user_id=user_id,
            institution=source_result.institution,
            account_last4=source_result.account_last4,
            currency=command.currency,
            account_id=account.id,
        )

    existing = (
        await db.execute(
            select(ReviewedStatementEnvelope).where(
                ReviewedStatementEnvelope.user_id == user_id,
                ReviewedStatementEnvelope.statement_id == statement.id,
                ReviewedStatementEnvelope.command_digest == command.digest,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        _apply_envelope_to_statement(statement, existing)
        await db.flush()
        return existing

    if (await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement.id)) is not None:
        raise ReviewedStatementEnvelopeConflict(
            "A different reviewed envelope already confirms this source result; reparse before replacing it"
        )
    previous = (
        await db.execute(
            select(ReviewedStatementEnvelope)
            .where(ReviewedStatementEnvelope.user_id == user_id, ReviewedStatementEnvelope.statement_id == statement.id)
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
    _apply_envelope_to_statement(statement, envelope)
    await db.flush()
    return envelope


def _validate_command_against_source(
    command: ReviewedStatementEnvelopeCommand, source_result: StatementExtractionResult
) -> None:
    if source_result.evidence_type is not StatementEvidenceType.TRANSACTION_LEDGER:
        raise ValueError("Only transaction-ledger sources accept a cash statement envelope confirmation")
    declared: dict[str, object] = {
        "currency": source_result.statement_currency,
        "period_start": source_result.period_start,
        "period_end": source_result.period_end,
    }
    if len(source_result.balances) == 1:
        bal = source_result.balances[0]
        declared.update(
            currency=source_result.statement_currency or bal.currency,
            opening_balance=bal.opening,
            closing_balance=bal.closing,
        )
    for name, value in declared.items():
        if value is not None and getattr(command, name) != value:
            raise ValueError(f"Confirmed {name} must match the declared source fact")
    currencies = {txn.currency for txn in source_result.transactions}
    if None in currencies or any(c != command.currency for c in currencies):
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
    target = VersionedTraceRef("reviewed_statement_envelope", str(source_result.result_id), command.digest)
    scope = TraceScope.tenant(user_id)
    operator = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("review", "operator-envelope-confirmation", "1"),
        authority=_authority(
            tier="CODE-LED", proof_kind="exact", provenance="manual", execution_stage="manual.adjudication"
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
        assertion=VersionedTraceRef("invariant", "reviewed-envelope-command-validation", "1"),
        authority=_authority(
            tier="CODE-ONLY", proof_kind="exact", provenance="deterministic", execution_stage="product.runtime"
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
