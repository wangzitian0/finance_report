"""Focused observability contract tests for EPIC-010."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from src import logger as logger_module, observability as observability_module
from src.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[4]
APP_IAC = REPO_ROOT / "repo" / "finance_report" / "finance_report" / "10.app"
pytestmark = pytest.mark.no_db


def _read(path: Path) -> str:
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

    assert "SigNoz OTLP HTTP endpoint" in readme
    assert "IAC_CONFIG_HASH: ${IAC_CONFIG_HASH:-}" in compose
    assert compose.count("IAC_CONFIG_HASH: ${IAC_CONFIG_HASH:-}") >= 2


def test_backend_otel_absence_is_startup_safe(monkeypatch) -> None:
    """AC10.7.1 AC10.7.4: Missing OTEL endpoint keeps startup path local."""
    monkeypatch.setattr(logger_module.settings, "otel_exporter_otlp_endpoint", None)

    logger_module._configure_otel_tracing()
    logger_module._configure_otel_logging()


def test_external_api_logging_omits_sensitive_arguments_by_default(caplog) -> None:
    """AC10.7.3: External API logging omits credentials unless explicitly requested."""

    @logger_module.log_external_api("signoz")
    def call_signoz(password: str, *, token: str) -> str:
        assert password
        assert token
        return "ok"

    with caplog.at_level(logging.INFO):
        assert call_signoz("super-secret-password", token="bearer-token") == "ok"

    assert "External API call to signoz" in caplog.text
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
    reporting = _read(REPO_ROOT / "apps" / "backend" / "src" / "services" / "reporting.py")

    assert "echo=settings.debug" in database
    assert 'logger.debug(\n        "Calculated unrealized FX gains/losses"' in fx_revaluation
    assert 'logger.debug(\n                "Skipping portfolio valuation without market price"' in reporting


def test_AC10_9_1_observability_status_is_redacted_and_alert_ready(monkeypatch) -> None:
    """AC10.9.1: Runtime observability status is stable, redacted, and alert-aware."""
    monkeypatch.setattr(
        observability_module.settings,
        "otel_exporter_otlp_endpoint",
        "http://platform-signoz-otel-collector:4318",
    )
    monkeypatch.setattr(observability_module.settings, "otel_service_name", "finance-report-backend")
    monkeypatch.setattr(
        observability_module.settings,
        "otel_resource_attributes",
        "deployment.environment=production,team=finance-report",
    )
    monkeypatch.setattr(observability_module.settings, "environment", "production")

    status = observability_module.get_observability_status()

    assert status["otel_exporter_configured"] is True
    assert status["logs_export_enabled"] is True
    assert status["traces_export_enabled"] is True
    assert status["service_name"] == "finance-report-backend"
    assert status["deployment_environment"] == "production"
    assert status["resource_attributes"] == {
        "deployment.environment": "production",
        "team": "finance-report",
    }
    assert status["alert_rule_name"] == "FinanceReportBackendErrorLogs"
    assert status["alert_rule_service_name"] == "finance-report-backend"
    assert status["alerting_pipeline"] == "component->otel->signoz->lark"
    assert "otel_exporter_otlp_endpoint" not in status
    assert "platform-signoz-otel-collector" not in json.dumps(status)


def test_AC10_9_2_observability_startup_log_uses_runtime_contract(monkeypatch) -> None:
    """AC10.9.2: Startup emits one safe structured observability contract event."""
    monkeypatch.setattr(observability_module.settings, "otel_exporter_otlp_endpoint", None)
    monkeypatch.setattr(observability_module.settings, "otel_service_name", "finance-report-backend")
    monkeypatch.setattr(observability_module.settings, "otel_resource_attributes", None)
    monkeypatch.setattr(observability_module.settings, "environment", "staging")
    mock_logger = Mock()

    observability_module.log_observability_startup(mock_logger)

    mock_logger.info.assert_called_once()
    (event,) = mock_logger.info.call_args.args
    fields = mock_logger.info.call_args.kwargs
    assert event == "Observability runtime configured"
    assert fields["otel_exporter_configured"] is False
    assert fields["deployment_environment"] == "staging"
    assert fields["alert_rule_name"] == "FinanceReportBackendErrorLogs"
    assert "otel_exporter_otlp_endpoint" not in fields


@pytest.mark.asyncio
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
    assert payload["observability"]["alert_rule_name"] == "FinanceReportBackendErrorLogs"
    assert "otel_exporter_otlp_endpoint" not in payload["observability"]
    assert "collector:4318" not in json.dumps(payload)


def test_AC10_9_4_observability_docs_declare_shared_alerting_pipeline() -> None:
    """AC10.9.4: Finance Report owns app contract docs, infra2 owns shared alert automation."""
    observability = _read(REPO_ROOT / "docs" / "ssot" / "observability.md")
    epic = _read(REPO_ROOT / "docs" / "project" / "EPIC-010.signoz-logging.md")
    infra_alerting = _read(REPO_ROOT / "repo" / "docs" / "ssot" / "ops.alerting.md")

    for text in (observability, epic):
        assert "component -> OTEL -> SigNoz -> Lark" in text
        assert "FinanceReportBackendErrorLogs" in text
        assert "finance-report-backend" in text

    assert "alerting.shared.ensure-log-error-rule" in infra_alerting
    assert "First live instance via shared rule automation" in infra_alerting
