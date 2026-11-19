from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.database import create_session_maker_from_db
from src.extraction import BankStatementStatus, ExtractionMethod, ParseJob, StatementEvidenceType
from src.extraction.extension import statement_parsing
from src.extraction.extension.result_contract import build_statement_extraction_result
from src.extraction.extension.service import ExtractionError
from src.extraction.extension.statement_parsing import route_brokerage_for_review_if_present
from src.extraction.orm.statement_summary import StatementSummary
from tests.factories import StatementSummaryFactory
from tests.statement_ingestion import execute_statement_ingestion as parse_statement_background, run_for


async def _create_statement(db, user_id, *, file_hash: str) -> StatementSummary:
    statement = StatementSummaryFactory.build(
        id=uuid4(), user_id=user_id, status=BankStatementStatus.PARSING, file_hash=file_hash, institution="DBS"
    )
    db.add(statement)
    await db.commit()
    return statement


async def _persist_fixture_result(*, db, statement_id, source):
    summary = await db.get(StatementSummary, statement_id)
    assert summary is not None
    parsed = StatementSummaryFactory.build(
        user_id=summary.user_id,
        file_hash=summary.file_hash,
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
    for field in (
        "institution",
        "account_last4",
        "currency",
        "period_start",
        "period_end",
        "opening_balance",
        "closing_balance",
        "status",
        "confidence_score",
        "balance_validated",
    ):
        setattr(summary, field, getattr(parsed, field))
    result = build_statement_extraction_result(
        source=source,
        file_type="pdf",
        statement=summary,
        transactions=[],
        provider_payload={"transactions": []},
        model="audit-fixture",
        provider="audit-fixture",
        method=ExtractionMethod.GOLDEN_FIXTURE,
        is_brokerage=False,
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        positions=[],
    )
    summary.extraction_metadata = {"statement_extraction_result": result.to_payload()}
    await db.flush()
    return result


async def _run_bg(db, statement: StatementSummary, request_id: str, content: bytes = b"%PDF-1.7"):
    await parse_statement_background(
        job=ParseJob(
            statement_id=statement.id,
            run_id=await run_for(db, statement.id),
            filename="audit.pdf",
            institution="DBS",
            user_id=statement.user_id,
            account_id=None,
            file_hash=statement.file_hash,
            storage_key="statements/audit.pdf",
            model="glm-5.1",
            request_id=request_id,
        ),
        content=content,
        session_maker=create_session_maker_from_db(db),
    )


def _spy_logs(monkeypatch):
    mocks = {name: MagicMock() for name in ("info", "error", "warning", "exception")}
    for name, mock in mocks.items():
        monkeypatch.setattr(statement_parsing.logger, name, mock)
    return mocks


async def test_AC10_8_2_and_AC_observability_11_4_parse_logs(db, test_user, monkeypatch):
    logs = _spy_logs(monkeypatch)

    success = await _create_statement(db, test_user.id, file_hash="success-hash")

    async def fake_parse_documents(*a, **kw):
        return [await _persist_fixture_result(db=kw["db"], statement_id=success.id, source=a[1])]

    monkeypatch.setattr(statement_parsing.ExtractionService, "parse_documents", fake_parse_documents)
    await _run_bg(db, success, "req-success")
    info_calls = [(c.args[0], c.kwargs) for c in logs["info"].call_args_list]
    checkpoints = [kw for ev, kw in info_calls if ev == "statement.parse.checkpoint"]
    assert [c["phase"] for c in checkpoints] == [
        "parse_started",
        "extraction_started",
        "extraction_completed",
        "statement_persisted",
    ]
    assert all(
        (c["audit_event"], c["statement_id"], c["request_id"], c["model_to_use"])
        == ("statement.parse.checkpoint", str(success.id), "req-success", "glm-5.1")
        for c in checkpoints
    )
    ext_done, done = (
        next(kw for ev, kw in info_calls if ev == "statement.parse.extraction_completed"),
        next(kw for ev, kw in info_calls if ev == "statement.parse.completed"),
    )
    assert (ext_done["audit_event"], done["audit_event"], done["phase"], done["transactions_count"]) == (
        "statement.parse.extraction_completed",
        "statement.parse.completed",
        "parse_completed",
        0,
    )

    for file_hash, req_id, msg, payload_bytes in (
        (
            "failure-hash",
            "req-failure",
            "provider failed without raw document content",
            b"%PDF-1.7 secret source bytes",
        ),
        ("contract-hash", "req-contract", "could not read a bank statement from this document", b"%PDF-1.7"),
    ):
        for name in ("error", "warning", "exception"):
            logs[name].reset_mock()
        stmt = await _create_statement(db, test_user.id, file_hash=file_hash)
        monkeypatch.setattr(
            statement_parsing.ExtractionService, "parse_documents", AsyncMock(side_effect=ExtractionError(msg))
        )
        await _run_bg(db, stmt, req_id, payload_bytes)
        failed = next(c.kwargs for c in logs["warning"].call_args_list if c.args[0] == "statement.parse.failed")
        assert (
            failed["audit_event"],
            failed["statement_id"],
            failed["request_id"],
            failed["phase"],
            failed["model_to_use"],
            failed["error_type"],
            failed["safe_error_message"],
        ) == ("statement.parse.failed", str(stmt.id), req_id, "extraction_started", "glm-5.1", "ExtractionError", msg)
        assert "secret source bytes" not in failed["safe_error_message"]
        logs["error"].assert_not_called()
        logs["exception"].assert_not_called()


async def test_AC10_8_3_brokerage_review_routing_audit_checkpoints(db, test_user, monkeypatch):
    statement = await _create_statement(db, test_user.id, file_hash="brokerage-audit-hash")
    statement.status = BankStatementStatus.PARSED
    await db.commit()
    payload, logs = (
        {"institution": "Moomoo", "positions": [{"symbol": "AAPL", "quantity": "10"}]},
        _spy_logs(monkeypatch),
    )
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
    calls = [(c.args[0], c.kwargs) for c in logs["info"].call_args_list]
    started, completed = (
        next(kw for ev, kw in calls if ev == "statement.brokerage_review_routing.started"),
        next(kw for ev, kw in calls if ev == "statement.brokerage_review_routing.completed"),
    )
    assert (
        started["audit_event"],
        started["statement_id"],
        started["request_id"],
        started["phase"],
        started["model_to_use"],
        started["broker"],
        started["parsed_positions"],
    ) == (
        "statement.brokerage_review_routing.started",
        str(statement.id),
        "req-brokerage",
        "brokerage_review_routing_started",
        "glm-5.1",
        "Moomoo",
        1,
    )
    assert (
        completed["audit_event"],
        completed["statement_id"],
        completed["phase"],
        completed["model_to_use"],
        completed["broker"],
        completed["parsed_positions"],
    ) == (
        "statement.brokerage_review_routing.completed",
        str(statement.id),
        "brokerage_review_routing_completed",
        "glm-5.1",
        "Moomoo",
        1,
    )

    fail_stmt = await _create_statement(db, test_user.id, file_hash="brokerage-failure-audit-hash")
    fail_stmt.status = BankStatementStatus.PARSED
    await db.commit()
    flush_calls = [0]

    async def flaky_flush(*_a, **_kw):
        flush_calls[0] += 1
        raise RuntimeError("forced routing flush failure")

    monkeypatch.setattr(db, "flush", flaky_flush)
    with pytest.raises(RuntimeError, match="forced routing flush failure"):
        await route_brokerage_for_review_if_present(
            summary=fail_stmt,
            db=db,
            user_id=test_user.id,
            filename="moomoo-positions.pdf",
            institution="Moomoo",
            payload=payload,
            request_id="req-brokerage-failed",
            model_to_use="glm-5.1",
        )
    failed = next(
        c.kwargs for c in logs["exception"].call_args_list if c.args[0] == "statement.brokerage_review_routing.failed"
    )
    assert (
        failed["audit_event"],
        failed["statement_id"],
        failed["request_id"],
        failed["phase"],
        failed["model_to_use"],
        failed["error_type"],
        flush_calls[0],
        failed["safe_error_message"],
    ) == (
        "statement.brokerage_review_routing.failed",
        str(fail_stmt.id),
        "req-brokerage-failed",
        "brokerage_review_routing_failed",
        "glm-5.1",
        "RuntimeError",
        1,
        "forced routing flush failure",
    )


@pytest.mark.parametrize(
    ("mode", "expected"), [("success", ["success"]), ("failure", ["failure"]), ("quarantined", ["rejected"])]
)
async def test_AC10_10_4_parse_outcome_metrics(db, test_user, monkeypatch, mode, expected):
    outcomes: list[str] = []
    monkeypatch.setattr(
        statement_parsing,
        "record_statement_parse_outcome",
        lambda *, outcome, parser="default": outcomes.append(outcome),
    )
    stmt = await _create_statement(db, test_user.id, file_hash=f"metric-{mode}")

    async def parse_fn(*args, **kwargs):
        if mode == "failure":
            raise ExtractionError("metric failure path")
        res = await _persist_fixture_result(db=kwargs["db"], statement_id=stmt.id, source=args[1])
        if mode == "quarantined":
            (await kwargs["db"].get(StatementSummary, stmt.id)).status = BankStatementStatus.REJECTED
        return [res]

    monkeypatch.setattr(statement_parsing.ExtractionService, "parse_documents", parse_fn)
    await _run_bg(db, stmt, f"req-metric-{mode}")
    assert outcomes == expected
