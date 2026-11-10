'AC-runtime.4.1'; from __future__ import annotations; import ast; from pathlib import Path; from unittest.mock import AsyncMock, MagicMock, patch; import pytest; from infra2_sdk.runtime import health as sdk_health; from infra2_sdk.runtime.health import DependencyStatus; import src.runtime as runtime_package; from src.runtime import AnalyticsCheck, DatabaseCheck, MarketDataCheck, RedisCheck, TelemetryCheck, WorkflowEngineCheck; pytestmark = pytest.mark.no_db
def _http_response(status_code: int) -> MagicMock: resp = MagicMock(); resp.status_code = status_code; return resp
class TestRedisCheck:
    async def test_unconfigured_is_absent(self):
        result = await RedisCheck(url=None).probe(); assert result.status is DependencyStatus.ABSENT; assert result.name == 'cache'; _m1_reader = AsyncMock(); _m1_reader.readline.return_value = b'+PONG\r\n'; _m1_writer = MagicMock(); _m1_writer.drain = AsyncMock(); _m1_writer.wait_closed = AsyncMock()
        with patch('asyncio.open_connection', AsyncMock(return_value=(_m1_reader, _m1_writer))): _m1_result = await RedisCheck(url='redis://cache:6379/0').probe()
        assert _m1_result.status is DependencyStatus.PRESENT
        with patch('asyncio.open_connection', AsyncMock(side_effect=ConnectionRefusedError('refused'))): _m2_result = await RedisCheck(url='redis://cache:6379/0').probe()
        assert _m2_result.status is DependencyStatus.ABSENT
class TestWorkflowEngineCheck:
    async def test_unconfigured_is_absent(self):
        result = await WorkflowEngineCheck(api_url=None).probe(); assert result.status is DependencyStatus.ABSENT; assert result.name == 'workflow_engine'
        with patch('httpx.AsyncClient.get', AsyncMock(return_value=_http_response(200))): _m1_result = await WorkflowEngineCheck(api_url='http://prefect:4200/api').probe()
        assert _m1_result.status is DependencyStatus.PRESENT; import httpx
        with patch('httpx.AsyncClient.get', AsyncMock(side_effect=httpx.ConnectError('down'))): _m2_result = await WorkflowEngineCheck(api_url='http://prefect:4200/api').probe()
        assert _m2_result.status is DependencyStatus.ABSENT
class TestTelemetryCheck:
    async def test_unconfigured_is_absent(self):
        result = await TelemetryCheck(endpoint=None).probe(); assert result.status is DependencyStatus.ABSENT; assert result.name == 'telemetry'; _m1_writer = MagicMock(); _m1_writer.wait_closed = AsyncMock()
        with patch('asyncio.open_connection', AsyncMock(return_value=(AsyncMock(), _m1_writer))): _m1_result = await TelemetryCheck(endpoint='http://otel-collector:4318').probe()
        assert _m1_result.status is DependencyStatus.PRESENT
        with patch('asyncio.open_connection', AsyncMock(side_effect=OSError('no route'))): _m2_result = await TelemetryCheck(endpoint='http://otel-collector:4318').probe()
        assert _m2_result.status is DependencyStatus.ABSENT
class TestAnalyticsCheck:
    async def test_unconfigured_is_absent(self):
        result = await AnalyticsCheck(api_url='').probe(); assert result.status is DependencyStatus.ABSENT; assert result.name == 'analytics'
        with patch('httpx.AsyncClient.get', AsyncMock(return_value=_http_response(404))): _m1_result = await AnalyticsCheck(api_url='https://op.example.com/api').probe()
        assert _m1_result.status is DependencyStatus.PRESENT
        with patch('httpx.AsyncClient.get', AsyncMock(return_value=_http_response(503))): _m2_result = await AnalyticsCheck(api_url='https://op.example.com/api').probe()
        assert _m2_result.status is DependencyStatus.ABSENT
class TestMarketDataCheck:
    async def test_responding_yahoo_is_present(self):
        with patch('httpx.AsyncClient.get', AsyncMock(return_value=_http_response(200))): result = await MarketDataCheck(timeout_seconds=5).probe()
        assert result.status is DependencyStatus.PRESENT; assert result.name == 'market_data'
        with patch('httpx.AsyncClient.get', AsyncMock(return_value=_http_response(429))): _m1_result = await MarketDataCheck(timeout_seconds=5).probe()
        assert _m1_result.status is DependencyStatus.PRESENT
        with patch('httpx.AsyncClient.get', AsyncMock(return_value=_http_response(503))): _m2_result = await MarketDataCheck(timeout_seconds=5).probe()
        assert _m2_result.status is DependencyStatus.ABSENT; import httpx
        with patch('httpx.AsyncClient.get', AsyncMock(side_effect=httpx.ConnectError('down'))): _m3_result = await MarketDataCheck(timeout_seconds=5).probe()
        assert _m3_result.status is DependencyStatus.ABSENT
class TestDatabaseCheck:
    async def test_successful_probe_is_present(self):
        mock_conn = AsyncMock(); mock_conn.execute = AsyncMock(); mock_engine = MagicMock(); mock_engine.connect.return_value.__aenter__.return_value = mock_conn; mock_engine.dispose = AsyncMock()
        with patch('src.runtime.extension.adapters.create_async_engine', return_value=mock_engine): result = await DatabaseCheck('postgresql+asyncpg://postgres:secret123@127.0.0.1:5432/finance').probe()
        assert result.status is DependencyStatus.PRESENT; assert result.name == 'database'; assert result.detail == 'Connection successful'; _m1_secret_dsn = 'postgresql+asyncpg://postgres:super_secret_password@127.0.0.1:5432/finance'; _m1_failure_message = f'connection failed with {_m1_secret_dsn}'
        with patch('src.runtime.extension.adapters.create_async_engine', side_effect=Exception(_m1_failure_message)): _m1_result = await DatabaseCheck(_m1_secret_dsn).probe()
        assert _m1_result.status is DependencyStatus.ABSENT; assert _m1_result.name == 'database'; assert 'super_secret_password' not in _m1_result.detail; assert '<redacted-postgres-dsn>' in _m1_result.detail
def test_AC_runtime_4_1_every_declared_dependency_has_a_probe_adapter():
    'AC-runtime.4.1'; from src.boot import Bootloader; from src.runtime import EnvTier
    for tier in EnvTier: _probed, unprobed = Bootloader._required_checks(tier); assert unprobed == [], f'{tier.value}: unprobed {unprobed}'
    _m1_sdk_owned = {'ProbeResult', 'DependencyStatus', 'DependencyCheck'}; assert _m1_sdk_owned.isdisjoint(runtime_package.__all__); _m1_package_dir = Path(runtime_package.__file__).resolve().parent; _m1_sources = sorted(_m1_package_dir.rglob('*.py')); assert any((_m1_path.name == 'adapters.py' for _m1_path in _m1_sources)), 'the scan must reach the adapters'; _m1_redefined = [f'{_m1_path.relative_to(_m1_package_dir).as_posix()}:{_m1_node.lineno}: class {_m1_node.name}' for _m1_path in _m1_sources for _m1_node in ast.walk(ast.parse(_m1_path.read_text(encoding='utf-8'))) if isinstance(_m1_node, ast.ClassDef) and _m1_node.name in _m1_sdk_owned]; assert _m1_redefined == [], f'the SDK owns these types: {_m1_redefined}'
async def test_adapters_return_the_sdk_probe_result_type(): result = await RedisCheck(url=None).probe(); assert isinstance(result, sdk_health.ProbeResult); assert result.status is sdk_health.DependencyStatus.ABSENT
@pytest.mark.parametrize(('make_check', 'name', 'patch_target'), [(lambda: WorkflowEngineCheck(api_url='http://prefect:4200/api'), 'workflow_engine', 'src.runtime.extension.adapters.probe_orchestrator'), (lambda: AnalyticsCheck(api_url='https://op.example.com/api'), 'analytics', 'src.runtime.extension.adapters.probe_http'), (lambda: MarketDataCheck(timeout_seconds=5), 'market_data', 'src.runtime.extension.adapters.probe_http')])
async def test_http_adapters_return_the_sdk_probe_result_unchanged(make_check, name, patch_target):
    sdk_result = sdk_health.ProbeResult(name, sdk_health.DependencyStatus.PRESENT, 'HTTP 200', 1.5)
    with patch(patch_target, AsyncMock(return_value=sdk_result)) as probe_fn: result = await make_check().probe()
    assert result is sdk_result; assert probe_fn.await_args.kwargs['name'] == name
