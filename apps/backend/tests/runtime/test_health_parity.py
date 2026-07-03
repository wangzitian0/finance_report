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


def _stub_probes(monkeypatch, **overrides: ServiceStatus) -> None:
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
    assert declared <= reported, f"declared {sorted(declared)} vs reported {sorted(reported)}"


async def test_full_health_503_when_a_declared_dep_is_absent(client: AsyncClient, monkeypatch) -> None:
    """Invariant 2 through the smoke path: absent declared dep ⇒ 503."""
    _stub_probes(monkeypatch, _check_s3=ServiceStatus("minio", "error", "down"))

    response = await client.get("/health?full=1")

    assert response.status_code == 503
    assert response.json()["status"] == "unhealthy"


async def test_plain_health_stays_light(client: AsyncClient, monkeypatch) -> None:
    """The frequent Docker healthcheck form still checks only database + s3."""
    _stub_probes(monkeypatch)

    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert set(body["checks"]) == {"database", "s3"}
    assert "tier" not in body


def test_smoke_script_calls_the_full_health_form() -> None:
    """The smoke script must assert dependency presence via /api/health?full=1 —
    dropping the line breaks parity (invariant 6), so it is pinned here."""
    script = Path(__file__).resolve().parents[4] / "tools/_lib/shell/smoke_test.sh"
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
