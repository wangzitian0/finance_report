"""Tests for scripts/seed_fx_rates.py"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import seed_fx_rates


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
            patch("seed_fx_rates.create_async_engine", return_value=mock_engine),
            patch("seed_fx_rates.async_sessionmaker", return_value=mock_session_maker),
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
            patch("seed_fx_rates.create_async_engine", return_value=mock_engine),
            patch("seed_fx_rates.async_sessionmaker", return_value=mock_session_maker),
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
            patch("seed_fx_rates.create_async_engine", return_value=mock_engine),
            patch("seed_fx_rates.async_sessionmaker", return_value=mock_session_maker),
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
            patch("seed_fx_rates.create_async_engine", return_value=mock_engine),
            patch("seed_fx_rates.async_sessionmaker", return_value=mock_session_maker),
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
            patch("seed_fx_rates.create_async_engine", return_value=mock_engine),
            patch("seed_fx_rates.async_sessionmaker", return_value=mock_session_maker),
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
            patch("seed_fx_rates.create_async_engine", return_value=mock_engine),
            patch("seed_fx_rates.async_sessionmaker", return_value=mock_session_maker),
        ):
            await seed_fx_rates.seed_fx_rates("local")

        captured = capsys.readouterr()
        assert "Expected FX Calculation" in captured.out
        assert "Unrealized FX gain: 300 SGD" in captured.out


class TestMain:
    def test_main_success(self, capsys, monkeypatch):
        """Given successful seeding, should print success message."""
        monkeypatch.setattr("sys.argv", ["seed_fx_rates.py", "--env", "local"])

        with patch(
            "seed_fx_rates.seed_fx_rates", new_callable=lambda: lambda: AsyncMock()
        ):
            mock_coro = AsyncMock()
            with (
                patch("seed_fx_rates.seed_fx_rates", return_value=mock_coro()),
                patch("seed_fx_rates.asyncio.run") as mock_run,
            ):
                seed_fx_rates.main()

        captured = capsys.readouterr()
        assert "Seeding FX rates for environment: local" in captured.out
        assert "✅ FX rates seeded successfully" in captured.out

    def test_main_error_exits_1(self, capsys, monkeypatch):
        """Given seed_fx_rates raises, should print error and sys.exit(1)."""
        monkeypatch.setattr("sys.argv", ["seed_fx_rates.py", "--env", "local"])

        with patch("seed_fx_rates.asyncio.run", side_effect=RuntimeError("DB down")):
            with pytest.raises(SystemExit) as exc:
                seed_fx_rates.main()

        assert exc.value.code == 1
        captured = capsys.readouterr()
        assert "❌ Error seeding FX rates" in captured.out

    def test_main_default_env_is_local(self, monkeypatch):
        """Given no --env flag, should default to 'local'."""
        monkeypatch.setattr("sys.argv", ["seed_fx_rates.py"])

        calls = []
        with patch("seed_fx_rates.asyncio.run") as mock_run:
            mock_run.side_effect = lambda coro: calls.append(coro) or coro.close()
            seed_fx_rates.main()

        # The argument to asyncio.run should be seed_fx_rates("local")

    def test_main_staging_env(self, capsys, monkeypatch):
        """Given --env staging, should pass 'staging' to seed_fx_rates."""
        monkeypatch.setattr("sys.argv", ["seed_fx_rates.py", "--env", "staging"])

        with patch("seed_fx_rates.asyncio.run") as mock_run:
            seed_fx_rates.main()

        captured = capsys.readouterr()
        assert "staging" in captured.out
