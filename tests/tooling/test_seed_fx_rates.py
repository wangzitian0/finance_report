"""Tests for tools._lib.market_data.seed_fx_rates.

Pre-migration coverage: `FxRate` and the `market_data` service consolidate into
the `pricing` package's unified observation model (#1610). These tests guard the
shipped code until that cutover, then migrate with it — do not extend them with
new FxRate behavior; new price/valuation work belongs to `pricing`.
"""

import sys
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Inject lightweight stubs for heavy backend dependencies BEFORE importing
# seed_fx_rates, so the test suite works in the CI tooling environment which
# only installs: pytest, pytest-cov, pyyaml, pydantic, pydantic-settings.
# (sqlalchemy and the full src.* package tree are NOT available there.)
#
# We use patch.dict(sys.modules, ...) scoped tightly around the import: the
# imported seed_fx_rates module keeps the stubbed symbols it bound at import
# time, while sys.modules is restored immediately so the stubs never leak
# into other tooling tests collected after this file.
# ---------------------------------------------------------------------------
_settings_stub = SimpleNamespace(database_url="postgresql+asyncpg://localhost/test")
_sqla_stub = MagicMock()
_src_config_stub = MagicMock()
_src_config_stub.settings = _settings_stub
# (select(FxRate).where(FxRate.rate_date == ...) and FxRate(**kwargs))
_FxRateStub = MagicMock()
_FxRateStub.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
_src_models_stub = MagicMock()
_src_models_market_data_stub = MagicMock()
_src_models_market_data_stub.FxRate = _FxRateStub
_MODULE_STUBS: dict[str, object] = {
    "sqlalchemy": _sqla_stub,
    "sqlalchemy.ext": _sqla_stub,
    "sqlalchemy.ext.asyncio": _sqla_stub,
    "src": MagicMock(),
    "src.config": _src_config_stub,
    "src.models": _src_models_stub,
    "src.pricing": MagicMock(),
    "src.pricing.orm": MagicMock(),
    "src.pricing.orm.market_data": _src_models_market_data_stub,
}

# Patch sys.modules only for the duration of the import (seed_fx_rates binds
# the stubbed symbols at import time; all its imports are top-level).
with patch.dict(sys.modules, _MODULE_STUBS):
    from tools._lib.market_data import (
        seed_fx_rates,  # noqa: E402 — must come inside the sys.modules stubs
    )

# patch.dict's exit rollback also drops keys ADDED inside the block — including
# the just-imported module itself. Re-register it so test-time
# patch("tools._lib.market_data.seed_fx_rates....") targets THIS module object
# instead of triggering a fresh import against the real (unstubbed) deps.
sys.modules["tools._lib.market_data.seed_fx_rates"] = seed_fx_rates

seed_fx_rates.settings = _settings_stub


class TestGetDatabaseUrl:
    def test_local_env_returns_settings_url(self):
        """Given env='local', should return settings.database_url."""
        with patch.object(
            seed_fx_rates.settings,
            "database_url",
            "postgresql+asyncpg://localhost/test",
        ):
            result = seed_fx_rates.get_database_url("local")
        assert result == "postgresql+asyncpg://localhost/test"

    def test_staging_with_env_var_returns_it(self, monkeypatch):
        """Given env='staging' and DATABASE_URL set, should return that URL."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://staging-host/db")
        result = seed_fx_rates.get_database_url("staging")
        assert result == "postgresql+asyncpg://staging-host/db"

    def test_production_with_env_var_returns_it(self, monkeypatch):
        """Given env='production' and DATABASE_URL set, should return that URL."""
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://prod-host/db")
        result = seed_fx_rates.get_database_url("production")
        assert result == "postgresql+asyncpg://prod-host/db"

    def test_staging_without_env_var_exits(self, monkeypatch):
        """Given env='staging' and no DATABASE_URL, should sys.exit(1)."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SystemExit) as exc:
            seed_fx_rates.get_database_url("staging")
        assert exc.value.code == 1

    def test_production_without_env_var_exits(self, monkeypatch):
        """Given env='production' and no DATABASE_URL, should sys.exit(1)."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SystemExit) as exc:
            seed_fx_rates.get_database_url("production")
        assert exc.value.code == 1


class TestSeedFxRates:
    def _make_mock_session(self, existing_rates=None, user_confirms=True):
        """Build a mock async session with configurable existing rates and user input."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = existing_rates or []

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()

        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session_maker = MagicMock(return_value=mock_session_ctx)

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()

        return mock_engine, mock_session_maker, mock_session

    @pytest.mark.asyncio
    async def test_seeds_rates_no_existing(self, capsys):
        """Given no existing rates, should add all rates and commit."""
        mock_engine, mock_session_maker, mock_session = self._make_mock_session()

        with (
            patch.object(
                seed_fx_rates,
                "get_database_url",
                return_value="postgresql+asyncpg://localhost/test",
            ),
            patch(
                "tools._lib.market_data.seed_fx_rates.create_async_engine",
                return_value=mock_engine,
            ),
            patch(
                "tools._lib.market_data.seed_fx_rates.async_sessionmaker",
                return_value=mock_session_maker,
            ),
        ):
            await seed_fx_rates.seed_fx_rates("local")

        assert mock_session.add.call_count == 7
        mock_session.commit.assert_awaited_once()
        mock_engine.dispose.assert_awaited_once()

        captured = capsys.readouterr()
        assert "USD/USD" in captured.out
        assert "Seeded 7 FX rates" in captured.out

    @pytest.mark.asyncio
    async def test_existing_rates_user_confirms_reseed(self, capsys, monkeypatch):
        """Given existing rates and user confirms 'y', should delete and reseed."""
        mock_rate = MagicMock()
        mock_rate.base_currency = "USD"
        mock_rate.quote_currency = "SGD"
        mock_rate.rate = Decimal("1.28")

        mock_engine, mock_session_maker, mock_session = self._make_mock_session(
            existing_rates=[mock_rate]
        )

        monkeypatch.setattr("builtins.input", lambda _: "y")

        with (
            patch.object(
                seed_fx_rates,
                "get_database_url",
                return_value="postgresql+asyncpg://localhost/test",
            ),
            patch(
                "tools._lib.market_data.seed_fx_rates.create_async_engine",
                return_value=mock_engine,
            ),
            patch(
                "tools._lib.market_data.seed_fx_rates.async_sessionmaker",
                return_value=mock_session_maker,
            ),
        ):
            await seed_fx_rates.seed_fx_rates("local")

        assert mock_session.execute.await_count == 2
        mock_session.commit.assert_awaited_once()

        captured = capsys.readouterr()
        assert "Found 1 existing rates" in captured.out
        assert "Deleted existing rates" in captured.out

    @pytest.mark.asyncio
    async def test_existing_rates_user_aborts(self, capsys, monkeypatch):
        """Given existing rates and user declines, should abort without seeding."""
        mock_rate = MagicMock()
        mock_rate.base_currency = "USD"
        mock_rate.quote_currency = "SGD"
        mock_rate.rate = Decimal("1.28")

        mock_engine, mock_session_maker, mock_session = self._make_mock_session(
            existing_rates=[mock_rate]
        )

        monkeypatch.setattr("builtins.input", lambda _: "n")

        with (
            patch.object(
                seed_fx_rates,
                "get_database_url",
                return_value="postgresql+asyncpg://localhost/test",
            ),
            patch(
                "tools._lib.market_data.seed_fx_rates.create_async_engine",
                return_value=mock_engine,
            ),
            patch(
                "tools._lib.market_data.seed_fx_rates.async_sessionmaker",
                return_value=mock_session_maker,
            ),
        ):
            await seed_fx_rates.seed_fx_rates("local")

        mock_session.commit.assert_not_awaited()

        captured = capsys.readouterr()
        assert "Aborted" in captured.out

    @pytest.mark.asyncio
    async def test_database_url_with_at_sign_masks_host(self, capsys):
        """Given a DB URL with @, should print only the host portion."""
        mock_engine, mock_session_maker, _ = self._make_mock_session()

        with (
            patch.object(
                seed_fx_rates,
                "get_database_url",
                return_value="postgresql+asyncpg://user:pass@myhost:5432/db",
            ),
            patch(
                "tools._lib.market_data.seed_fx_rates.create_async_engine",
                return_value=mock_engine,
            ),
            patch(
                "tools._lib.market_data.seed_fx_rates.async_sessionmaker",
                return_value=mock_session_maker,
            ),
        ):
            await seed_fx_rates.seed_fx_rates("staging")

        captured = capsys.readouterr()
        assert "myhost:5432/db" in captured.out

    @pytest.mark.asyncio
    async def test_database_url_without_at_sign(self, capsys):
        """Given a DB URL without @, should print 'local'."""
        mock_engine, mock_session_maker, _ = self._make_mock_session()

        with (
            patch.object(
                seed_fx_rates, "get_database_url", return_value="sqlite:///test.db"
            ),
            patch(
                "tools._lib.market_data.seed_fx_rates.create_async_engine",
                return_value=mock_engine,
            ),
            patch(
                "tools._lib.market_data.seed_fx_rates.async_sessionmaker",
                return_value=mock_session_maker,
            ),
        ):
            await seed_fx_rates.seed_fx_rates("local")

        captured = capsys.readouterr()
        assert "local" in captured.out

    @pytest.mark.asyncio
    async def test_prints_expected_fx_calculation(self, capsys):
        """Given successful seeding, should print expected FX calculation summary."""
        mock_engine, mock_session_maker, _ = self._make_mock_session()

        with (
            patch.object(
                seed_fx_rates,
                "get_database_url",
                return_value="postgresql+asyncpg://localhost/test",
            ),
            patch(
                "tools._lib.market_data.seed_fx_rates.create_async_engine",
                return_value=mock_engine,
            ),
            patch(
                "tools._lib.market_data.seed_fx_rates.async_sessionmaker",
                return_value=mock_session_maker,
            ),
        ):
            await seed_fx_rates.seed_fx_rates("local")

        captured = capsys.readouterr()
        assert "Expected FX Calculation" in captured.out
        assert "Unrealized FX gain: 300 SGD" in captured.out


class TestMain:
    def test_main_success(self, capsys, monkeypatch):
        """Given successful seeding, should print success message."""
        monkeypatch.setattr(
            "sys.argv", ["tools._lib.market_data.seed_fx_rates.py", "--env", "local"]
        )

        with patch(
            "tools._lib.market_data.seed_fx_rates.seed_fx_rates",
            new=MagicMock(return_value=object()),
        ):
            with patch("tools._lib.market_data.seed_fx_rates.asyncio.run"):
                seed_fx_rates.main()

        captured = capsys.readouterr()
        assert "Seeding FX rates for environment: local" in captured.out
        assert "✅ FX rates seeded successfully" in captured.out

    def test_main_error_exits_1(self, capsys, monkeypatch):
        """Given seed_fx_rates raises, should print error and sys.exit(1)."""
        monkeypatch.setattr(
            "sys.argv", ["tools._lib.market_data.seed_fx_rates.py", "--env", "local"]
        )

        with (
            patch(
                "tools._lib.market_data.seed_fx_rates.seed_fx_rates",
                new=MagicMock(return_value=object()),
            ) as mock_seed,
            patch(
                "tools._lib.market_data.seed_fx_rates.asyncio.run",
                side_effect=RuntimeError("DB down"),
            ),
        ):
            assert seed_fx_rates.main() == 1

        mock_seed.assert_called_once_with("local")
        captured = capsys.readouterr()
        assert "❌ Error seeding FX rates" in captured.out

    def test_main_default_env_is_local(self, monkeypatch):
        """Given no --env flag, should default to 'local'."""
        monkeypatch.setattr("sys.argv", ["tools._lib.market_data.seed_fx_rates.py"])
        with (
            patch(
                "tools._lib.market_data.seed_fx_rates.seed_fx_rates",
                new=MagicMock(return_value=object()),
            ) as mock_seed,
            patch("tools._lib.market_data.seed_fx_rates.asyncio.run") as mock_run,
        ):
            seed_fx_rates.main()
        mock_seed.assert_called_once_with("local")
        mock_run.assert_called_once()

    def test_main_staging_env(self, capsys, monkeypatch):
        """Given --env staging, should pass 'staging' to seed_fx_rates."""
        monkeypatch.setattr(
            "sys.argv", ["tools._lib.market_data.seed_fx_rates.py", "--env", "staging"]
        )

        with (
            patch(
                "tools._lib.market_data.seed_fx_rates.seed_fx_rates",
                new=MagicMock(return_value=object()),
            ) as mock_seed,
            patch("tools._lib.market_data.seed_fx_rates.asyncio.run") as mock_run,
        ):
            seed_fx_rates.main()

        mock_seed.assert_called_once_with("staging")
        mock_run.assert_called_once()
        captured = capsys.readouterr()
        assert "staging" in captured.out
