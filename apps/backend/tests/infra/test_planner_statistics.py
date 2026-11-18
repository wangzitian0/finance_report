from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.extraction.orm.bank_custody_binding import BankCustodyBinding
from src.identity import User
from src.reporting import generate_cash_flow
from tests._support.test_isolation import get_test_db_name, sanitize_namespace
from tests.factories import seed_year_of_journal_entries

YEAR_TABLES = ("accounts", "journal_entries", "journal_lines")
BACKEND_DIR = Path(__file__).resolve().parents[2]
PROBE_TABLES = ("planner_probe_plain", "planner_probe_ctas", "planner_probe_into", "planner_probe_replica")


async def _autovacuum_options(session: AsyncSession) -> dict[str, str]:
    return dict((await session.execute(text("SELECT c.relname, coalesce(array_to_string(c.reloptions, ','), '') FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r'"))).all())


def _autovacuum_enabled(options: dict[str, str]) -> list[str]:
    return sorted(n for n, v in options.items() if "autovacuum_enabled=false" not in v)


async def test_AC_testing_backend_test_planner_1_worker_tables_have_autovacuum_disabled(db: AsyncSession) -> None:
    options = await _autovacuum_options(db)
    assert set(YEAR_TABLES) <= set(options) and _autovacuum_enabled(options) == [], _autovacuum_enabled(options)


async def test_AC_testing_backend_test_planner_3_a_recreated_table_has_autovacuum_disabled(db: AsyncSession) -> None:
    table = BankCustodyBinding.__table__
    await db.run_sync(lambda s: table.drop(s.connection()))
    await db.run_sync(lambda s: table.create(s.connection()))
    for ddl in ("CREATE TABLE planner_probe_plain (id integer)", "CREATE TABLE planner_probe_ctas AS SELECT 1 AS id", "SELECT 1 AS id INTO planner_probe_into", "SET LOCAL session_replication_role = replica", "CREATE TABLE planner_probe_replica (id integer)"):
        await db.execute(text(ddl))
    await db.commit()
    try:
        options = await _autovacuum_options(db)
        assert {table.name, *PROBE_TABLES} <= set(options) and _autovacuum_enabled(options) == [], options
    finally:
        for name in PROBE_TABLES:
            await db.execute(text(f"DROP TABLE IF EXISTS {name}"))
        await db.commit()


async def _drop_database(worker_url: URL, database: str) -> None:
    admin = create_async_engine(worker_url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            await conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    finally:
        await admin.dispose()


async def test_AC_testing_backend_test_planner_4_the_guard_passes_in_the_session_after_a_table_was_recreated(test_database_url: str) -> None:
    ns = f"planner_seq_{uuid4().hex[:8]}"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("COV_CORE_", "PYTEST_XDIST_", "PYTEST_ADDOPTS")) and k != "COVERAGE_PROCESS_START"}
    env.update(TEST_NAMESPACE=ns, DATABASE_URL=test_database_url, ENVIRONMENT="testing")
    here = Path(__file__).resolve().relative_to(BACKEND_DIR)
    cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-o", "addopts=", "-q", f"{here}::test_AC_testing_backend_test_planner_3_a_recreated_table_has_autovacuum_disabled", f"{here}::test_AC_testing_backend_test_planner_1_worker_tables_have_autovacuum_disabled"]
    try:
        res = subprocess.run(cmd, cwd=BACKEND_DIR, env=env, check=False, capture_output=True, text=True, timeout=40)
    except subprocess.TimeoutExpired as timeout:
        pytest.fail(f"the pytest session did not end in 40 s: {timeout.stdout!r}")
    finally:
        await _drop_database(make_url(test_database_url), get_test_db_name(sanitize_namespace(ns)))
    assert res.returncode == 0 and re.search(r"\b2 passed\b", res.stdout), (res.stdout + res.stderr)[-3000:]


async def _seed_year(session: AsyncSession) -> User:
    user = User(id=uuid4(), email=f"planner-{uuid4()}@example.com", hashed_password="hashed")
    session.add(user)
    await session.commit()
    await seed_year_of_journal_entries(session, user.id, first_day=date(2026, 1, 1), entry_count=1000)
    return user


async def test_AC_testing_backend_test_planner_2_a_year_load_keeps_true_size_estimates_and_a_fast_cash_flow(test_database_url: str) -> None:
    worker_url = make_url(test_database_url)
    scratch = f"{worker_url.database[:63 - 8]}_planner"
    admin = create_async_engine(worker_url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    async with admin.connect() as conn:
        await conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
        await conn.exec_driver_sql(f'CREATE DATABASE "{scratch}" TEMPLATE "{worker_url.database}"')
    engine = create_async_engine(worker_url.set(database=scratch), poolclass=NullPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _empty(s: AsyncSession) -> None:
        await s.execute(text("SET session_replication_role = replica"))
        for table in reversed(YEAR_TABLES):
            await s.execute(text(f'DELETE FROM "{table}"'))
        await s.commit()

    async def _est(s: AsyncSession) -> float:
        return (await s.execute(text("EXPLAIN (FORMAT JSON) SELECT * FROM journal_lines"))).scalar_one()[0]["Plan"]["Plan Rows"]

    async def _unanalyzed(s: AsyncSession) -> int:
        return (await s.execute(text("SELECT count(*) FROM pg_class WHERE relname = ANY(:names) AND reltuples < 0"), {"names": list(YEAR_TABLES)})).scalar_one()

    try:
        async with sessions() as s:
            await _empty(s)
            assert await _unanalyzed(s) == len(YEAR_TABLES)
            user = await _seed_year(s)
            est = await _est(s)
            assert 500 <= est <= 8000, est
            await s.execute(text("SET LOCAL statement_timeout = '3s'"))
            try:
                cf = await generate_cash_flow(s, user.id, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), currency="SGD")
            finally:
                await s.rollback()
            assert cf["summary"]["ending_cash"] == Decimal("100.00") * 1000
            await _empty(s)
            for table in YEAR_TABLES:
                await s.execute(text(f'ANALYZE "{table}"'))
            await s.commit()
            assert await _unanalyzed(s) == 0
            await _seed_year(s)
            assert await _est(s) <= 10
    finally:
        await engine.dispose()
        await _drop_database(worker_url, scratch)
        await admin.dispose()
