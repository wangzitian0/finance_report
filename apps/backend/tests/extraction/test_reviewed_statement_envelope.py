"""Proof for the source-result -> reviewed-envelope confirmation boundary (#1912)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

from src.audit import SqlTraceRecordRepository, TraceEmitter
from src.audit.orm.trace_record import TraceRecordParentRow
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
    ReviewedStatementEnvelopeConflict,
    confirm_reviewed_statement_envelope,
    current_reviewed_statement_envelope,
    persist_statement_extraction_result,
)
from src.extraction.orm.reviewed_statement_envelope import (
    ReviewedStatementEnvelope,
    StatementExtractionResultRecord,
)
from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType
from tests.factories import UserFactory

pytestmark = pytest.mark.asyncio


def _missing_source_result(
    *, source_digest: str, transaction_currency: str | None = "SGD"
) -> StatementExtractionResult:
    return StatementExtractionResult.create(
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
                currency=transaction_currency,
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
            intake_mode="csv",
            method=ExtractionMethod.DETERMINISTIC,
            provider="csv-parser",
            model="csv-parser@1",
        ),
        statement_currency=None,
    )


def _command(*, account_id, source_result_digest: str, closing: Decimal = Decimal("110.00")):
    return ReviewedStatementEnvelopeCommand(
        source_result_digest=source_result_digest,
        account_id=account_id,
        currency="SGD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=closing,
        rationale="CSV export omits its statement header and balance summary.",
    )


async def _seed_statement_source_and_account(
    db,
    test_user,
    *,
    source_digest: str,
    transaction_currency: str | None = "SGD",
):
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
    )
    account = Account(
        user_id=test_user.id,
        name="Example Bank - SGD",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add_all((statement, account))
    await db.flush()

    result = _missing_source_result(
        source_digest=source_digest,
        transaction_currency=transaction_currency,
    )
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
    await db.commit()
    return statement, account, result, source_record


async def _confirm(db, *, user_id, statement_id, command):
    return await confirm_reviewed_statement_envelope(
        db,
        user_id=user_id,
        statement_id=statement_id,
        command=command,
        trace_emitter=TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())),
    )


async def test_AC_extraction_reviewed_envelope_1_preserves_source_absence_until_typed_command(db, test_user):
    """AC-extraction.reviewed-envelope.1: confirmation adds review facts, never source defaults."""
    statement, account, result, _source_record = await _seed_statement_source_and_account(
        db, test_user, source_digest="a" * 64
    )
    raw_payload = result.to_payload()

    envelope = await _confirm(
        db,
        user_id=test_user.id,
        statement_id=statement.id,
        command=_command(account_id=account.id, source_result_digest=result.content_digest),
    )

    assert result.to_payload() == raw_payload
    assert result.missing_required_facts == ("statement_currency", "period", "balances")
    effective = await current_reviewed_statement_envelope(db, user_id=test_user.id, statement_id=statement.id)
    assert effective is not None
    assert effective.id == envelope.id
    assert effective.currency == "SGD"
    assert effective.opening_balance == Decimal("100.00")


async def test_AC_extraction_reviewed_envelope_2_rejects_invalid_or_stale_commands_atomically(db, test_user):
    """AC-extraction.reviewed-envelope.2: invalid confirmation cannot create trusted facts."""
    statement, account, result, _source_record = await _seed_statement_source_and_account(
        db, test_user, source_digest="b" * 64
    )
    stale = _command(account_id=account.id, source_result_digest="c" * 64)

    with pytest.raises(ValueError, match="current source result"):
        await _confirm(db, user_id=test_user.id, statement_id=statement.id, command=stale)

    with pytest.raises(ValueError, match="ISO"):
        replace(_command(account_id=account.id, source_result_digest=result.content_digest), currency="SG")
    with pytest.raises(ValueError, match="period_start"):
        ReviewedStatementEnvelopeCommand(
            source_result_digest=result.content_digest,
            account_id=account.id,
            currency="SGD",
            period_start=date(2026, 2, 1),
            period_end=date(2026, 1, 1),
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("110.00"),
            rationale="Invalid period must never be recorded.",
        )
    with pytest.raises(TypeError, match="finite Decimal"):
        ReviewedStatementEnvelopeCommand(
            source_result_digest=result.content_digest,
            account_id=account.id,
            currency="SGD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            opening_balance=Decimal("NaN"),
            closing_balance=Decimal("110.00"),
            rationale="Invalid Decimal must never be recorded.",
        )
    with pytest.raises(ValueError, match="must equal closing"):
        await _confirm(
            db,
            user_id=test_user.id,
            statement_id=statement.id,
            command=_command(
                account_id=account.id,
                source_result_digest=result.content_digest,
                closing=Decimal("111.00"),
            ),
        )

    unsupported_statement, unsupported_account, unsupported_result, _ = await _seed_statement_source_and_account(
        db,
        test_user,
        source_digest="c" * 64,
        transaction_currency=None,
    )
    with pytest.raises(ValueError, match="cannot be confirmed with a cash statement envelope"):
        await _confirm(
            db,
            user_id=test_user.id,
            statement_id=unsupported_statement.id,
            command=_command(
                account_id=unsupported_account.id,
                source_result_digest=unsupported_result.content_digest,
            ),
        )

    other_user = await UserFactory.create_async(db)
    other_account = Account(
        user_id=other_user.id,
        name="Other user account",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(other_account)
    await db.flush()
    with pytest.raises(ValueError, match="custody account"):
        await _confirm(
            db,
            user_id=test_user.id,
            statement_id=statement.id,
            command=_command(account_id=other_account.id, source_result_digest=result.content_digest),
        )

    count = await db.scalar(select(func.count()).select_from(ReviewedStatementEnvelope))
    assert count == 0
    await db.refresh(statement)
    assert statement.current_extraction_result_id is not None
    assert statement.currency is None
    assert statement.opening_balance is None


async def test_AC_extraction_reviewed_envelope_3_appends_trace_and_preserves_source_payload(db, test_user):
    """AC-extraction.reviewed-envelope.3: source and human decision remain separately auditable."""
    statement, account, result, source_record = await _seed_statement_source_and_account(
        db, test_user, source_digest="d" * 64
    )
    source_payload = dict(source_record.payload)

    envelope = await _confirm(
        db,
        user_id=test_user.id,
        statement_id=statement.id,
        command=_command(account_id=account.id, source_result_digest=result.content_digest),
    )

    assert envelope.source_result_id == source_record.id
    assert envelope.review_trace_record_id is not None
    assert source_record.payload == source_payload
    parent_ids = await db.scalars(
        select(TraceRecordParentRow.parent_id).where(TraceRecordParentRow.record_id == envelope.review_trace_record_id)
    )
    assert source_record.source_trace_record_id in set(parent_ids)
    await db.refresh(statement)
    assert statement.extraction_metadata is None
    assert statement.currency == "SGD"
    assert statement.account_id == account.id


async def test_AC_extraction_reviewed_envelope_5_reparse_and_retry_are_explicit(db, test_user):
    """AC-extraction.reviewed-envelope.5: no confirmation silently crosses a source version."""
    statement, account, first_result, _source_record = await _seed_statement_source_and_account(
        db, test_user, source_digest="e" * 64
    )
    command = _command(account_id=account.id, source_result_digest=first_result.content_digest)
    first = await _confirm(db, user_id=test_user.id, statement_id=statement.id, command=command)
    retry = await _confirm(db, user_id=test_user.id, statement_id=statement.id, command=command)
    assert retry.id == first.id

    with pytest.raises(ReviewedStatementEnvelopeConflict):
        await _confirm(
            db,
            user_id=test_user.id,
            statement_id=statement.id,
            command=replace(command, rationale="A different reviewer rationale must not overwrite this fact."),
        )

    reparsed = _missing_source_result(source_digest="f" * 64)
    trace_records = build_extraction_trace_records(
        reparsed,
        user_id=test_user.id,
        execution_id=f"test:{statement.id}:result:{reparsed.result_id}",
        occurred_at=datetime.now(UTC),
    )
    emitter = TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry()))
    await emitter.emit_many(trace_records)
    await persist_statement_extraction_result(
        db,
        statement=statement,
        result=reparsed,
        source_trace_record_id=trace_records[0].record_id,
    )
    assert await current_reviewed_statement_envelope(db, user_id=test_user.id, statement_id=statement.id) is None

    successor = await _confirm(
        db,
        user_id=test_user.id,
        statement_id=statement.id,
        command=_command(account_id=account.id, source_result_digest=reparsed.content_digest),
    )
    assert successor.supersedes_id == first.id


async def test_AC_extraction_reviewed_envelope_7_database_rejects_fact_mutation(db, test_user):
    """AC-extraction.reviewed-envelope.7: ORM bypass cannot rewrite audit facts."""
    statement, account, result, source_record = await _seed_statement_source_and_account(
        db, test_user, source_digest="a" * 64
    )
    envelope = await _confirm(
        db,
        user_id=test_user.id,
        statement_id=statement.id,
        command=_command(account_id=account.id, source_result_digest=result.content_digest),
    )
    await db.commit()

    with pytest.raises(DBAPIError, match="append-only"):
        async with db.begin_nested():
            await db.execute(
                update(StatementExtractionResultRecord)
                .where(StatementExtractionResultRecord.id == source_record.id)
                .values(producer_version="tampered")
            )

    with pytest.raises(DBAPIError, match="append-only"):
        async with db.begin_nested():
            await db.execute(delete(ReviewedStatementEnvelope).where(ReviewedStatementEnvelope.id == envelope.id))
