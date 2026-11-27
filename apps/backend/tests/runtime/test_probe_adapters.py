from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from infra2_sdk import service as sdk_health
from infra2_sdk.config import EnvironmentTier
from infra2_sdk.service import DependencyStatus

import src.runtime as runtime_package
from src.boot import Bootloader
from src.runtime import (
    AnalyticsCheck,
    DatabaseCheck,
    LlmCheck,
    MarketDataCheck,
    ObjectStorageCheck,
    RedisCheck,
    TelemetryCheck,
    WorkflowEngineCheck,
)

pytestmark = pytest.mark.no_db


def _http(code: int, payload: object = None) -> MagicMock:
    resp = MagicMock(status_code=code)
    if payload is None:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = payload
    return resp


async def test_telemetry_check_http_and_tcp() -> None:
    absent = await TelemetryCheck(endpoint=None).probe()
    assert (absent.name, absent.status) == ("telemetry", DependencyStatus.ABSENT) and isinstance(
        absent, sdk_health.ProbeResult
    )

    reader, writer = (
        AsyncMock(readline=AsyncMock(return_value=b"+PONG\r\n")),
        MagicMock(close=MagicMock(), wait_closed=AsyncMock()),
    )
    with patch("asyncio.open_connection", AsyncMock(return_value=(reader, writer))) as open_conn:
        assert (await TelemetryCheck(endpoint="otel-collector:4317").probe()).status is DependencyStatus.PRESENT
    open_conn.assert_awaited_once_with("otel-collector", 4317)
    with patch("asyncio.open_connection", AsyncMock(side_effect=OSError("no route"))):
        assert (await TelemetryCheck(endpoint="otel-collector:4317").probe()).status is DependencyStatus.ABSENT

    for code, expected in (
        (200, DependencyStatus.PRESENT),
        (400, DependencyStatus.PRESENT),
        (415, DependencyStatus.PRESENT),
        (401, DependencyStatus.ABSENT),
        (404, DependencyStatus.ABSENT),
        (405, DependencyStatus.ABSENT),
        (503, DependencyStatus.ABSENT),
    ):
        with patch("httpx.AsyncClient.post", AsyncMock(return_value=_http(code))) as post_fn:
            res = await TelemetryCheck(endpoint="https://otel.zitian.party").probe()
        assert res.status is expected
        assert post_fn.await_args.args[0] == "https://otel.zitian.party/v1/traces"

    assert (await TelemetryCheck(endpoint="/sock").probe()).status is DependencyStatus.ABSENT
    with patch("httpx.AsyncClient.post", AsyncMock(side_effect=httpx.ConnectError("down"))):
        assert (
            await TelemetryCheck(endpoint="http://otel-collector:4318/v1/traces").probe()
        ).status is DependencyStatus.ABSENT


async def test_analytics_check_requires_client_id_and_ready_healthcheck() -> None:
    assert (await AnalyticsCheck(api_url="", client_id="cid").probe()).status is DependencyStatus.ABSENT
    missing_cid = await AnalyticsCheck(api_url="https://op.example.com/api", client_id="").probe()
    assert missing_cid.status is DependencyStatus.ABSENT and "OPENPANEL_CLIENT_ID" in missing_cid.detail

    with patch("httpx.AsyncClient.get", AsyncMock(return_value=_http(200, {"ready": True}))) as get_fn:
        ok = await AnalyticsCheck(api_url="https://op.example.com/api", client_id="cid").probe()
    assert ok.status is DependencyStatus.PRESENT
    assert get_fn.await_args.args[0] == "https://op.example.com/api/healthcheck"

    for outcome in (
        _http(200),
        _http(200, {"status": "ok"}),
        _http(200, {"ready": False}),
        _http(404),
        _http(503),
        httpx.ConnectError("down"),
    ):
        kw = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
        with patch("httpx.AsyncClient.get", AsyncMock(**kw)):
            assert (
                await AnalyticsCheck(api_url="https://op.example.com/api", client_id="cid").probe()
            ).status is DependencyStatus.ABSENT


async def test_llm_check_probes_models_chat_fallback_and_redacts_key() -> None:
    assert (
        await LlmCheck(api_key=None, provider="zai", base_url="https://ai.example/v1").probe()
    ).status is DependencyStatus.ABSENT
    assert (
        await LlmCheck(api_key="   ", provider="zai", base_url="https://ai.example/v1").probe()
    ).status is DependencyStatus.ABSENT
    no_url = await LlmCheck(api_key="tok", provider="zai", base_url=None).probe()
    assert no_url.status is DependencyStatus.ABSENT and "base_url" in no_url.detail

    for code, expected in (
        (200, DependencyStatus.PRESENT),
        (429, DependencyStatus.PRESENT),
        (401, DependencyStatus.ABSENT),
        (403, DependencyStatus.ABSENT),
        (503, DependencyStatus.ABSENT),
    ):
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=_http(code))) as get_fn:
            res = await LlmCheck(
                api_key="secret-llm-key",
                provider="zai",
                base_url="https://ai.example/v1/",
            ).probe()
        assert res.status is expected
        assert get_fn.await_args.args[0] == "https://ai.example/v1/models"
        assert get_fn.await_args.kwargs["headers"] == {"Authorization": "Bearer secret-llm-key"}

    for models_code, chat_code, expected in (
        (404, 200, DependencyStatus.PRESENT),
        (404, 400, DependencyStatus.PRESENT),
        (405, 422, DependencyStatus.PRESENT),
        (404, 429, DependencyStatus.PRESENT),
        (405, 401, DependencyStatus.ABSENT),
        (404, 404, DependencyStatus.ABSENT),
    ):
        with (
            patch("httpx.AsyncClient.get", AsyncMock(return_value=_http(models_code))),
            patch("httpx.AsyncClient.post", AsyncMock(return_value=_http(chat_code))) as post_fn,
        ):
            res = await LlmCheck(
                api_key="secret-llm-key",
                provider="zai",
                base_url="https://ai.example/v1",
            ).probe()
        assert res.status is expected
        assert post_fn.await_args.args[0] == "https://ai.example/v1/chat/completions"
        if chat_code == 401:
            assert "Authentication failed" in res.detail

    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=RuntimeError("boom secret-llm-key"))):
        err = await LlmCheck(
            api_key="secret-llm-key",
            provider="zai",
            base_url="https://ai.example/v1",
        ).probe()
    assert err.status is DependencyStatus.ABSENT and "secret-llm-key" not in err.detail and "***" in err.detail


async def test_redis_check_uses_redis_ping_and_rejects_auth_errors() -> None:
    absent = await RedisCheck(url=None).probe()
    assert (absent.name, absent.status) == ("cache", DependencyStatus.ABSENT)

    invalid = await RedisCheck(url="http://:secret_pw@cache:6379/0").probe()
    assert (invalid.name, invalid.status) == ("cache", DependencyStatus.ABSENT)
    assert "secret_pw" not in invalid.detail

    class _FakeRespSocket:
        def __init__(self, replies: list[bytes]) -> None:
            self._replies = b"".join(replies)
            self._offset = 0
            self.sent: list[bytes] = []
            self.closed = False

        def settimeout(self, _timeout: float | None) -> None:
            return None

        def sendall(self, data: bytes) -> None:
            self.sent.append(data)

        def recv(self, _bufsize: int) -> bytes:
            if self._offset >= len(self._replies):
                return b""
            chunk = self._replies[self._offset : self._offset + 64]
            self._offset += len(chunk)
            return chunk

        def close(self) -> None:
            self.closed = True

    ok_sock = _FakeRespSocket([b"+OK\r\n", b"+PONG\r\n"])
    with patch("socket.create_connection", return_value=ok_sock) as conn:
        res = await RedisCheck(url="redis://:secret_pw@cache:6379/0").probe()
    assert (res.name, res.status) == ("cache", DependencyStatus.PRESENT)
    conn.assert_called_once()
    assert ok_sock.closed is True
    assert not any(b"SETEX" in frame for frame in ok_sock.sent)

    auth_sock = _FakeRespSocket([b"-ERR Authentication required\r\n"])
    with patch("socket.create_connection", return_value=auth_sock):
        auth_res = await RedisCheck(url="redis://:secret_pw@cache:6379/0").probe()
    assert (auth_res.name, auth_res.status) == ("cache", DependencyStatus.ABSENT)
    assert "secret_pw" not in auth_res.detail
    assert auth_sock.closed is True

    with patch(
        "socket.create_connection",
        side_effect=ConnectionRefusedError("refused for redis://:secret_pw@cache:6379/0"),
    ):
        refused_res = await RedisCheck(url="redis://:secret_pw@cache:6379/0").probe()
    assert (refused_res.name, refused_res.status) == ("cache", DependencyStatus.ABSENT)
    assert "secret_pw" not in refused_res.detail


@pytest.mark.parametrize(
    ("make_check", "name", "outcomes"),
    [
        (lambda: WorkflowEngineCheck(api_url=None), "workflow_engine", []),
        (
            lambda: WorkflowEngineCheck(api_url="http://prefect:4200/api"),
            "workflow_engine",
            [(_http(200), DependencyStatus.PRESENT), (httpx.ConnectError("down"), DependencyStatus.ABSENT)],
        ),
        (
            lambda: MarketDataCheck(timeout_seconds=5),
            "market_data",
            [
                (_http(200), DependencyStatus.PRESENT),
                (_http(429), DependencyStatus.PRESENT),
                (_http(503), DependencyStatus.ABSENT),
                (httpx.ConnectError("down"), DependencyStatus.ABSENT),
            ],
        ),
    ],
)
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
        assert (
            (ok := await DatabaseCheck("postgresql+asyncpg://postgres:secret123@127.0.0.1:5432/finance").probe()).name,
            ok.status,
            ok.detail,
        ) == ("database", DependencyStatus.PRESENT, "Connection successful")

    dsn = "postgresql+asyncpg://postgres:super_secret_password@127.0.0.1:5432/finance"
    with patch("src.runtime.extension.adapters.create_async_engine", side_effect=Exception(f"failed {dsn}")):
        assert (
            ((err := await DatabaseCheck(dsn).probe()).name, err.status) == ("database", DependencyStatus.ABSENT)
            and "super_secret_password" not in err.detail
            and "postgresql://[REDACTED]" in err.detail
        )

    kw = {"endpoint": "http://localhost:9000", "access_key": "minio", "region": "us-east-1", "bucket": "statements"}
    sdk_res = sdk_health.ProbeResult(
        name="object_storage", status=DependencyStatus.PRESENT, detail="bucket accessible", duration_ms=1.2
    )
    with patch("src.runtime.extension.adapters.probe_s3", return_value=sdk_res) as probe_fn:
        assert await ObjectStorageCheck(secret_key="minio123", **kw).probe() is sdk_res
    assert (probe_fn.call_args.args[0].bucket, probe_fn.call_args.args[0].endpoint_url) == (
        "statements",
        "http://localhost:9000",
    )
    assert ((bad := await ObjectStorageCheck(secret_key=None, **kw).probe()).name, bad.status) == (
        "object_storage",
        DependencyStatus.ABSENT,
    ) and "secret key" in bad.detail


async def test_object_storage_public_and_write_delete_probe() -> None:
    kw = {
        "endpoint": "http://minio:9000",
        "access_key": "minio",
        "secret_key": "secret-s3-key",
        "region": "us-east-1",
        "bucket": "statements",
    }
    ok_primary = sdk_health.ProbeResult(
        name="object_storage", status=DependencyStatus.PRESENT, detail="bucket accessible", duration_ms=1.0
    )
    ok_public = sdk_health.ProbeResult(
        name="object_storage", status=DependencyStatus.PRESENT, detail="bucket accessible", duration_ms=1.1
    )
    bad_public = sdk_health.ProbeResult(
        name="object_storage", status=DependencyStatus.ABSENT, detail="DNS error with secret-s3-key", duration_ms=1.1
    )

    with patch("src.runtime.extension.adapters.probe_s3", side_effect=[ok_primary, bad_public]):
        failed_pub = await ObjectStorageCheck(public_endpoint="https://s3.zitian.party", **kw).probe()
    assert failed_pub.status is DependencyStatus.ABSENT and "public S3 probe failed" in failed_pub.detail
    assert "secret-s3-key" not in failed_pub.detail and "***" in failed_pub.detail

    asym = await ObjectStorageCheck(
        public_endpoint="https://s3.zitian.party", public_access_key="pub-only", public_secret_key="  ", **kw
    ).probe()
    assert asym.status is DependencyStatus.ABSENT and "Incomplete public S3 credentials" in asym.detail

    s3_client = MagicMock(put_object=MagicMock(), delete_object=MagicMock(), close=MagicMock())
    with (
        patch("src.runtime.extension.adapters.probe_s3", side_effect=[ok_primary, ok_public]) as probe_fn,
        patch("infra2_sdk.storage.create_s3_client", return_value=s3_client),
    ):
        ok = await ObjectStorageCheck(
            public_endpoint="https://s3.zitian.party",
            public_access_key=" ",
            public_secret_key="",
            public_bucket="  ",
            verify_write=True,
            **kw,
        ).probe()
    assert ok.status is DependencyStatus.PRESENT and "write/delete ok" in ok.detail
    assert probe_fn.call_count == 2
    assert probe_fn.call_args_list[0].args[0].use_path_style is True
    assert (probe_fn.call_args_list[1].args[0].bucket, probe_fn.call_args_list[1].args[0].secret_access_key) == (
        "statements",
        "secret-s3-key",
    )
    with patch("src.runtime.extension.adapters.probe_s3", side_effect=[ok_primary, ok_public]) as custom_fn:
        custom_ok = await ObjectStorageCheck(
            public_endpoint="https://s3.zitian.party",
            public_bucket="statements-pub",
            public_access_key="pub-ak",
            public_secret_key="pub-sk",
            **kw,
        ).probe()
    assert custom_ok.status is DependencyStatus.PRESENT
    assert (custom_fn.call_args_list[1].args[0].bucket, custom_fn.call_args_list[1].args[0].access_key_id) == (
        "statements-pub",
        "pub-ak",
    )
    s3_client.put_object.assert_called_once()
    s3_client.delete_object.assert_called_once()
    s3_client.close.assert_called_once()

    failing_put = MagicMock(
        put_object=MagicMock(side_effect=PermissionError("AccessDenied secret-s3-key")),
        delete_object=MagicMock(),
        close=MagicMock(),
    )
    with (
        patch("src.runtime.extension.adapters.probe_s3", return_value=ok_primary),
        patch("infra2_sdk.storage.create_s3_client", return_value=failing_put),
    ):
        err = await ObjectStorageCheck(verify_write=True, **kw).probe()
    assert err.status is DependencyStatus.ABSENT and "S3 write/delete probe failed" in err.detail
    assert "secret-s3-key" not in err.detail
    failing_put.delete_object.assert_called_once()
    failing_put.close.assert_called_once()

    failing_del = MagicMock(
        put_object=MagicMock(), delete_object=MagicMock(side_effect=PermissionError("DeleteDenied")), close=MagicMock()
    )
    with (
        patch("src.runtime.extension.adapters.probe_s3", return_value=ok_primary),
        patch("infra2_sdk.storage.create_s3_client", return_value=failing_del),
    ):
        err_del = await ObjectStorageCheck(verify_write=True, **kw).probe()
    assert err_del.status is DependencyStatus.ABSENT and "DeleteDenied" in err_del.detail
    failing_del.close.assert_called_once()


def test_every_declared_dependency_has_a_probe_adapter() -> None:
    assert all(Bootloader._required_checks(tier)[1] == [] for tier in EnvironmentTier)
    sdk_owned = {
        "Dependency",
        "DependencyCheck",
        "DependencyKind",
        "DependencyManifest",
        "DependencyStatus",
        "EnvironmentTier",
        "ProbeResult",
        "resolve_tier",
    }
    sources = sorted(Path(runtime_package.__file__).resolve().parent.rglob("*.py"))
    assert sdk_owned.isdisjoint(runtime_package.__all__) and any(p.name == "adapters.py" for p in sources)
    assert not [
        f"{p.name}:{n.lineno}:{n.name}"
        for p in sources
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        if isinstance(n, ast.ClassDef) and n.name in sdk_owned
    ]


@pytest.mark.parametrize(
    ("make_check", "name", "target"),
    [
        (
            lambda: WorkflowEngineCheck(api_url="http://prefect:4200/api"),
            "workflow_engine",
            "src.runtime.extension.adapters.probe_http",
        ),
        (lambda: MarketDataCheck(timeout_seconds=5), "market_data", "src.runtime.extension.adapters.probe_http"),
    ],
)
async def test_http_adapters_return_the_sdk_probe_result_unchanged(make_check, name: str, target: str) -> None:
    sdk_res = sdk_health.ProbeResult(
        name=name, status=sdk_health.DependencyStatus.PRESENT, detail="HTTP 200", duration_ms=1.5
    )
    with patch(target, AsyncMock(return_value=sdk_res)) as probe_fn:
        assert await make_check().probe() is sdk_res and probe_fn.await_args.kwargs["name"] == name
