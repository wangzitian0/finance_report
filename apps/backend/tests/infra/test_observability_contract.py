from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from infra2_sdk.telemetry import init_worker
from pydantic import ValidationError

from src import observability as observability_module
from src.config import Settings
from src.observability import telemetry_metrics as telemetry_metrics_module

REPO_ROOT = Path(__file__).resolve().parents[4]
pytestmark = pytest.mark.no_db


def _read(path: Path) -> str:
    return (
        "\n# <<< file-boundary >>>\n".join(p.read_text(encoding="utf-8") for p in sorted(path.rglob("*.py")))
        if path.is_dir()
        else path.read_text(encoding="utf-8")
    )


def _set_env(monkeypatch: pytest.MonkeyPatch, **values: str | None) -> None:
    for key, val in values.items():
        monkeypatch.delenv(key, raising=False) if val is None else monkeypatch.setenv(key, val)


def _set_otel(
    monkeypatch: pytest.MonkeyPatch, *, endpoint: str | None, attrs: str | None = None, env: str | None = None
) -> None:
    for attr, val in (
        ("otel_exporter_otlp_endpoint", endpoint),
        ("otel_service_name", "finance-report-backend"),
        ("otel_resource_attributes", attrs),
    ):
        monkeypatch.setattr(observability_module.settings, attr, val)
    if env is not None:
        monkeypatch.setattr(observability_module.settings, "environment", env)


def test_otel_settings_and_telemetry_contract(monkeypatch) -> None:
    _set_env(monkeypatch, OTEL_EXPORTER_OTLP_ENDPOINT=None, OTEL_SERVICE_NAME=None, OTEL_RESOURCE_ATTRIBUTES=None)
    d = Settings(_env_file=None)
    assert (d.otel_exporter_otlp_endpoint, d.otel_service_name, d.otel_resource_attributes) == (
        None,
        "finance-report-backend",
        None,
    )

    _set_env(
        monkeypatch,
        OTEL_EXPORTER_OTLP_ENDPOINT="http://collector:4318",
        OTEL_SERVICE_NAME="finance-report-worker",
        OTEL_RESOURCE_ATTRIBUTES="deployment.environment=staging",
    )
    s = Settings(_env_file=None)
    assert (s.otel_exporter_otlp_endpoint, s.otel_service_name, s.otel_resource_attributes) == (
        "http://collector:4318",
        "finance-report-worker",
        "deployment.environment=staging",
    )

    _set_env(
        monkeypatch,
        ENVIRONMENT="production",
        OTEL_EXPORTER_OTLP_ENDPOINT="http://collector:4318",
        OTEL_RESOURCE_ATTRIBUTES="service.version=abc123",
    )
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    for env, ep, attrs in (
        ("production", "http://collector:4318", "deployment.environment=production"),
        ("production", None, ""),
        ("development", "http://collector:4318", ""),
        ("development", "http://collector:4318", "deployment.environment=production"),
    ):
        _set_env(monkeypatch, ENVIRONMENT=env, OTEL_EXPORTER_OTLP_ENDPOINT=ep, OTEL_RESOURCE_ATTRIBUTES=attrs)
        assert Settings(_env_file=None).environment == env


@pytest.mark.parametrize(
    ("env", "declared", "ok"),
    [
        ("production", "staging", False),
        ("staging", "production", False),
        ("production", "development", False),
        ("staging", "staging", True),
        ("production", "production", True),
        ("staging", " STAGING", True),
    ],
)
def test_AC_runtime_guard_proofs_7_and_8_telemetry_tag(monkeypatch, env: str, declared: str, ok: bool) -> None:
    _set_env(
        monkeypatch,
        ENVIRONMENT=env,
        OTEL_EXPORTER_OTLP_ENDPOINT="http://collector:4318",
        OTEL_RESOURCE_ATTRIBUTES=f"deployment.environment={declared}",
    )
    if ok:
        assert Settings(_env_file=None).environment == env
    else:
        with pytest.raises(ValidationError, match="deployment.environment"):
            Settings(_env_file=None)


def test_observability_ssot_manifest_and_json_renderer(monkeypatch, capsys) -> None:
    obs_doc, env_ex = _read(REPO_ROOT / "common/observability/observability.md"), _read(REPO_ROOT / ".env.example")
    fields = {
        e["env"]: e for e in json.loads(_read(REPO_ROOT / "common/runtime/required-env.generated.json"))["fields"]
    }
    assert (
        "SSOT Key" in obs_doc
        and "observability" in obs_doc
        and all(
            k in obs_doc and k in env_ex and k in fields
            for k in ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_SERVICE_NAME", "OTEL_RESOURCE_ATTRIBUTES")
        )
    )

    monkeypatch.setattr(observability_module.settings, "otel_exporter_otlp_endpoint", None)
    monkeypatch.setattr(telemetry_metrics_module.settings, "otel_exporter_otlp_endpoint", None)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "local_dev")
    logging.getLogger().handlers.clear()
    providers = init_worker("backend", set_global=False)
    try:
        telemetry_metrics_module.configure_otel_metrics()
        logging.getLogger("test").info("startup")
        lines = [line for line in capsys.readouterr().out.splitlines() if line.strip().startswith("{")]
        payload = json.loads(lines[-1])
        assert telemetry_metrics_module.is_metrics_export_active() is False and (
            payload["message"],
            payload["service.name"],
        ) == ("startup", "backend")
    finally:
        if providers is not None:
            providers.shutdown()


@pytest.mark.parametrize("debug", [True, False])
def test_AC10_8_4_sql_echo_and_debug_levels(monkeypatch, debug) -> None:
    from src import database

    monkeypatch.setattr(database.settings, "debug", debug)
    assert (
        bool(database.create_app_engine("postgresql+asyncpg://user:password@127.0.0.1:1/unused").sync_engine.echo)
        is debug
    )
    if debug:
        assert 'logger.debug(\n        "Calculated unrealized FX gains/losses"' in _read(
            REPO_ROOT / "apps/backend/src/ledger/extension/fx_revaluation.py"
        )
        assert 'logger.debug(\n                "Skipping portfolio valuation without market price"' in _read(
            REPO_ROOT / "apps/backend/src/reporting"
        )


def test_AC10_9_and_AC10_11_status_startup_redaction_and_callsites(monkeypatch) -> None:
    _set_otel(
        monkeypatch,
        endpoint="http://platform-otel-collector:4318",
        attrs="deployment.environment=production,team=finance-report",
        env="production",
    )
    telemetry_metrics_module.mark_metrics_export_active(False)
    status = observability_module.get_observability_status()
    assert (
        status["otel_exporter_configured"],
        status["logs_export_enabled"],
        status["traces_export_enabled"],
        status["metrics_export_enabled"],
        status["service_name"],
        status["deployment_environment"],
        status["resource_attributes"],
    ) == (
        True,
        True,
        True,
        False,
        "finance-report-backend",
        "production",
        {"deployment.environment": "production", "team": "finance-report"},
    )
    assert all(
        k not in status
        for k in ("alert_rule_name", "alert_rule_service_name", "alerting_pipeline", "otel_exporter_otlp_endpoint")
    ) and "platform-otel-collector" not in json.dumps(status)

    _set_otel(monkeypatch, endpoint=None, attrs=None, env="staging")
    log = Mock()
    observability_module.log_observability_startup(log)
    f = log.info.call_args.kwargs
    assert (
        log.info.call_args.args == ("Observability runtime configured",)
        and (f["otel_exporter_configured"], f["metrics_export_enabled"], f["deployment_environment"])
        == (False, False, "staging")
        and "otel_exporter_otlp_endpoint" not in f
    )

    observability_module.log_security_warning(
        log,
        "auth.failure",
        reason="invalid_token",
        client_ip="203.0.113.10",
        token="raw-token",
        authorization="Bearer raw-token",
    )
    sec = log.warning.call_args.kwargs
    assert (log.warning.call_args.args, sec["audit_event"], sec["token"], sec["authorization"]) == (
        ("auth.failure",),
        "auth.failure",
        "[REDACTED]",
        "[REDACTED]",
    )

    uid, eid = uuid4(), uuid4()
    observability_module.log_financial_mutation(
        log,
        "journal.entry.posted",
        user_id=uid,
        action="post",
        resource_type="journal_entry",
        resource_id=eid,
        response_body="must not leak",
    )
    fin = log.info.call_args.kwargs
    assert (fin["audit_event"], fin["user_id"], fin["resource_id"], fin["response_body"]) == (
        "journal.entry.posted",
        str(uid),
        str(eid),
        "[REDACTED]",
    )
    assert all(
        tok in _read(REPO_ROOT / "apps/backend/src/routers/journal.py")
        for tok in ("journal.entry.posted", "journal.entry.voided", "log_financial_mutation")
    )
    assert all(
        tok in _read(REPO_ROOT / "apps/backend/src/routers/reconciliation.py")
        for tok in ("reconciliation.match.accepted", "log_financial_mutation")
    )

    safe = observability_module.safe_log_fields({"error_body": "raw", "nested": {"provider_response": "raw JSON"}})
    long_msg, pii_msg = (
        observability_module.safe_error_message("x" * 500),
        observability_module.safe_error_message("provider failed for alice@example.com and account 123456789"),
    )
    assert (safe["error_body"], safe["nested"]["provider_response"]) == ("[REDACTED]", "[REDACTED]")
    assert (
        long_msg.endswith("...")
        and len(long_msg) <= 300
        and "[EMAIL]" in pii_msg
        and "[BANK_ACCOUNT]" in pii_msg
        and "alice@example.com" not in pii_msg
        and "123456789" not in pii_msg
    )
    extraction = _read(REPO_ROOT / "apps/backend/src/extraction/extension")
    assert "error_body=" not in extraction and "safe_error_message=" in extraction


async def test_AC10_9_3_and_10_4_health_instrumentation_and_logger_ast(monkeypatch) -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from src import main as main_module
    from src.boot import Bootloader, ServiceStatus
    from src.observability import ErrorIds

    monkeypatch.setattr(Bootloader, "_check_database", AsyncMock(return_value=ServiceStatus("database", "ok", "OK")))
    monkeypatch.setattr(Bootloader, "_check_s3", AsyncMock(return_value=ServiceStatus("s3", "ok", "Reachable")))
    _set_otel(monkeypatch, endpoint="http://collector:4318", attrs="deployment.environment=production")
    async with AsyncClient(transport=ASGITransport(app=main_module.app), base_url="http://test") as client:
        resp = await client.get("/health?full=1")
    pl = resp.json()
    assert resp.status_code == 200 and (
        pl["checks"]["database"]["status"],
        pl["checks"]["object_storage"]["status"],
        pl["observability"]["service_name"],
        pl["observability"]["deployment_environment"],
    ) == ("present", "present", "finance-report-backend", "production")
    assert "alert_rule_name" not in pl["observability"] and "collector:4318" not in json.dumps(pl)

    src_main = _read(REPO_ROOT / "apps/backend/src/main.py")
    assert (
        "telemetry=" in src_main
        and "_sync_fastapi_telemetry_status(app)" in src_main
        and "FastAPIInstrumentor" not in src_main
    )
    orig = observability_module.is_fastapi_instrumentation_active()
    try:
        for flag in (False, True):
            observability_module.mark_fastapi_instrumentation_active(flag)
            assert (
                observability_module.get_observability_status()["request_instrumentation_active"] is flag
                and "service_version" in observability_module.get_observability_status()
            )
    finally:
        observability_module.mark_fastapi_instrumentation_active(orig)
    assert (ErrorIds.HEALTH_CHECK_FAILED, ErrorIds.UNHANDLED_EXCEPTION) == ("ERR_SYS_001", "ERR_SYS_002")

    offenders = [
        f"{p.name}:{n.lineno}"
        for p in sorted((REPO_ROOT / "apps/backend/src").rglob("*.py"))
        if "__pycache__" not in p.parts
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "logger"
        and (
            any(
                kw.arg == "raw_preview"
                or (
                    isinstance(kw.value, ast.Subscript)
                    and isinstance(kw.value.value, ast.Name)
                    and kw.value.value.id == "content"
                )
                for kw in n.keywords
            )
            or any(
                isinstance(a, ast.Subscript) and isinstance(a.value, ast.Name) and a.value.id == "content"
                for a in n.args
            )
        )
    ]
    assert not offenders, offenders

    _set_env(
        monkeypatch,
        ENVIRONMENT="production",
        OTEL_SERVICE_NAME="finance-report-backend",
        SERVICE_VERSION="abc1234",
        OTEL_EXPORTER_OTLP_ENDPOINT="http://collector:4318",
    )
    providers = init_worker("finance-report-backend", strict=True, set_global=False)
    try:
        attrs = dict(providers.tracer_provider.resource.attributes)
        assert (attrs.get("service.version"), attrs.get("service.name")) == ("abc1234", "finance-report-backend")
    finally:
        if providers is not None:
            providers.shutdown()

    enabled, disabled = (
        FastAPI(telemetry={"tracing": True, "tracer_provider": object()}),
        FastAPI(telemetry={"tracing": False, "metrics": False, "logs": False}),
    )
    monkeypatch.setattr(main_module.settings, "otel_exporter_otlp_endpoint", "http://collector:4318", raising=False)
    observability_module.mark_fastapi_instrumentation_active(False)
    assert (
        main_module._sync_fastapi_telemetry_status(enabled) is True
        and observability_module.is_fastapi_instrumentation_active() is True
    )
    assert (
        main_module._sync_fastapi_telemetry_status(disabled) is False
        and observability_module.is_fastapi_instrumentation_active() is False
    )
    monkeypatch.setattr(main_module.settings, "otel_exporter_otlp_endpoint", None, raising=False)
    observability_module.mark_fastapi_instrumentation_active(True)
    assert (
        main_module._sync_fastapi_telemetry_status(enabled) is False
        and observability_module.is_fastapi_instrumentation_active() is False
    )
