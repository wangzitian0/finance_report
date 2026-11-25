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
from src.identity import User
from src.ledger import Account, AccountType, Direction, calculate_account_balance, post_journal_entry
from tests.ledger._ledger_helpers import create_anchored_test_journal_entry as create_journal_entry

pytestmark = [pytest.mark.integration, pytest.mark.no_db, pytest.mark.asyncio]
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _db_url(name: str) -> str:
    return (
        make_url(
            os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test")
        )
        .set(database=name)
        .render_as_string(hide_password=False)
    )


async def _admin_exec(*stmts: str) -> None:
    engine = create_async_engine(_db_url("postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            for s in stmts:
                await conn.execute(text(s))
    finally:
        await engine.dispose()


async def test_alembic_business_persistence_keeps_user_fk_contract() -> None:
    db_name = f"finance_report_test_ac8_13_127_{uuid4().hex[:16]}"
    db_url = _db_url(db_name)
    engine = None
    await _admin_exec(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)', f'CREATE DATABASE "{db_name}"')
    try:
        env = {**os.environ, "DATABASE_URL": db_url, "ENVIRONMENT": "testing"}
        res = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        assert res.returncode == 0, res.stdout + res.stderr
        engine = create_async_engine(db_url, poolclass=NullPool)
        async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as db:
            fks = (
                (
                    await db.execute(
                        text(
                            "SELECT kcu.constraint_name FROM information_schema.referential_constraints rc JOIN information_schema.key_column_usage kcu USING (constraint_catalog, constraint_schema, constraint_name) JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_catalog=rc.unique_constraint_catalog AND ccu.constraint_schema=rc.unique_constraint_schema AND ccu.constraint_name=rc.unique_constraint_name WHERE kcu.table_schema='public' AND kcu.table_name='accounts' AND kcu.column_name='user_id' AND ccu.table_schema='public' AND ccu.table_name='users' AND ccu.column_name='id'"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert fks
            detached_user_id = uuid4()
            db.add(
                Account(
                    user_id=detached_user_id, name="Detached owner must fail", type=AccountType.ASSET, currency="SGD"
                )
            )
            with pytest.raises(IntegrityError):
                await db.commit()
            await db.rollback()
            user = User(email=f"faithful-{uuid4()}@example.com", hashed_password="hashed")
            db.add(user)
            await db.flush()
            cash, income = (
                Account(user_id=user.id, name="Faithful Cash", type=AccountType.ASSET, currency="SGD"),
                Account(user_id=user.id, name="Faithful Income", type=AccountType.INCOME, currency="SGD"),
            )
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
        await _admin_exec(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
