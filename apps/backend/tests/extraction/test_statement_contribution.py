"""Statement source contributions for package consumers (#1681)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from src.audit import SqlTraceRecordRepository, TraceEmitter
from src.extraction.base.result import (
    ExtractedPositionFact,
    ExtractedTransactionFact,
    ExtractionMethod,
    SourceProvenance,
    StatementEvidenceType,
    StatementExtractionResult,
    StatementSourceType,
)
from src.extraction.base.reviewed_statement_envelope import ReviewedStatementEnvelopeCommand
from src.extraction.extension.extraction_trace import build_extraction_trace_records, extraction_trace_policy_registry
from src.extraction.extension.reviewed_statement_envelope import (
    confirm_reviewed_statement_envelope,
    persist_statement_extraction_result,
)
from src.extraction.extension.statement_contribution import (
    list_statement_contributions,
    resolve_statement_contribution,
)
from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType

pytestmark = pytest.mark.asyncio


def _result(*, source_digest: str, evidence_type: StatementEvidenceType) -> StatementExtractionResult:
    position_facts = (
        ExtractedPositionFact(
            fact_id="position-aapl",
            symbol="AAPL",
            quantity=Decimal("10"),
            market_value=Decimal("1855.00"),
            currency="USD",
            confidence=Decimal("0.93"),
        ),
    )
    transaction_facts = (
        ExtractedTransactionFact(
            fact_id="transaction-1",
            transaction_date=date(2026, 1, 2),
            description="Salary",
            amount=Decimal("10.00"),
            direction="IN",
            currency="SGD",
            balance_after=Decimal("110.00"),
            confidence=Decimal("0.93"),
        ),
    )
    if evidence_type is StatementEvidenceType.POSITION_SNAPSHOT:
        return StatementExtractionResult.create(
            producer_version="brokerage-parser@1",
            source_content_digest=source_digest,
            source_type=StatementSourceType.BROKERAGE,
            evidence_type=evidence_type,
            institution="Example Broker",
            account_last4="1234",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            balances=(),
            transactions=(),
            positions=position_facts,
            confidence=Decimal("0.93"),
            balance_validated=True,
            warnings=(),
            review_reasons=(),
            provenance=SourceProvenance(
                intake_mode="csv",
                method=ExtractionMethod.DETERMINISTIC,
                provider="brokerage-parser",
                model="brokerage-parser@1",
            ),
            statement_currency="USD",
        )
    return StatementExtractionResult.create(
        producer_version="csv-parser@1",
        source_content_digest=source_digest,
        source_type=StatementSourceType.BANK,
        evidence_type=evidence_type,
        institution="Example Bank",
        account_last4="1234",
        period_start=None,
        period_end=None,
        balances=(),
        transactions=transaction_facts,
        positions=(),
        confidence=Decimal("0.93"),
        balance_validated=None,
        warnings=(),
        review_reasons=("source facts require confirmation",),
        provenance=SourceProvenance(
            intake_mode="csv",
            method=ExtractionMethod.DETERMINISTIC,
            provider="csv-parser",
            model="csv-parser@1",
        ),
        statement_currency=None,
    )


async def _seed_current_result(db, test_user, *, result: StatementExtractionResult):
    statement = StatementSummary(
        user_id=test_user.id,
        file_hash=result.source_content_digest,
        institution=result.institution,
        account_last4=result.account_last4,
        currency=result.statement_currency,
        period_start=result.period_start,
        period_end=result.period_end,
        opening_balance=None,
        closing_balance=None,
        status=BankStatementStatus.PARSED,
    )
    db.add(statement)
    await db.flush()
    trace_records = build_extraction_trace_records(
        result,
        user_id=test_user.id,
        execution_id=f"test:{statement.id}:result:{result.result_id}",
        occurred_at=datetime.now(UTC),
    )
    emitter = TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry()))
    await emitter.emit_many(trace_records)
    source_record = await persist_statement_extraction_result(
        db,
        statement=statement,
        result=result,
        source_trace_record_id=trace_records[0].record_id,
    )
    return statement, source_record, emitter


async def test_AC_extraction_statement_contribution_1_preserves_exact_position_source_result(db, test_user):
    """AC-extraction.statement-contribution.1: source facts cross the package boundary intact."""
    result = _result(source_digest="a" * 64, evidence_type=StatementEvidenceType.POSITION_SNAPSHOT)
    statement, source_record, _emitter = await _seed_current_result(db, test_user, result=result)

    contribution = await resolve_statement_contribution(db, user_id=test_user.id, statement_id=statement.id)
    listed = await list_statement_contributions(db, user_id=test_user.id, as_of=date(2026, 1, 31))

    assert contribution.is_authoritative
    assert contribution.source_result_id == source_record.id
    assert contribution.source_result is not None
    assert contribution.source_result.content_digest == result.content_digest
    assert contribution.source_result.positions == result.positions
    assert contribution.effective_period_start == date(2026, 1, 1)
    assert contribution.effective_period_end == date(2026, 1, 31)
    assert contribution.input_refs == (f"statement_result:{source_record.id}",)
    assert listed == (contribution,)


async def test_AC_extraction_statement_contribution_2_reviewed_envelope_pins_exact_decision(db, test_user):
    """AC-extraction.statement-contribution.2: an incomplete CSV needs its current review decision."""
    result = _result(source_digest="b" * 64, evidence_type=StatementEvidenceType.TRANSACTION_LEDGER)
    statement, source_record, emitter = await _seed_current_result(db, test_user, result=result)
    account = Account(user_id=test_user.id, name="Example Bank - SGD", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()
    envelope = await confirm_reviewed_statement_envelope(
        db,
        user_id=test_user.id,
        statement_id=statement.id,
        command=ReviewedStatementEnvelopeCommand(
            source_result_digest=result.content_digest,
            account_id=account.id,
            currency="SGD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("110.00"),
            rationale="The CSV has no statement header or balance envelope.",
        ),
        trace_emitter=emitter,
    )

    contribution = await resolve_statement_contribution(db, user_id=test_user.id, statement_id=statement.id)

    assert contribution.is_authoritative
    assert contribution.source_result_id == source_record.id
    assert contribution.decision_id == envelope.review_trace_record_id
    assert contribution.effective_period_start == date(2026, 1, 1)
    assert contribution.effective_period_end == date(2026, 1, 31)
    assert contribution.input_refs == (f"statement_result:{source_record.id}",)


async def test_AC_extraction_statement_contribution_3_fails_closed_without_current_decision(db, test_user):
    """AC-extraction.statement-contribution.3: metadata and source rows cannot grant authority."""
    result = _result(source_digest="c" * 64, evidence_type=StatementEvidenceType.TRANSACTION_LEDGER)
    statement, source_record, _emitter = await _seed_current_result(db, test_user, result=result)

    missing_review = await resolve_statement_contribution(db, user_id=test_user.id, statement_id=statement.id)
    cross_tenant = await resolve_statement_contribution(db, user_id=uuid4(), statement_id=statement.id)

    assert not missing_review.is_authoritative
    assert missing_review.source_result_id == source_record.id
    assert missing_review.reason_code == "missing_reviewed_envelope"
    assert missing_review.decision_id is None
    assert not cross_tenant.is_authoritative
    assert cross_tenant.reason_code == "missing_statement"
