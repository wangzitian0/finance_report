"EPIC-010"

from __future__ import annotations
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
import pytest
from pydantic import ValidationError
from src import observability as observability_module
from src.config import Settings
from src.observability import telemetry_metrics as telemetry_metrics_module

REPO_ROOT = Path(__file__).resolve().parents[4]
pytestmark = pytest.mark.no_db


def _read(path: Path) -> str:
    if path.is_dir():
        return "\n# <<< file-boundary >>>\n".join((p.read_text(encoding="utf-8") for p in sorted(path.rglob("*.py"))))
    return path.read_text(encoding="utf-8")


def test_otel_settings_are_explicit_and_environment_backed(monkeypatch) -> None:
    "AC-observability.1.1 AC-observability.5.4"
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
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "service.version=abc123")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=production")
    assert Settings(_env_file=None).environment == "production"
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "")
    assert Settings(_env_file=None).environment == "production"
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "")
    assert Settings(_env_file=None).environment == "development"


@pytest.mark.parametrize(
    ("environment", "declared"), [("production", "staging"), ("staging", "production"), ("production", "development")]
)
def test_AC_runtime_guard_proofs_7_telemetry_tag_value_mismatch_fails_boot(
    monkeypatch, environment: str, declared: str
) -> None:
    "AC-runtime.guard-proofs.7"
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", f"deployment.environment={declared}")
    with pytest.raises(ValidationError, match="deployment.environment"):
        Settings(_env_file=None)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_AC_runtime_guard_proofs_8_telemetry_tag_value_match_boots(monkeypatch, environment: str) -> None:
    "AC-runtime.guard-proofs.8"
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", f"deployment.environment={environment}")
    assert Settings(_env_file=None).environment == environment
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", f"deployment.environment= {environment.upper()}")
    assert Settings(_env_file=None).environment == environment
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment=production")
    assert Settings(_env_file=None).environment == "development"


def test_observability_ssot_and_env_docs_are_linked() -> None:
    "AC-observability.17.1 AC-observability.17.2 AC-observability.17.3 AC-observability.17.4 AC10.5.1 AC10.5.2 AC10.5.3 AC10.7.5"
    observability = _read(REPO_ROOT / "common" / "observability" / "observability.md")
    env_example = _read(REPO_ROOT / ".env.example")
    assert "SSOT Key" in observability
    assert "observability" in observability
    assert all(
        (
            key in observability and key in env_example
            for key in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_SERVICE_NAME", "OTEL_RESOURCE_ATTRIBUTES")
        )
    )


def test_required_env_manifest_exports_observability_contract() -> None:
    "AC-observability.6.1 AC-observability.6.2 AC-observability.6.3 AC-observability.6.4"
    manifest = json.loads(_read(REPO_ROOT / "common" / "runtime" / "required-env.generated.json"))
    fields = {entry["env"]: entry for entry in manifest["fields"]}
    assert all(
        (
            key in fields and key in _read(REPO_ROOT / "common" / "runtime" / "env-reference.generated.md")
            for key in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_SERVICE_NAME", "OTEL_RESOURCE_ATTRIBUTES")
        )
    )


def test_backend_otel_absence_is_startup_safe(monkeypatch) -> None:
    "AC-observability.7.1 AC-observability.7.4"
    monkeypatch.setattr(observability_module.settings, "otel_exporter_otlp_endpoint", None)
    monkeypatch.setattr(telemetry_metrics_module.settings, "otel_exporter_otlp_endpoint", None)
    observability_module.configure_logging()
    telemetry_metrics_module.configure_otel_metrics()
    assert telemetry_metrics_module.is_metrics_export_active() is False


def test_production_renderer_outputs_structured_json() -> None:
    "AC-observability.7.7"
    from infra2_sdk.runtime.otel import _JsonLogFormatter

    formatter = _JsonLogFormatter(
        {"service.name": "backend", "deployment.environment.name": "production", "service.version": "1.0"}
    )
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "startup", (), None)
    payload = json.loads(formatter.format(record))
    assert payload["message"] == "startup"
    assert payload["service.name"] == "backend"


def test_AC10_8_4_high_volume_fx_audit_noise_uses_debug_level() -> None:
    "AC-observability.8.4"
    fx_revaluation = _read(REPO_ROOT / "apps" / "backend" / "src" / "ledger" / "extension" / "fx_revaluation.py")
    reporting = _read(REPO_ROOT / "apps" / "backend" / "src" / "reporting")
    assert 'logger.debug(\n        "Calculated unrealized FX gains/losses"' in fx_revaluation
    assert 'logger.debug(\n                "Skipping portfolio valuation without market price"' in reporting


@pytest.mark.parametrize("debug", [True, False])
def test_AC10_8_4_sql_echo_of_the_app_engine_follows_settings_debug(monkeypatch, debug) -> None:
    """AC-observability.8.4: The engine of the app echoes SQL exactly when settings.debug is on."""
    from src import database

    monkeypatch.setattr(database.settings, "debug", debug)

    engine = database.create_app_engine("postgresql+asyncpg://user:password@127.0.0.1:1/unused")

    assert bool(engine.sync_engine.echo) is debug


def test_AC10_9_1_observability_status_is_redacted_and_vendor_neutral(monkeypatch) -> None:
    "AC-observability.9.1"
    monkeypatch.setattr(
        observability_module.settings, "otel_exporter_otlp_endpoint", "http://platform-otel-collector:4318"
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
    assert status["resource_attributes"] == {"deployment.environment": "production", "team": "finance-report"}
    assert "alert_rule_name" not in status
    assert "alert_rule_service_name" not in status
    assert "alerting_pipeline" not in status
    assert "otel_exporter_otlp_endpoint" not in status
    assert "platform-otel-collector" not in json.dumps(status)


def test_AC10_9_2_observability_startup_log_uses_runtime_contract(monkeypatch) -> None:
    "AC-observability.9.2"
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
    "AC-observability.11.1 AC-observability.7.3"
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
    "AC-observability.11.2"
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
    "AC-observability.11.3"
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
    extraction = _read(REPO_ROOT / "apps" / "backend" / "src" / "extraction" / "extension")
    assert "error_body=" not in extraction
    assert "safe_error_message=" in extraction
    assert "OCR layout parsing failed: HTTP {response.status_code}: {error_body}" not in extraction


async def test_AC10_9_3_health_response_includes_redacted_observability_status(monkeypatch) -> None:
    "AC-observability.9.3"
    from httpx import ASGITransport, AsyncClient
    from src import main as main_module
    from src.boot import Bootloader, ServiceStatus

    monkeypatch.setattr(Bootloader, "_check_database", AsyncMock(return_value=ServiceStatus("database", "ok", "OK")))
    monkeypatch.setattr(Bootloader, "_check_s3", AsyncMock(return_value=ServiceStatus("s3", "ok", "Reachable")))
    monkeypatch.setattr(observability_module.settings, "otel_exporter_otlp_endpoint", "http://collector:4318")
    monkeypatch.setattr(observability_module.settings, "otel_service_name", "finance-report-backend")
    monkeypatch.setattr(observability_module.settings, "otel_resource_attributes", "deployment.environment=production")
    async with AsyncClient(transport=ASGITransport(app=main_module.app), base_url="http://test") as client:
        response = await client.get("/health?full=1")
    payload = response.json()
    assert response.status_code == 200
    assert payload["checks"]["database"]["status"] == "present"
    assert payload["checks"]["object_storage"]["status"] == "present"
    assert payload["observability"]["service_name"] == "finance-report-backend"
    assert payload["observability"]["deployment_environment"] == "production"
    assert "alert_rule_name" not in payload["observability"]
    assert "otel_exporter_otlp_endpoint" not in payload["observability"]
    assert "collector:4318" not in json.dumps(payload)


def test_AC10_4_3_main_instruments_fastapi_app_instance() -> None:
    "AC-observability.4.3"
    source = _read(REPO_ROOT / "apps" / "backend" / "src" / "main.py")
    assert "telemetry=" in source
    assert "_sync_fastapi_telemetry_status(app)" in source
    assert "FastAPIInstrumentor" not in source
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
    from src.observability import ErrorIds

    assert ErrorIds.HEALTH_CHECK_FAILED == "ERR_SYS_001"
    assert ErrorIds.UNHANDLED_EXCEPTION == "ERR_SYS_002"
    import ast

    backend_src = REPO_ROOT / "apps" / "backend" / "src"
    offenders: list[str] = []
    for path in sorted(backend_src.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "logger"):
                continue
            rel = path.relative_to(REPO_ROOT)
            for kw in node.keywords:
                if kw.arg == "raw_preview":
                    offenders.append(f"{rel}:{node.lineno} passes raw_preview=")
                if (
                    isinstance(kw.value, ast.Subscript)
                    and isinstance(kw.value.value, ast.Name)
                    and kw.value.value.id == "content"
                ):
                    offenders.append(f"{rel}:{node.lineno} slices content[...] in logger.{func.attr}")
            for arg in node.args:
                if isinstance(arg, ast.Subscript) and isinstance(arg.value, ast.Name) and arg.value.id == "content":
                    offenders.append(f"{rel}:{node.lineno} slices content[...] in logger.{func.attr}")
    assert not offenders, f"Logger calls must never emit raw model/statement content slices (#2676): {offenders}"


def test_AC10_4_4_otel_resource_includes_commit_version(monkeypatch) -> None:
    "AC-observability.4.4"
    from infra2_sdk.runtime.otel import OtelSettings, resource_attributes

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "finance-report-backend")
    monkeypatch.setenv("SERVICE_VERSION", "abc1234")
    s = OtelSettings.from_env(strict=True)
    attributes = resource_attributes(s)
    assert attributes.get("service.version") == "abc1234"
    assert attributes.get("service.name") == "finance-report-backend"


def test_AC10_4_3_instrument_app_applies_to_instance(monkeypatch) -> None:
    "AC-observability.4.3"
    from fastapi import FastAPI
    from src import main as main_module

    monkeypatch.setattr(main_module.settings, "otel_exporter_otlp_endpoint", "http://collector:4318", raising=False)
    observability_module.mark_fastapi_instrumentation_active(False)
    app = FastAPI(telemetry={"tracing": True, "tracer_provider": object()})
    assert main_module._sync_fastapi_telemetry_status(app) is True
    assert observability_module.is_fastapi_instrumentation_active() is True
    disabled_app = FastAPI(telemetry={"tracing": False, "metrics": False, "logs": False})
    assert main_module._sync_fastapi_telemetry_status(disabled_app) is False
    assert observability_module.is_fastapi_instrumentation_active() is False


def test_AC10_4_3_instrument_app_skips_without_endpoint(monkeypatch) -> None:
    "AC-observability.4.3"
    from fastapi import FastAPI
    from src import main as main_module

    monkeypatch.setattr(main_module.settings, "otel_exporter_otlp_endpoint", None, raising=False)
    observability_module.mark_fastapi_instrumentation_active(True)
    app = FastAPI(telemetry={"tracing": True, "tracer_provider": object()})
    assert main_module._sync_fastapi_telemetry_status(app) is False
    assert observability_module.is_fastapi_instrumentation_active() is False
