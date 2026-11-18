from __future__ import annotations

import types
from unittest.mock import patch

import pytest
from src.boot import Bootloader, ServiceStatus
from src.config import settings

_REAL_CHECK_DATABASE = Bootloader._check_database
_REAL_CHECK_S3 = Bootloader._check_s3
_MOCK_MESSAGE = "Mocked for tests"
pytestmark = [pytest.mark.integration, pytest.mark.no_db, pytest.mark.asyncio]
_as_static = lambda func: staticmethod(func) if isinstance(func, types.FunctionType) else func
_real_checks_patched = lambda: patch.multiple(Bootloader, _check_database=_as_static(_REAL_CHECK_DATABASE), _check_s3=_as_static(_REAL_CHECK_S3))


async def _ensure_bucket_exists() -> None:
    from infra2_sdk.runtime.s3 import S3Settings, ensure_bucket

    ensure_bucket(
        S3Settings(bucket=settings.s3_bucket, endpoint_url=settings.s3_endpoint, access_key_id=settings.s3_access_key, secret_access_key=settings.s3_secret_key, region_name=settings.s3_region),
        allow_create=True,
    )


async def test_real_database_check_passes_against_live_service() -> None:
    with _real_checks_patched():
        status: ServiceStatus = await Bootloader._check_database()
    assert status.message != _MOCK_MESSAGE and status.status == "ok" and status.duration_ms > 0


async def test_real_s3_check_passes_against_live_service() -> None:
    await _ensure_bucket_exists()
    with _real_checks_patched():
        status: ServiceStatus = await Bootloader._check_s3()
    assert status.message != _MOCK_MESSAGE and status.status == "ok" and status.duration_ms > 0


async def test_real_database_check_reds_on_dead_port(monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_url", "postgresql+asyncpg://postgres:placeholder-password@127.0.0.1:9/finance_report_test")
    with _real_checks_patched():
        status: ServiceStatus = await Bootloader._check_database()
    assert status.message != _MOCK_MESSAGE and status.status == "error"
