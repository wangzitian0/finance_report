"""A failed brokerage import stays visible on the statement until an import succeeds (#2648).

Before #2648 a failed import left no trace: the statement stayed ``parsed`` with its old note, so
the upload list showed "Ready to review" and "Review & Approve" for a file whose import failed.
The failure lives in ``extraction_metadata`` (``BROKERAGE_IMPORT_FAILURE_KEY``), not in
``validation_error``: a write of that note must not clear or replace it.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import SqlTraceRecordRepository, TraceEmitter
from src.config import settings
from src.extraction import (
    BROKERAGE_IMPORT_FAILED_MESSAGE,
    BROKERAGE_IMPORT_FAILURE_KEY,
    BankStatementStatus,
    BrokerageImportRejectedError,
    ExtractedTransactionFact,
    ExtractionMethod,
    SourceProvenance,
    StatementEvidenceType,
    StatementExtractionResult,
    StatementSourceType,
    StatementSummary,
    extraction_trace_policy_registry,
    persist_statement_extraction_result,
    record_brokerage_import_failure,
)
from src.extraction.extension.extraction_trace import build_extraction_trace_records
from src.routers import statements as statements_router
from src.schemas.extraction import compose_statement_response
from src.schemas.review import ReviewedStatementEnvelopeRequest
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account

ECONOMIC_NOTE = "Economic review required: intent_missing"
REJECTED_REASON = (
    "The positions source does not state an as-of date for 2 of 2 positions. "
    "The import needs the date that the source states."
)


def _import_result() -> SimpleNamespace:
    return SimpleNamespace(
        broker="Interactive Brokers",
        parsed_positions=2,
        created_atomic_positions=2,
        existing_atomic_positions=0,
        reconcile_created=2,
        reconcile_updated=0,
        reconcile_disposed=0,
        skipped=0,
        account_id=None,
    )


async def _listed(db, user_id, statement_id):
    response = await statements_router.list_statements(db=db, user_id=user_id)
    return {item.id: item for item in response.items}[statement_id]


async def _stored(db, statement_id) -> StatementSummary:
    statement = await db.get(StatementSummary, statement_id, populate_existing=True)
    assert statement is not None
    return statement


async def _import(db, monkeypatch, *, statement_id, user_id, outcome) -> None:
    """Call the import endpoint with an import service that returns or raises ``outcome``."""

    async def fake_import(*_args, **_kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(statements_router._BROKERAGE_IMPORT_SERVICE, "import_positions", fake_import)
    await statements_router.import_brokerage_statement_positions(statement_id=statement_id, db=db, user_id=user_id)


async def test_AC_extraction_2648_1_failed_import_is_recorded_beside_the_note_and_a_success_clears_it(
    db, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-extraction.2648.1: an import that raises keeps the statement ``parsed`` and its earlier
    "Economic review required:" note, and records the failure (reason, request id, time) in
    ``extraction_metadata``. The list reports ``brokerage_import_failed`` and the reason. The
    original error still reaches the caller. A successful import removes only the record."""
    user_id = test_user.id  # the router commits, which expires the fixture user
    statement = build_statement(user_id, "ibkr-positions-2648", 20)
    statement.institution = "Interactive Brokers"
    statement.validation_error = ECONOMIC_NOTE
    statement.extraction_metadata = {"within_document_dedup_collapse": 1}
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    with pytest.raises(RuntimeError, match="no ticker column"):
        await _import(
            db,
            monkeypatch,
            statement_id=statement_id,
            user_id=user_id,
            outcome=RuntimeError("positions payload has no ticker column"),
        )

    failed = await _stored(db, statement_id)
    assert failed.status is BankStatementStatus.PARSED
    assert failed.validation_error == ECONOMIC_NOTE
    record = failed.extraction_metadata[BROKERAGE_IMPORT_FAILURE_KEY]
    assert record["reason"] == BROKERAGE_IMPORT_FAILED_MESSAGE
    assert isinstance(record["request_id"], str) and record["request_id"]
    assert datetime.fromisoformat(record["failed_at"]).tzinfo is not None
    assert failed.extraction_metadata["within_document_dedup_collapse"] == 1
    listed = await _listed(db, user_id, statement_id)
    assert (listed.brokerage_import_failed, listed.brokerage_import_failure_reason, listed.validation_error) == (
        True,
        BROKERAGE_IMPORT_FAILED_MESSAGE,
        ECONOMIC_NOTE,
    )

    await _import(db, monkeypatch, statement_id=statement_id, user_id=user_id, outcome=_import_result())

    cleared = await _stored(db, statement_id)
    assert cleared.validation_error == ECONOMIC_NOTE
    assert cleared.extraction_metadata == {"within_document_dedup_collapse": 1}
    listed = await _listed(db, user_id, statement_id)
    assert (listed.brokerage_import_failed, listed.brokerage_import_failure_reason) == (False, None)


async def test_AC_extraction_2648_1_a_rejected_import_records_its_specific_reason(
    db, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-extraction.2648.1: a source that the import rejects (HTTP 422, #2649) records its own
    reason, so the upload list shows the remedy. The generic message is only for a missing reason."""
    user_id = test_user.id
    statement = build_statement(user_id, "ibkr-positions-2648-422", 20)
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    with pytest.raises(BrokerageImportRejectedError):
        await _import(
            db,
            monkeypatch,
            statement_id=statement_id,
            user_id=user_id,
            outcome=BrokerageImportRejectedError("brokerage_snapshot_date_missing", REJECTED_REASON),
        )

    rejected = await _stored(db, statement_id)
    assert rejected.extraction_metadata[BROKERAGE_IMPORT_FAILURE_KEY]["reason"] == REJECTED_REASON
    assert rejected.validation_error is None
    listed = await _listed(db, user_id, statement_id)
    assert (listed.brokerage_import_failed, listed.brokerage_import_failure_reason) == (True, REJECTED_REASON)


async def test_AC_extraction_2648_1_envelope_confirmation_and_a_blocked_approval_keep_the_failure(
    db, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-extraction.2648.1: the envelope confirmation sets ``validation_error`` to None, and a
    blocked approval writes the "Economic review required:" note. Neither clears the recorded
    import failure. Only the successful import clears it."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    user_id = test_user.id
    statement = build_statement(user_id, "ibkr-positions-2648-envelope", 80)
    db.add(statement)
    await db.flush()
    source_result = StatementExtractionResult.create(
        producer_version="csv-parser@1",
        source_content_digest="b" * 64,
        source_type=StatementSourceType.BANK,
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        institution="DBS",
        account_last4="1234",
        period_start=None,
        period_end=None,
        balances=(),
        transactions=(
            ExtractedTransactionFact(
                fact_id="row-1",
                transaction_date=date(2025, 1, 2),
                description="Opaque merchant",
                amount=Decimal("10.00"),
                direction="IN",
                currency="SGD",
                balance_after=None,
                confidence=Decimal("0.95"),
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
    trace_records = build_extraction_trace_records(
        source_result,
        user_id=user_id,
        execution_id=f"test:{statement.id}:result:{source_result.result_id}",
        occurred_at=datetime.now(UTC),
    )
    await TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())).emit_many(trace_records)
    await persist_statement_extraction_result(
        db, statement=statement, result=source_result, source_trace_record_id=trace_records[0].record_id
    )
    transaction = await add_txn(
        db, statement, txn_date=date(2025, 1, 2), description="Opaque merchant", amount=Decimal("10.00"), direction="IN"
    )
    transaction.dedup_hash = "row-1"
    account = await create_statement_account(db, user_id, "Envelope Custody 2648")
    await db.commit()
    statement_id = statement.id
    account_id = account.id

    with pytest.raises(BrokerageImportRejectedError):
        await _import(
            db,
            monkeypatch,
            statement_id=statement_id,
            user_id=user_id,
            outcome=BrokerageImportRejectedError("brokerage_snapshot_date_missing", REJECTED_REASON),
        )
    assert (await _listed(db, user_id, statement_id)).brokerage_import_failed is True

    await statements_router.confirm_statement_review_envelope(
        statement_id=statement_id,
        request=ReviewedStatementEnvelopeRequest(
            source_result_digest=source_result.content_digest,
            account_id=account_id,
            currency="SGD",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("110.00"),
            rationale="The CSV export omits source header and balance facts.",
        ),
        db=db,
        user_id=user_id,
    )
    await db.commit()
    confirmed = await _listed(db, user_id, statement_id)
    assert (
        confirmed.validation_error,
        confirmed.brokerage_import_failed,
        confirmed.brokerage_import_failure_reason,
    ) == (
        None,
        True,
        REJECTED_REASON,
    )

    with pytest.raises(HTTPException) as blocked:
        await statements_router.approve_statement_stage1(statement_id=statement_id, db=db, user_id=user_id)
    assert blocked.value.detail == ECONOMIC_NOTE
    held = await _listed(db, user_id, statement_id)
    assert (held.validation_error, held.brokerage_import_failed, held.brokerage_import_failure_reason) == (
        ECONOMIC_NOTE,
        True,
        REJECTED_REASON,
    )

    await _import(db, monkeypatch, statement_id=statement_id, user_id=user_id, outcome=_import_result())
    imported = await _listed(db, user_id, statement_id)
    assert (imported.validation_error, imported.brokerage_import_failed, imported.brokerage_import_failure_reason) == (
        ECONOMIC_NOTE,
        False,
        None,
    )


async def test_AC_extraction_2648_1_only_a_parsed_or_approved_statement_reports_the_failure(
    db, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-extraction.2648.1: only a statement that can be imported (``parsed`` or ``approved``)
    reports the failure. A rejected, parsing or uploaded statement shows its own state."""
    user_id = test_user.id
    statement = build_statement(user_id, "ibkr-positions-2648-status", 20)
    db.add(statement)
    await db.commit()
    statement_id = statement.id
    with pytest.raises(RuntimeError):
        await _import(db, monkeypatch, statement_id=statement_id, user_id=user_id, outcome=RuntimeError("fault"))

    # The response builder of GET /statements, per status. A status change in the database needs
    # the fields of its review stage, so the test sets the status on the loaded row only.
    stored = await _stored(db, statement_id)
    reported = {}
    for status in (
        BankStatementStatus.PARSED,
        BankStatementStatus.APPROVED,
        BankStatementStatus.REJECTED,
        BankStatementStatus.PARSING,
        BankStatementStatus.UPLOADED,
    ):
        stored.status = status
        response = compose_statement_response(stored, None, [])
        reported[status.value] = (response.brokerage_import_failed, response.brokerage_import_failure_reason)
    await db.rollback()
    assert reported == {
        "parsed": (True, BROKERAGE_IMPORT_FAILED_MESSAGE),
        "approved": (True, BROKERAGE_IMPORT_FAILED_MESSAGE),
        "rejected": (False, None),
        "parsing": (False, None),
        "uploaded": (False, None),
    }


#: A concurrent write of another metadata key. A real re-parse also writes ``statement_extraction_result``;
#: the import path parses that key, so the test changes a key that no import step reads.
NEW_EXTRACTION = {"within_document_dedup_collapse": 2}


async def _write_in_another_session(db_engine, statement_id, metadata) -> None:
    """A concurrent re-parse: another session replaces the extraction metadata and commits."""
    async with AsyncSession(db_engine, expire_on_commit=False) as other:
        row = await other.get(StatementSummary, statement_id)
        assert row is not None
        row.extraction_metadata = metadata
        await other.commit()


async def test_AC_extraction_2648_1_a_concurrent_extraction_write_survives_an_import(
    db, db_engine, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-extraction.2648.1: the import loads the statement, then another session writes a new
    extraction (a re-parse) and commits. The successful import and the failed import change only
    the record key, so the new extraction stays. A write of the whole metadata from the object
    that the import loaded put the old extraction back (the review probe)."""
    user_id = test_user.id
    statement = build_statement(user_id, "ibkr-positions-2648-concurrent", 20)
    statement.extraction_metadata = {"within_document_dedup_collapse": 1}
    db.add(statement)
    await db.commit()
    statement_id = statement.id
    with pytest.raises(RuntimeError):
        await _import(db, monkeypatch, statement_id=statement_id, user_id=user_id, outcome=RuntimeError("fault"))

    async def import_while_reparsed(*_args, **_kwargs):
        # The new extraction keeps a failure record, so the clear of the successful import runs.
        await _write_in_another_session(
            db_engine, statement_id, {**NEW_EXTRACTION, BROKERAGE_IMPORT_FAILURE_KEY: {"reason": "x"}}
        )
        return _import_result()

    monkeypatch.setattr(statements_router._BROKERAGE_IMPORT_SERVICE, "import_positions", import_while_reparsed)
    await statements_router.import_brokerage_statement_positions(statement_id=statement_id, db=db, user_id=user_id)
    assert (await _stored(db, statement_id)).extraction_metadata == NEW_EXTRACTION

    async def fail_while_reparsed(*_args, **_kwargs):
        await _write_in_another_session(db_engine, statement_id, {"within_document_dedup_collapse": 3})
        raise RuntimeError("fault")

    monkeypatch.setattr(statements_router._BROKERAGE_IMPORT_SERVICE, "import_positions", fail_while_reparsed)
    with pytest.raises(RuntimeError):
        await statements_router.import_brokerage_statement_positions(statement_id=statement_id, db=db, user_id=user_id)
    stored = (await _stored(db, statement_id)).extraction_metadata
    assert stored["within_document_dedup_collapse"] == 3
    assert stored[BROKERAGE_IMPORT_FAILURE_KEY]["reason"] == BROKERAGE_IMPORT_FAILED_MESSAGE


async def test_AC_extraction_2648_1_an_import_that_succeeds_after_another_failed_clears_that_failure(
    db, db_engine, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-extraction.2648.1: import B loads the statement. While B imports, import A fails and
    records its failure in another session. B succeeds later, so the statement shows no failure.
    A clear that read the metadata of the object that B loaded kept the failure."""
    user_id = test_user.id
    statement = build_statement(user_id, "ibkr-positions-2648-overlap", 20)
    db.add(statement)
    await db.commit()
    statement_id = statement.id

    async def import_while_another_fails(*_args, **_kwargs):
        async with AsyncSession(db_engine, expire_on_commit=False) as other:
            await record_brokerage_import_failure(
                other, statement_id=statement_id, user_id=user_id, reason="Import A failed.", request_id="request-a"
            )
            await other.commit()
        return _import_result()

    monkeypatch.setattr(statements_router._BROKERAGE_IMPORT_SERVICE, "import_positions", import_while_another_fails)
    await statements_router.import_brokerage_statement_positions(statement_id=statement_id, db=db, user_id=user_id)

    stored = await _stored(db, statement_id)
    assert BROKERAGE_IMPORT_FAILURE_KEY not in (stored.extraction_metadata or {})
    listed = await _listed(db, user_id, statement_id)
    assert (listed.brokerage_import_failed, listed.brokerage_import_failure_reason) == (False, None)
