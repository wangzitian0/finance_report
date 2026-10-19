"""AC-ledger.14.7: Alembic and the ORM metadata install the same ledger functions and triggers (#2528).

The backend tests build their schema from the ORM metadata. Staging and production build theirs with
`alembic upgrade head`. #2472 changed `fr_guard_journal_entry_immutability` in the ORM DDL and added no migration.
The tests passed. Every category correction of a reconciled entry returned 500 on staging, because the trigger
of the migrated schema still refused `reconciled -> void`. `alembic check` compares tables and columns only.
This test builds one database with each method and compares every `fr_*` function and every trigger.
"""

from __future__ import annotations

import difflib
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import src.counter.extension.sql  # noqa: F401  -- registers CounterTally on Base.metadata
import src.identity.extension.sql  # noqa: F401  -- registers User/AiFeedback on Base.metadata
import src.orm_registry  # noqa: F401  -- eager-imports every model module onto Base.metadata
import src.platform.extension.sql  # noqa: F401  -- registers Outbox on Base.metadata
from src.database import Base

BACKEND_DIR = Path(__file__).resolve().parents[2]

FUNCTION_QUERY = text(
    """
    SELECT p.proname, pg_get_functiondef(p.oid)
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND p.proname LIKE 'fr\\_%'
    ORDER BY p.proname
    """
)
TRIGGER_QUERY = text(
    """
    SELECT c.relname || '.' || t.tgname, pg_get_triggerdef(t.oid)
    FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    WHERE NOT t.tgisinternal
    ORDER BY c.relname, t.tgname
    """
)


# Objects that only a migration installs. Migration 0034 owns them, and
# `test_audit_anchor_schema_invariants.py` checks its source. The test fails when the ORM schema starts to install
# one of them, so that the entry leaves this set.
MIGRATION_ONLY = frozenset(
    {
        "function fr_validate_evidence_edge_tenant_scope",
        "trigger evidence_edges.trg_evidence_edges_same_user_endpoints",
    }
)


def _url(async_url: str, database: str) -> str:
    return make_url(async_url).set(database=database).render_as_string(hide_password=False)


async def _definitions(engine: AsyncEngine) -> dict[str, str]:
    """The definition of each function and trigger, with runs of white space folded to one space."""
    async with engine.connect() as connection:
        functions = (await connection.execute(FUNCTION_QUERY)).all()
        triggers = (await connection.execute(TRIGGER_QUERY)).all()
    rows = [
        *(("function " + name, body) for name, body in functions),
        *(("trigger " + name, body) for name, body in triggers),
    ]
    return {name: " ".join(body.split()) for name, body in rows}


@pytest_asyncio.fixture
async def scratch_databases(test_database_url: str) -> AsyncIterator[tuple[str, str]]:
    """Two empty databases on the server of the test database. Drop both afterwards."""
    suffix = uuid.uuid4().hex[:8]
    names = (f"drift_migrated_{suffix}", f"drift_orm_{suffix}")
    admin = create_async_engine(_url(test_database_url, "postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            for name in names:
                await connection.execute(text(f'CREATE DATABASE "{name}"'))
        yield names
    finally:
        async with admin.connect() as connection:
            for name in names:
                await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


def _build_with_alembic(async_url: str, database: str) -> None:
    environment = {**os.environ, "DATABASE_URL": _url(async_url, database)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, f"alembic upgrade head failed:\n{result.stdout[-2000:]}\n{result.stderr[-4000:]}"


async def _build_with_orm(async_url: str, database: str) -> None:
    """Build the schema the way the backend tests do: the ORM metadata and its DDL events, on asyncpg."""
    engine = create_async_engine(_url(async_url, database))
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


def _describe(migrated: dict[str, str], orm: dict[str, str], migration_only: frozenset[str] = frozenset()) -> list[str]:
    problems: list[str] = []
    for name in sorted(set(migrated) | set(orm)):
        if name in migration_only:
            if name in orm:
                problems.append(f"{name}: the ORM schema installs it now. Remove it from MIGRATION_ONLY")
            elif name not in migrated:
                problems.append(f"{name}: listed in MIGRATION_ONLY, but the migrated schema lacks it")
        elif name not in migrated:
            problems.append(f"{name}: only the ORM schema has it")
        elif name not in orm:
            problems.append(f"{name}: only the migrated schema has it")
        elif migrated[name] != orm[name]:
            diff = difflib.unified_diff(
                migrated[name].replace("; ", ";\n").splitlines(),
                orm[name].replace("; ", ";\n").splitlines(),
                "migrated",
                "orm",
                lineterm="",
                n=0,
            )
            problems.append(f"{name}: the definitions differ\n" + "\n".join(list(diff)[:24]))
    for name in sorted(migration_only - set(migrated) - set(orm)):
        problems.append(f"{name}: listed in MIGRATION_ONLY, but the migrated schema lacks it")
    return problems


async def test_AC_ledger_14_7_alembic_and_orm_schemas_hold_the_same_functions_and_triggers(
    test_database_url: str, scratch_databases: tuple[str, str]
) -> None:
    migrated_name, orm_name = scratch_databases
    _build_with_alembic(test_database_url, migrated_name)
    await _build_with_orm(test_database_url, orm_name)

    migrated_engine = create_async_engine(_url(test_database_url, migrated_name))
    orm_engine = create_async_engine(_url(test_database_url, orm_name))
    try:
        migrated, orm = await _definitions(migrated_engine), await _definitions(orm_engine)
    finally:
        await migrated_engine.dispose()
        await orm_engine.dispose()

    # An empty comparison would pass without a check: both schemas must hold the ledger guards.
    assert "function fr_guard_journal_entry_immutability" in migrated
    assert "function fr_guard_journal_entry_immutability" in orm
    assert "trigger journal_entries.ck_journal_entries_immutable" in migrated
    assert _describe(migrated, orm, MIGRATION_ONLY) == []


@pytest.mark.parametrize(
    ("migrated", "orm", "migration_only", "expected"),
    [
        ({"function f": "a b"}, {"function f": "a b"}, frozenset(), []),
        ({"function f": "a b"}, {"function f": "a c"}, frozenset(), ["function f: the definitions differ"]),
        ({"function f": "a"}, {}, frozenset(), ["function f: only the migrated schema has it"]),
        ({}, {"trigger t": "a"}, frozenset(), ["trigger t: only the ORM schema has it"]),
        # A listed object may exist in the migrated schema only.
        ({"function f": "a"}, {}, frozenset({"function f"}), []),
        # A listed object that the ORM schema installs now must leave the list.
        (
            {"function f": "a"},
            {"function f": "a"},
            frozenset({"function f"}),
            ["function f: the ORM schema installs it now. Remove it from MIGRATION_ONLY"],
        ),
        # A listed object that no schema holds is a stale entry.
        ({}, {}, frozenset({"function f"}), ["function f: listed in MIGRATION_ONLY, but the migrated schema lacks it"]),
    ],
    ids=["equal", "differ", "migrated-only", "orm-only", "listed", "listed-but-orm-has-it", "listed-but-absent"],
)
def test_AC_ledger_14_7_the_comparison_names_each_difference(
    migrated: dict[str, str], orm: dict[str, str], migration_only: frozenset[str], expected: list[str]
) -> None:
    assert [problem.splitlines()[0] for problem in _describe(migrated, orm, migration_only)] == expected
