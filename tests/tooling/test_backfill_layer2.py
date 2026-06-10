"""Tests for tools._lib.migrations.backfill_layer2 (EPIC-011 Stage 2a CLI).

The CLI module defers all backend imports into its functions, so importing it
here is side-effect-free and needs no module-level stubbing. Each test that
triggers a lazy ``src.*`` / ``sqlalchemy`` import provides those stubs through a
``patch.dict(sys.modules, ...)`` scoped to that test, so nothing leaks into the
rest of the tooling test session.
"""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools._lib.migrations import backfill_layer2


class TestGetDatabaseUrl:
    def test_local_env_returns_settings_url(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        stub_config = SimpleNamespace(
            settings=SimpleNamespace(database_url="postgresql+asyncpg://localhost/test")
        )
        with patch.dict(sys.modules, {"src": MagicMock(), "src.config": stub_config}):
            assert (
                backfill_layer2.get_database_url("local")
                == "postgresql+asyncpg://localhost/test"
            )

    def test_local_env_prefers_database_url_env(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://other/db")
        stub_config = SimpleNamespace(
            settings=SimpleNamespace(database_url="postgresql+asyncpg://localhost/test")
        )
        with patch.dict(sys.modules, {"src": MagicMock(), "src.config": stub_config}):
            assert (
                backfill_layer2.get_database_url("local")
                == "postgresql+asyncpg://other/db"
            )

    def test_staging_with_env_var_returns_it(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://staging-host/db")
        assert (
            backfill_layer2.get_database_url("staging")
            == "postgresql+asyncpg://staging-host/db"
        )

    def test_production_without_env_var_exits(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(SystemExit):
            backfill_layer2.get_database_url("production")


def _make_engine_and_maker():
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_session_maker = MagicMock(return_value=mock_session_ctx)

    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()
    return mock_engine, mock_session_maker, mock_session


class TestRun:
    @pytest.mark.asyncio
    async def test_run_invokes_backfill_commits_and_disposes(self, capsys, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://staging-host/db")
        mock_engine, mock_session_maker, mock_session = _make_engine_and_maker()
        counts = {
            "statements_scanned": 3,
            "documents_created": 2,
            "atomic_transactions_upserted": 5,
        }
        mock_backfill = AsyncMock(return_value=counts)

        sqla_async = SimpleNamespace(
            create_async_engine=MagicMock(return_value=mock_engine),
            async_sessionmaker=MagicMock(return_value=mock_session_maker),
        )
        dedup_mod = SimpleNamespace(
            backfill_atomic_transactions_from_statements=mock_backfill
        )
        stubs = {
            "sqlalchemy": MagicMock(),
            "sqlalchemy.ext": MagicMock(),
            "sqlalchemy.ext.asyncio": sqla_async,
            "src": MagicMock(),
            "src.services": MagicMock(),
            "src.services.deduplication": dedup_mod,
        }

        with patch.dict(sys.modules, stubs):
            rc = await backfill_layer2.run("staging", None)

        assert rc == 0
        mock_backfill.assert_awaited_once()
        mock_session.commit.assert_awaited_once()
        mock_engine.dispose.assert_awaited_once()
        out = capsys.readouterr().out
        assert "statements_scanned=3" in out
        assert "documents_created=2" in out
        assert "atomic_transactions_upserted=5" in out


class TestMain:
    def test_main_default_env_local_no_user(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["backfill_layer2.py"])
        mock_run = MagicMock(return_value=object())
        with (
            patch.object(backfill_layer2, "run", mock_run),
            patch.object(
                backfill_layer2.asyncio, "run", return_value=0
            ) as mock_async_run,
        ):
            assert backfill_layer2.main() == 0
        mock_async_run.assert_called_once()
        assert mock_run.call_args.args == ("local", None)

    def test_main_passes_env_and_user_id(self, monkeypatch):
        from uuid import UUID

        uid = "11111111-1111-1111-1111-111111111111"
        monkeypatch.setattr(
            "sys.argv", ["backfill_layer2.py", "--env", "staging", "--user-id", uid]
        )

        sentinel = object()
        mock_run = MagicMock(return_value=sentinel)
        with (
            patch.object(backfill_layer2, "run", mock_run),
            patch.object(
                backfill_layer2.asyncio, "run", return_value=0
            ) as mock_async_run,
        ):
            assert backfill_layer2.main() == 0

        args, _ = mock_run.call_args
        assert args[0] == "staging"
        assert args[1] == UUID(uid)
        mock_async_run.assert_called_once_with(sentinel)
