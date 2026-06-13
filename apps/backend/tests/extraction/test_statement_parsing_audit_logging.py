"""Audit logging coverage for statement parsing replayability."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from src.database import create_session_maker_from_db
from src.models import BankStatementStatus
from src.models.statement_summary import StatementSummary
from src.services import statement_parsing
from src.services.extraction import ExtractionError
from src.services.statement_parsing import import_brokerage_payload_if_present, parse_statement_background
from tests.factories import StatementSummaryFactory


def _parsed_statement(user_id, file_hash: str) -> StatementSummary:
    return StatementSummaryFactory.build(
        user_id=user_id,
        file_hash=file_hash,
        institution="DBS",
        account_last4="1234",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 18),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
        status=BankStatementStatus.PARSED,
        confidence_score=90,
        balance_validated=True,
    )


async def _create_statement(db, user_id, *, statement_id=None, file_hash="audit-hash") -> StatementSummary:
    statement = StatementSummaryFactory.build(
        id=statement_id or uuid4(),
        user_id=user_id,
        status=BankStatementStatus.PARSING,
        file_hash=file_hash,
        institution="DBS",
    )
    db.add(statement)
    await db.commit()
    return statement


async def test_AC10_8_2_parse_checkpoints_and_failure_logs_are_structured(db, test_user, monkeypatch):
    """AC10.8.2: Async parsing emits replay checkpoints and safe failure context."""
    user_id = test_user.id
    success = await _create_statement(db, user_id, file_hash="success-hash")
    mock_info = MagicMock()
    mock_error = MagicMock()

    async def fake_parse_document(*_args, **_kwargs):
        return _parsed_statement(user_id, "success-hash"), []

    monkeypatch.setattr(statement_parsing.logger, "info", mock_info)
    monkeypatch.setattr(statement_parsing.logger, "error", mock_error)
    monkeypatch.setattr(statement_parsing.ExtractionService, "parse_document", fake_parse_document)
    monkeypatch.setattr(
        statement_parsing.StorageService,
        "generate_presigned_url",
        lambda *_args, **_kwargs: "https://example.com/audit.pdf",
    )

    await parse_statement_background(
        statement_id=success.id,
        filename="audit.pdf",
        institution="DBS",
        user_id=user_id,
        account_id=None,
        file_hash="success-hash",
        storage_key="statements/audit.pdf",
        content=b"%PDF-1.7",
        model="glm-5.1",
        session_maker=create_session_maker_from_db(db),
        request_id="req-success",
    )

    info_calls = [(call.args[0], call.kwargs) for call in mock_info.call_args_list]
    checkpoints = [kwargs for event, kwargs in info_calls if event == "statement.parse.checkpoint"]
    assert [checkpoint["phase"] for checkpoint in checkpoints] == [
        "parse_started",
        "storage_url_resolved",
        "extraction_started",
        "extraction_completed",
        "statement_persisted",
    ]
    assert all(checkpoint["audit_event"] == "statement.parse.checkpoint" for checkpoint in checkpoints)
    assert all(checkpoint["statement_id"] == str(success.id) for checkpoint in checkpoints)
    assert all(checkpoint["request_id"] == "req-success" for checkpoint in checkpoints)
    assert all(checkpoint["model_to_use"] == "glm-5.1" for checkpoint in checkpoints)

    extraction_completed = next(
        kwargs for event, kwargs in info_calls if event == "statement.parse.extraction_completed"
    )
    completed = next(kwargs for event, kwargs in info_calls if event == "statement.parse.completed")
    assert extraction_completed["audit_event"] == "statement.parse.extraction_completed"
    assert completed["audit_event"] == "statement.parse.completed"
    assert completed["phase"] == "parse_completed"
    assert completed["transactions_count"] == 0

    failure = await _create_statement(db, user_id, file_hash="failure-hash")

    async def fail_parse_document(*_args, **_kwargs):
        raise ExtractionError("provider failed without raw document content")

    mock_error.reset_mock()
    monkeypatch.setattr(statement_parsing.ExtractionService, "parse_document", fail_parse_document)

    await parse_statement_background(
        statement_id=failure.id,
        filename="audit.pdf",
        institution="DBS",
        user_id=user_id,
        account_id=None,
        file_hash="failure-hash",
        storage_key="statements/audit.pdf",
        content=b"%PDF-1.7 secret source bytes",
        model="glm-5.1",
        session_maker=create_session_maker_from_db(db),
        request_id="req-failure",
    )

    failed = next(call.kwargs for call in mock_error.call_args_list if call.args[0] == "statement.parse.failed")
    assert failed["audit_event"] == "statement.parse.failed"
    assert failed["statement_id"] == str(failure.id)
    assert failed["request_id"] == "req-failure"
    assert failed["phase"] == "extraction_started"
    assert failed["model_to_use"] == "glm-5.1"
    assert failed["error_type"] == "ExtractionError"
    assert failed["safe_error_message"] == "provider failed without raw document content"
    assert "secret source bytes" not in failed["safe_error_message"]


async def test_AC10_8_3_brokerage_import_audit_checkpoints(db, test_user, monkeypatch):
    """AC10.8.3: Brokerage import logs start/completion/failure replay context."""
    statement = await _create_statement(db, test_user.id, file_hash="brokerage-audit-hash")
    payload = {
        "institution": "Moomoo",
        "positions": [{"symbol": "AAPL", "quantity": "10"}],
    }
    result = SimpleNamespace(
        broker="Moomoo",
        parsed_positions=1,
        created_atomic_positions=1,
        existing_atomic_positions=0,
        reconcile_created=1,
        reconcile_updated=0,
        reconcile_disposed=0,
    )
    mock_info = MagicMock()
    mock_exception = MagicMock()

    async def fake_import_positions(*_args, **_kwargs):
        return result

    monkeypatch.setattr(statement_parsing.logger, "info", mock_info)
    monkeypatch.setattr(statement_parsing.logger, "exception", mock_exception)
    monkeypatch.setattr(statement_parsing._brokerage_import_service, "import_positions", fake_import_positions)

    await import_brokerage_payload_if_present(
        summary=statement,
        db=db,
        user_id=test_user.id,
        filename="moomoo-positions.pdf",
        institution="Moomoo",
        payload=payload,
        request_id="req-brokerage",
        model_to_use="glm-5.1",
    )

    calls = [(call.args[0], call.kwargs) for call in mock_info.call_args_list]
    started = next(kwargs for event, kwargs in calls if event == "statement.brokerage_import.started")
    completed = next(kwargs for event, kwargs in calls if event == "statement.brokerage_import.completed")

    assert started["audit_event"] == "statement.brokerage_import.started"
    assert started["statement_id"] == str(statement.id)
    assert started["request_id"] == "req-brokerage"
    assert started["phase"] == "brokerage_import_started"
    assert started["model_to_use"] == "glm-5.1"
    assert started["broker"] == "Moomoo"
    assert started["parsed_positions"] == 1

    assert completed["audit_event"] == "statement.brokerage_import.completed"
    assert completed["statement_id"] == str(statement.id)
    assert completed["phase"] == "brokerage_import_completed"
    assert completed["model_to_use"] == "glm-5.1"
    assert completed["broker"] == "Moomoo"
    assert completed["created_atomic_positions"] == 1
    assert completed["existing_atomic_positions"] == 0
    assert completed["reconcile_created"] == 1

    failure_statement = await _create_statement(db, test_user.id, file_hash="brokerage-failure-audit-hash")

    async def fail_import_positions(*_args, **_kwargs):
        raise RuntimeError("provider payload had no positions and raw text is omitted")

    monkeypatch.setattr(statement_parsing._brokerage_import_service, "import_positions", fail_import_positions)

    await import_brokerage_payload_if_present(
        summary=failure_statement,
        db=db,
        user_id=test_user.id,
        filename="moomoo-positions.pdf",
        institution="Moomoo",
        payload=payload,
        request_id="req-brokerage-failed",
        model_to_use="glm-5.1",
    )

    failed = next(
        call.kwargs for call in mock_exception.call_args_list if call.args[0] == "statement.brokerage_import.failed"
    )
    assert failed["audit_event"] == "statement.brokerage_import.failed"
    assert failed["statement_id"] == str(failure_statement.id)
    assert failed["request_id"] == "req-brokerage-failed"
    assert failed["phase"] == "brokerage_import_failed"
    assert failed["model_to_use"] == "glm-5.1"
    assert failed["error_type"] == "RuntimeError"
    assert failed["safe_error_message"] == "provider payload had no positions and raw text is omitted"
