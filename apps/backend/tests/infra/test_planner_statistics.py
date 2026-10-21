"""AC-testing.backend-test-planner.1/.2: planner statistics of the worker database stay fixed (#2398).

Each test deletes the rows of the tables it wrote. Autovacuum could then ANALYZE a table while it was
empty. A year-scale test that next loaded 1000 entries got plans for empty tables. In CI the cash flow
query of that test was still active after 33 s at 99% CPU (ps and pg_stat_activity, run 39592701300),
and the 60 s test timeout ended the xdist worker. The harness disables autovacuum on every table of the worker
database, so no statistics come from a transient state.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from src.identity import User
from src.reporting import generate_cash_flow
from tests.factories import seed_year_of_journal_entries

YEAR_TABLES = ("accounts", "journal_entries", "journal_lines")
ENTRY_COUNT = 1000
LINE_COUNT = 2 * ENTRY_COUNT
AMOUNT = Decimal("100.00")
# On fresh statistics the query took 59 ms locally. On statistics of empty tables it ran past 60 s.
STATEMENT_TIMEOUT = "3s"


async def test_AC_testing_backend_test_planner_1_worker_tables_have_autovacuum_disabled(db: AsyncSession) -> None:
    """AC-testing.backend-test-planner.1: every table of the worker database has autovacuum disabled."""
    rows = (
        await db.execute(
            text(
                "SELECT c.relname, coalesce(array_to_string(c.reloptions, ','), '') "
                "FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r'"
            )
        )
    ).all()
    options = dict(rows)

    assert set(YEAR_TABLES) <= set(options), sorted(options)
    enabled = sorted(name for name, value in options.items() if "autovacuum_enabled=false" not in value)
    assert enabled == [], f"autovacuum can sample these tables while a test has emptied them: {enabled}"


def _scratch_name(worker_database: str) -> str:
    suffix = "_planner"
    return f"{worker_database[: 63 - len(suffix)]}{suffix}"


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
