"""Focused observability contract tests for EPIC-010."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src import (
    logger as logger_module,
    observability as observability_module,
    telemetry_metrics as telemetry_metrics_module,
)
from src.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[4]
APP_IAC = REPO_ROOT / "repo" / "finance_report" / "finance_report" / "10.app"
pytestmark = pytest.mark.no_db


def _read(path: Path) -> str:
    if path.is_dir():
        return "\n# <<< file-boundary >>>\n".join(p.read_text(encoding="utf-8") for p in sorted(path.rglob("*.py")))
    return path.read_text(encoding="utf-8")


def test_otel_settings_are_explicit_and_environment_backed(monkeypatch) -> None:
    """AC10.1.1 AC10.5.4: OTEL settings are owned by backend config."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)

    defaults = Settings(_env_file=None)
    assert defaults.otel_exporter_otlp_endpoint is None
    assert defaults.otel_service_name == "finance-report-backend"
    assert defaults.otel_resource_attributes is None

    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "finance-report-worker")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=staging")

    settings = Settings(_env_file=None)
    assert settings.otel_exporter_otlp_endpoint == "http://collector:4318"
    assert settings.otel_service_name == "finance-report-worker"
    assert settings.otel_resource_attributes == "deployment.environment=staging"


def test_telemetry_contract_fast_fails_in_deployed_env_without_tag(monkeypatch) -> None:
    """Infra-014 C4: a deployed env exporting OTEL without a deployment.environment
    tag fails fast at config load; local/CI/preview and telemetry-off are exempt."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "service.version=abc123")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)

    # Tag present -> loads.
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=production")
    assert Settings(_env_file=None).environment == "production"

    # Telemetry off in a deployed env is allowed (no endpoint).
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "")
    assert Settings(_env_file=None).environment == "production"

    # Non-deployed env is exempt even with endpoint set and no tag.
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "")
    assert Settings(_env_file=None).environment == "development"


def test_observability_ssot_and_env_docs_are_linked() -> None:
    """AC10.5.1 AC10.5.2 AC10.5.3 AC10.7.5: Observability docs are anchored."""
    observability = _read(REPO_ROOT / "docs" / "ssot" / "observability.md")
    ssot_index = _read(REPO_ROOT / "docs" / "ssot" / "README.md")
    env_example = _read(REPO_ROOT / ".env.example")

    assert "SSOT Key" in observability
    assert "observability" in observability
    assert "[observability.md](./observability.md)" in ssot_index

    for key in (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_SERVICE_NAME",
        "OTEL_RESOURCE_ATTRIBUTES",
    ):
        assert key in observability
        assert key in env_example


def test_vault_template_exposes_otel_keys_with_safe_quoting() -> None:
    """AC10.6.1 AC10.6.4 AC10.7.6: Vault template renders OTEL keys safely."""
    template = _read(APP_IAC / "secrets.ctmpl")

    for key in (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_SERVICE_NAME",
        "OTEL_RESOURCE_ATTRIBUTES",
    ):
        line = next(line for line in template.splitlines() if line.startswith(f"{key}="))
        assert f"with .Data.data.{key}" in line
        assert 'printf "%q"' in line
        assert " default " not in line


def test_app_readme_and_compose_document_observability_rollout() -> None:
    """AC10.6.2 AC10.6.3: App docs and compose expose OTEL rollout controls."""
    readme = _read(APP_IAC / "README.md")
    compose = _read(APP_IAC / "compose.yaml")

    for key in (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_SERVICE_NAME",
        "OTEL_RESOURCE_ATTRIBUTES",
    ):
        assert f"| `{key}` |" in readme

    assert "OTLP HTTP endpoint" in readme
    assert "IAC_CONFIG_HASH: ${IAC_CONFIG_HASH:-}" in compose
    assert compose.count("IAC_CONFIG_HASH: ${IAC_CONFIG_HASH:-}") >= 2


def test_backend_otel_absence_is_startup_safe(monkeypatch) -> None:
    """AC10.7.1 AC10.7.4: Missing OTEL endpoint keeps startup path local."""
    monkeypatch.setattr(logger_module.settings, "otel_exporter_otlp_endpoint", None)

    logger_module._configure_otel_tracing()
    logger_module._configure_otel_logging()


def test_external_api_logging_omits_sensitive_arguments_by_default(caplog) -> None:
    """AC10.7.3: External API logging omits credentials unless explicitly requested."""

    @logger_module.log_external_api("example-provider")
    def call_provider(password: str, *, token: str) -> str:
        assert password
        assert token
        return "ok"

    with caplog.at_level(logging.INFO):
        assert call_provider("super-secret-password", token="bearer-token") == "ok"

    assert "External API call to example-provider" in caplog.text
    assert "super-secret-password" not in caplog.text
    assert "bearer-token" not in caplog.text
    assert "kwargs_keys" not in caplog.text


def test_production_renderer_outputs_structured_json(monkeypatch) -> None:
    """AC10.7.7: Non-debug renderer emits parseable structured JSON."""
    monkeypatch.setattr(logger_module.settings, "debug", False)

    renderer = logger_module._select_renderer()
    rendered = renderer(None, "info", {"event": "startup", "service": "backend"})

    payload = json.loads(rendered)
    assert payload == {"event": "startup", "service": "backend"}


def test_AC10_8_4_high_volume_fx_audit_noise_uses_debug_level() -> None:
    """AC10.8.4: High-volume staging audit noise is debug-only by default."""
    database = _read(REPO_ROOT / "apps" / "backend" / "src" / "database.py")
    fx_revaluation = _read(REPO_ROOT / "apps" / "backend" / "src" / "services" / "fx_revaluation.py")
    reporting = _read(REPO_ROOT / "apps" / "backend" / "src" / "services" / "reporting")

    assert "echo=settings.debug" in database
    assert 'logger.debug(\n        "Calculated unrealized FX gains/losses"' in fx_revaluation
    assert 'logger.debug(\n                "Skipping portfolio valuation without market price"' in reporting


def test_AC10_9_1_observability_status_is_redacted_and_vendor_neutral(monkeypatch) -> None:
    """AC10.9.1: Runtime observability status is stable, redacted, and vendor-neutral OTEL."""
    monkeypatch.setattr(
        observability_module.settings,
        "otel_exporter_otlp_endpoint",
        "http://platform-otel-collector:4318",
    )
    monkeypatch.setattr(observability_module.settings, "otel_service_name", "finance-report-backend")
    monkeypatch.setattr(
        observability_module.settings,
        "otel_resource_attributes",
        "deployment.environment=production,team=finance-report",
    )
    monkeypatch.setattr(observability_module.settings, "environment", "production")
    telemetry_metrics_module.mark_metrics_export_active(False)

    status = observability_module.get_observability_status()

    assert status["otel_exporter_configured"] is True
    assert status["logs_export_enabled"] is True
    assert status["traces_export_enabled"] is True
    assert status["metrics_export_enabled"] is False
    assert status["service_name"] == "finance-report-backend"
    assert status["deployment_environment"] == "production"
    assert status["resource_attributes"] == {
        "deployment.environment": "production",
        "team": "finance-report",
    }
    # The app no longer declares any backend-specific alert routing; choosing the
    # backend and wiring alert rules is infra2's concern behind the OTLP endpoint.
    assert "alert_rule_name" not in status
    assert "alert_rule_service_name" not in status
    assert "alerting_pipeline" not in status
    assert "otel_exporter_otlp_endpoint" not in status
    assert "platform-otel-collector" not in json.dumps(status)


def test_AC10_9_2_observability_startup_log_uses_runtime_contract(monkeypatch) -> None:
    """AC10.9.2: Startup emits one safe structured observability contract event."""
    monkeypatch.setattr(observability_module.settings, "otel_exporter_otlp_endpoint", None)
    monkeypatch.setattr(observability_module.settings, "otel_service_name", "finance-report-backend")
    monkeypatch.setattr(observability_module.settings, "otel_resource_attributes", None)
    monkeypatch.setattr(observability_module.settings, "environment", "staging")
    telemetry_metrics_module.mark_metrics_export_active(False)
    mock_logger = Mock()

    observability_module.log_observability_startup(mock_logger)

    mock_logger.info.assert_called_once()
    (event,) = mock_logger.info.call_args.args
    fields = mock_logger.info.call_args.kwargs
    assert event == "Observability runtime configured"
    assert fields["otel_exporter_configured"] is False
    assert fields["metrics_export_enabled"] is False
    assert fields["deployment_environment"] == "staging"
    assert "alert_rule_name" not in fields
    assert "otel_exporter_otlp_endpoint" not in fields


def test_AC10_11_1_security_warning_redacts_credentials() -> None:
    """AC10.11.1: Security warning helper never emits raw credentials."""
    mock_logger = Mock()

    observability_module.log_security_warning(
        mock_logger,
        "auth.failure",
        reason="invalid_token",
        client_ip="203.0.113.10",
        token="raw-token",
        authorization="Bearer raw-token",
    )

    mock_logger.warning.assert_called_once()
    (event,) = mock_logger.warning.call_args.args
    fields = mock_logger.warning.call_args.kwargs
    assert event == "auth.failure"
    assert fields["audit_event"] == "auth.failure"
    assert fields["reason"] == "invalid_token"
    assert fields["client_ip"] == "203.0.113.10"
    assert fields["token"] == "[REDACTED]"
    assert fields["authorization"] == "[REDACTED]"


def test_AC10_11_2_financial_mutation_audit_helpers_and_callsites() -> None:
    """AC10.11.2: Financial mutation audit events are stable and wired."""
    mock_logger = Mock()
    user_id = uuid4()
    entry_id = uuid4()

    observability_module.log_financial_mutation(
        mock_logger,
        "journal.entry.posted",
        user_id=user_id,
        action="post",
        resource_type="journal_entry",
        resource_id=entry_id,
        response_body="must not leak",
    )

    mock_logger.info.assert_called_once()
    (event,) = mock_logger.info.call_args.args
    fields = mock_logger.info.call_args.kwargs
    assert event == "journal.entry.posted"
    assert fields["audit_event"] == "journal.entry.posted"
    assert fields["user_id"] == str(user_id)
    assert fields["resource_id"] == str(entry_id)
    assert fields["response_body"] == "[REDACTED]"

    journal = _read(REPO_ROOT / "apps" / "backend" / "src" / "routers" / "journal.py")
    reconciliation = _read(REPO_ROOT / "apps" / "backend" / "src" / "routers" / "reconciliation.py")
    assert "journal.entry.posted" in journal
    assert "journal.entry.voided" in journal
    assert "reconciliation.match.accepted" in reconciliation
    assert "log_financial_mutation" in journal
    assert "log_financial_mutation" in reconciliation


def test_AC10_11_3_provider_error_body_logging_is_redacted() -> None:
    """AC10.11.3: Raw provider bodies are redacted or summarized before logging."""
    safe = observability_module.safe_log_fields(
        {
            "error_body": "provider raw response with prompt and account 123456789",
            "nested": {"provider_response": "raw JSON"},
        }
    )
    assert safe["error_body"] == "[REDACTED]"
    assert safe["nested"]["provider_response"] == "[REDACTED]"

    long_message = "x" * 500
    assert observability_module.safe_error_message(long_message).endswith("...")
    assert len(observability_module.safe_error_message(long_message)) <= 300

    pii_message = observability_module.safe_error_message("provider failed for alice@example.com and account 123456789")
    assert "alice@example.com" not in pii_message
    assert "123456789" not in pii_message
    assert "[EMAIL]" in pii_message
    assert "[BANK_ACCOUNT]" in pii_message

    extraction = _read(REPO_ROOT / "apps" / "backend" / "src" / "services" / "extraction")
    assert "error_body=" not in extraction
    assert "safe_error_message=" in extraction
    assert "OCR layout parsing failed: HTTP {response.status_code}: {error_body}" not in extraction


async def test_AC10_9_3_health_response_includes_redacted_observability_status(monkeypatch) -> None:
    """AC10.9.3: Health exposes the same redacted observability contract for deploy checks."""
    from src import main
    from src.boot import Bootloader, ServiceStatus

    mock_db = AsyncMock()
    monkeypatch.setattr(
        Bootloader,
        "_check_s3",
        AsyncMock(return_value=ServiceStatus("s3", "ok", "Reachable")),
    )
    monkeypatch.setattr(observability_module.settings, "otel_exporter_otlp_endpoint", "http://collector:4318")
    monkeypatch.setattr(observability_module.settings, "otel_service_name", "finance-report-backend")
    monkeypatch.setattr(
        observability_module.settings,
        "otel_resource_attributes",
        "deployment.environment=production",
    )

    response = await main.health_check(db=mock_db)
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["checks"] == {"database": True, "s3": True}
    assert payload["observability"]["service_name"] == "finance-report-backend"
    assert payload["observability"]["deployment_environment"] == "production"
    assert "alert_rule_name" not in payload["observability"]
    assert "otel_exporter_otlp_endpoint" not in payload["observability"]
    assert "collector:4318" not in json.dumps(payload)


def test_AC10_4_3_main_instruments_fastapi_app_instance() -> None:
    """AC10.4.3: main wires FastAPI request instrumentation to the app instance.

    Regression guard for #768/#576: the broken `FastAPIInstrumentor.instrument()`
    (no instance, before the app existed) must not return, and the per-app
    `instrument_app(app)` API must be used after app creation.
    """
    source = _read(REPO_ROOT / "apps" / "backend" / "src" / "main.py")

    assert "FastAPIInstrumentor.instrument_app(app)" in source
    assert "_instrument_fastapi_app(app)" in source
    # The no-op base-class form must never be reintroduced.
    assert "FastAPIInstrumentor.instrument()" not in source


def test_AC10_4_3_instrumentation_state_reflected_in_status() -> None:
    """AC10.4.3: observability status reports REAL instrumentation init, not config."""
    original = observability_module.is_fastapi_instrumentation_active()
    try:
        observability_module.mark_fastapi_instrumentation_active(False)
        status = observability_module.get_observability_status()
        assert status["request_instrumentation_active"] is False
        assert "service_version" in status

        observability_module.mark_fastapi_instrumentation_active(True)
        assert observability_module.get_observability_status()["request_instrumentation_active"] is True
    finally:
        observability_module.mark_fastapi_instrumentation_active(original)


def test_AC10_4_4_otel_resource_includes_commit_version(monkeypatch) -> None:
    """AC10.4.4: trace/log resource carries the deploy commit for correlation."""
    monkeypatch.setattr(logger_module.settings, "git_commit_sha", "abc1234", raising=False)
    resource = logger_module._build_otel_resource()
    attributes = dict(resource.attributes)
    assert attributes.get("service.version") == "abc1234"
    assert attributes.get("git.commit") == "abc1234"
    assert attributes.get("service.name") == logger_module.settings.otel_service_name


def test_AC10_4_3_instrument_app_applies_to_instance(monkeypatch) -> None:
    """AC10.4.3: _instrument_fastapi_app applies instrumentation to the app instance."""
    import sys
    import types

    from fastapi import FastAPI

    from src import main as main_module

    fake_module = types.ModuleType("opentelemetry.instrumentation.fastapi")
    fake_instrumentor = Mock()
    fake_module.FastAPIInstrumentor = fake_instrumentor
    monkeypatch.setitem(sys.modules, "opentelemetry.instrumentation.fastapi", fake_module)
    monkeypatch.setattr(main_module.settings, "otel_exporter_otlp_endpoint", "http://collector:4318", raising=False)
    observability_module.mark_fastapi_instrumentation_active(False)

    app = FastAPI()
    main_module._instrument_fastapi_app(app)

    fake_instrumentor.instrument_app.assert_called_once_with(app)
    assert observability_module.is_fastapi_instrumentation_active() is True


def test_AC10_4_3_instrument_app_skips_without_endpoint(monkeypatch) -> None:
    """AC10.4.3: instrumentation is a no-op (and stays inactive) without an endpoint."""
    from fastapi import FastAPI

    from src import main as main_module

    monkeypatch.setattr(main_module.settings, "otel_exporter_otlp_endpoint", None, raising=False)
    observability_module.mark_fastapi_instrumentation_active(False)

    main_module._instrument_fastapi_app(FastAPI())

    assert observability_module.is_fastapi_instrumentation_active() is False
