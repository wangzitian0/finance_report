"""AC-runtime.6.1 (#1578) — smoke ↔ declaration parity via ``/health?full=1``.

Invariant 6: the smoke's dependency-presence assertion covers exactly the
manifest-declared set for the running tier. ``GET /health?full=1`` (which the
smoke script calls) probes every dependency in
``DEPENDENCY_MANIFEST.required_for(tier)`` and returns 503 if any is absent.
The parity is structural: the response's ``checks`` keys are derived from the
manifest, so a manifest edit cannot silently widen or narrow the smoke.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

from src.boot import Bootloader, ServiceStatus
from src.runtime import DEPENDENCY_MANIFEST, EnvTier

_ALL_OK = {
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


def _dummy_session_maker():
    return _DummyAsyncSessionContext()


def _stub_probes(monkeypatch, **overrides: ServiceStatus) -> None:
    import src.runtime.extension.api.health as health_api

    monkeypatch.setattr(health_api, "_test_session_maker", _dummy_session_maker)
    for method, status in {**_ALL_OK, **overrides}.items():
        monkeypatch.setattr(Bootloader, method, AsyncMock(return_value=status))


async def test_AC_runtime_6_1_full_health_asserts_the_declared_set(client: AsyncClient, monkeypatch) -> None:
    """AC-runtime.6.1: ?full=1 reports a check per declared dependency of the tier."""
    _stub_probes(monkeypatch)

    response = await client.get("/health?full=1")

    assert response.status_code == 200
    body = response.json()
    tier = EnvTier(body["tier"])
    declared = DEPENDENCY_MANIFEST.required_for(tier)
    # 'database' and legacy 's3' are the light-form keys; object_storage maps to s3.
    reported = (set(body["checks"]) - {"s3"}) | ({"object_storage"} if "s3" in body["checks"] else set())
    # Strict equality (invariant 6 is EXACT parity): an extra reported key is
    # drift just like a missing one. database/object_storage are declared in
    # every tier, so the mapped check set must equal the declaration.
    assert reported == declared, f"declared {sorted(declared)} vs reported {sorted(reported)}"


async def test_full_health_503_when_a_declared_dep_is_absent(client: AsyncClient, monkeypatch) -> None:
    """Invariant 2 through the smoke path: absent declared dep ⇒ 503."""
    _stub_probes(monkeypatch, _check_s3=ServiceStatus("minio", "error", "down"))

    response = await client.get("/health?full=1")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


async def test_plain_health_stays_light(client: AsyncClient, monkeypatch) -> None:
    """The frequent Docker healthcheck / liveness form checks liveness without dependency overhead."""
    _stub_probes(monkeypatch)

    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["checks"] == {"liveness": True}
    assert "tier" not in body


async def test_health_reports_the_sdk_environment_tier_as_a_second_opinion(client: AsyncClient, monkeypatch) -> None:
    """infra2_sdk.runtime.environment.resolve_environment_tier runs alongside (not
    instead of) this repo's own EnvTier resolution — present even on the light form,
    fed settings.environment directly (not environment_from_env(), which reads
    os.environ; pydantic-settings' env_file loads ENVIRONMENT from the vault-rendered
    file without ever populating the real process environment)."""
    import os

    from infra2_sdk.runtime.environment import resolve_environment_tier

    from src.config import settings

    _stub_probes(monkeypatch)

    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    # Must mirror health.py's own github_actions detection exactly: this test's
    # own CI run has GITHUB_ACTIONS=true, so omitting it here passed locally
    # (both sides silently defaulted to False) but failed in CI, where health.py
    # correctly resolves "github_ci" while this line was still computing
    # "local_test" for the "expected" side — a false mismatch in the test's own
    # oracle, not a health.py bug. Caught by CI, not local runs.
    expected = resolve_environment_tier(
        settings.environment,
        github_actions=os.getenv("GITHUB_ACTIONS", "").lower() == "true",
        unknown="production",
    )
    assert body["sdk_environment_tier"] == expected.value


def test_smoke_script_calls_the_full_health_form() -> None:
    """The smoke script must assert dependency presence via /api/health?full=1 —
    dropping the line breaks parity (invariant 6), so it is pinned here."""
    script = Path(__file__).resolve().parents[4] / "common/runtime/shell/smoke_test.sh"
    content = script.read_text(encoding="utf-8")
    assert "api/health?full=1" in content, "smoke_test.sh no longer asserts the manifest-declared dependency set"


@pytest.mark.no_db
@pytest.mark.parametrize("tier", list(EnvTier))
def test_every_tier_declaration_is_smoke_assertable(tier: EnvTier) -> None:
    """Structural parity: every declared dependency of every tier resolves to a
    probe, so ?full=1 can assert the whole declaration (no silent remainder)."""
    probed, unprobed = Bootloader._required_checks(tier)
    assert set(probed) == DEPENDENCY_MANIFEST.required_for(tier)
    assert unprobed == []


# ── #2684: the body carries verdict-bearing fields only ──
# The secrets-file freshness snapshot (#1828) was never part of the verdict, no
# consumer read it, and it turned stale one hour after each deploy. It is gone;
# this pins the body so an informational field cannot return unnoticed.

_LIVENESS_BODY_KEYS = {"status", "timestamp", "version", "git_sha", "checks", "observability", "sdk_environment_tier"}


@pytest.mark.parametrize(
    ("path", "expected_keys"),
    [("/health", _LIVENESS_BODY_KEYS), ("/health?full=1", _LIVENESS_BODY_KEYS | {"tier"})],
)
async def test_health_body_has_no_secrets_file_freshness_field(
    client: AsyncClient, monkeypatch, tmp_path, path: str, expected_keys: set[str]
) -> None:
    from src import boot as boot_module

    _stub_probes(monkeypatch)
    secrets_file = tmp_path / ".env"
    secrets_file.write_text("PLACEHOLDER=1\n", encoding="utf-8")
    monkeypatch.setattr(boot_module, "VAULT_SECRETS_FILE_PATH", str(secrets_file))

    response = await client.get(path)

    assert response.status_code == 200
    assert set(response.json()) == expected_keys


async def test_health_unexpected_failure_logs_error_id(client: AsyncClient, monkeypatch) -> None:
    """Unexpected exception in /health logs with ErrorIds.HEALTH_CHECK_FAILED."""
    from unittest.mock import AsyncMock, MagicMock

    import src.runtime.extension.api.health as health_api
    from src.boot import Bootloader
    from src.observability import ErrorIds

    mock_logger = MagicMock()
    monkeypatch.setattr(health_api, "logger", mock_logger)
    monkeypatch.setattr(Bootloader, "_check_s3", AsyncMock(side_effect=RuntimeError("catastrophic failure")))

    response = await client.get("/health?full=1")
    assert response.status_code == 503
    assert response.json()["status"] == "error"
    mock_logger.error.assert_called_once()
    assert mock_logger.error.call_args.kwargs.get("error_id") == ErrorIds.HEALTH_CHECK_FAILED


async def test_AC_runtime_7_3_plain_health_is_fast_liveness_without_external_io(
    client: AsyncClient, monkeypatch
) -> None:
    """AC-runtime.7.3: plain /health is a fast liveness check without DB or S3 roundtrips."""
    from unittest.mock import AsyncMock, MagicMock

    import src.runtime.extension.api.health as health_api
    from src.boot import Bootloader, ServiceStatus

    mock_s3 = AsyncMock(return_value=ServiceStatus("minio", "ok", "OK"))
    monkeypatch.setattr(Bootloader, "_check_s3", mock_s3)

    mock_db_maker = MagicMock(side_effect=AssertionError("DB session maker invoked on plain liveness"))
    monkeypatch.setattr(health_api, "_test_session_maker", mock_db_maker)
    monkeypatch.setattr(health_api, "async_session_maker", mock_db_maker)

    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert "timestamp" in body
    assert "git_sha" in body
    assert "checks" in body
    assert body["checks"].get("liveness") is True
    # Crucial: S3 and external dependencies must NOT be called on plain liveness
    assert mock_s3.call_count == 0
    assert mock_db_maker.call_count == 0
    assert "s3" not in body["checks"]
    assert "database" not in body["checks"]
