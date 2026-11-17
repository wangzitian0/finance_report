"AC-runtime.6.1"

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from infra2_sdk.runtime.environment import resolve_environment_tier

from src.boot import Bootloader, ServiceStatus
from src.config import settings
from src.observability import ErrorIds
from src.runtime import DEPENDENCY_MANIFEST, EnvTier, resolve_env_tier

_ALL_OK = {
    "_check_database": ServiceStatus("database", "ok", "OK"),
    "_check_s3": ServiceStatus("minio", "ok", "OK"),
    "_check_openrouter": ServiceStatus("ai_provider", "ok", "OK"),
    "_check_cache": ServiceStatus("cache", "ok", "OK"),
    "_check_workflow_engine": ServiceStatus("workflow_engine", "ok", "OK"),
    "_check_telemetry": ServiceStatus("telemetry", "ok", "OK"),
    "_check_analytics": ServiceStatus("analytics", "ok", "OK"),
    "_check_market_data": ServiceStatus("market_data", "ok", "OK"),
}


class _DummyAsyncSession:
    async def execute(self, *args, **kwargs):
        return None


class _DummyAsyncSessionContext:
    async def __aenter__(self):
        return _DummyAsyncSession()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


_dummy_session_maker = lambda: _DummyAsyncSessionContext()


def _stub_probes(monkeypatch, **overrides: ServiceStatus) -> None:
    import src.main as main_module

    monkeypatch.setattr(main_module, "get_test_session_maker", lambda: _dummy_session_maker)
    for method, status in {**_ALL_OK, **overrides}.items():
        monkeypatch.setattr(Bootloader, method, AsyncMock(return_value=status))


async def test_AC_runtime_6_1_full_health_asserts_the_declared_set(client: AsyncClient, monkeypatch) -> None:
    "AC-runtime.6.1"
    _stub_probes(monkeypatch)
    response = await client.get("/health?full=1")
    assert response.status_code == 200
    body = response.json()
    tier = resolve_env_tier(settings.environment, github_actions=os.getenv("GITHUB_ACTIONS", "").lower() == "true")
    declared = DEPENDENCY_MANIFEST.required_for(tier)
    assert set(body["checks"]) == declared, f"declared {sorted(declared)} vs reported {sorted(body['checks'])}"
    assert all(entry["status"] == "present" for entry in body["checks"].values())


async def test_full_health_503_when_a_declared_dep_is_absent(client: AsyncClient, monkeypatch) -> None:
    _stub_probes(monkeypatch, _check_s3=ServiceStatus("minio", "error", "down"))
    response = await client.get("/health?full=1")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
    assert response.json()["checks"]["object_storage"]["status"] == "absent"


async def test_plain_health_stays_light(client: AsyncClient, monkeypatch) -> None:
    _stub_probes(monkeypatch)
    response = await client.get("/livez")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "alive"
    assert body["service"] == "finance-report-backend"


async def test_health_reports_the_sdk_environment_tier_as_a_second_opinion(client: AsyncClient, monkeypatch) -> None:
    _stub_probes(monkeypatch)
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    expected = resolve_environment_tier(
        settings.environment,
        github_actions=os.getenv("GITHUB_ACTIONS", "").lower() == "true",
        unknown="production",
    )
    assert body["sdk_environment_tier"] == expected.value


def test_smoke_script_calls_the_full_health_form() -> None:
    script = Path(__file__).resolve().parents[4] / "common/runtime/shell/smoke_test.sh"
    content = script.read_text(encoding="utf-8")
    assert "api/health?full=1" in content, "smoke_test.sh no longer asserts the manifest-declared dependency set"


@pytest.mark.no_db
@pytest.mark.parametrize("tier", list(EnvTier))
def test_every_tier_declaration_is_smoke_assertable(tier: EnvTier) -> None:
    probed, unprobed = Bootloader._required_checks(tier)
    assert set(probed) == DEPENDENCY_MANIFEST.required_for(tier)
    assert unprobed == []


_LIVENESS_BODY_KEYS = {
    "status",
    "service",
    "timestamp",
    "version",
    "git_sha",
    "checks",
    "reasons",
    "observability",
    "sdk_environment_tier",
}


@pytest.mark.parametrize("path", ["/health", "/health?full=1"])
async def test_health_body_carries_only_the_pinned_fields(client: AsyncClient, monkeypatch, path: str) -> None:
    _stub_probes(monkeypatch)
    response = await client.get(path)
    assert response.status_code == 200
    assert set(response.json()) == _LIVENESS_BODY_KEYS


async def test_health_unexpected_failure_logs_error_id(client: AsyncClient, monkeypatch) -> None:
    import src.main as main_module

    mock_logger = MagicMock()
    monkeypatch.setattr(main_module, "logger", mock_logger)
    monkeypatch.setattr(Bootloader, "_check_s3", AsyncMock(side_effect=RuntimeError("catastrophic failure")))
    response = await client.get("/health?full=1")
    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"
    mock_logger.error.assert_called_once()
    assert mock_logger.error.call_args.kwargs.get("error_id") == ErrorIds.HEALTH_CHECK_FAILED


async def test_AC_runtime_7_3_plain_health_is_fast_liveness_without_external_io(
    client: AsyncClient, monkeypatch
) -> None:
    "AC-runtime.7.3"
    import src.main as main_module

    mock_s3 = AsyncMock(return_value=ServiceStatus("minio", "ok", "OK"))
    monkeypatch.setattr(Bootloader, "_check_s3", mock_s3)
    mock_db_maker = MagicMock(side_effect=AssertionError("DB session maker invoked on plain liveness"))
    monkeypatch.setattr(main_module, "get_test_session_maker", mock_db_maker)
    response = await client.get("/livez")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "alive"
    assert mock_s3.call_count == 0
    assert mock_db_maker.call_count == 0


@pytest.mark.no_db
def test_bootloader_and_health_have_no_vault_secrets_file_coupling() -> None:
    import src.boot as boot_module
    import src.main as main_module

    assert not hasattr(boot_module.Bootloader, "_check_vault_secrets")
    assert not hasattr(boot_module, "VAULT_SECRETS_FILE_PATH")
    assert not hasattr(boot_module, "VAULT_SECRETS_STALENESS_THRESHOLD_SECONDS")
    assert not hasattr(main_module, "VAULT_SECRETS_FILE_PATH")
