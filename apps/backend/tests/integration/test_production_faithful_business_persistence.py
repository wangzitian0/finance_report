"""Production-faithful backend persistence tests built from Alembic."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.models import Account, AccountType, Direction, User
from src.services.accounting import calculate_account_balance, create_journal_entry, post_journal_entry

pytestmark = [pytest.mark.integration, pytest.mark.no_db, pytest.mark.asyncio]

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _database_url_with_name(database_name: str) -> str:
    base_url = make_url(
        os.environ.get(
            "DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test",
        )
    )
    return base_url.set(database=database_name).render_as_string(hide_password=False)


def _sync_alembic_url(async_url: str) -> str:
    return async_url.replace("+asyncpg", "")


async def _create_database(database_name: str) -> None:
    admin_url = _database_url_with_name("postgres")
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
            await conn.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        await engine.dispose()


async def _drop_database(database_name: str) -> None:
    admin_url = _database_url_with_name("postgres")
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'))
    finally:
        await engine.dispose()


def _run_alembic_upgrade(database_url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["ENVIRONMENT"] = "testing"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def _user_fk_names(db: AsyncSession, table_name: str) -> list[str]:
    result = await db.execute(
        text(
            """
            SELECT kcu.constraint_name
            FROM information_schema.referential_constraints rc
            JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_catalog = rc.constraint_catalog
             AND kcu.constraint_schema = rc.constraint_schema
             AND kcu.constraint_name = rc.constraint_name
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_catalog = rc.unique_constraint_catalog
             AND ccu.constraint_schema = rc.unique_constraint_schema
             AND ccu.constraint_name = rc.unique_constraint_name
            WHERE kcu.table_schema = 'public'
              AND kcu.table_name = :table_name
              AND kcu.column_name = 'user_id'
              AND ccu.table_schema = 'public'
              AND ccu.table_name = 'users'
              AND ccu.column_name = 'id'
            ORDER BY kcu.constraint_name
            """
        ),
        {"table_name": table_name},
    )
    return list(result.scalars())


async def test_AC8_13_127_alembic_business_persistence_keeps_user_fk_contract() -> None:
    """AC8.13.127: Alembic-built business persistence keeps production user FKs."""
    database_name = f"fr_ac8_13_127_{uuid4().hex[:16]}"
    database_url = _database_url_with_name(database_name)
    engine = None

    await _create_database(database_name)
    try:
        _run_alembic_upgrade(database_url)

        engine = create_async_engine(database_url, poolclass=NullPool)
        session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with session_maker() as db:
            assert await _user_fk_names(db, "accounts")

            detached_user_id = uuid4()
            db.add(
                Account(
                    user_id=detached_user_id,
                    name="Detached owner must fail",
                    type=AccountType.ASSET,
                    currency="SGD",
                )
            )
            with pytest.raises(IntegrityError):
                await db.commit()
            await db.rollback()

            user = User(
                email=f"faithful-{uuid4()}@example.com",
                hashed_password="hashed",
            )
            db.add(user)
            await db.flush()

            cash = Account(user_id=user.id, name="Faithful Cash", type=AccountType.ASSET, currency="SGD")
            income = Account(user_id=user.id, name="Faithful Income", type=AccountType.INCOME, currency="SGD")
            db.add_all([cash, income])
            await db.flush()

            entry = await create_journal_entry(
                db,
                user.id,
                date(2026, 6, 14),
                "Production faithful income",
                [
                    {"account_id": cash.id, "direction": Direction.DEBIT, "amount": Decimal("125.00")},
                    {"account_id": income.id, "direction": Direction.CREDIT, "amount": Decimal("125.00")},
                ],
            )
            await post_journal_entry(db, entry.id, user.id)
            await db.commit()

            assert await calculate_account_balance(db, cash.id, user.id) == Decimal("125.00")
    finally:
        if engine is not None:
            await engine.dispose()
        await _drop_database(database_name)
