"""Resolve immutable statement source facts into package-facing contributions."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    SqlTraceRecordRepository,
    TraceDecisionRef,
    TraceLineage,
    TraceResult,
    TraceScope,
    VersionedTraceRef,
)
from src.extraction.base.contribution import ResolvedStatementContribution
from src.extraction.base.result import StatementEvidenceType, StatementExtractionResult, StatementSourceType
from src.extraction.extension.extraction_trace import ExtractionPromotionTracePolicy, extraction_trace_policy_registry
from src.extraction.extension.reviewed_statement_envelope import (
    ReviewedEnvelopeDecisionTracePolicy,
    current_reviewed_statement_envelope,
)
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.extraction.orm.statement_summary import StatementSummary


def _unproven(
    statement_id: UUID,
    reason_code: str,
    *,
    source_result_id: UUID | None = None,
    source_result: StatementExtractionResult | None = None,
    effective_period_start: date | None = None,
    effective_period_end: date | None = None,
    source_document_id: UUID | None = None,
    account_id: UUID | None = None,
) -> ResolvedStatementContribution:
    return ResolvedStatementContribution(
        statement_id=statement_id,
        source_result_id=source_result_id,
        source_result=source_result,
        effective_period_start=effective_period_start,
        effective_period_end=effective_period_end,
        state="unproven",
        reason_code=reason_code,
        decision=None,
        source_document_id=source_document_id,
        account_id=account_id,
    )


async def resolve_statement_contribution(
    db: AsyncSession, *, user_id: UUID, statement_id: UUID
) -> ResolvedStatementContribution:
    """Resolve one current statement source result into an authoritative or unproven contribution."""
    statement = await db.get(StatementSummary, statement_id)
    if statement is None or statement.user_id != user_id:
        return _unproven(statement_id, "missing_statement")
    doc_id = statement.uploaded_document_id
    if statement.current_extraction_result_id is None:
        return _unproven(statement.id, "missing_current_source_result", source_document_id=doc_id, account_id=statement.account_id)

    source_record = await db.get(StatementExtractionResultRecord, statement.current_extraction_result_id)
    if source_record is None or source_record.user_id != user_id or source_record.statement_id != statement.id:
        return _unproven(statement.id, "missing_current_source_result", source_document_id=doc_id, account_id=statement.account_id)
    try:
        source_result = StatementExtractionResult.from_payload(source_record.payload)
    except (KeyError, TypeError, ValueError):
        return _unproven(
            statement.id,
            "invalid_current_source_result",
            source_result_id=source_record.id,
            source_document_id=doc_id,
            account_id=statement.account_id,
        )

    statement_id_val = statement.id
    initial_account_id = statement.account_id
    source_record_id = source_record.id

    def fail(
        reason: str,
        *,
        acct: UUID | None = initial_account_id,
        ps: date | None = source_result.period_start,
        pe: date | None = source_result.period_end,
    ) -> ResolvedStatementContribution:
        return _unproven(
            statement_id_val,
            reason,
            source_result_id=source_record_id,
            source_result=source_result,
            effective_period_start=ps,
            effective_period_end=pe,
            source_document_id=doc_id,
            account_id=acct,
        )

    if source_result.content_digest != source_record.content_digest:
        return fail("source_result_digest_mismatch")

    repository = SqlTraceRecordRepository(db, extraction_trace_policy_registry())
    scope = TraceScope.tenant(user_id)
    eff_start: date | None = source_result.period_start
    eff_end: date | None = source_result.period_end
    account_id = statement.account_id
    envelope = await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement.id)
    if source_result.requires_review or envelope is not None:
        if envelope is None or envelope.source_result_id != source_record.id:
            return fail("missing_reviewed_envelope")
        if statement.account_id != envelope.account_id:
            return fail("custody_account_mismatch", acct=None)
        account_id = envelope.account_id
        target = VersionedTraceRef("reviewed_statement_envelope", str(source_result.result_id), envelope.command_digest)
        assertion = ReviewedEnvelopeDecisionTracePolicy().assertion
        expected_decision_id = envelope.review_trace_record_id
        eff_start, eff_end = envelope.period_start, envelope.period_end
    else:
        target = VersionedTraceRef(
            "statement_extraction_result", str(source_result.result_id), source_result.content_digest
        )
        assertion = ExtractionPromotionTracePolicy().assertion
        expected_decision_id = None

    decision = await repository.current_decision(scope, TraceLineage.from_refs(target, assertion))
    if decision is None:
        return fail("missing_current_decision", acct=account_id)
    if decision.target != target or (expected_decision_id is not None and decision.record_id != expected_decision_id):
        return fail("target_mismatched_decision", acct=account_id)
    if decision.result is not TraceResult.AUTHORITATIVE:
        return fail("non_authoritative_decision", acct=account_id)
    if (
        source_result.source_type is StatementSourceType.BANK
        or source_result.evidence_type is StatementEvidenceType.TRANSACTION_LEDGER
    ) and account_id is None:
        return fail("missing_custody_account", acct=None, ps=eff_start, pe=eff_end)
    return ResolvedStatementContribution(
        statement_id=statement.id,
        source_result_id=source_record.id,
        source_result=source_result,
        effective_period_start=eff_start,
        effective_period_end=eff_end,
        state="authoritative",
        reason_code=None,
        decision=TraceDecisionRef(decision.record_id, decision.target, decision.assertion),
        source_document_id=doc_id,
        account_id=account_id,
    )


async def list_statement_contributions(
    db: AsyncSession, *, user_id: UUID, as_of: date
) -> tuple[ResolvedStatementContribution, ...]:
    statement_ids = (
        (
            await db.execute(
                select(StatementSummary.id)
                .where(StatementSummary.user_id == user_id, StatementSummary.current_extraction_result_id.is_not(None))
                .order_by(StatementSummary.id)
            )
        )
        .scalars()
        .all()
    )
    contributions = [
        await resolve_statement_contribution(db, user_id=user_id, statement_id=sid) for sid in statement_ids
    ]
    return tuple(
        c for c in contributions if c.effective_period_end is not None and c.effective_period_end <= as_of
    )
