import os; import runpy; import sys; import types; from unittest.mock import AsyncMock, MagicMock, patch; import pytest; from src.boot import Bootloader, Bootloader as BootloaderClass, BootMode, ServiceStatus; _ORIGINAL_CHECK_DATABASE = BootloaderClass._check_database; _ORIGINAL_CHECK_S3 = BootloaderClass._check_s3; ZAI_CODING_BASE_URL = 'https://api.z.ai/api/coding/paas/v4'; pytestmark = pytest.mark.no_db
@pytest.fixture(autouse=True)
def restore_original_s3_check(): BootloaderClass._check_s3 = staticmethod(_ORIGINAL_CHECK_S3) if isinstance(_ORIGINAL_CHECK_S3, types.FunctionType) else _ORIGINAL_CHECK_S3; yield; BootloaderClass._check_s3 = _ORIGINAL_CHECK_S3
@pytest.fixture
def mock_settings():
    with patch('src.boot.settings') as mock: mock.database_url = 'postgresql+asyncpg://test:test@localhost/test'; mock.secret_key = 'unit-test-' + 'x' * 26; mock.ai_api_key = None; mock.s3_endpoint = 'http://localhost:9000'; mock.s3_access_key = 'minio'; mock.s3_secret_key = 'minio123'; mock.s3_region = 'us-east-1'; mock.s3_bucket = 'statements'; mock.next_public_app_url = 'http://localhost:3000'; mock.debug = False; mock.environment = 'test'; mock.base_currency = 'USD'; mock.ai_provider = 'zai'; mock.ai_base_url = ZAI_CODING_BASE_URL; mock.large_model = 'test-large-model'; mock.small_model = 'test-model'; mock.multimodal_model = 'test-vision-model'; mock.cors_origin_regex = '.*'; mock.cors_origins_str = 'http://localhost:3000'; mock.otel_exporter_otlp_endpoint = 'http://otel:4318'; mock.otel_resource_attributes = 'deployment.environment=test'; mock.otel_service_name = 'test'; mock.openpanel_api_url = 'https://openpanel.zitian.party/api'; mock.prefect_api_url = 'http://prefect:4200/api'; mock.s3_public_endpoint = 'https://s3.zitian.party'; mock.s3_presign_expiry_seconds = 300; mock.api_rate_limit_requests = 300; mock.git_commit_sha = 'deadbeef'; mock.ai_base_url = ZAI_CODING_BASE_URL; yield mock
@pytest.fixture
def mock_logger():
    with patch('src.boot.logger') as mock: yield mock
@pytest.fixture
def mock_db_check():
    with patch('src.boot.Bootloader._check_database', new_callable=AsyncMock) as mock: yield mock
@pytest.fixture
def mock_minio_check():
    with patch('src.boot.Bootloader._check_s3', new_callable=AsyncMock) as mock: yield mock
@pytest.fixture
def mock_openrouter_check():
    with patch('src.boot.Bootloader._check_openrouter', new_callable=AsyncMock) as mock: yield mock
class TestBootloader:
    async def test_dry_run_passes(self, mock_settings): await Bootloader.validate(BootMode.DRY_RUN)
    async def test_critical_check_database_failure(self, mock_db_check, mock_settings):
        mock_db_check.return_value = ServiceStatus(service='database', status='error', message='Conn refused')
        with pytest.raises(SystemExit): await Bootloader.validate(BootMode.CRITICAL)
    async def test_critical_check_success(self, mock_db_check, mock_settings): mock_db_check.return_value = ServiceStatus(service='database', status='ok', message='Connected', duration_ms=10); await Bootloader.validate(BootMode.CRITICAL); mock_db_check.assert_called_once()
    async def test_full_check_runs_all(self, mock_db_check, mock_minio_check, mock_settings): mock_db_check.return_value = ServiceStatus(service='database', status='ok', message='OK'); mock_minio_check.return_value = ServiceStatus(service='minio', status='ok', message='OK'); await Bootloader.validate(BootMode.FULL); mock_db_check.assert_called_once(); mock_minio_check.assert_called_once()
    async def test_full_check_warns_but_proceeds(self, mock_db_check, mock_minio_check): mock_db_check.return_value = ServiceStatus(service='database', status='ok', message='OK'); mock_minio_check.return_value = ServiceStatus(service='minio', status='ok', message='OK'); await Bootloader.validate(BootMode.FULL)
    async def test_check_s3_handles_client_error(self):
        with patch('aioboto3.Session') as mock_session: mock_client_ctx = AsyncMock(); mock_client = AsyncMock(); mock_session.return_value.client.return_value = mock_client_ctx; mock_client_ctx.__aenter__.return_value = mock_client; mock_client.head_bucket.side_effect = Exception('S3 Down'); status = await Bootloader._check_s3(); assert status.status == 'error'; assert 'S3 Down' in str(status.message)
class TestBootloaderStaticConfig:
    def test_import_boot_succeeds_without_env(self, monkeypatch):
        monkeypatch.delenv('APP_ENV', raising=False); monkeypatch.setenv('ENVIRONMENT', 'development'); from src.config import Settings; local_settings = Settings(_env_file=None)
        with patch('src.boot.settings', local_settings): assert Bootloader._check_static_config() is True
    def test_check_static_config_success(self, mock_settings): result = Bootloader._check_static_config(); assert result is True
    def test_AC1_10_1_static_config_rejects_default_secret_key_in_production(self, mock_settings): 'AC-runtime.21.1 AC1.10.1'; mock_settings.environment = 'production'; mock_settings.secret_key = 'dev_secret_key_change_in_prod'; result = Bootloader._check_static_config(); assert result is False
    def test_AC1_10_1_static_config_rejects_short_secret_key_in_staging(self, mock_settings): 'AC-runtime.21.2 AC1.10.1'; mock_settings.environment = 'staging'; mock_settings.secret_key = 'short-secret'; result = Bootloader._check_static_config(); assert result is False
    def test_AC1_10_1_static_config_rejects_default_db_in_protected_env(self, mock_settings): 'AC-runtime.21.3 AC1.10.1'; mock_settings.environment = 'production'; mock_settings.secret_key = 'a' * 32; mock_settings.database_url = 'postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report'; result = Bootloader._check_static_config(); assert result is False
    def test_AC1_10_1_static_config_rejects_default_s3_secret_in_production_like_url(self, mock_settings): 'AC-runtime.21.4 AC1.10.1'; mock_settings.environment = 'preview'; mock_settings.secret_key = 'a' * 32; mock_settings.database_url = 'postgresql+asyncpg://finance:secure@db.internal/finance_report'; mock_settings.s3_secret_key = 'minio_local_secret'; mock_settings.next_public_app_url = 'https://report.zitian.party'; result = Bootloader._check_static_config(); assert result is False
    def test_AC1_10_1_static_config_rejects_blank_secret_key_in_production(self, mock_settings): 'AC-runtime.21.5 AC1.10.1'; mock_settings.environment = 'production'; mock_settings.secret_key = '   '; result = Bootloader._check_static_config(); assert result is False
    def test_AC1_10_1_static_config_allows_development_default_secret_key(self, mock_settings): 'AC-runtime.21.6 AC1.10.1'; mock_settings.environment = 'development'; mock_settings.secret_key = 'dev_secret_key_change_in_prod'; result = Bootloader._check_static_config(); assert result is True
    def test_check_static_config_failure(self):
        with patch('src.boot.settings') as mock: mock.database_url = property(lambda self: (_ for _ in ()).throw(Exception('Missing DB URL'))); type(mock).database_url = property(lambda self: (_ for _ in ()).throw(ValueError('Missing'))); result = Bootloader._check_static_config(); assert result is False
    async def test_static_config_fail_critical_exits(self):
        with patch.object(Bootloader, '_check_static_config', return_value=False), pytest.raises(SystemExit) as exc_info: await Bootloader.validate(BootMode.CRITICAL)
        assert exc_info.value.code == 1
        with patch.object(Bootloader, '_check_static_config', return_value=False): _m1_result = await Bootloader.validate(BootMode.FULL)
        assert _m1_result is False
_GUARD_DEV_DEFAULTS = {'secret_key': 'dev_secret_key_change_in_prod', 'database_url': 'postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report', 's3_secret_key': 'minio_local_secret'}; _GUARD_STRONG_VALUES = {'secret_key': 'unit-test-' + 'x' * 26, 'database_url': 'postgresql+asyncpg://finance:placeholder-password@db.internal:5432/finance_report', 's3_secret_key': 'placeholder-' + 'y' * 12}; _GUARD_PROTECTED_TRIGGERS = {'staging-env': ('staging', 'http://localhost:3000'), 'production-env': ('production', 'http://localhost:3000'), 'unknown-env-fails-closed': ('prod-eu', 'http://localhost:3000'), 'public-https-url': ('development', 'https://report.example.com')}; _GUARD_LOCAL_ENVIRONMENTS = ('development', 'test', 'ci')
class TestGuardProofsStaticConfigMatrix:
    def _configure(self, mock_settings, environment: str, app_url: str, **overrides: str) -> None: values = {**_GUARD_STRONG_VALUES, **overrides}; [setattr(mock_settings, field, value) for field, value in values.items()]; mock_settings.environment = environment; mock_settings.next_public_app_url = app_url
    @pytest.mark.parametrize('trigger', sorted(_GUARD_PROTECTED_TRIGGERS))
    @pytest.mark.parametrize('field', sorted(_GUARD_DEV_DEFAULTS))
    def test_AC_runtime_guard_proofs_1_every_default_is_rejected_under_every_protected_trigger(self, mock_settings, field: str, trigger: str) -> None: 'AC-runtime.guard-proofs.1'; environment, app_url = _GUARD_PROTECTED_TRIGGERS[trigger]; self._configure(mock_settings, environment, app_url, **{field: _GUARD_DEV_DEFAULTS[field]}); assert Bootloader._check_static_config() is False
    @pytest.mark.parametrize('environment', _GUARD_LOCAL_ENVIRONMENTS)
    def test_AC_runtime_guard_proofs_2_development_defaults_accepted_in_local_environments(self, mock_settings, environment: str) -> None: 'AC-runtime.guard-proofs.2'; self._configure(mock_settings, environment, 'http://localhost:3000', **_GUARD_DEV_DEFAULTS); assert Bootloader._check_static_config() is True
    @pytest.mark.parametrize('trigger', sorted(_GUARD_PROTECTED_TRIGGERS))
    def test_guard_proofs_strong_values_accepted_under_every_protected_trigger(self, mock_settings, trigger: str) -> None: 'AC-runtime.guard-proofs.2'; environment, app_url = _GUARD_PROTECTED_TRIGGERS[trigger]; self._configure(mock_settings, environment, app_url); assert Bootloader._check_static_config() is True
    @pytest.mark.parametrize(('environment', 'app_url', 'expected'), [('staging', 'http://localhost:3000', True), ('production', 'http://localhost:3000', True), ('  Production ', 'http://localhost:3000', True), ('prod-eu', 'http://localhost:3000', True), ('development', 'https://report.example.com', True), ('development', 'http://localhost:3000', False), ('test', '', False), ('ci', 'https://localhost:8443', False), ('development', 'https://127.0.0.1:8443', False)])
    def test_AC_runtime_guard_proofs_3_protected_runtime_classification(self, mock_settings, environment: str, app_url: str, expected: bool) -> None: 'AC-runtime.guard-proofs.3'; mock_settings.next_public_app_url = app_url; assert Bootloader._is_protected_runtime(environment) is expected
class TestBootloaderPrintConfig:
    def test_print_config_skipped_when_not_debug(self, mock_settings, capsys):
        with patch.dict(os.environ, {'DEBUG': 'false'}, clear=False): Bootloader.print_config()
        captured = capsys.readouterr(); assert captured.out == ''
    def test_print_config_shows_config_when_debug(self, mock_settings, capsys):
        mock_settings.debug = True; mock_settings.environment = 'development'; mock_settings.base_currency = 'USD'; mock_settings.small_model = 'gemini'; mock_settings.ai_provider = 'zai'; mock_settings.ai_base_url = ZAI_CODING_BASE_URL; mock_settings.multimodal_model = 'test-vision-model'; mock_settings.s3_endpoint = 'http://localhost:9000'; mock_settings.s3_bucket = 'statements'; mock_settings.cors_origin_regex = '.*'; mock_settings.otel_exporter_otlp_endpoint = None; mock_settings.otel_service_name = 'finance-report'; mock_settings.database_url = 'secret'; mock_settings.ai_api_key = None; mock_settings.s3_access_key = 'key'; mock_settings.s3_secret_key = 'secret'
        with patch.dict(os.environ, {'DEBUG': 'true'}, clear=False): Bootloader.print_config()
        captured = capsys.readouterr(); assert 'Config loaded (DEBUG mode)' in captured.out; assert 'database_url: set' in captured.out
    def test_print_config_shows_defaults_used(self, mock_settings, capsys):
        mock_settings.debug = True; mock_settings.environment = 'development'; mock_settings.base_currency = 'USD'; mock_settings.small_model = 'gemini'; mock_settings.ai_provider = 'zai'; mock_settings.ai_base_url = ZAI_CODING_BASE_URL; mock_settings.multimodal_model = 'test-vision-model'; mock_settings.s3_endpoint = 'http://localhost:9000'; mock_settings.s3_bucket = 'statements'; mock_settings.cors_origin_regex = '.*'; mock_settings.otel_exporter_otlp_endpoint = None; mock_settings.otel_service_name = 'finance-report'; mock_settings.database_url = 'secret'; mock_settings.ai_api_key = None; mock_settings.s3_access_key = 'key'; mock_settings.s3_secret_key = 'secret'
        with patch.dict(os.environ, {'DEBUG': 'true', 'ENVIRONMENT': 'development', 'BASE_CURRENCY': 'USD'}, clear=False): Bootloader.print_config()
        captured = capsys.readouterr(); assert 'Fields using defaults:' in captured.out
    def test_print_config_shows_no_defaults_when_all_env_present(self, mock_settings, capsys):
        mock_settings.debug = True; mock_settings.environment = 'development'; mock_settings.base_currency = 'USD'; mock_settings.large_model = 'test-large-model'; mock_settings.small_model = 'gemini'; mock_settings.ai_provider = 'zai'; mock_settings.ai_base_url = ZAI_CODING_BASE_URL; mock_settings.multimodal_model = 'test-vision-model'; mock_settings.s3_endpoint = 'http://localhost:9000'; mock_settings.s3_bucket = 'statements'; mock_settings.cors_origin_regex = '.*'; mock_settings.otel_exporter_otlp_endpoint = 'http://otel:4317'; mock_settings.otel_service_name = 'finance-report'; mock_settings.database_url = 'secret'; mock_settings.ai_api_key = 'k'; mock_settings.s3_access_key = 'key'; mock_settings.s3_secret_key = 'secret'
        with patch.dict(os.environ, {'DEBUG': 'true', 'ENVIRONMENT': 'development', 'BASE_CURRENCY': 'USD', 'LARGE_MODEL': 'test-large-model', 'SMALL_MODEL': 'gemini', 'AI_PROVIDER': 'zai', 'AI_BASE_URL': ZAI_CODING_BASE_URL, 'MULTIMODAL_MODEL': 'test-vision-model', 'S3_ENDPOINT': 'http://localhost:9000', 'S3_BUCKET': 'statements', 'CORS_ORIGIN_REGEX': '.*', 'OTEL_EXPORTER_OTLP_ENDPOINT': 'http://otel:4317', 'OTEL_SERVICE_NAME': 'finance-report'}, clear=False): Bootloader.print_config()
        captured = capsys.readouterr(); assert '(none)' in captured.out
class TestBootloaderMainEntrypoint:
    def test_main_exits_zero_when_validation_passes(self):
        def _run_success(coro): coro.close(); return True
        with patch.object(sys, 'argv', ['boot.py', '--mode', 'full']), patch('asyncio.run', side_effect=_run_success), patch('sys.exit', side_effect=SystemExit(0)), pytest.raises(SystemExit) as exc_info: runpy.run_module('src.boot', run_name='__main__')
        assert exc_info.value.code == 0
    def test_main_exits_one_when_validation_fails(self):
        def _run_failure(coro): coro.close(); return False
        with patch.object(sys, 'argv', ['boot.py', '--mode', 'critical']), patch('asyncio.run', side_effect=_run_failure), patch('sys.exit', side_effect=SystemExit(1)), pytest.raises(SystemExit) as exc_info: runpy.run_module('src.boot', run_name='__main__')
        assert exc_info.value.code == 1
    def test_main_keyboard_interrupt_exits_130(self):
        def _run_interrupt(coro): coro.close(); raise KeyboardInterrupt
        with patch.object(sys, 'argv', ['boot.py', '--mode', 'dry-run']), patch('asyncio.run', side_effect=_run_interrupt), patch('sys.exit', side_effect=SystemExit(130)), pytest.raises(SystemExit) as exc_info: runpy.run_module('src.boot', run_name='__main__')
        assert exc_info.value.code == 130
class TestBootloaderDatabase:
    @pytest.fixture(autouse=True)
    def restore_original_db_check(self): BootloaderClass._check_database = staticmethod(_ORIGINAL_CHECK_DATABASE) if isinstance(_ORIGINAL_CHECK_DATABASE, types.FunctionType) else _ORIGINAL_CHECK_DATABASE; yield
    async def test_check_database_success(self, mock_settings):
        with patch('src.runtime.extension.adapters.create_async_engine') as mock_engine: mock_conn = AsyncMock(); mock_conn.execute = AsyncMock(); mock_engine_instance = MagicMock(); mock_engine_instance.connect.return_value.__aenter__.return_value = mock_conn; mock_engine_instance.dispose = AsyncMock(); mock_engine.return_value = mock_engine_instance; status = await Bootloader._check_database(); assert status.status == 'ok'; assert status.service == 'database'; mock_conn.execute.assert_called_once()
    async def test_check_database_failure(self, mock_settings):
        with patch('src.runtime.extension.adapters.create_async_engine') as mock_engine: mock_engine.side_effect = Exception('Connection refused'); status = await Bootloader._check_database(); assert status.status == 'error'; assert 'Connection refused' in status.message
class TestBootloaderS3:
    async def test_check_s3_success(self, mock_settings):
        with patch('aioboto3.Session') as mock_session: mock_client_ctx = AsyncMock(); mock_client = AsyncMock(); mock_session.return_value.client.return_value = mock_client_ctx; mock_client_ctx.__aenter__.return_value = mock_client; mock_client.head_bucket = AsyncMock(); status = await Bootloader._check_s3(); assert status.status == 'ok'; assert status.service == 'minio'
class TestBootloaderOpenrouter:
    async def test_check_openrouter_absent_is_error_not_skipped(self, mock_settings): mock_settings.ai_api_key = None; status = await Bootloader._check_openrouter(); assert status.status == 'error'; assert status.service == 'ai_provider'
    async def test_check_openrouter_success(self, mock_settings): mock_settings.ai_api_key = 'test-key'; mock_settings.ai_base_url = ZAI_CODING_BASE_URL; status = await Bootloader._check_openrouter(); assert status.status == 'ok'; assert status.service == 'ai_provider'; assert 'Configured provider=' in status.message
class TestBootloaderFullMode:
    async def test_full_mode_includes_openrouter(self, mock_settings, mock_db_check, mock_minio_check, mock_openrouter_check):
        from src.runtime import EnvTier; mock_db_check.return_value = ServiceStatus('database', 'ok', 'OK'); mock_minio_check.return_value = ServiceStatus('minio', 'ok', 'OK'); mock_openrouter_check.return_value = ServiceStatus('ai_provider', 'ok', 'OK')
        with patch.object(Bootloader, '_check_cache', new_callable=AsyncMock) as m_cache, patch.object(Bootloader, '_check_workflow_engine', new_callable=AsyncMock) as m_wf, patch.object(Bootloader, '_check_telemetry', new_callable=AsyncMock) as m_tel, patch.object(Bootloader, '_check_analytics', new_callable=AsyncMock) as m_an:
            for (name, m) in {'cache': m_cache, 'workflow_engine': m_wf, 'telemetry': m_tel, 'analytics': m_an}.items(): m.return_value = ServiceStatus(name, 'ok', 'OK')
            result = await Bootloader.validate(BootMode.FULL, tier=EnvTier.STAGING)
        assert result is True; mock_openrouter_check.assert_called_once()
    async def test_full_mode_warning_status_logged(self, mock_settings, mock_db_check, mock_logger):
        mock_db_check.return_value = ServiceStatus('database', 'warning', 'Slow connection', 500.0)
        with patch.object(Bootloader, '_check_s3', new_callable=AsyncMock) as mock_s3, patch.object(Bootloader, '_check_openrouter', new_callable=AsyncMock) as mock_openrouter: mock_s3.return_value = ServiceStatus('minio', 'ok', 'OK'); mock_openrouter.return_value = ServiceStatus('ai_provider', 'ok', 'OK'); result = await Bootloader.validate(BootMode.FULL); assert result is True; mock_logger.warning.assert_called()
    async def test_full_mode_service_error_returns_false(self, mock_settings, mock_db_check, mock_logger):
        mock_db_check.return_value = ServiceStatus('database', 'error', 'Connection refused')
        with patch.object(Bootloader, '_check_s3', new_callable=AsyncMock) as mock_s3, patch.object(Bootloader, '_check_openrouter', new_callable=AsyncMock) as mock_openrouter: mock_s3.return_value = ServiceStatus('minio', 'ok', 'OK'); mock_openrouter.return_value = ServiceStatus('ai_provider', 'ok', 'OK'); result = await Bootloader.validate(BootMode.FULL)
        assert result is False; mock_logger.error.assert_called()
class TestBootloaderNoVaultSecretsResidueAndFailClosedEnv:
    def test_bootloader_has_no_vault_secrets_file_residue(self): import src.boot as boot_module; assert not hasattr(Bootloader, '_check_vault_secrets'); assert not hasattr(boot_module, 'VAULT_SECRETS_FILE_PATH'); assert not hasattr(boot_module, 'VAULT_SECRETS_STALENESS_THRESHOLD_SECONDS'); assert not hasattr(boot_module, 'PROTECTED_REQUIRED_INJECTED_FIELDS')
    @pytest.mark.parametrize('attr_name', ['secret_key', 'database_url', 's3_secret_key', 's3_access_key', 's3_endpoint', 's3_bucket', 'next_public_app_url'])
    def test_static_config_fails_closed_when_required_injected_setting_missing_in_protected_runtime(self, mock_settings, attr_name: str): mock_settings.environment = 'production'; mock_settings.secret_key = 'unit-test-' + 'x' * 26; mock_settings.database_url = 'postgresql+asyncpg://finance:placeholder@db.internal:5432/finance_report'; mock_settings.s3_secret_key = 'placeholder-' + 'y' * 12; mock_settings.s3_access_key = 'minio-prod'; mock_settings.s3_endpoint = 'http://minio:9000'; mock_settings.s3_bucket = 'statements'; mock_settings.next_public_app_url = 'https://report.zitian.party'; setattr(mock_settings, attr_name, '   '); assert Bootloader._check_static_config() is False
    async def test_critical_boot_exits_when_required_injected_setting_missing_in_protected_runtime(self, mock_settings):
        mock_settings.environment = 'production'; mock_settings.secret_key = 'unit-test-' + 'x' * 26; mock_settings.database_url = 'postgresql+asyncpg://finance:placeholder@db.internal:5432/finance_report'; mock_settings.s3_secret_key = 'placeholder-' + 'y' * 12; mock_settings.s3_access_key = ''
        with pytest.raises(SystemExit) as exc_info: await Bootloader.validate(BootMode.CRITICAL)
        assert exc_info.value.code == 1
    def test_static_config_fails_closed_on_conflicting_alias_env_vars(self, mock_settings, monkeypatch): monkeypatch.setenv('AI_API_KEY', 'key-one'); monkeypatch.setenv('ZAI_API_KEY', 'key-two'); assert Bootloader._check_static_config() is False
class TestStaticConfigInjectedValuesScope:
    def _configure_deployed(self, mock_settings, monkeypatch, environment: str, app_url: str) -> None: monkeypatch.delenv('PREFECT_API_URL', raising=False); monkeypatch.delenv('S3_PUBLIC_ENDPOINT', raising=False); [setattr(mock_settings, field, value) for field, value in _GUARD_STRONG_VALUES.items()]; mock_settings.environment = environment; mock_settings.next_public_app_url = app_url; mock_settings.prefect_api_url = None; mock_settings.s3_public_endpoint = None
    def test_static_config_accepts_preview_alias_without_prefect_and_public_s3_endpoint(self, mock_settings, mock_logger, monkeypatch): self._configure_deployed(mock_settings, monkeypatch, 'pr-123', 'https://report-pr-123.zitian.party'); assert Bootloader._is_protected_runtime('pr-123') is True; assert Bootloader._check_static_config() is True; mock_logger.error.assert_not_called()
    def test_static_config_rejects_staging_without_prefect_api_url(self, mock_settings, mock_logger, monkeypatch): self._configure_deployed(mock_settings, monkeypatch, 'staging', 'https://report-staging.zitian.party'); mock_settings.s3_public_endpoint = 'https://s3.zitian.party'; assert Bootloader._check_static_config() is False; mock_logger.error.assert_called_once(); assert 'PREFECT_API_URL' in mock_logger.error.call_args.kwargs['error']
class TestStaticConfigEmptyOkSetButEmpty:
    def _configure_production(self, mock_settings, monkeypatch) -> None: monkeypatch.delenv('PREFECT_API_URL', raising=False); monkeypatch.delenv('S3_PUBLIC_ENDPOINT', raising=False); [setattr(mock_settings, field, value) for field, value in _GUARD_STRONG_VALUES.items()]; mock_settings.environment = 'production'; mock_settings.next_public_app_url = 'https://report.zitian.party'; mock_settings.prefect_api_url = 'http://prefect:4200/api'; mock_settings.s3_public_endpoint = 'https://s3.zitian.party'; mock_settings.s3_public_bucket = None; monkeypatch.setenv('S3_PUBLIC_BUCKET', '')
    def test_static_config_accepts_production_with_empty_s3_public_bucket(self, mock_settings, mock_logger, monkeypatch): self._configure_production(mock_settings, monkeypatch); assert Bootloader._check_static_config() is True; mock_logger.error.assert_not_called()
    def test_static_config_rejects_production_without_prefect_api_url_when_s3_public_bucket_is_empty(self, mock_settings, mock_logger, monkeypatch): self._configure_production(mock_settings, monkeypatch); mock_settings.prefect_api_url = None; assert Bootloader._check_static_config() is False; mock_logger.error.assert_called_once(); error_text = mock_logger.error.call_args.kwargs['error']; assert 'PREFECT_API_URL' in error_text; assert 'S3_PUBLIC_BUCKET' not in error_text
def test_AC_runtime_3_1_required_checks_cover_the_tier_declaration():
    'AC-runtime.3.1'; from src.runtime import DEPENDENCY_MANIFEST, EnvTier
    for tier in EnvTier: probed, unprobed = Bootloader._required_checks(tier); assert set(probed) | set(unprobed) == DEPENDENCY_MANIFEST.required_for(tier); assert not set(probed) & set(unprobed)
class TestManifestDrivenValidate:
    'AC-runtime.3.1'
    def test_github_ci_tier_has_no_unprobed_requirements(self): from src.runtime import EnvTier; probed, unprobed = Bootloader._required_checks(EnvTier.GITHUB_CI); assert set(probed) == {'database', 'object_storage'}; assert unprobed == []; from src.runtime import DEPENDENCY_MANIFEST, EnvTier; _m1_probed, _m1_unprobed = Bootloader._required_checks(EnvTier.PRODUCTION); assert set(_m1_probed) == DEPENDENCY_MANIFEST.required_for(EnvTier.PRODUCTION); assert _m1_unprobed == []
    async def test_full_mode_probes_the_manifest_set_for_the_tier(self, mock_settings, mock_db_check, mock_minio_check, mock_openrouter_check): from src.runtime import EnvTier; mock_db_check.return_value = ServiceStatus('database', 'ok', 'OK'); mock_minio_check.return_value = ServiceStatus('minio', 'ok', 'OK'); mock_openrouter_check.return_value = ServiceStatus('ai_provider', 'ok', 'OK'); result = await Bootloader.validate(BootMode.FULL, tier=EnvTier.GITHUB_CI); assert result is True; mock_db_check.assert_called_once(); mock_minio_check.assert_called_once(); mock_openrouter_check.assert_not_called()
    async def test_full_mode_probes_all_eight_deps_on_production(self, mock_settings, mock_db_check, mock_minio_check, mock_openrouter_check):
        'AC-runtime.4.1'; from src.runtime import EnvTier; mock_db_check.return_value = ServiceStatus('database', 'ok', 'OK'); mock_minio_check.return_value = ServiceStatus('minio', 'ok', 'OK'); mock_openrouter_check.return_value = ServiceStatus('ai_provider', 'ok', 'OK'); extra = {}
        with patch.object(Bootloader, '_check_cache', new_callable=AsyncMock) as extra['cache'], patch.object(Bootloader, '_check_workflow_engine', new_callable=AsyncMock) as extra['workflow_engine'], patch.object(Bootloader, '_check_telemetry', new_callable=AsyncMock) as extra['telemetry'], patch.object(Bootloader, '_check_analytics', new_callable=AsyncMock) as extra['analytics'], patch.object(Bootloader, '_check_market_data', new_callable=AsyncMock) as extra['market_data']:
            for (name, mock) in extra.items(): mock.return_value = ServiceStatus(name, 'ok', 'OK')
            result = await Bootloader.validate(BootMode.FULL, tier=EnvTier.PRODUCTION)
        assert result is True; [(mock.assert_called_once(), name) for name, mock in extra.items()]
    async def test_full_mode_absent_new_probe_fails_validate(self, mock_settings, mock_db_check, mock_minio_check, mock_openrouter_check):
        from src.runtime import EnvTier; mock_db_check.return_value = ServiceStatus('database', 'ok', 'OK'); mock_minio_check.return_value = ServiceStatus('minio', 'ok', 'OK'); mock_openrouter_check.return_value = ServiceStatus('ai_provider', 'ok', 'OK')
        with patch.object(Bootloader, '_check_cache', new_callable=AsyncMock) as mock_cache, patch.object(Bootloader, '_check_workflow_engine', new_callable=AsyncMock) as m_wf, patch.object(Bootloader, '_check_telemetry', new_callable=AsyncMock) as m_tel, patch.object(Bootloader, '_check_analytics', new_callable=AsyncMock) as m_an, patch.object(Bootloader, '_check_market_data', new_callable=AsyncMock) as m_md:
            mock_cache.return_value = ServiceStatus('cache', 'error', 'Connection refused')
            for (name, m) in {'workflow_engine': m_wf, 'telemetry': m_tel, 'analytics': m_an, 'market_data': m_md}.items(): m.return_value = ServiceStatus(name, 'ok', 'OK')
            result = await Bootloader.validate(BootMode.FULL, tier=EnvTier.PRODUCTION)
        assert result is False
    async def test_full_mode_absent_required_dep_fails(self, mock_settings, mock_db_check, mock_logger):
        from src.runtime import EnvTier; mock_db_check.return_value = ServiceStatus('database', 'error', 'Connection refused')
        with patch.object(Bootloader, '_check_s3', new_callable=AsyncMock) as mock_s3, patch.object(Bootloader, '_check_openrouter', new_callable=AsyncMock) as mock_openrouter: mock_s3.return_value = ServiceStatus('minio', 'ok', 'OK'); mock_openrouter.return_value = ServiceStatus('ai_provider', 'ok', 'OK'); result = await Bootloader.validate(BootMode.FULL, tier=EnvTier.STAGING)
        assert result is False
