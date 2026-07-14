"""#1828 G-health-honest-somewhere — the REAL Bootloader checks run somewhere.

``apps/backend/tests/conftest.py`` autouse-mocks ``Bootloader._check_database``
and ``_check_s3`` suite-wide (message ``"Mocked for tests"``), so no ordinary
backend test ever executes the real probes. This module is the one blocking CI
lane (backend-integration, which runs real Postgres + MinIO services) where the
real implementations are re-patched OVER the autouse mock and asserted against
live services.

Structure lock: every assertion here pins the returned ``ServiceStatus.message``
away from the autouse stub's ``"Mocked for tests"`` — if the mock ever leaks
back into these tests (or the capture below ever grabs the stub instead of the
real function), the lane goes red instead of vacuously green. The dead-port
canary is the strongest form: the stub would report ok where the real check
must report error.
"""

from __future__ import annotations

import types
from unittest.mock import patch

import pytest

from src.boot import Bootloader, ServiceStatus
from src.config import settings

# Captured at import (collection) time — BEFORE the autouse
# ``mock_bootloader_checks`` fixture patches the class attributes — so these are
# the REAL implementations regardless of the suite-wide mock.
_REAL_CHECK_DATABASE = Bootloader._check_database
_REAL_CHECK_S3 = Bootloader._check_s3

# The autouse stub's marker message (apps/backend/tests/conftest.py).
_MOCK_MESSAGE = "Mocked for tests"

pytestmark = [pytest.mark.integration, pytest.mark.no_db, pytest.mark.asyncio]


def _as_static(func: object) -> object:
    return staticmethod(func) if isinstance(func, types.FunctionType) else func


def _real_checks_patched():
    """Context: restore the REAL check implementations over the autouse mock."""
    return patch.multiple(
        Bootloader,
        _check_database=_as_static(_REAL_CHECK_DATABASE),
        _check_s3=_as_static(_REAL_CHECK_S3),
    )


async def _ensure_bucket_exists() -> None:
    """Create the configured bucket if missing (idempotent; CI also pre-creates
    it via ``mc mb --ignore-existing``, this keeps local runs self-contained)."""
    import aioboto3
    from botocore.config import Config

    session = aioboto3.Session()
    async with session.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(connect_timeout=5, read_timeout=5),
    ) as s3:
        try:
            await s3.head_bucket(Bucket=settings.s3_bucket)
        except Exception:  # noqa: BLE001 - missing bucket (or race) -> create
            await s3.create_bucket(Bucket=settings.s3_bucket)


async def test_AC_runtime_guard_proofs_4_real_database_check_passes_against_live_service() -> None:
    """AC-runtime.guard-proofs.4 (#1828 G-health-honest-somewhere): the REAL
    ``_check_database`` (not the suite-wide autouse mock) runs a live SELECT 1
    against this lane's Postgres and reports ok — structure-locked so a leaked
    mock (message "Mocked for tests") fails the lane."""
    with _real_checks_patched():
        status: ServiceStatus = await Bootloader._check_database()

    assert status.message != _MOCK_MESSAGE, "autouse bootloader mock leaked into the honest-health lane"
    assert status.status == "ok", f"real database check failed: {status.message}"
    assert status.duration_ms > 0  # a real probe takes real time; the stub reports 0.0


async def test_AC_runtime_guard_proofs_5_real_s3_check_passes_against_live_service() -> None:
    """AC-runtime.guard-proofs.5 (#1828 G-health-honest-somewhere): the REAL
    ``_check_s3`` performs a live HEAD-bucket against this lane's MinIO and
    reports ok — structure-locked against the autouse mock's message."""
    await _ensure_bucket_exists()

    with _real_checks_patched():
        status: ServiceStatus = await Bootloader._check_s3()

    assert status.message != _MOCK_MESSAGE, "autouse bootloader mock leaked into the honest-health lane"
    assert status.status == "ok", f"real S3 check failed: {status.message}"
    assert status.duration_ms > 0


async def test_AC_runtime_guard_proofs_6_real_database_check_reds_on_dead_port(monkeypatch) -> None:
    """AC-runtime.guard-proofs.6 (#1828 G-health-honest-somewhere, red-team
    canary): pointed at a dead port, the REAL ``_check_database`` reports
    error. The autouse stub would report ok here — so this test failing-closed
    proves the real code path is the one being exercised (mock-leak canary,
    permanently recorded red-team demo)."""
    monkeypatch.setattr(
        settings,
        "database_url",
        # Port 9 (discard) on loopback: connection refused immediately.
        # Obvious placeholder credentials — never a real secret.
        "postgresql+asyncpg://postgres:placeholder-password@127.0.0.1:9/finance_report_test",
    )

    with _real_checks_patched():
        status: ServiceStatus = await Bootloader._check_database()

    assert status.message != _MOCK_MESSAGE
    assert status.status == "error", "real database check reported ok against a dead port"
