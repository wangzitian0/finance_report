from unittest.mock import AsyncMock, patch

import pytest

from src.boot import Bootloader, BootMode, ServiceStatus


@pytest.fixture
def mock_settings():
    with patch("src.boot.settings") as mock:
        yield mock


@pytest.fixture
def mock_logger():
    with patch("src.boot.logger") as mock:
        yield mock


@pytest.fixture
def mock_db_check():
    with patch("src.boot.Bootloader._check_database", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_redis_check():
    with patch("src.boot.Bootloader._check_redis", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_minio_check():
    with patch("src.boot.Bootloader._check_s3", new_callable=AsyncMock) as mock:
        yield mock


class TestBootloader:
    @pytest.mark.asyncio
    async def test_dry_run_passes(self, mock_settings):
        """Dry run should only check config."""
        await Bootloader.validate(BootMode.DRY_RUN)
        # Should not raise exception

    @pytest.mark.asyncio
    async def test_critical_check_database_failure(self, mock_db_check, mock_settings):
        """Critical check must exit if DB fails."""
        mock_db_check.return_value = ServiceStatus(service="database", status="error", message="Conn refused")

        with pytest.raises(SystemExit):
            await Bootloader.validate(BootMode.CRITICAL)

    @pytest.mark.asyncio
    async def test_critical_check_success(self, mock_db_check, mock_settings):
        """Critical check passes if DB is OK."""
        mock_db_check.return_value = ServiceStatus(service="database", status="ok", message="Connected", duration_ms=10)

        await Bootloader.validate(BootMode.CRITICAL)
        mock_db_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_check_runs_all(self, mock_db_check, mock_redis_check, mock_minio_check, mock_settings):
        """Full check must verify all services."""
        mock_db_check.return_value = ServiceStatus(service="database", status="ok", message="OK")
        mock_redis_check.return_value = ServiceStatus(service="redis", status="ok", message="OK")
        mock_minio_check.return_value = ServiceStatus(service="minio", status="ok", message="OK")

        await Bootloader.validate(BootMode.FULL)

        mock_db_check.assert_called_once()
        mock_redis_check.assert_called_once()
        mock_minio_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_check_warns_but_proceeds(self, mock_db_check, mock_redis_check, mock_minio_check):
        """Full check warns on optional service failure but doesn't exit."""
        mock_db_check.return_value = ServiceStatus(service="database", status="ok", message="OK")
        mock_redis_check.return_value = ServiceStatus(service="redis", status="error", message="No Redis")
        mock_minio_check.return_value = ServiceStatus(service="minio", status="ok", message="OK")

        # Should not raise SystemExit
        await Bootloader.validate(BootMode.FULL)

        mock_redis_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_redis_skipped_if_no_url(self, mock_settings):
        """Redis check skipped if URL not configured."""
        mock_settings.redis_url = None
        status = await Bootloader._check_redis()
        assert status.status == "skipped"

    @pytest.mark.asyncio
    async def test_check_s3_handles_client_error(self):
        """S3 check handles client errors gracefully."""
        with patch("aioboto3.Session") as mock_session:
            # Mock the client context manager
            mock_client_ctx = AsyncMock()
            mock_client = AsyncMock()

            # When client() is called, return ctx manager
            mock_session.return_value.client.return_value = mock_client_ctx

            # When entering ctx manager, return the client
            mock_client_ctx.__aenter__.return_value = mock_client

            # The actual call failing
            mock_client.head_bucket.side_effect = Exception("S3 Down")

            status = await Bootloader._check_s3()
            assert status.status == "error"
            assert "S3 Down" in str(status.message)
