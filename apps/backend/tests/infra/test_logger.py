from __future__ import annotations

import datetime
import io
import json
import logging
import sys
from unittest.mock import patch

from infra2_sdk.runtime.otel import OtelSettings, _JsonLogFormatter, signal_endpoint
from opentelemetry.exporter.otlp.proto.common._internal import _encode_value

from src import observability
from src.observability import configure_logging, get_logger


def test_build_otlp_logs_endpoint_delegates_to_public_sdk_helper() -> None:
    "AC-observability.2.1 AC-observability.2.2 AC-observability.4.10 AC12.1.1 AC12.1.2 AC12.12.3"
    assert signal_endpoint("http://collector:4318", "logs") == "http://collector:4318/v1/logs"
    assert signal_endpoint("http://collector:4318/", "logs") == "http://collector:4318/v1/logs"
    assert signal_endpoint("http://collector:4318/v1/logs", "logs") == "http://collector:4318/v1/logs"
    assert signal_endpoint("http://collector:4318/", "traces") == "http://collector:4318/v1/traces"


def test_sdk_json_formatter_emits_structured_json_and_trace_context(monkeypatch) -> None:
    "AC-observability.1.2 AC-observability.1.3 AC-observability.1.4 AC-observability.4.2 AC-observability.4.9 AC-observability.16.2 AC-observability.16.3 AC-observability.16.4"

    class _SpanCtx:
        def __init__(self, *, valid: bool) -> None:
            self.trace_id = 0x1234567890ABCDEF1234567890ABCDEF if valid else 0
            self.span_id = 0xFEDCBA0987654321 if valid else 0
            self.is_valid = valid

    class _Span:
        def __init__(self, *, valid: bool) -> None:
            self._ctx = _SpanCtx(valid=valid)

        def get_span_context(self):
            return self._ctx

    formatter = _JsonLogFormatter(
        {
            "service.name": "finance-report-backend",
            "deployment.environment.name": "staging",
            "service.version": "abc1234",
        }
    )
    record = logging.LogRecord("test.logger", logging.INFO, __file__, 1, "Account S1234567A failed", (), None)
    record.audit_event = "statement.parse"
    with patch("opentelemetry.trace.get_current_span", return_value=_Span(valid=True)):
        payload = json.loads(formatter.format(record))
    assert payload["service.name"] == "finance-report-backend"
    assert payload["deployment.environment.name"] == "staging"
    assert payload["service.version"] == "abc1234"
    assert payload["trace_id"] == "1234567890abcdef1234567890abcdef"
    assert payload["span_id"] == "fedcba0987654321"
    assert payload["audit_event"] == "statement.parse"

    with patch("opentelemetry.trace.get_current_span", return_value=_Span(valid=False)):
        no_trace = json.loads(formatter.format(record))
    assert no_trace["trace_id"] is None
    assert no_trace["span_id"] is None

    monkeypatch.delitem(sys.modules, "opentelemetry.trace", raising=False)
    no_mod = json.loads(formatter.format(record))
    assert no_mod["trace_id"] is None


def test_configure_logging_installs_sdk_json_handler(monkeypatch) -> None:
    "AC-observability.1.5 AC-observability.1.6 AC-observability.4.6 AC-observability.4.8"
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    stream = io.StringIO()
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setattr(observability.settings, "debug", False)
    try:
        configure_logging(take_over_root=True)
        get_logger("test.sdk.logging").info("statement.logged", amount_count=2)
        payload = json.loads(stream.getvalue().strip().splitlines()[-1])
        assert payload["message"] == "statement.logged"
        assert payload["amount_count"] == 2
        assert payload["service.name"] == observability.settings.otel_service_name
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)


def test_sanitize_value_and_fields_redact_pii_and_risky_keys() -> None:
    "AC-observability.11.3 AC-observability.16.1"
    today = datetime.date(2025, 4, 30)
    assert observability._sanitize_value(today) == "2025-04-30"
    assert _encode_value(observability._sanitize_value(today)).string_value == "2025-04-30"

    processed = observability._sanitize_fields(
        {
            "event": "Account 1234567890 failed for holder S1234567A",
            "raw_response": '{"account_number": "1234567890"}',
            "Authorization": "Bearer secret-jwt-token",
            "nested": {"provider_response": "raw provider secret", "note": "Contact S1234567A on 1234567890"},
            "items": ["Account 1234567890", "S1234567A"],
        }
    )
    assert "1234567890" not in str(processed)
    assert "S1234567A" not in str(processed)
    assert processed["raw_response"] == "[REDACTED]"
    assert processed["Authorization"] == "[REDACTED]"
    assert processed["nested"] == {
        "provider_response": "[REDACTED]",
        "note": "Contact [NRIC] on [BANK_ACCOUNT]",
    }
    assert processed["items"] == ["Account [BANK_ACCOUNT]", "[NRIC]"]


def test_otel_settings_reads_resource_attributes(monkeypatch) -> None:
    "AC-observability.4.1 AC-observability.4.5 AC-observability.4.7 AC-observability.7.2 AC12.5.1"
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "my-service")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=production,team=finance")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    s = OtelSettings.from_env(strict=True)
    assert s.service_name == "my-service"
    assert s.deployment_environment == "production"
    assert s.resource_attributes["team"] == "finance"
    assert s.enabled is True


def test_structured_logger_propagates_contextvars_to_otel_records_and_redacts_capture_logs() -> None:
    import structlog
    from structlog.testing import capture_logs

    captured: list[logging.LogRecord] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record)

    root = logging.getLogger()
    handler = _CaptureHandler()
    root.addHandler(handler)
    saved_level = root.level
    root.setLevel(logging.INFO)
    structlog.contextvars.bind_contextvars(user_id="user-42", authorization="Bearer secret-token")
    try:
        get_logger("test.ctx").info("Contact S1234567A")
        assert captured
        rec = captured[-1]
        assert rec.user_id == "user-42"
        assert rec.authorization == "[REDACTED]"
        assert rec.getMessage() == "Contact [NRIC]"

        with capture_logs() as logs:
            get_logger("test.ctx").info("Contact S1234567A", token="raw-secret")
        assert logs[-1]["event"] == "Contact [NRIC]"
        assert logs[-1]["token"] == "[REDACTED]"
        assert logs[-1]["user_id"] == "user-42"
    finally:
        structlog.contextvars.clear_contextvars()
        root.removeHandler(handler)
        root.setLevel(saved_level)
