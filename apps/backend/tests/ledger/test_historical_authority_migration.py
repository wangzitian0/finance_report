"""Historical-data migration proof for decision-anchored ledger authority."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [pytest.mark.integration, pytest.mark.no_db, pytest.mark.asyncio]

BACKEND_DIR = Path(__file__).resolve().parents[2]
LEGACY_HEAD = "0055_reviewed_stmt_envelope"


def _database_url(database_name: str) -> str:
    base_url = make_url(
        os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test",
        )
    )
    return base_url.set(database=database_name).render_as_string(hide_password=False)


async def _create_database(database_name: str) -> None:
    engine = create_async_engine(_database_url("postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        await engine.dispose()


async def _drop_database(database_name: str) -> None:
    engine = create_async_engine(_database_url("postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
    finally:
        await engine.dispose()


def _upgrade(database_url: str, revision: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment["ENVIRONMENT"] = "testing"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=BACKEND_DIR,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def _insert_posted_legacy_entry(engine: AsyncEngine) -> UUID:
    user_id = uuid4()
    debit_account_id = uuid4()
    credit_account_id = uuid4()
    entry_id = uuid4()
    debit_line_id = uuid4()
    credit_line_id = uuid4()

    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                INSERT INTO users (id, email, hashed_password, ai_settings, created_at, updated_at)
                VALUES (:id, :email, 'generated-hash', CAST('{}' AS jsonb), NOW(), NOW())
                """
            ),
            {"id": user_id, "email": f"legacy-{user_id.hex}@example.test"},
        )
        for account_id, account_name, account_type in (
            (debit_account_id, "Generated legacy asset", "ASSET"),
            (credit_account_id, "Generated legacy income", "INCOME"),
        ):
            await connection.execute(
                text(
                    """
                    INSERT INTO accounts (
                        id, user_id, name, type, currency, is_active, is_system, created_at, updated_at
                    )
                    VALUES (
                        :id, :user_id, :name, CAST(:account_type AS account_type_enum),
                        'SGD', true, false, NOW(), NOW()
                    )
                    """
                ),
                {
                    "id": account_id,
                    "user_id": user_id,
                    "name": account_name,
                    "account_type": account_type,
                },
            )
        await connection.execute(
            text(
                """
                INSERT INTO journal_entries (
                    id, user_id, entry_date, memo, source_type, status, created_at, updated_at
                )
                VALUES (
                    :id, :user_id, DATE '2026-07-18', 'Generated posted legacy entry',
                    CAST('manual' AS journal_source_type_enum),
                    CAST('posted' AS journal_entry_status_enum), NOW(), NOW()
                )
                """
            ),
            {"id": entry_id, "user_id": user_id},
        )
        for line_id, account_id, direction in (
            (debit_line_id, debit_account_id, "DEBIT"),
            (credit_line_id, credit_account_id, "CREDIT"),
        ):
            await connection.execute(
                text(
                    """
                    INSERT INTO journal_lines (
                        id, journal_entry_id, account_id, direction, amount, currency, created_at, updated_at
                    )
                    VALUES (
                        :id, :entry_id, :account_id,
                        CAST(:direction AS journal_line_direction_enum),
                        1.00, 'SGD', NOW(), NOW()
                    )
                    """
                ),
                {
                    "id": line_id,
                    "entry_id": entry_id,
                    "account_id": account_id,
                    "direction": direction,
                },
            )
    return entry_id


async def test_AC_ledger_79_8_posted_legacy_entry_upgrades_without_mutation() -> None:
    """AC-ledger.79.8: historical posted rows upgrade without weakening immutability."""
    database_name = f"fr_ac_ledger_79_8_{uuid4().hex[:16]}"
    database_url = _database_url(database_name)
    engine: AsyncEngine | None = None

    await _create_database(database_name)
    try:
        _upgrade(database_url, LEGACY_HEAD)
        engine = create_async_engine(database_url, poolclass=NullPool)
        entry_id = await _insert_posted_legacy_entry(engine)
        await engine.dispose()
        engine = None

        _upgrade(database_url, "head")

        engine = create_async_engine(database_url, poolclass=NullPool)
        async with engine.connect() as connection:
            entry = (
                await connection.execute(
                    text(
                        """
                        SELECT status::text, decision_authority_state::text, decision_anchor_id
                        FROM journal_entries
                        WHERE id = :entry_id
                        """
                    ),
                    {"entry_id": entry_id},
                )
            ).one()
            server_default = await connection.scalar(
                text(
                    """
                    SELECT column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'journal_entries'
                      AND column_name = 'decision_authority_state'
                    """
                )
            )

            assert entry == ("posted", "legacy_unproven", None)
            assert server_default is None

        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                with pytest.raises(IntegrityError, match="cannot directly update immutable journal entry"):
                    await connection.execute(
                        text("UPDATE journal_entries SET memo = 'mutation denied' WHERE id = :entry_id"),
                        {"entry_id": entry_id},
                    )
            finally:
                await transaction.rollback()
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(database_name)
