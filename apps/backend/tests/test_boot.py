import os
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.boot import Bootloader, Bootloader as BootloaderClass, BootMode, ServiceStatus

_ORIGINAL_CHECK_DATABASE = BootloaderClass._check_database


@pytest.fixture
def mock_settings():
    with patch("src.boot.settings") as mock:
        mock.database_url = "postgresql+asyncpg://test:test@localhost/test"
        mock.redis_url = None
        mock.openrouter_api_key = None
        mock.s3_endpoint = "http://localhost:9000"
        mock.s3_access_key = "minio"
        mock.s3_secret_key = "minio123"
        mock.s3_region = "us-east-1"
        mock.s3_bucket = "statements"
        mock.debug = False
        mock.environment = "test"
        mock.base_currency = "USD"
        mock.primary_model = "test-model"
        mock.cors_origin_regex = ".*"
        mock.otel_exporter_otlp_endpoint = None
        mock.otel_service_name = "test"
        mock.openrouter_base_url = "https://openrouter.ai/api/v1"
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


@pytest.fixture
def mock_openrouter_check():
    with patch("src.boot.Bootloader._check_openrouter", new_callable=AsyncMock) as mock:
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


class TestBootloaderStaticConfig:
    def test_check_static_config_success(self, mock_settings):
        result = Bootloader._check_static_config()
        assert result is True

    def test_check_static_config_failure(self):
        with patch("src.boot.settings") as mock:
            mock.database_url = property(lambda self: (_ for _ in ()).throw(Exception("Missing DB URL")))
            type(mock).database_url = property(lambda self: (_ for _ in ()).throw(ValueError("Missing")))
            result = Bootloader._check_static_config()
            assert result is False

    @pytest.mark.asyncio
    async def test_static_config_fail_critical_exits(self):
        with (
            patch.object(Bootloader, "_check_static_config", return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            await Bootloader.validate(BootMode.CRITICAL)
        assert exc_info.value.code == 1

    @pytest.mark.asyncio
    async def test_static_config_fail_noncritical_returns_false(self):
        with patch.object(Bootloader, "_check_static_config", return_value=False):
            result = await Bootloader.validate(BootMode.FULL)
        assert result is False


class TestBootloaderPrintConfig:
    def test_print_config_skipped_when_not_debug(self, mock_settings, capsys):
        with patch.dict(os.environ, {"DEBUG": "false"}, clear=False):
            Bootloader.print_config()
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_print_config_shows_config_when_debug(self, mock_settings, capsys):
        mock_settings.debug = True
        mock_settings.environment = "development"
        mock_settings.base_currency = "USD"
        mock_settings.primary_model = "gemini"
        mock_settings.s3_endpoint = "http://localhost:9000"
        mock_settings.s3_bucket = "statements"
        mock_settings.cors_origin_regex = ".*"
        mock_settings.otel_exporter_otlp_endpoint = None
        mock_settings.otel_service_name = "finance-report"
        mock_settings.database_url = "secret"
        mock_settings.redis_url = None
        mock_settings.openrouter_api_key = None
        mock_settings.s3_access_key = "key"
        mock_settings.s3_secret_key = "secret"

        with patch.dict(os.environ, {"DEBUG": "true"}, clear=False):
            Bootloader.print_config()
        captured = capsys.readouterr()
        assert "Config loaded (DEBUG mode)" in captured.out
        assert "database_url: set" in captured.out
        assert "redis_url: not set" in captured.out

    def test_print_config_shows_defaults_used(self, mock_settings, capsys):
        mock_settings.debug = True
        mock_settings.environment = "development"
        mock_settings.base_currency = "USD"
        mock_settings.primary_model = "gemini"
        mock_settings.s3_endpoint = "http://localhost:9000"
        mock_settings.s3_bucket = "statements"
        mock_settings.cors_origin_regex = ".*"
        mock_settings.otel_exporter_otlp_endpoint = None
        mock_settings.otel_service_name = "finance-report"
        mock_settings.database_url = "secret"
        mock_settings.redis_url = None
        mock_settings.openrouter_api_key = None
        mock_settings.s3_access_key = "key"
        mock_settings.s3_secret_key = "secret"

        with patch.dict(
            os.environ,
            {"DEBUG": "true", "ENVIRONMENT": "development", "BASE_CURRENCY": "USD"},
            clear=False,
        ):
            Bootloader.print_config()
        captured = capsys.readouterr()
        assert "Fields using defaults:" in captured.out


class TestBootloaderDatabase:
    @pytest.fixture(autouse=True)
    def restore_original_db_check(self):
        """Restore original _check_database for these tests (conftest mocks it)."""
        if isinstance(_ORIGINAL_CHECK_DATABASE, types.FunctionType):
            BootloaderClass._check_database = staticmethod(_ORIGINAL_CHECK_DATABASE)
        else:
            BootloaderClass._check_database = _ORIGINAL_CHECK_DATABASE
        yield

    @pytest.mark.asyncio
    async def test_check_database_success(self, mock_settings):
        with patch("src.boot.create_async_engine") as mock_engine:
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()
            mock_engine_instance = MagicMock()
            mock_engine_instance.connect.return_value.__aenter__.return_value = mock_conn
            mock_engine_instance.dispose = AsyncMock()
            mock_engine.return_value = mock_engine_instance

            status = await Bootloader._check_database()

            assert status.status == "ok"
            assert status.service == "database"
            mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_database_failure(self, mock_settings):
        with patch("src.boot.create_async_engine") as mock_engine:
            mock_engine.side_effect = Exception("Connection refused")

            status = await Bootloader._check_database()

            assert status.status == "error"
            assert "Connection refused" in status.message


class TestBootloaderRedis:
    @pytest.mark.asyncio
    async def test_check_redis_success(self, mock_settings):
        mock_settings.redis_url = "redis://localhost:6379"
        with patch("redis.asyncio.from_url") as mock_redis:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_client.aclose = AsyncMock()
            mock_redis.return_value = mock_client

            status = await Bootloader._check_redis()

            assert status.status == "ok"
            assert status.service == "redis"
            mock_client.ping.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_redis_failure(self, mock_settings):
        mock_settings.redis_url = "redis://localhost:6379"
        with patch("redis.asyncio.from_url") as mock_redis:
            mock_redis.side_effect = Exception("Connection failed")

            status = await Bootloader._check_redis()

            assert status.status == "error"
            assert "Connection failed" in status.message


class TestBootloaderS3:
    @pytest.mark.asyncio
    async def test_check_s3_success(self, mock_settings):
        with patch("aioboto3.Session") as mock_session:
            mock_client_ctx = AsyncMock()
            mock_client = AsyncMock()
            mock_session.return_value.client.return_value = mock_client_ctx
            mock_client_ctx.__aenter__.return_value = mock_client
            mock_client.head_bucket = AsyncMock()

            status = await Bootloader._check_s3()

            assert status.status == "ok"
            assert status.service == "minio"


class TestBootloaderOpenrouter:
    @pytest.mark.asyncio
    async def test_check_openrouter_skipped(self, mock_settings):
        mock_settings.openrouter_api_key = None

        status = await Bootloader._check_openrouter()

        assert status.status == "skipped"
        assert status.service == "openrouter"

    @pytest.mark.asyncio
    async def test_check_openrouter_success(self, mock_settings):
        mock_settings.openrouter_api_key = "test-key"
        mock_settings.openrouter_base_url = "https://openrouter.ai/api/v1"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            status = await Bootloader._check_openrouter()

            assert status.status == "ok"
            assert status.service == "openrouter"

    @pytest.mark.asyncio
    async def test_check_openrouter_auth_failure(self, mock_settings):
        mock_settings.openrouter_api_key = "test-key"
        mock_settings.openrouter_base_url = "https://openrouter.ai/api/v1"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_class.return_value.__aenter__.return_value = mock_client

            status = await Bootloader._check_openrouter()

            assert status.status == "error"
            assert "401" in status.message

    @pytest.mark.asyncio
    async def test_check_openrouter_exception(self, mock_settings):
        mock_settings.openrouter_api_key = "test-key"
        mock_settings.openrouter_base_url = "https://openrouter.ai/api/v1"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client_class.return_value.__aenter__.side_effect = Exception("Network error")

            status = await Bootloader._check_openrouter()

            assert status.status == "error"
            assert "Network error" in status.message


class TestBootloaderFullMode:
    @pytest.mark.asyncio
    async def test_full_mode_includes_openrouter(
        self, mock_settings, mock_db_check, mock_redis_check, mock_minio_check, mock_openrouter_check
    ):
        mock_db_check.return_value = ServiceStatus("database", "ok", "OK")
        mock_redis_check.return_value = ServiceStatus("redis", "ok", "OK")
        mock_minio_check.return_value = ServiceStatus("minio", "ok", "OK")
        mock_openrouter_check.return_value = ServiceStatus("openrouter", "ok", "OK")

        result = await Bootloader.validate(BootMode.FULL)

        assert result is True
        mock_openrouter_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_mode_warning_status_logged(self, mock_settings, mock_db_check, mock_logger):
        mock_db_check.return_value = ServiceStatus("database", "warning", "Slow connection", 500.0)

        with (
            patch.object(Bootloader, "_check_redis", new_callable=AsyncMock) as mock_redis,
            patch.object(Bootloader, "_check_s3", new_callable=AsyncMock) as mock_s3,
            patch.object(Bootloader, "_check_openrouter", new_callable=AsyncMock) as mock_openrouter,
        ):
            mock_redis.return_value = ServiceStatus("redis", "ok", "OK")
            mock_s3.return_value = ServiceStatus("minio", "ok", "OK")
            mock_openrouter.return_value = ServiceStatus("openrouter", "ok", "OK")

            result = await Bootloader.validate(BootMode.FULL)

            assert result is True
            mock_logger.warning.assert_called()
