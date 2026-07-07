"""Audit logging coverage for statement parsing replayability."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

from src.database import create_session_maker_from_db
from src.extraction.extension.service import ExtractionError
from src.models.statement_enums import BankStatementStatus
from src.models.statement_summary import StatementSummary
from src.extraction.extension import statement_parsing
from src.extraction.extension.statement_parsing import parse_statement_background, route_brokerage_for_review_if_present
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
    """AC-observability.8.2: Async parsing emits replay checkpoints and safe failure context."""
    user_id = test_user.id
    success = await _create_statement(db, user_id, file_hash="success-hash")
    mock_info = MagicMock()
    mock_error = MagicMock()
    mock_warning = MagicMock()

    async def fake_parse_document(*_args, **_kwargs):
        return _parsed_statement(user_id, "success-hash"), []

    monkeypatch.setattr(statement_parsing.logger, "info", mock_info)
    monkeypatch.setattr(statement_parsing.logger, "error", mock_error)
    monkeypatch.setattr(statement_parsing.logger, "warning", mock_warning)
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
    mock_warning.reset_mock()
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

    failed = next(call.kwargs for call in mock_warning.call_args_list if call.args[0] == "statement.parse.failed")
    assert failed["audit_event"] == "statement.parse.failed"
    assert failed["statement_id"] == str(failure.id)
    assert failed["request_id"] == "req-failure"
    assert failed["phase"] == "extraction_started"
    assert failed["model_to_use"] == "glm-5.1"
    assert failed["error_type"] == "ExtractionError"
    assert failed["safe_error_message"] == "provider failed without raw document content"
    assert "secret source bytes" not in failed["safe_error_message"]


async def test_AC10_8_3_brokerage_review_routing_audit_checkpoints(db, test_user, monkeypatch):
    """AC-observability.8.3/#1408: Brokerage review-routing logs start/completion/failure replay context.

    Parse no longer imports positions (#1408); it routes a detected brokerage statement to
    Stage-1 review, so the replay events are the routing start/complete/failure events.
    """
    statement = await _create_statement(db, test_user.id, file_hash="brokerage-audit-hash")
    statement.status = BankStatementStatus.PARSED
    await db.commit()
    payload = {
        "institution": "Moomoo",
        "positions": [{"symbol": "AAPL", "quantity": "10"}],
    }
    mock_info = MagicMock()
    mock_exception = MagicMock()

    monkeypatch.setattr(statement_parsing.logger, "info", mock_info)
    monkeypatch.setattr(statement_parsing.logger, "exception", mock_exception)

    await route_brokerage_for_review_if_present(
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
    started = next(kwargs for event, kwargs in calls if event == "statement.brokerage_review_routing.started")
    completed = next(kwargs for event, kwargs in calls if event == "statement.brokerage_review_routing.completed")

    assert started["audit_event"] == "statement.brokerage_review_routing.started"
    assert started["statement_id"] == str(statement.id)
    assert started["request_id"] == "req-brokerage"
    assert started["phase"] == "brokerage_review_routing_started"
    assert started["model_to_use"] == "glm-5.1"
    assert started["broker"] == "Moomoo"
    assert started["parsed_positions"] == 1

    assert completed["audit_event"] == "statement.brokerage_review_routing.completed"
    assert completed["statement_id"] == str(statement.id)
    assert completed["phase"] == "brokerage_review_routing_completed"
    assert completed["model_to_use"] == "glm-5.1"
    assert completed["broker"] == "Moomoo"
    assert completed["parsed_positions"] == 1

    # Failure path: the routing commit raises -> a replayable failure event is emitted.
    failure_statement = await _create_statement(db, test_user.id, file_hash="brokerage-failure-audit-hash")
    failure_statement.status = BankStatementStatus.PARSED
    await db.commit()

    commit_calls = {"count": 0}
    real_commit = db.commit

    async def flaky_commit(*args, **kwargs):
        commit_calls["count"] += 1
        if commit_calls["count"] == 1:
            raise RuntimeError("forced routing commit failure")
        return await real_commit(*args, **kwargs)

    async def missing_statement(*_args, **_kwargs):
        return None

    monkeypatch.setattr(db, "commit", flaky_commit)
    monkeypatch.setattr(db, "rollback", missing_statement)
    monkeypatch.setattr(db, "get", missing_statement)

    await route_brokerage_for_review_if_present(
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
        call.kwargs
        for call in mock_exception.call_args_list
        if call.args[0] == "statement.brokerage_review_routing.failed"
    )
    assert failed["audit_event"] == "statement.brokerage_review_routing.failed"
    assert failed["statement_id"] == str(failure_statement.id)
    assert failed["request_id"] == "req-brokerage-failed"
    assert failed["phase"] == "brokerage_review_routing_failed"
    assert failed["model_to_use"] == "glm-5.1"
    assert failed["error_type"] == "RuntimeError"
    assert failed["safe_error_message"] == "forced routing commit failure"


async def test_AC10_10_4_parse_outcome_metric_emitted(db, test_user, monkeypatch):
    """AC-observability.10.4: parse_statement_background emits the parse-outcome business metric
    on both the success and failure paths, driven through the real code path."""
    user_id = test_user.id
    outcomes: list[str] = []
    monkeypatch.setattr(
        statement_parsing,
        "record_statement_parse_outcome",
        lambda *, outcome, parser="default": outcomes.append(outcome),
    )
    monkeypatch.setattr(
        statement_parsing.StorageService,
        "generate_presigned_url",
        lambda *_args, **_kwargs: "https://example.com/audit.pdf",
    )

    success = await _create_statement(db, user_id, file_hash="metric-success")

    async def ok_parse_document(*_args, **_kwargs):
        return _parsed_statement(user_id, "metric-success"), []

    monkeypatch.setattr(statement_parsing.ExtractionService, "parse_document", ok_parse_document)
    await parse_statement_background(
        statement_id=success.id,
        filename="audit.pdf",
        institution="DBS",
        user_id=user_id,
        account_id=None,
        file_hash="metric-success",
        storage_key="statements/audit.pdf",
        content=b"%PDF-1.7",
        model="glm-5.1",
        session_maker=create_session_maker_from_db(db),
        request_id="req-metric-ok",
    )

    failure = await _create_statement(db, user_id, file_hash="metric-failure")

    async def bad_parse_document(*_args, **_kwargs):
        raise ExtractionError("metric failure path")

    monkeypatch.setattr(statement_parsing.ExtractionService, "parse_document", bad_parse_document)
    await parse_statement_background(
        statement_id=failure.id,
        filename="audit.pdf",
        institution="DBS",
        user_id=user_id,
        account_id=None,
        file_hash="metric-failure",
        storage_key="statements/audit.pdf",
        content=b"%PDF-1.7",
        model="glm-5.1",
        session_maker=create_session_maker_from_db(db),
        request_id="req-metric-fail",
    )

    assert outcomes == ["success", "failure"]
