from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

from src.audit import SqlTraceRecordRepository, TraceEmitter
from src.audit.orm.trace_record import TraceRecordParentRow
from src.extraction import BankStatementStatus
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
from src.extraction.orm.reviewed_statement_envelope import ReviewedStatementEnvelope, StatementExtractionResultRecord
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import AccountType
from tests.extraction._statement_run_helpers import make_account
from tests.factories import UserFactory

pytestmark = pytest.mark.asyncio


def _missing_source_result(*, source_digest: str, transaction_currency: str = "SGD"):
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
            intake_mode="csv", method=ExtractionMethod.DETERMINISTIC, provider="csv-parser", model="csv-parser@1"
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
    db, test_user, *, source_digest: str, transaction_currency: str | None = "SGD"
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
    account = await make_account(db, test_user.id, name="Example Bank - SGD", type=AccountType.ASSET)
    db.add(statement)
    await db.flush()
    result = _missing_source_result(source_digest=source_digest, transaction_currency=transaction_currency)
    traces = build_extraction_trace_records(
        result,
        user_id=test_user.id,
        execution_id=f"test:{statement.id}:result:{result.result_id}",
        occurred_at=datetime.now(UTC),
    )
    await TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())).emit_many(traces)
    source_record = await persist_statement_extraction_result(
        db, statement=statement, result=result, source_trace_record_id=traces[0].record_id
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
    statement, account, result, _ = await _seed_statement_source_and_account(db, test_user, source_digest="a" * 64)
    raw_payload = result.to_payload()
    envelope = await _confirm(
        db,
        user_id=test_user.id,
        statement_id=statement.id,
        command=_command(account_id=account.id, source_result_digest=result.content_digest),
    )
    effective = await current_reviewed_statement_envelope(db, user_id=test_user.id, statement_id=statement.id)
    assert (
        result.to_payload(),
        result.missing_required_facts,
        effective is not None,
        effective.id if effective else None,
        effective.currency if effective else None,
        effective.opening_balance if effective else None,
    ) == (raw_payload, ("statement_currency", "period", "balances"), True, envelope.id, "SGD", Decimal("100.00"))


async def test_AC_extraction_reviewed_envelope_2_rejects_invalid_or_stale_commands_atomically(db, test_user):
    statement, account, result, _ = await _seed_statement_source_and_account(db, test_user, source_digest="b" * 64)
    with pytest.raises(ValueError, match="current source result"):
        await _confirm(
            db,
            user_id=test_user.id,
            statement_id=statement.id,
            command=_command(account_id=account.id, source_result_digest="c" * 64),
        )
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
                account_id=account.id, source_result_digest=result.content_digest, closing=Decimal("111.00")
            ),
        )

    unsup_stmt, unsup_acct, _, _ = await _seed_statement_source_and_account(
        db, test_user, source_digest="c" * 64, transaction_currency="SGD"
    )
    unsup_res = StatementExtractionResult.create(
        producer_version="brokerage-parser@1",
        source_content_digest="c" * 64,
        source_type=StatementSourceType.BROKERAGE,
        evidence_type=StatementEvidenceType.POSITION_SNAPSHOT,
        institution="Example Broker",
        account_last4="9999",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        balances=(),
        transactions=(),
        positions=(),
        confidence=Decimal("0.90"),
        balance_validated=None,
        warnings=(),
        review_reasons=("positions missing",),
        provenance=SourceProvenance(
            intake_mode="pdf", method=ExtractionMethod.LIVE_LLM, provider="openrouter", model="m@1"
        ),
        statement_currency="SGD",
    )
    emitter = TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry()))
    unsup_traces = build_extraction_trace_records(
        unsup_res,
        user_id=test_user.id,
        execution_id=f"test:{unsup_stmt.id}:result:{unsup_res.result_id}",
        occurred_at=datetime.now(UTC),
    )
    await emitter.emit_many(unsup_traces)
    await persist_statement_extraction_result(
        db, statement=unsup_stmt, result=unsup_res, source_trace_record_id=unsup_traces[0].record_id
    )
    with pytest.raises(ValueError, match="cannot be confirmed with a cash statement envelope"):
        await _confirm(
            db,
            user_id=test_user.id,
            statement_id=unsup_stmt.id,
            command=_command(account_id=unsup_acct.id, source_result_digest=unsup_res.content_digest),
        )

    other_account = await make_account(
        db, (await UserFactory.create_async(db)).id, name="Other user account", type=AccountType.ASSET
    )
    with pytest.raises(ValueError, match="custody account"):
        await _confirm(
            db,
            user_id=test_user.id,
            statement_id=statement.id,
            command=_command(account_id=other_account.id, source_result_digest=result.content_digest),
        )
    await db.refresh(statement)
    assert (
        await db.scalar(select(func.count()).select_from(ReviewedStatementEnvelope)),
        statement.current_extraction_result_id is not None,
        statement.currency,
        statement.opening_balance,
    ) == (0, True, None, None)


async def test_AC_extraction_reviewed_envelope_3_5_7_trace_reparse_and_append_only(db, test_user):
    statement, account, result, source_record = await _seed_statement_source_and_account(
        db, test_user, source_digest="d" * 64
    )
    source_payload = dict(source_record.payload)
    command = _command(account_id=account.id, source_result_digest=result.content_digest)
    envelope = await _confirm(db, user_id=test_user.id, statement_id=statement.id, command=command)
    retry = await _confirm(db, user_id=test_user.id, statement_id=statement.id, command=command)
    parent_ids = set(
        await db.scalars(
            select(TraceRecordParentRow.parent_id).where(
                TraceRecordParentRow.record_id == envelope.review_trace_record_id
            )
        )
    )
    await db.refresh(statement)
    assert (
        envelope.source_result_id,
        envelope.review_trace_record_id is not None,
        source_record.payload == source_payload,
        source_record.source_trace_record_id in parent_ids,
        statement.extraction_metadata,
        statement.currency,
        statement.account_id,
        retry.id,
    ) == (source_record.id, True, True, True, None, "SGD", account.id, envelope.id)
    with pytest.raises(ReviewedStatementEnvelopeConflict):
        await _confirm(
            db,
            user_id=test_user.id,
            statement_id=statement.id,
            command=replace(command, rationale="A different reviewer rationale must not overwrite this fact."),
        )

    reparsed = _missing_source_result(source_digest="f" * 64)
    traces = build_extraction_trace_records(
        reparsed,
        user_id=test_user.id,
        execution_id=f"test:{statement.id}:result:{reparsed.result_id}",
        occurred_at=datetime.now(UTC),
    )
    await TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())).emit_many(traces)
    await persist_statement_extraction_result(
        db, statement=statement, result=reparsed, source_trace_record_id=traces[0].record_id
    )
    assert await current_reviewed_statement_envelope(db, user_id=test_user.id, statement_id=statement.id) is None
    successor = await _confirm(
        db,
        user_id=test_user.id,
        statement_id=statement.id,
        command=_command(account_id=account.id, source_result_digest=reparsed.content_digest),
    )
    await db.commit()
    assert successor.supersedes_id == envelope.id

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


async def test_reviewed_envelope_resolves_missing_transaction_currency(db, test_user):
    """#3254: confirm_reviewed_statement_envelope resolves missing transaction_currency onto Layer-2 rows."""
    from src.extraction.base.source_vocabulary import DocumentStatus, DocumentType, TransactionDirection
    from src.extraction.orm.layer1 import UploadedDocument
    from src.extraction.orm.layer2 import AtomicTransaction

    statement, account, result, _ = await _seed_statement_source_and_account(
        db, test_user, source_digest="e" * 64, transaction_currency=None
    )
    assert "transaction_currency" in result.missing_required_facts
    doc = UploadedDocument(
        user_id=test_user.id,
        file_path="statements/icici.pdf",
        original_filename="icici.pdf",
        file_hash="e" * 64,
        document_type=DocumentType.BANK_STATEMENT,
        status=DocumentStatus.COMPLETED,
    )
    db.add(doc)
    await db.flush()
    statement.uploaded_document_id = doc.id
    txn = AtomicTransaction(
        user_id=test_user.id,
        txn_date=date(2026, 1, 2),
        amount=Decimal("10.00"),
        direction=TransactionDirection.IN,
        description="Salary",
        currency="SGD",
        currency_unresolved=True,
        dedup_hash="dedup-icici-row-1",
        source_documents=[{"doc_id": str(doc.id)}],
    )
    db.add(txn)
    await db.flush()

    envelope = await _confirm(
        db,
        user_id=test_user.id,
        statement_id=statement.id,
        command=_command(account_id=account.id, source_result_digest=result.content_digest),
    )
    await db.refresh(statement)
    await db.refresh(txn)
    assert envelope.currency == "SGD"
    assert statement.currency == "SGD"
    assert txn.currency == "SGD"
    assert txn.currency_unresolved is False
    assert txn.currency_resolved_by == test_user.id
    assert txn.currency_resolved_at is not None
