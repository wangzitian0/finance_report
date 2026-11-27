from __future__ import annotations

import datetime
import io
import json
import logging
from unittest.mock import patch
from uuid import UUID

from infra2_sdk.telemetry import TelemetryProviders, bind_log_context, current_request_id, init_worker
from opentelemetry.exporter.otlp.proto.common._internal import _encode_value

from src import observability
from src.observability import detect_pii, get_logger


def test_sdk_init_worker_json_formatter_and_log_context(monkeypatch, capsys) -> None:
    for k, v in (
        ("ENVIRONMENT", "local_dev"),
        ("SERVICE_VERSION", "abc1234"),
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:4318"),
    ):
        monkeypatch.setenv(k, v)
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    root.handlers.clear()
    providers = init_worker("finance-report-backend", set_global=False)
    assert isinstance(providers, TelemetryProviders)
    try:
        assert current_request_id() is None
        with bind_log_context(audit_event="statement.parse", request_id="req-42"):
            logging.getLogger("test.logger").info("Account S1234567A failed")
        lines = [line for line in capsys.readouterr().out.splitlines() if line.strip().startswith("{")]
        payload = json.loads(lines[-1])
        assert payload["service.name"] == "finance-report-backend"
        assert payload["deployment.environment.name"] == "local_dev"
        assert payload["service.version"] == "abc1234"
        assert payload["audit_event"] == "statement.parse"
        assert payload["request_id"] == "req-42"
    finally:
        providers.shutdown()
        root.handlers[:] = saved_handlers


def test_configure_logging_sanitization_and_contextvars(monkeypatch) -> None:
    import structlog
    from structlog.testing import capture_logs

    today = datetime.date(2025, 4, 30)
    assert (
        observability._sanitize_value(today) == "2025-04-30"
        and _encode_value(observability._sanitize_value(today)).string_value == "2025-04-30"
    )
    proc = observability._sanitize_fields(
        {
            "event": "Account 1234567890 failed for holder S1234567A",
            "raw_response": '{"account_number": "1234567890"}',
            "Authorization": "Bearer secret-jwt-token",
            "nested": {"provider_response": "raw provider secret", "note": "Contact S1234567A on 1234567890"},
            "items": ["Account 1234567890", "S1234567A"],
        }
    )
    assert (
        "1234567890" not in str(proc)
        and "S1234567A" not in str(proc)
        and (proc["raw_response"], proc["Authorization"]) == ("[REDACTED]", "[REDACTED]")
    )
    assert proc["nested"] == {"provider_response": "[REDACTED]", "note": "Contact [NRIC] on [BANK_ACCOUNT]"} and proc[
        "items"
    ] == ["Account [BANK_ACCOUNT]", "[NRIC]"]
    assert (
        detect_pii(
            "run_id=d2bb00b4-d59f-4e2a-809e-ea6b81234567 stmt=81234567-0123-4123-8123-123456789012 token=ea6b81234567"
        )
        == []
    )
    assert observability._sanitize_fields(
        {
            "run_id": UUID("d2bb00b4-d59f-4e2a-809e-ea6b81234567"),
            "stmt_id": "81234567-0123-4123-8123-123456789012",
            "phone": "+65 81234567",
        }
    ) == {
        "run_id": "d2bb00b4-d59f-4e2a-809e-ea6b81234567",
        "stmt_id": "81234567-0123-4123-8123-123456789012",
        "phone": "[PHONE]",
    }

    root, stream = logging.getLogger(), io.StringIO()
    saved_handlers, saved_level = list(root.handlers), root.level
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setattr(observability.settings, "debug", False)
    captured: list[logging.LogRecord] = []

    class _Cap(logging.Handler):
        emit = lambda self, r: captured.append(r)

    try:
        logging.getLogger().handlers.clear()
        init_worker(
            observability.settings.otel_service_name,
            strict=False,
            log_level=logging.INFO,
            set_global=False,
            environ={"ENVIRONMENT": observability.settings.environment, "OTEL_SDK_DISABLED": "true"},
        )
        with patch.object(structlog, "is_configured", return_value=False):
            get_logger("test.sdk.logging").info("statement.logged", amount_count=2)
        pl = json.loads(stream.getvalue().strip().splitlines()[-1])
        assert (pl["message"], pl["amount_count"], pl["service.name"]) == (
            "statement.logged",
            2,
            observability.settings.otel_service_name,
        )

        root.addHandler(_Cap())
        root.setLevel(logging.INFO)
        structlog.contextvars.bind_contextvars(user_id="user-42", authorization="Bearer secret-token")
        with patch.object(structlog, "is_configured", return_value=False):
            get_logger("test.ctx").info("Contact S1234567A")
        assert (captured[-1].user_id, captured[-1].authorization, captured[-1].getMessage()) == (
            "user-42",
            "[REDACTED]",
            "Contact [NRIC]",
        )
        with capture_logs() as logs:
            get_logger("test.ctx").info("Contact S1234567A", token="raw-secret")
        assert (logs[-1]["event"], logs[-1]["token"], logs[-1]["user_id"]) == (
            "Contact [NRIC]",
            "[REDACTED]",
            "user-42",
        )
    finally:
        structlog.contextvars.clear_contextvars()
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
