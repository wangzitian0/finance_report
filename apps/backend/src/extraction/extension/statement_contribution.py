"""Resolve immutable statement source facts into package-facing contributions."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import SqlTraceRecordRepository, TraceLineage, TraceResult, TraceScope, VersionedTraceRef
from src.extraction.base.contribution import ResolvedStatementContribution
from src.extraction.base.result import StatementExtractionResult
from src.extraction.extension.extraction_trace import ExtractionPromotionTracePolicy, extraction_trace_policy_registry
from src.extraction.extension.reviewed_statement_envelope import (
    ReviewedEnvelopeDecisionTracePolicy,
    current_reviewed_statement_envelope,
)
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.extraction.orm.statement_summary import StatementSummary


def _unproven(
    *,
    statement_id: UUID,
    reason_code: str,
    source_result_id: UUID | None = None,
    source_result: StatementExtractionResult | None = None,
    effective_period_start: date | None = None,
    effective_period_end: date | None = None,
) -> ResolvedStatementContribution:
    return ResolvedStatementContribution(
        statement_id=statement_id,
        source_result_id=source_result_id,
        source_result=source_result,
        effective_period_start=effective_period_start,
        effective_period_end=effective_period_end,
        state="unproven",
        reason_code=reason_code,
        decision_id=None,
    )


async def resolve_statement_contribution(
    db: AsyncSession,
    *,
    user_id: UUID,
    statement_id: UUID,
) -> ResolvedStatementContribution:
    """Resolve exactly one current statement source result, never a projection.

    A complete result requires its current extraction-promotion decision. A
    source which requires review instead requires its current reviewed-envelope
    decision. Both checks pin the target version, so a reparse or decision
    supersession cannot authorize an older source payload.
    """
    statement = await db.get(StatementSummary, statement_id)
    if statement is None or statement.user_id != user_id:
        return _unproven(statement_id=statement_id, reason_code="missing_statement")
    if statement.current_extraction_result_id is None:
        return _unproven(statement_id=statement.id, reason_code="missing_current_source_result")

    source_record = await db.get(StatementExtractionResultRecord, statement.current_extraction_result_id)
    if source_record is None or source_record.user_id != user_id or source_record.statement_id != statement.id:
        return _unproven(statement_id=statement.id, reason_code="missing_current_source_result")
    try:
        source_result = StatementExtractionResult.from_payload(source_record.payload)
    except (TypeError, ValueError):
        return _unproven(
            statement_id=statement.id,
            source_result_id=source_record.id,
            reason_code="invalid_current_source_result",
        )
    if source_result.content_digest != source_record.content_digest:
        return _unproven(
            statement_id=statement.id,
            source_result_id=source_record.id,
            source_result=source_result,
            effective_period_start=source_result.period_start,
            effective_period_end=source_result.period_end,
            reason_code="source_result_digest_mismatch",
        )

    repository = SqlTraceRecordRepository(db, extraction_trace_policy_registry())
    scope = TraceScope.tenant(user_id)
    effective_period_start: date | None = source_result.period_start
    effective_period_end: date | None = source_result.period_end
    if source_result.requires_review:
        envelope = await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement.id)
        if envelope is None or envelope.source_result_id != source_record.id:
            return _unproven(
                statement_id=statement.id,
                source_result_id=source_record.id,
                source_result=source_result,
                effective_period_start=source_result.period_start,
                effective_period_end=source_result.period_end,
                reason_code="missing_reviewed_envelope",
            )
        target = VersionedTraceRef(
            kind="reviewed_statement_envelope",
            id=str(source_result.result_id),
            version=envelope.command_digest,
        )
        assertion = ReviewedEnvelopeDecisionTracePolicy().assertion
        expected_decision_id = envelope.review_trace_record_id
        effective_period_start = envelope.period_start
        effective_period_end = envelope.period_end
    else:
        target = VersionedTraceRef(
            kind="statement_extraction_result",
            id=str(source_result.result_id),
            version=source_result.content_digest,
        )
        assertion = ExtractionPromotionTracePolicy().assertion
        expected_decision_id = None

    decision = await repository.current_decision(scope, TraceLineage.from_refs(target, assertion))
    if decision is None:
        return _unproven(
            statement_id=statement.id,
            source_result_id=source_record.id,
            source_result=source_result,
            effective_period_start=source_result.period_start,
            effective_period_end=source_result.period_end,
            reason_code="missing_current_decision",
        )
    if decision.target != target or (expected_decision_id is not None and decision.record_id != expected_decision_id):
        return _unproven(
            statement_id=statement.id,
            source_result_id=source_record.id,
            source_result=source_result,
            effective_period_start=source_result.period_start,
            effective_period_end=source_result.period_end,
            reason_code="target_mismatched_decision",
        )
    if decision.result is not TraceResult.AUTHORITATIVE:
        return _unproven(
            statement_id=statement.id,
            source_result_id=source_record.id,
            source_result=source_result,
            effective_period_start=source_result.period_start,
            effective_period_end=source_result.period_end,
            reason_code="non_authoritative_decision",
        )
    return ResolvedStatementContribution(
        statement_id=statement.id,
        source_result_id=source_record.id,
        source_result=source_result,
        effective_period_start=effective_period_start,
        effective_period_end=effective_period_end,
        state="authoritative",
        reason_code=None,
        decision_id=decision.record_id,
    )


async def list_statement_contributions(
    db: AsyncSession,
    *,
    user_id: UUID,
    as_of: date,
) -> tuple[ResolvedStatementContribution, ...]:
    """Resolve only current source results whose statement period is in scope."""
    statement_ids = (
        (
            await db.execute(
                select(StatementSummary.id)
                .where(StatementSummary.user_id == user_id)
                .where(StatementSummary.current_extraction_result_id.is_not(None))
                .order_by(StatementSummary.id)
            )
        )
        .scalars()
        .all()
    )
    contributions = [
        await resolve_statement_contribution(db, user_id=user_id, statement_id=statement_id)
        for statement_id in statement_ids
    ]
    return tuple(
        contribution
        for contribution in contributions
        if contribution.effective_period_end is not None and contribution.effective_period_end <= as_of
    )
