from __future__ import annotations

import datetime
import io
import json
import logging
import sys
import types
from unittest.mock import patch
from uuid import UUID

from infra2_sdk.telemetry import JsonLogFormatter, OtelSettings, signal_endpoint
from opentelemetry.exporter.otlp.proto.common._internal import _encode_value

from src import observability
from src.observability import configure_logging, detect_pii, get_logger


def test_sdk_json_formatter_otel_settings_and_endpoints(monkeypatch) -> None:
    for raw, signal in (
        ("http://collector:4318", "logs"),
        ("http://collector:4318/", "logs"),
        ("http://collector:4318/v1/logs", "logs"),
        ("http://collector:4318/", "traces"),
    ):
        assert signal_endpoint(raw, signal) == f"http://collector:4318/v1/{signal}"
    for k, v in (
        ("ENVIRONMENT", "production"),
        ("OTEL_SERVICE_NAME", "my-service"),
        ("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=production,team=finance"),
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318"),
    ):
        monkeypatch.setenv(k, v)
    s = OtelSettings.from_env(strict=True)
    assert (s.service_name, s.deployment_environment, s.resource_attributes["team"], s.enabled) == (
        "my-service",
        "production",
        "finance",
        True,
    )

    span = lambda valid: types.SimpleNamespace(
        get_span_context=lambda: types.SimpleNamespace(
            trace_id=0x1234567890ABCDEF1234567890ABCDEF if valid else 0,
            span_id=0xFEDCBA0987654321 if valid else 0,
            is_valid=valid,
        )
    )
    fmt = JsonLogFormatter(
        {
            "service.name": "finance-report-backend",
            "deployment.environment.name": "staging",
            "service.version": "abc1234",
        }
    )
    rec = logging.LogRecord("test.logger", logging.INFO, __file__, 1, "Account S1234567A failed", (), None)
    rec.audit_event = "statement.parse"
    with patch("opentelemetry.trace.get_current_span", return_value=span(True)):
        p = json.loads(fmt.format(rec))
    assert (
        p["service.name"],
        p["deployment.environment.name"],
        p["service.version"],
        p["trace_id"],
        p["span_id"],
        p["audit_event"],
    ) == (
        "finance-report-backend",
        "staging",
        "abc1234",
        "1234567890abcdef1234567890abcdef",
        "fedcba0987654321",
        "statement.parse",
    )
    with patch("opentelemetry.trace.get_current_span", return_value=span(False)):
        assert (json.loads(fmt.format(rec))["trace_id"], json.loads(fmt.format(rec))["span_id"]) == (None, None)
    monkeypatch.delitem(sys.modules, "opentelemetry.trace", raising=False)
    assert json.loads(fmt.format(rec))["trace_id"] is None


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
        configure_logging(take_over_root=True)
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
