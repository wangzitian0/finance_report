"""AC-testing.backend-test-planner.1/.2/.3/.4: planner statistics of the worker database stay fixed (#2398).

Each test deletes the rows of the tables it wrote. Autovacuum could then ANALYZE a table while it was
empty. A year-scale test that next loaded 1000 entries got plans for empty tables. In CI the cash flow
query of that test was still active after 33 s at 99% CPU (ps and pg_stat_activity, run 39592701300),
and the 60 s test timeout ended the xdist worker. The harness disables autovacuum on every table of the worker
database, so no statistics come from a transient state.

A test can drop a table and create it again in the worker database. A migration test does this.
A table that is created again has the default storage options, so autovacuum was on for it in the
rest of the worker session. The guard of AC .1 then failed or passed by the order of the tests on
one worker (run 39904398832, shard 3/4). AC .3 and AC .4 pin that the order has no effect.
"""

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
from common.testing.test_isolation import get_test_db_name, sanitize_namespace
from sqlalchemy import text
from sqlalchemy.engine.url import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.extraction.orm.bank_custody_binding import BankCustodyBinding
from src.identity import User
from src.reporting import generate_cash_flow
from tests.factories import seed_year_of_journal_entries

YEAR_TABLES = ("accounts", "journal_entries", "journal_lines")
ENTRY_COUNT = 1000
LINE_COUNT = 2 * ENTRY_COUNT
AMOUNT = Decimal("100.00")
# On fresh statistics the query took 59 ms locally. On statistics of empty tables it ran past 60 s.
STATEMENT_TIMEOUT = "3s"
BACKEND_DIR = Path(__file__).resolve().parents[2]
GUARD_TEST = "test_AC_testing_backend_test_planner_1_worker_tables_have_autovacuum_disabled"
RECREATE_TEST = "test_AC_testing_backend_test_planner_3_a_recreated_table_has_autovacuum_disabled"
SEQUENCE_TIMEOUT_SECONDS = 40
PROBE_TABLES = ("planner_probe_plain", "planner_probe_ctas", "planner_probe_into", "planner_probe_replica")


async def _autovacuum_options(session: AsyncSession) -> dict[str, str]:
    """Map each table of schema public to its storage options."""
    rows = (
        await session.execute(
            text(
                "SELECT c.relname, coalesce(array_to_string(c.reloptions, ','), '') "
                "FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r'"
            )
        )
    ).all()
    return dict(rows)


def _autovacuum_enabled(options: dict[str, str]) -> list[str]:
    return sorted(name for name, value in options.items() if "autovacuum_enabled=false" not in value)


async def test_AC_testing_backend_test_planner_1_worker_tables_have_autovacuum_disabled(db: AsyncSession) -> None:
    """AC-testing.backend-test-planner.1: every table of the worker database has autovacuum disabled."""
    options = await _autovacuum_options(db)

    assert set(YEAR_TABLES) <= set(options), sorted(options)
    enabled = _autovacuum_enabled(options)
    assert enabled == [], f"autovacuum can sample these tables while a test has emptied them: {enabled}"


async def test_AC_testing_backend_test_planner_3_a_recreated_table_has_autovacuum_disabled(db: AsyncSession) -> None:
    """AC-testing.backend-test-planner.3: each table that a CREATE statement makes has autovacuum disabled.

    The test drops one real table and creates it again. It also makes tables with CREATE TABLE AS,
    SELECT INTO and, with session_replication_role set to replica, CREATE TABLE.
    The table that is created again stays in the worker database on purpose.
    Every later test of the worker session sees it.
    """
    table = BankCustodyBinding.__table__
    await db.run_sync(lambda session: table.drop(session.connection()))
    await db.run_sync(lambda session: table.create(session.connection()))
    await db.execute(text("CREATE TABLE planner_probe_plain (id integer)"))
    await db.execute(text("CREATE TABLE planner_probe_ctas AS SELECT 1 AS id"))
    await db.execute(text("SELECT 1 AS id INTO planner_probe_into"))
    await db.execute(text("SET LOCAL session_replication_role = replica"))
    await db.execute(text("CREATE TABLE planner_probe_replica (id integer)"))
    await db.commit()
    try:
        options = await _autovacuum_options(db)

        assert {table.name, *PROBE_TABLES} <= set(options), sorted(options)
        assert _autovacuum_enabled(options) == [], options
    finally:
        for name in PROBE_TABLES:
            await db.execute(text(f"DROP TABLE IF EXISTS {name}"))
        await db.commit()


async def test_AC_testing_backend_test_planner_4_the_guard_passes_in_the_session_after_a_table_was_recreated(
    test_database_url: str,
) -> None:
    """AC-testing.backend-test-planner.4: the guard of AC .1 passes after a test made a table again.

    A pytest session in a subprocess runs the test of AC .3 and then the guard of AC .1 on one worker database.
    The session uses its own database, so the database of this worker stays untouched.
    """
    namespace = f"planner_seq_{uuid4().hex[:8]}"
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("COV_CORE_", "PYTEST_XDIST_", "PYTEST_ADDOPTS")) and key != "COVERAGE_PROCESS_START"
    }
    environment.update(TEST_NAMESPACE=namespace, DATABASE_URL=test_database_url, ENVIRONMENT="testing")
    session_database = get_test_db_name(sanitize_namespace(namespace))
    here = Path(__file__).resolve().relative_to(BACKEND_DIR)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "-o",
        "addopts=",
        "-q",
        f"{here}::{RECREATE_TEST}",
        f"{here}::{GUARD_TEST}",
    ]
    try:
        result = subprocess.run(
            command,
            cwd=BACKEND_DIR,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=SEQUENCE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as timeout:
        pytest.fail(f"the pytest session did not end in {SEQUENCE_TIMEOUT_SECONDS} s: {timeout.stdout!r}")
    finally:
        await _drop_database(make_url(test_database_url), session_database)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output[-3000:]
    assert re.search(r"\b2 passed\b", result.stdout), output[-3000:]


def _scratch_name(worker_database: str) -> str:
    suffix = "_planner"
    return f"{worker_database[: 63 - len(suffix)]}{suffix}"


async def _drop_database(worker_url: URL, database: str) -> None:
    admin = create_async_engine(worker_url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            await conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    finally:
        await admin.dispose()


async def _empty_year_tables(session: AsyncSession) -> None:
    await session.execute(text("SET session_replication_role = replica"))
    for table in reversed(YEAR_TABLES):
        await session.execute(text(f'DELETE FROM "{table}"'))
    await session.commit()


async def _never_analyzed(session: AsyncSession) -> int:
    """Count the year tables that VACUUM or ANALYZE never processed (pg_class.reltuples is -1)."""
    return (
        await session.execute(
            text("SELECT count(*) FROM pg_class WHERE relname = ANY(:names) AND reltuples < 0"),
            {"names": list(YEAR_TABLES)},
        )
    ).scalar_one()


async def _estimated_lines(session: AsyncSession) -> float:
    plan = (await session.execute(text("EXPLAIN (FORMAT JSON) SELECT * FROM journal_lines"))).scalar_one()
    return plan[0]["Plan"]["Plan Rows"]


async def _seed_year(session: AsyncSession) -> User:
    user = User(id=uuid4(), email=f"planner-{uuid4()}@example.com", hashed_password="hashed")
    session.add(user)
    await session.commit()
    await seed_year_of_journal_entries(session, user.id, first_day=date(2026, 1, 1), entry_count=ENTRY_COUNT)
    return user


async def _cash_flow_within_timeout(session: AsyncSession, user: User) -> dict:
    await session.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    try:
        return await generate_cash_flow(
            session,
            user.id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            currency="SGD",
        )
    finally:
        await session.rollback()


async def test_AC_testing_backend_test_planner_2_a_year_load_keeps_true_size_estimates_and_a_fast_cash_flow(
    test_database_url: str,
) -> None:
    """AC-testing.backend-test-planner.2: after a year load on the harness statistics, the planner estimates
    the 2000 journal lines within a factor of 4, and the year cash flow ends within 3 s. Statistics sampled
    from empty tables make the planner estimate at most 10 lines for the same load."""
    worker_url = make_url(test_database_url)
    scratch = _scratch_name(worker_url.database)
    admin = create_async_engine(worker_url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    # A copy keeps the statistics of the worker database: the analyzed tables below stay in the copy.
    async with admin.connect() as conn:
        await conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
        await conn.exec_driver_sql(f'CREATE DATABASE "{scratch}" TEMPLATE "{worker_url.database}"')
    engine = create_async_engine(worker_url.set(database=scratch), poolclass=NullPool)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with sessions() as session:
            await _empty_year_tables(session)
            assert await _never_analyzed(session) == len(YEAR_TABLES)
            user = await _seed_year(session)
            estimate = await _estimated_lines(session)
            assert LINE_COUNT / 4 <= estimate <= LINE_COUNT * 4, estimate
            cash_flow = await _cash_flow_within_timeout(session, user)
            assert cash_flow["summary"]["ending_cash"] == AMOUNT * ENTRY_COUNT

            # The autovacuum timing before #2398: the tables are analyzed while they are empty.
            await _empty_year_tables(session)
            for table in YEAR_TABLES:
                await session.execute(text(f'ANALYZE "{table}"'))
            await session.commit()
            assert await _never_analyzed(session) == 0
            await _seed_year(session)
            assert await _estimated_lines(session) <= 10
    finally:
        await engine.dispose()
        async with admin.connect() as conn:
            await conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
        await admin.dispose()
