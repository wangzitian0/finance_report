from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.audit import SqlTraceRecordRepository, TraceEmitter
from src.extraction import BankStatementStatus, Stage1Status
from src.extraction.base.result import (
    ExtractedTransactionFact,
    ExtractionMethod,
    SourceProvenance,
    StatementEvidenceType,
    StatementExtractionResult,
    StatementSourceType,
)
from src.extraction.extension.extraction_trace import build_extraction_trace_records, extraction_trace_policy_registry
from src.extraction.extension.reviewed_statement_envelope import (
    ReviewedStatementEnvelopeCommand,
    confirm_reviewed_statement_envelope,
    persist_statement_extraction_result,
    require_current_statement_envelope_trust,
)
from src.extraction.orm.statement_summary import StatementSummary
from tests.extraction._statement_run_helpers import make_account

pytestmark = pytest.mark.asyncio


async def test_AC_extraction_2723_1_same_digest_retry_and_reconfirm_preserve_reviewed_envelope_projection(
    db, test_user
):
    source_digest = "7" * 64
    statement = StatementSummary(
        user_id=test_user.id,
        file_hash=source_digest,
        institution="Example Bank",
        account_last4="1234",
        currency=None,
        period_start=None,
        period_end=None,
        opening_balance=None,
        closing_balance=None,
        status=BankStatementStatus.PARSED,
        stage1_status=Stage1Status.PENDING_REVIEW,
    )
    account = await make_account(db, test_user.id, name="Example Bank - SGD")
    db.add(statement)
    await db.flush()
    result = StatementExtractionResult.create(
        producer_version="csv-parser@1",
        source_content_digest=source_digest,
        source_type=StatementSourceType.BANK,
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        institution="Example Bank",
        account_last4="1234",
        period_start=None,
        period_end=None,
        balances=(),
        transactions=(
            ExtractedTransactionFact(
                fact_id="row-1",
                transaction_date=date(2026, 1, 2),
                description="Salary",
                amount=Decimal("10.00"),
                direction="IN",
                currency="SGD",
                balance_after=None,
                confidence=Decimal("0.90"),
            ),
        ),
        positions=(),
        confidence=Decimal("0.90"),
        balance_validated=None,
        warnings=(),
        review_reasons=("source facts require confirmation",),
        provenance=SourceProvenance(
            intake_mode="csv", method=ExtractionMethod.DETERMINISTIC, provider="csv-parser", model="csv-parser@1"
        ),
        statement_currency=None,
    )
    emitter = TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry()))
    trace_records = build_extraction_trace_records(
        result,
        user_id=test_user.id,
        execution_id=f"test:{statement.id}:result:{result.result_id}",
        occurred_at=datetime.now(UTC),
    )
    await emitter.emit_many(trace_records)
    await persist_statement_extraction_result(
        db, statement=statement, result=result, source_trace_record_id=trace_records[0].record_id
    )
    command = ReviewedStatementEnvelopeCommand(
        source_result_digest=result.content_digest,
        account_id=account.id,
        currency="SGD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("110.00"),
        rationale="CSV export omits its statement header and balance summary.",
    )
    confirmed = await confirm_reviewed_statement_envelope(
        db, user_id=test_user.id, statement_id=statement.id, command=command, trace_emitter=emitter
    )
    await require_current_statement_envelope_trust(db, statement=statement)

    for persist_first, err in ((True, "Balance validation failed"), (False, "Diverged projection")):
        (
            statement.period_start,
            statement.period_end,
            statement.opening_balance,
            statement.closing_balance,
            statement.currency,
            statement.balance_validated,
            statement.validation_error,
        ) = date(2026, 1, 2), date(2026, 1, 2), None, None, "SGD", False, err
        await db.flush()
        if persist_first:
            await persist_statement_extraction_result(
                db, statement=statement, result=result, source_trace_record_id=trace_records[0].record_id
            )
        else:
            assert (
                await confirm_reviewed_statement_envelope(
                    db, user_id=test_user.id, statement_id=statement.id, command=command, trace_emitter=emitter
                )
            ).id == confirmed.id
        assert (
            statement.account_id,
            statement.currency,
            statement.period_start,
            statement.period_end,
            statement.opening_balance,
            statement.closing_balance,
            statement.balance_validated,
            statement.validation_error,
        ) == (account.id, "SGD", date(2026, 1, 1), date(2026, 1, 31), Decimal("100.00"), Decimal("110.00"), True, None)
        await require_current_statement_envelope_trust(db, statement=statement)
