import os
import runpy
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.boot import Bootloader, Bootloader as BootloaderClass, BootMode, ServiceStatus

_ORIGINAL_CHECK_DATABASE = BootloaderClass._check_database
_ORIGINAL_CHECK_S3 = BootloaderClass._check_s3
ZAI_CODING_BASE_URL = "https://api.z.ai/api/coding/paas/v4"
pytestmark = pytest.mark.no_db


@pytest.fixture(autouse=True)
def restore_original_s3_check():
    """Restore the real _check_s3 for this module.

    conftest autouse-stubs ``Bootloader._check_s3`` so ``/health`` is fast in the
    rest of the suite; the Bootloader tests here exercise the real implementation,
    so undo that stub. Tests that want it mocked (e.g. ``mock_minio_check``) re-patch
    it, which overrides this restore.
    """
    if isinstance(_ORIGINAL_CHECK_S3, types.FunctionType):
        BootloaderClass._check_s3 = staticmethod(_ORIGINAL_CHECK_S3)
    else:
        BootloaderClass._check_s3 = _ORIGINAL_CHECK_S3
    yield
    BootloaderClass._check_s3 = _ORIGINAL_CHECK_S3


@pytest.fixture
def mock_settings():
    with patch("src.boot.settings") as mock:
        mock.database_url = "postgresql+asyncpg://test:test@localhost/test"
        mock.ai_api_key = None
        mock.s3_endpoint = "http://localhost:9000"
        mock.s3_access_key = "minio"
        mock.s3_secret_key = "minio123"
        mock.s3_region = "us-east-1"
        mock.s3_bucket = "statements"
        mock.debug = False
        mock.environment = "test"
        mock.base_currency = "USD"
        mock.ai_provider = "zai"
        mock.ai_base_url = ZAI_CODING_BASE_URL
        mock.primary_model = "test-model"
        mock.ocr_model = "glm-4.6v"
        mock.vision_model = "glm-4.6v"
        mock.cors_origin_regex = ".*"
        mock.otel_exporter_otlp_endpoint = None
        mock.otel_service_name = "test"
        mock.ai_base_url = ZAI_CODING_BASE_URL
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
def mock_minio_check():
    with patch("src.boot.Bootloader._check_s3", new_callable=AsyncMock) as mock:
        yield mock


@pytest.fixture
def mock_openrouter_check():
    with patch("src.boot.Bootloader._check_openrouter", new_callable=AsyncMock) as mock:
        yield mock


class TestBootloader:
    async def test_dry_run_passes(self, mock_settings):
        """Dry run should only check config."""
        await Bootloader.validate(BootMode.DRY_RUN)
        # Should not raise exception

    async def test_critical_check_database_failure(self, mock_db_check, mock_settings):
        """Critical check must exit if DB fails."""
        mock_db_check.return_value = ServiceStatus(service="database", status="error", message="Conn refused")

        with pytest.raises(SystemExit):
            await Bootloader.validate(BootMode.CRITICAL)

    async def test_critical_check_success(self, mock_db_check, mock_settings):
        """Critical check passes if DB is OK."""
        mock_db_check.return_value = ServiceStatus(service="database", status="ok", message="Connected", duration_ms=10)

        await Bootloader.validate(BootMode.CRITICAL)
        mock_db_check.assert_called_once()

    async def test_full_check_runs_all(self, mock_db_check, mock_minio_check, mock_settings):
        """Full check must verify all services."""
        mock_db_check.return_value = ServiceStatus(service="database", status="ok", message="OK")
        mock_minio_check.return_value = ServiceStatus(service="minio", status="ok", message="OK")

        await Bootloader.validate(BootMode.FULL)

        mock_db_check.assert_called_once()
        mock_minio_check.assert_called_once()

    async def test_full_check_warns_but_proceeds(self, mock_db_check, mock_minio_check):
        """Full check warns on optional service failure but doesn't exit."""
        mock_db_check.return_value = ServiceStatus(service="database", status="ok", message="OK")
        mock_minio_check.return_value = ServiceStatus(service="minio", status="ok", message="OK")

        # Should not raise SystemExit
        await Bootloader.validate(BootMode.FULL)

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

    def test_AC1_10_1_static_config_rejects_default_secret_key_in_production(self, mock_settings):
        """AC-runtime.21.1: AC1.10.1: Production startup refuses the development JWT secret."""
        mock_settings.environment = "production"
        mock_settings.secret_key = "dev_secret_key_change_in_prod"

        result = Bootloader._check_static_config()

        assert result is False

    def test_AC1_10_1_static_config_rejects_short_secret_key_in_staging(self, mock_settings):
        """AC-runtime.21.2: AC1.10.1: Staging startup requires a high-entropy JWT secret."""
        mock_settings.environment = "staging"
        mock_settings.secret_key = "short-secret"

        result = Bootloader._check_static_config()

        assert result is False

    def test_AC1_10_1_static_config_rejects_default_db_in_protected_env(self, mock_settings):
        """AC-runtime.21.3: AC1.10.1: Protected runtimes cannot boot with local development DB defaults."""
        mock_settings.environment = "production"
        mock_settings.secret_key = "a" * 32
        mock_settings.database_url = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report"

        result = Bootloader._check_static_config()

        assert result is False

    def test_AC1_10_1_static_config_rejects_default_s3_secret_in_production_like_url(self, mock_settings):
        """AC-runtime.21.4: AC1.10.1: Public app URLs are treated as protected even if ENV is misnamed."""
        mock_settings.environment = "preview"
        mock_settings.secret_key = "a" * 32
        mock_settings.database_url = "postgresql+asyncpg://finance:secure@db.internal/finance_report"
        mock_settings.s3_secret_key = "minio_local_secret"
        mock_settings.next_public_app_url = "https://report.zitian.party"

        result = Bootloader._check_static_config()

        assert result is False

    def test_AC1_10_1_static_config_rejects_blank_secret_key_in_production(self, mock_settings):
        """AC-runtime.21.5: AC1.10.1: Protected environments require a configured JWT secret."""
        mock_settings.environment = "production"
        mock_settings.secret_key = "   "

        result = Bootloader._check_static_config()

        assert result is False

    def test_AC1_10_1_static_config_allows_development_default_secret_key(self, mock_settings):
        """AC-runtime.21.6: AC1.10.1: Local development keeps convenient defaults."""
        mock_settings.environment = "development"
        mock_settings.secret_key = "dev_secret_key_change_in_prod"

        result = Bootloader._check_static_config()

        assert result is True

    def test_check_static_config_failure(self):
        with patch("src.boot.settings") as mock:
            mock.database_url = property(lambda self: (_ for _ in ()).throw(Exception("Missing DB URL")))
            type(mock).database_url = property(lambda self: (_ for _ in ()).throw(ValueError("Missing")))
            result = Bootloader._check_static_config()
            assert result is False

    async def test_static_config_fail_critical_exits(self):
        with (
            patch.object(Bootloader, "_check_static_config", return_value=False),
            pytest.raises(SystemExit) as exc_info,
        ):
            await Bootloader.validate(BootMode.CRITICAL)
        assert exc_info.value.code == 1

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
        mock_settings.ai_provider = "zai"
        mock_settings.ai_base_url = ZAI_CODING_BASE_URL
        mock_settings.ocr_model = "glm-4.6v"
        mock_settings.vision_model = "glm-4.6v"
        mock_settings.s3_endpoint = "http://localhost:9000"
        mock_settings.s3_bucket = "statements"
        mock_settings.cors_origin_regex = ".*"
        mock_settings.otel_exporter_otlp_endpoint = None
        mock_settings.otel_service_name = "finance-report"
        mock_settings.database_url = "secret"
        mock_settings.ai_api_key = None
        mock_settings.s3_access_key = "key"
        mock_settings.s3_secret_key = "secret"

        with patch.dict(os.environ, {"DEBUG": "true"}, clear=False):
            Bootloader.print_config()
        captured = capsys.readouterr()
        assert "Config loaded (DEBUG mode)" in captured.out
        assert "database_url: set" in captured.out

    def test_print_config_shows_defaults_used(self, mock_settings, capsys):
        mock_settings.debug = True
        mock_settings.environment = "development"
        mock_settings.base_currency = "USD"
        mock_settings.primary_model = "gemini"
        mock_settings.ai_provider = "zai"
        mock_settings.ai_base_url = ZAI_CODING_BASE_URL
        mock_settings.ocr_model = "glm-4.6v"
        mock_settings.vision_model = "glm-4.6v"
        mock_settings.s3_endpoint = "http://localhost:9000"
        mock_settings.s3_bucket = "statements"
        mock_settings.cors_origin_regex = ".*"
        mock_settings.otel_exporter_otlp_endpoint = None
        mock_settings.otel_service_name = "finance-report"
        mock_settings.database_url = "secret"
        mock_settings.ai_api_key = None
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

    def test_print_config_shows_no_defaults_when_all_env_present(self, mock_settings, capsys):
        mock_settings.debug = True
        mock_settings.environment = "development"
        mock_settings.base_currency = "USD"
        mock_settings.primary_model = "gemini"
        mock_settings.ai_provider = "zai"
        mock_settings.ai_base_url = ZAI_CODING_BASE_URL
        mock_settings.ocr_model = "glm-4.6v"
        mock_settings.vision_model = "glm-4.6v"
        mock_settings.s3_endpoint = "http://localhost:9000"
        mock_settings.s3_bucket = "statements"
        mock_settings.cors_origin_regex = ".*"
        mock_settings.otel_exporter_otlp_endpoint = "http://otel:4317"
        mock_settings.otel_service_name = "finance-report"
        mock_settings.database_url = "secret"
        mock_settings.ai_api_key = "k"
        mock_settings.s3_access_key = "key"
        mock_settings.s3_secret_key = "secret"

        with patch.dict(
            os.environ,
            {
                "DEBUG": "true",
                "ENVIRONMENT": "development",
                "BASE_CURRENCY": "USD",
                "PRIMARY_MODEL": "gemini",
                "AI_PROVIDER": "zai",
                "AI_BASE_URL": ZAI_CODING_BASE_URL,
                "OCR_MODEL": "glm-4.6v",
                "VISION_MODEL": "glm-4.6v",
                "S3_ENDPOINT": "http://localhost:9000",
                "S3_BUCKET": "statements",
                "CORS_ORIGIN_REGEX": ".*",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel:4317",
                "OTEL_SERVICE_NAME": "finance-report",
            },
            clear=False,
        ):
            Bootloader.print_config()
        captured = capsys.readouterr()
        assert "(none)" in captured.out


class TestBootloaderMainEntrypoint:
    def test_main_exits_zero_when_validation_passes(self):
        def _run_success(coro):
            coro.close()
            return True

        with (
            patch.object(sys, "argv", ["boot.py", "--mode", "full"]),
            patch("asyncio.run", side_effect=_run_success),
            patch("sys.exit", side_effect=SystemExit(0)),
            pytest.raises(SystemExit) as exc_info,
        ):
            runpy.run_module("src.boot", run_name="__main__")

        assert exc_info.value.code == 0

    def test_main_exits_one_when_validation_fails(self):
        def _run_failure(coro):
            coro.close()
            return False

        with (
            patch.object(sys, "argv", ["boot.py", "--mode", "critical"]),
            patch("asyncio.run", side_effect=_run_failure),
            patch("sys.exit", side_effect=SystemExit(1)),
            pytest.raises(SystemExit) as exc_info,
        ):
            runpy.run_module("src.boot", run_name="__main__")

        assert exc_info.value.code == 1

    def test_main_keyboard_interrupt_exits_130(self):
        def _run_interrupt(coro):
            coro.close()
            raise KeyboardInterrupt

        with (
            patch.object(sys, "argv", ["boot.py", "--mode", "dry-run"]),
            patch("asyncio.run", side_effect=_run_interrupt),
            patch("sys.exit", side_effect=SystemExit(130)),
            pytest.raises(SystemExit) as exc_info,
        ):
            runpy.run_module("src.boot", run_name="__main__")

        assert exc_info.value.code == 130


class TestBootloaderDatabase:
    @pytest.fixture(autouse=True)
    def restore_original_db_check(self):
        """Restore original _check_database for these tests (conftest mocks it)."""
        if isinstance(_ORIGINAL_CHECK_DATABASE, types.FunctionType):
            BootloaderClass._check_database = staticmethod(_ORIGINAL_CHECK_DATABASE)
        else:
            BootloaderClass._check_database = _ORIGINAL_CHECK_DATABASE
        yield

    async def test_check_database_success(self, mock_settings):
        with patch("src.runtime.extension.adapters.create_async_engine") as mock_engine:
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

    async def test_check_database_failure(self, mock_settings):
        with patch("src.runtime.extension.adapters.create_async_engine") as mock_engine:
            mock_engine.side_effect = Exception("Connection refused")

            status = await Bootloader._check_database()

            assert status.status == "error"
            assert "Connection refused" in status.message


class TestBootloaderS3:
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
    async def test_check_openrouter_absent_is_error_not_skipped(self, mock_settings):
        # runtime invariant 2: a declared dependency that is absent is an error,
        # not a silent `skipped`.
        mock_settings.ai_api_key = None

        status = await Bootloader._check_openrouter()

        assert status.status == "error"
        assert status.service == "ai_provider"

    async def test_check_openrouter_success(self, mock_settings):
        # The model catalogue is local (src/llm/catalog.py): a configured api_key
        # reports ok with the configured provider, no remote /models probe.
        mock_settings.ai_api_key = "test-key"
        mock_settings.ai_base_url = ZAI_CODING_BASE_URL

        status = await Bootloader._check_openrouter()

        assert status.status == "ok"
        assert status.service == "ai_provider"
        assert "Configured provider=" in status.message


class TestBootloaderFullMode:
    async def test_full_mode_includes_openrouter(
        self, mock_settings, mock_db_check, mock_minio_check, mock_openrouter_check
    ):
        """The real-provider check runs on tiers that declare llm (staging/prod)."""
        from src.runtime import EnvTier

        mock_db_check.return_value = ServiceStatus("database", "ok", "OK")
        mock_minio_check.return_value = ServiceStatus("minio", "ok", "OK")
        mock_openrouter_check.return_value = ServiceStatus("ai_provider", "ok", "OK")

        with patch.object(Bootloader, "_check_vault_secrets") as mock_vault:
            mock_vault.return_value = ServiceStatus("vault_secrets", "ok", "OK")
            with (
                patch.object(Bootloader, "_check_cache", new_callable=AsyncMock) as m_cache,
                patch.object(Bootloader, "_check_workflow_engine", new_callable=AsyncMock) as m_wf,
                patch.object(Bootloader, "_check_telemetry", new_callable=AsyncMock) as m_tel,
                patch.object(Bootloader, "_check_analytics", new_callable=AsyncMock) as m_an,
            ):
                for name, m in {
                    "cache": m_cache,
                    "workflow_engine": m_wf,
                    "telemetry": m_tel,
                    "analytics": m_an,
                }.items():
                    m.return_value = ServiceStatus(name, "ok", "OK")
                result = await Bootloader.validate(BootMode.FULL, tier=EnvTier.STAGING)

        assert result is True
        mock_openrouter_check.assert_called_once()

    async def test_full_mode_warning_status_logged(self, mock_settings, mock_db_check, mock_logger):
        mock_db_check.return_value = ServiceStatus("database", "warning", "Slow connection", 500.0)

        with (
            patch.object(Bootloader, "_check_s3", new_callable=AsyncMock) as mock_s3,
            patch.object(Bootloader, "_check_openrouter", new_callable=AsyncMock) as mock_openrouter,
            patch.object(Bootloader, "_check_vault_secrets") as mock_vault,
        ):
            mock_s3.return_value = ServiceStatus("minio", "ok", "OK")
            mock_openrouter.return_value = ServiceStatus("ai_provider", "ok", "OK")
            mock_vault.return_value = ServiceStatus("vault_secrets", "ok", "OK")

            result = await Bootloader.validate(BootMode.FULL)

            assert result is True
            mock_logger.warning.assert_called()

    async def test_full_mode_service_error_returns_false(self, mock_settings, mock_db_check, mock_logger):
        """Full mode returns False (not sys.exit) when a service check has error status."""
        mock_db_check.return_value = ServiceStatus("database", "error", "Connection refused")

        with (
            patch.object(Bootloader, "_check_s3", new_callable=AsyncMock) as mock_s3,
            patch.object(Bootloader, "_check_openrouter", new_callable=AsyncMock) as mock_openrouter,
            patch.object(Bootloader, "_check_vault_secrets") as mock_vault,
        ):
            mock_s3.return_value = ServiceStatus("minio", "ok", "OK")
            mock_openrouter.return_value = ServiceStatus("ai_provider", "ok", "OK")
            mock_vault.return_value = ServiceStatus("vault_secrets", "ok", "OK")

            result = await Bootloader.validate(BootMode.FULL)

        assert result is False
        mock_logger.error.assert_called()


class TestBootloaderVaultSecrets:
    def test_vault_secrets_file_not_found(self):
        with patch("os.path.exists", return_value=False):
            status = Bootloader._check_vault_secrets()

        assert status.status == "warning"
        assert status.service == "vault_secrets"
        assert "not found" in status.message
        assert "invoke vault.setup-approle" in status.message

    def test_vault_secrets_file_stale(self):
        with (
            patch("os.path.exists", return_value=True),
            patch("os.stat") as mock_stat,
            patch("time.time", return_value=10000),
        ):
            mock_stat.return_value.st_mtime = 10000 - 7200

            status = Bootloader._check_vault_secrets()

        assert status.status == "warning"
        assert "old" in status.message
        assert "Check token expiry" in status.message

    def test_vault_secrets_file_fresh(self):
        with (
            patch("os.path.exists", return_value=True),
            patch("os.stat") as mock_stat,
            patch("time.time", return_value=10000),
        ):
            mock_stat.return_value.st_mtime = 10000 - 300

            status = Bootloader._check_vault_secrets()

        assert status.status == "ok"
        assert "last modified" in status.message

    def test_vault_secrets_os_error(self):
        with (
            patch("os.path.exists", return_value=True),
            patch("os.stat", side_effect=OSError("Permission denied")),
        ):
            status = Bootloader._check_vault_secrets()

        assert status.status == "error"
        assert "Permission denied" in status.message


def test_AC_runtime_3_1_required_checks_cover_the_tier_declaration():
    """AC-runtime.3.1 (#1577): the probed + unprobed split is exactly
    DEPENDENCY_MANIFEST.required_for(tier) — the set comes from the manifest,
    not a hardcoded per-mode list."""
    from src.runtime import DEPENDENCY_MANIFEST, EnvTier

    for tier in EnvTier:
        probed, unprobed = Bootloader._required_checks(tier)
        assert set(probed) | set(unprobed) == DEPENDENCY_MANIFEST.required_for(tier)
        assert not set(probed) & set(unprobed)


class TestManifestDrivenValidate:
    """AC-runtime.3.1 (#1577) — FULL mode derives its checks from the manifest."""

    def test_github_ci_tier_has_no_unprobed_requirements(self):
        """Everything github_ci requires already has a probe adapter; the real
        LLM provider is a staging/prod requirement (recorded substitute in CI)."""
        from src.runtime import EnvTier

        probed, unprobed = Bootloader._required_checks(EnvTier.GITHUB_CI)
        assert set(probed) == {"database", "object_storage"}
        assert unprobed == []

    def test_production_tier_probes_every_declared_dependency(self):
        """Since #1580 every declared-required dep has a probe — nothing unprobed."""
        from src.runtime import DEPENDENCY_MANIFEST, EnvTier

        probed, unprobed = Bootloader._required_checks(EnvTier.PRODUCTION)
        assert set(probed) == DEPENDENCY_MANIFEST.required_for(EnvTier.PRODUCTION)
        assert unprobed == []

    async def test_full_mode_probes_the_manifest_set_for_the_tier(
        self, mock_settings, mock_db_check, mock_minio_check, mock_openrouter_check
    ):
        from src.runtime import EnvTier

        mock_db_check.return_value = ServiceStatus("database", "ok", "OK")
        mock_minio_check.return_value = ServiceStatus("minio", "ok", "OK")
        mock_openrouter_check.return_value = ServiceStatus("ai_provider", "ok", "OK")

        with patch.object(Bootloader, "_check_vault_secrets") as mock_vault:
            mock_vault.return_value = ServiceStatus("vault_secrets", "ok", "OK")
            result = await Bootloader.validate(BootMode.FULL, tier=EnvTier.GITHUB_CI)

        assert result is True
        mock_db_check.assert_called_once()
        mock_minio_check.assert_called_once()
        # The real LLM provider is not a github_ci requirement (recorded-substitute tier).
        mock_openrouter_check.assert_not_called()

    async def test_full_mode_probes_all_eight_deps_on_production(
        self, mock_settings, mock_db_check, mock_minio_check, mock_openrouter_check
    ):
        """AC-runtime.4.1 (#1580): production FULL probes every declared dependency."""
        from src.runtime import EnvTier

        mock_db_check.return_value = ServiceStatus("database", "ok", "OK")
        mock_minio_check.return_value = ServiceStatus("minio", "ok", "OK")
        mock_openrouter_check.return_value = ServiceStatus("ai_provider", "ok", "OK")

        extra = {}
        with patch.object(Bootloader, "_check_vault_secrets") as mock_vault:
            mock_vault.return_value = ServiceStatus("vault_secrets", "ok", "OK")
            with (
                patch.object(Bootloader, "_check_cache", new_callable=AsyncMock) as extra["cache"],
                patch.object(Bootloader, "_check_workflow_engine", new_callable=AsyncMock) as extra["workflow_engine"],
                patch.object(Bootloader, "_check_telemetry", new_callable=AsyncMock) as extra["telemetry"],
                patch.object(Bootloader, "_check_analytics", new_callable=AsyncMock) as extra["analytics"],
                patch.object(Bootloader, "_check_market_data", new_callable=AsyncMock) as extra["market_data"],
            ):
                for name, mock in extra.items():
                    mock.return_value = ServiceStatus(name, "ok", "OK")
                result = await Bootloader.validate(BootMode.FULL, tier=EnvTier.PRODUCTION)

        assert result is True
        for name, mock in extra.items():
            mock.assert_called_once(), name

    async def test_full_mode_absent_new_probe_fails_validate(
        self, mock_settings, mock_db_check, mock_minio_check, mock_openrouter_check
    ):
        """An absent cache (Redis down) now fails production FULL — invariant 2."""
        from src.runtime import EnvTier

        mock_db_check.return_value = ServiceStatus("database", "ok", "OK")
        mock_minio_check.return_value = ServiceStatus("minio", "ok", "OK")
        mock_openrouter_check.return_value = ServiceStatus("ai_provider", "ok", "OK")

        with patch.object(Bootloader, "_check_vault_secrets") as mock_vault:
            mock_vault.return_value = ServiceStatus("vault_secrets", "ok", "OK")
            with (
                patch.object(Bootloader, "_check_cache", new_callable=AsyncMock) as mock_cache,
                patch.object(Bootloader, "_check_workflow_engine", new_callable=AsyncMock) as m_wf,
                patch.object(Bootloader, "_check_telemetry", new_callable=AsyncMock) as m_tel,
                patch.object(Bootloader, "_check_analytics", new_callable=AsyncMock) as m_an,
                patch.object(Bootloader, "_check_market_data", new_callable=AsyncMock) as m_md,
            ):
                mock_cache.return_value = ServiceStatus("cache", "error", "Connection refused")
                for name, m in {
                    "workflow_engine": m_wf,
                    "telemetry": m_tel,
                    "analytics": m_an,
                    "market_data": m_md,
                }.items():
                    m.return_value = ServiceStatus(name, "ok", "OK")
                result = await Bootloader.validate(BootMode.FULL, tier=EnvTier.PRODUCTION)

        assert result is False

    async def test_full_mode_absent_required_dep_fails(self, mock_settings, mock_db_check, mock_logger):
        from src.runtime import EnvTier

        mock_db_check.return_value = ServiceStatus("database", "error", "Connection refused")
        with (
            patch.object(Bootloader, "_check_s3", new_callable=AsyncMock) as mock_s3,
            patch.object(Bootloader, "_check_openrouter", new_callable=AsyncMock) as mock_openrouter,
            patch.object(Bootloader, "_check_vault_secrets") as mock_vault,
        ):
            mock_s3.return_value = ServiceStatus("minio", "ok", "OK")
            mock_openrouter.return_value = ServiceStatus("ai_provider", "ok", "OK")
            mock_vault.return_value = ServiceStatus("vault_secrets", "ok", "OK")
            result = await Bootloader.validate(BootMode.FULL, tier=EnvTier.STAGING)

        assert result is False
