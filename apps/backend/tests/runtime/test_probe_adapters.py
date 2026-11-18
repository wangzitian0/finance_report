from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from infra2_sdk.runtime import health as sdk_health
from infra2_sdk.runtime.health import DependencyStatus

import src.runtime as runtime_package
from src.boot import Bootloader
from src.runtime import AnalyticsCheck, DatabaseCheck, EnvTier, MarketDataCheck, ObjectStorageCheck, RedisCheck, TelemetryCheck, WorkflowEngineCheck

pytestmark = pytest.mark.no_db


def _http(code: int) -> MagicMock:
    return MagicMock(status_code=code)


@pytest.mark.parametrize(("make_check", "name", "ok_exc"), [(lambda: RedisCheck(url=None), "cache", None), (lambda: RedisCheck(url="redis://cache:6379/0"), "cache", ConnectionRefusedError("refused")), (lambda: TelemetryCheck(endpoint=None), "telemetry", None), (lambda: TelemetryCheck(endpoint="http://otel-collector:4318"), "telemetry", OSError("no route"))])
async def test_tcp_checks(make_check, name: str, ok_exc: Exception | None) -> None:
    check = make_check()
    if ok_exc is None:
        res = await check.probe()
        assert (res.name, res.status) == (name, DependencyStatus.ABSENT) and isinstance(res, sdk_health.ProbeResult)
        return
    reader, writer = AsyncMock(readline=AsyncMock(return_value=b"+PONG\r\n")), MagicMock(drain=AsyncMock(), wait_closed=AsyncMock())
    with patch("asyncio.open_connection", AsyncMock(return_value=(reader, writer))):
        assert (await check.probe()).status is DependencyStatus.PRESENT
    with patch("asyncio.open_connection", AsyncMock(side_effect=ok_exc)):
        assert (await check.probe()).status is DependencyStatus.ABSENT


@pytest.mark.parametrize(("make_check", "name", "outcomes"), [(lambda: WorkflowEngineCheck(api_url=None), "workflow_engine", []), (lambda: WorkflowEngineCheck(api_url="http://prefect:4200/api"), "workflow_engine", [(_http(200), DependencyStatus.PRESENT), (httpx.ConnectError("down"), DependencyStatus.ABSENT)]), (lambda: AnalyticsCheck(api_url=""), "analytics", []), (lambda: AnalyticsCheck(api_url="https://op.example.com/api"), "analytics", [(_http(404), DependencyStatus.PRESENT), (_http(503), DependencyStatus.ABSENT)]), (lambda: MarketDataCheck(timeout_seconds=5), "market_data", [(_http(200), DependencyStatus.PRESENT), (_http(429), DependencyStatus.PRESENT), (_http(503), DependencyStatus.ABSENT), (httpx.ConnectError("down"), DependencyStatus.ABSENT)])])
async def test_http_checks(make_check, name: str, outcomes: list[tuple[object, DependencyStatus]]) -> None:
    check = make_check()
    if not outcomes:
        assert (await check.probe()).status is DependencyStatus.ABSENT
        return
    for outcome, expected in outcomes:
        kw = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
        with patch("httpx.AsyncClient.get", AsyncMock(**kw)):
            assert (await check.probe()).status is expected


async def test_database_and_object_storage_checks() -> None:
    eng = MagicMock(dispose=AsyncMock())
    eng.connect.return_value.__aenter__.return_value = AsyncMock(execute=AsyncMock())
    with patch("src.runtime.extension.adapters.create_async_engine", return_value=eng):
        assert ((ok := await DatabaseCheck("postgresql+asyncpg://postgres:secret123@127.0.0.1:5432/finance").probe()).name, ok.status, ok.detail) == ("database", DependencyStatus.PRESENT, "Connection successful")

    dsn = "postgresql+asyncpg://postgres:super_secret_password@127.0.0.1:5432/finance"
    with patch("src.runtime.extension.adapters.create_async_engine", side_effect=Exception(f"failed {dsn}")):
        assert ((err := await DatabaseCheck(dsn).probe()).name, err.status) == ("database", DependencyStatus.ABSENT) and "super_secret_password" not in err.detail and "<redacted-postgres-dsn>" in err.detail

    kw = {"endpoint": "http://localhost:9000", "access_key": "minio", "region": "us-east-1", "bucket": "statements"}
    sdk_res = sdk_health.ProbeResult("object_storage", DependencyStatus.PRESENT, "bucket accessible", 1.2)
    with patch("src.runtime.extension.adapters.probe_s3", return_value=sdk_res) as probe_fn:
        assert await ObjectStorageCheck(secret_key="minio123", **kw).probe() is sdk_res
    assert (probe_fn.call_args.args[0].bucket, probe_fn.call_args.args[0].endpoint_url) == ("statements", "http://localhost:9000")
    assert ((bad := await ObjectStorageCheck(secret_key=None, **kw).probe()).name, bad.status) == ("object_storage", DependencyStatus.ABSENT) and "secret key" in bad.detail


def test_every_declared_dependency_has_a_probe_adapter() -> None:
    assert all(Bootloader._required_checks(tier)[1] == [] for tier in EnvTier)
    sdk_owned = {"ProbeResult", "DependencyStatus", "DependencyCheck"}
    sources = sorted(Path(runtime_package.__file__).resolve().parent.rglob("*.py"))
    assert sdk_owned.isdisjoint(runtime_package.__all__) and any(p.name == "adapters.py" for p in sources)
    assert not [f"{p.name}:{n.lineno}:{n.name}" for p in sources for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))) if isinstance(n, ast.ClassDef) and n.name in sdk_owned]


@pytest.mark.parametrize(("make_check", "name", "target"), [(lambda: WorkflowEngineCheck(api_url="http://prefect:4200/api"), "workflow_engine", "src.runtime.extension.adapters.probe_orchestrator"), (lambda: AnalyticsCheck(api_url="https://op.example.com/api"), "analytics", "src.runtime.extension.adapters.probe_http"), (lambda: MarketDataCheck(timeout_seconds=5), "market_data", "src.runtime.extension.adapters.probe_http")])
async def test_http_adapters_return_the_sdk_probe_result_unchanged(make_check, name: str, target: str) -> None:
    sdk_res = sdk_health.ProbeResult(name, sdk_health.DependencyStatus.PRESENT, "HTTP 200", 1.5)
    with patch(target, AsyncMock(return_value=sdk_res)) as probe_fn:
        assert await make_check().probe() is sdk_res and probe_fn.await_args.kwargs["name"] == name
