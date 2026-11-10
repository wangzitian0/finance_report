import sys; from decimal import Decimal; from types import SimpleNamespace; from unittest.mock import AsyncMock, MagicMock, patch; import pytest; _settings_stub = SimpleNamespace(database_url='postgresql+asyncpg://localhost/test'); _sqla_stub = MagicMock(); _src_config_stub = MagicMock(); _src_config_stub.settings = _settings_stub; _FxRateStub = MagicMock(); _FxRateStub.side_effect = lambda **kwargs: SimpleNamespace(**kwargs); _src_models_stub = MagicMock(); _src_models_market_data_stub = MagicMock(); _src_models_market_data_stub.FxRate = _FxRateStub; _MODULE_STUBS: dict[str, object] = {'sqlalchemy': _sqla_stub, 'sqlalchemy.ext': _sqla_stub, 'sqlalchemy.ext.asyncio': _sqla_stub, 'src': MagicMock(), 'src.config': _src_config_stub, 'src.models': _src_models_stub, 'src.pricing': MagicMock(), 'src.pricing.orm': MagicMock(), 'src.pricing.orm.market_data': _src_models_market_data_stub}
with patch.dict(sys.modules, _MODULE_STUBS): from common.pricing import seed_fx_rates
sys.modules['common.pricing.seed_fx_rates'] = seed_fx_rates; seed_fx_rates.settings = _settings_stub
class TestGetDatabaseUrl:
    def test_local_env_returns_settings_url(self):
        with patch.object(seed_fx_rates.settings, 'database_url', 'postgresql+asyncpg://localhost/test'): result = seed_fx_rates.get_database_url('local')
        assert result == 'postgresql+asyncpg://localhost/test'
    def test_staging_with_env_var_returns_it(self, monkeypatch): monkeypatch.setenv('DATABASE_URL', 'postgresql+asyncpg://staging-host/db'); result = seed_fx_rates.get_database_url('staging'); assert result == 'postgresql+asyncpg://staging-host/db'
    def test_production_with_env_var_returns_it(self, monkeypatch): monkeypatch.setenv('DATABASE_URL', 'postgresql+asyncpg://prod-host/db'); result = seed_fx_rates.get_database_url('production'); assert result == 'postgresql+asyncpg://prod-host/db'
    def test_staging_without_env_var_exits(self, monkeypatch):
        monkeypatch.delenv('DATABASE_URL', raising=False)
        with pytest.raises(SystemExit) as exc: seed_fx_rates.get_database_url('staging')
        assert exc.value.code == 1
    def test_production_without_env_var_exits(self, monkeypatch):
        monkeypatch.delenv('DATABASE_URL', raising=False)
        with pytest.raises(SystemExit) as exc: seed_fx_rates.get_database_url('production')
        assert exc.value.code == 1
class TestSeedFxRates:
    def _make_mock_session(self, existing_rates=None, user_confirms=True): mock_scalars = MagicMock(); mock_scalars.all.return_value = existing_rates or []; mock_result = MagicMock(); mock_result.scalars.return_value = mock_scalars; mock_session = AsyncMock(); mock_session.execute = AsyncMock(return_value=mock_result); mock_session.commit = AsyncMock(); mock_session.add = MagicMock(); mock_session_ctx = AsyncMock(); mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session); mock_session_ctx.__aexit__ = AsyncMock(return_value=False); mock_session_maker = MagicMock(return_value=mock_session_ctx); mock_engine = MagicMock(); mock_engine.dispose = AsyncMock(); return (mock_engine, mock_session_maker, mock_session)
    async def test_seeds_rates_no_existing(self, capsys):
        mock_engine, mock_session_maker, mock_session = self._make_mock_session()
        with patch.object(seed_fx_rates, 'get_database_url', return_value='postgresql+asyncpg://localhost/test'), patch('common.pricing.seed_fx_rates.create_async_engine', return_value=mock_engine), patch('common.pricing.seed_fx_rates.async_sessionmaker', return_value=mock_session_maker): await seed_fx_rates.seed_fx_rates('local')
        assert mock_session.add.call_count == 7; mock_session.commit.assert_awaited_once(); mock_engine.dispose.assert_awaited_once(); captured = capsys.readouterr(); assert 'USD/USD' in captured.out; assert 'Seeded 7 FX rates' in captured.out; capsys.readouterr(); _m1_mock_engine, _m1_mock_session_maker, _m1__ = self._make_mock_session()
        with patch.object(seed_fx_rates, 'get_database_url', return_value='postgresql+asyncpg://user:pass@myhost:5432/db'), patch('common.pricing.seed_fx_rates.create_async_engine', return_value=_m1_mock_engine), patch('common.pricing.seed_fx_rates.async_sessionmaker', return_value=_m1_mock_session_maker): await seed_fx_rates.seed_fx_rates('staging')
        _m1_captured = capsys.readouterr(); assert 'myhost:5432/db' in _m1_captured.out; capsys.readouterr(); _m2_mock_engine, _m2_mock_session_maker, _m2__ = self._make_mock_session()
        with patch.object(seed_fx_rates, 'get_database_url', return_value='sqlite:///test.db'), patch('common.pricing.seed_fx_rates.create_async_engine', return_value=_m2_mock_engine), patch('common.pricing.seed_fx_rates.async_sessionmaker', return_value=_m2_mock_session_maker): await seed_fx_rates.seed_fx_rates('local')
        _m2_captured = capsys.readouterr(); assert 'local' in _m2_captured.out; capsys.readouterr(); _m3_mock_engine, _m3_mock_session_maker, _m3__ = self._make_mock_session()
        with patch.object(seed_fx_rates, 'get_database_url', return_value='postgresql+asyncpg://localhost/test'), patch('common.pricing.seed_fx_rates.create_async_engine', return_value=_m3_mock_engine), patch('common.pricing.seed_fx_rates.async_sessionmaker', return_value=_m3_mock_session_maker): await seed_fx_rates.seed_fx_rates('local')
        _m3_captured = capsys.readouterr(); assert 'Expected FX Calculation' in _m3_captured.out; assert 'Unrealized FX gain: 300 SGD' in _m3_captured.out
    async def test_existing_rates_user_confirms_reseed(self, capsys, monkeypatch):
        mock_rate = MagicMock(); mock_rate.base_currency = 'USD'; mock_rate.quote_currency = 'SGD'; mock_rate.rate = Decimal('1.28'); mock_engine, mock_session_maker, mock_session = self._make_mock_session(existing_rates=[mock_rate]); monkeypatch.setattr('builtins.input', lambda _: 'y')
        with patch.object(seed_fx_rates, 'get_database_url', return_value='postgresql+asyncpg://localhost/test'), patch('common.pricing.seed_fx_rates.create_async_engine', return_value=mock_engine), patch('common.pricing.seed_fx_rates.async_sessionmaker', return_value=mock_session_maker): await seed_fx_rates.seed_fx_rates('local')
        assert mock_session.execute.await_count == 2; mock_session.commit.assert_awaited_once(); captured = capsys.readouterr(); assert 'Found 1 existing rates' in captured.out; assert 'Deleted existing rates' in captured.out
    async def test_existing_rates_user_aborts(self, capsys, monkeypatch):
        mock_rate = MagicMock(); mock_rate.base_currency = 'USD'; mock_rate.quote_currency = 'SGD'; mock_rate.rate = Decimal('1.28'); mock_engine, mock_session_maker, mock_session = self._make_mock_session(existing_rates=[mock_rate]); monkeypatch.setattr('builtins.input', lambda _: 'n')
        with patch.object(seed_fx_rates, 'get_database_url', return_value='postgresql+asyncpg://localhost/test'), patch('common.pricing.seed_fx_rates.create_async_engine', return_value=mock_engine), patch('common.pricing.seed_fx_rates.async_sessionmaker', return_value=mock_session_maker): await seed_fx_rates.seed_fx_rates('local')
        mock_session.commit.assert_not_awaited(); captured = capsys.readouterr(); assert 'Aborted' in captured.out
class TestMain:
    def test_main_success(self, capsys, monkeypatch):
        monkeypatch.setattr('sys.argv', ['common.pricing.seed_fx_rates.py', '--env', 'local'])
        with patch('common.pricing.seed_fx_rates.seed_fx_rates', new=MagicMock(return_value=object())), patch('common.pricing.seed_fx_rates.asyncio.run'): seed_fx_rates.main()
        captured = capsys.readouterr(); assert 'Seeding FX rates for environment: local' in captured.out; assert '✅ FX rates seeded successfully' in captured.out
    def test_main_error_exits_1(self, capsys, monkeypatch):
        monkeypatch.setattr('sys.argv', ['common.pricing.seed_fx_rates.py', '--env', 'local'])
        with patch('common.pricing.seed_fx_rates.seed_fx_rates', new=MagicMock(return_value=object())) as mock_seed, patch('common.pricing.seed_fx_rates.asyncio.run', side_effect=RuntimeError('DB down')): assert seed_fx_rates.main() == 1
        mock_seed.assert_called_once_with('local'); captured = capsys.readouterr(); assert '❌ Error seeding FX rates' in captured.out
    def test_main_default_env_is_local(self, monkeypatch):
        monkeypatch.setattr('sys.argv', ['common.pricing.seed_fx_rates.py'])
        with patch('common.pricing.seed_fx_rates.seed_fx_rates', new=MagicMock(return_value=object())) as mock_seed, patch('common.pricing.seed_fx_rates.asyncio.run') as mock_run: seed_fx_rates.main()
        mock_seed.assert_called_once_with('local'); mock_run.assert_called_once()
    def test_main_staging_env(self, capsys, monkeypatch):
        monkeypatch.setattr('sys.argv', ['common.pricing.seed_fx_rates.py', '--env', 'staging'])
        with patch('common.pricing.seed_fx_rates.seed_fx_rates', new=MagicMock(return_value=object())) as mock_seed, patch('common.pricing.seed_fx_rates.asyncio.run') as mock_run: seed_fx_rates.main()
        mock_seed.assert_called_once_with('staging'); mock_run.assert_called_once(); captured = capsys.readouterr(); assert 'staging' in captured.out
