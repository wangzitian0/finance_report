'AC-ledger.14.7'; from __future__ import annotations; import difflib; import os; import subprocess; import sys; import uuid; from collections.abc import AsyncIterator; from pathlib import Path; import pytest; import pytest_asyncio; from sqlalchemy import text; from sqlalchemy.engine import make_url; from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine; import src.counter.extension.sql; import src.identity.extension.sql; import src.orm_registry; import src.platform.extension.sql; from src.database import Base; BACKEND_DIR = Path(__file__).resolve().parents[2]; FUNCTION_QUERY = text("\n    SELECT p.proname, pg_get_functiondef(p.oid)\n    FROM pg_proc p\n    JOIN pg_namespace n ON n.oid = p.pronamespace\n    WHERE n.nspname = 'public' AND p.proname LIKE 'fr\\_%'\n    ORDER BY p.proname\n    "); TRIGGER_QUERY = text("\n    SELECT c.relname || '.' || t.tgname, pg_get_triggerdef(t.oid)\n    FROM pg_trigger t\n    JOIN pg_class c ON c.oid = t.tgrelid\n    WHERE NOT t.tgisinternal\n    ORDER BY c.relname, t.tgname\n    "); MIGRATION_ONLY = frozenset({'function fr_validate_evidence_edge_tenant_scope', 'trigger evidence_edges.trg_evidence_edges_same_user_endpoints'}); _url = lambda async_url, database: make_url(async_url).set(database=database).render_as_string(hide_password=False)
async def _definitions(engine: AsyncEngine) -> dict[str, str]:
    async with engine.connect() as connection: functions = (await connection.execute(FUNCTION_QUERY)).all(); triggers = (await connection.execute(TRIGGER_QUERY)).all()
    rows = [*(('function ' + name, body) for name, body in functions), *(('trigger ' + name, body) for name, body in triggers)]; return {name: ' '.join(body.split()) for name, body in rows}
@pytest_asyncio.fixture
async def scratch_databases(test_database_url: str) -> AsyncIterator[tuple[str, str]]:
    suffix = uuid.uuid4().hex[:8]; names = (f'drift_migrated_{suffix}', f'drift_orm_{suffix}'); admin = create_async_engine(_url(test_database_url, 'postgres'), isolation_level='AUTOCOMMIT')
    try:
        async with admin.connect() as connection:
            for name in names: await connection.execute(text(f'CREATE DATABASE "{name}"'))
        yield names
    finally:
        async with admin.connect() as connection:
            for name in names: await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()
def _build_with_alembic(async_url: str, database: str) -> None: environment = {**os.environ, 'DATABASE_URL': _url(async_url, database)}; result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND_DIR, env=environment, capture_output=True, text=True, timeout=600); assert result.returncode == 0, f'alembic upgrade head failed:\n{result.stdout[-2000:]}\n{result.stderr[-4000:]}'
async def _build_with_orm(async_url: str, database: str) -> None:
    engine = create_async_engine(_url(async_url, database))
    try:
        async with engine.begin() as connection: await connection.run_sync(Base.metadata.create_all)
    finally: await engine.dispose()
def _describe(migrated: dict[str, str], orm: dict[str, str], migration_only: frozenset[str]=frozenset()) -> list[str]:
    problems: list[str] = []
    for name in sorted(set(migrated) | set(orm)):
        if name in migration_only: problems.append(f'{name}: the ORM schema installs it now. Remove it from MIGRATION_ONLY') if name in orm else problems.append(f'{name}: listed in MIGRATION_ONLY, but the migrated schema lacks it') if name not in migrated else None
        elif name not in migrated: problems.append(f'{name}: only the ORM schema has it')
        elif name not in orm: problems.append(f'{name}: only the migrated schema has it')
        elif migrated[name] != orm[name]: diff = difflib.unified_diff(migrated[name].replace('; ', ';\n').splitlines(), orm[name].replace('; ', ';\n').splitlines(), 'migrated', 'orm', lineterm='', n=0); problems.append(f'{name}: the definitions differ\n' + '\n'.join(list(diff)[:24]))
    [problems.append(f'{name}: listed in MIGRATION_ONLY, but the migrated schema lacks it') for name in sorted(migration_only - set(migrated) - set(orm))]; return problems
async def test_AC_ledger_14_7_alembic_and_orm_schemas_hold_the_same_functions_and_triggers(test_database_url: str, scratch_databases: tuple[str, str]) -> None:
    migrated_name, orm_name = scratch_databases; _build_with_alembic(test_database_url, migrated_name); await _build_with_orm(test_database_url, orm_name); migrated_engine = create_async_engine(_url(test_database_url, migrated_name)); orm_engine = create_async_engine(_url(test_database_url, orm_name))
    try: migrated, orm = (await _definitions(migrated_engine), await _definitions(orm_engine))
    finally: await migrated_engine.dispose(); await orm_engine.dispose()
    assert 'function fr_guard_journal_entry_immutability' in migrated; assert 'function fr_guard_journal_entry_immutability' in orm; assert 'trigger journal_entries.ck_journal_entries_immutable' in migrated; assert _describe(migrated, orm, MIGRATION_ONLY) == []
@pytest.mark.parametrize(('migrated', 'orm', 'migration_only', 'expected'), [({'function f': 'a b'}, {'function f': 'a b'}, frozenset(), []), ({'function f': 'a b'}, {'function f': 'a c'}, frozenset(), ['function f: the definitions differ']), ({'function f': 'a'}, {}, frozenset(), ['function f: only the migrated schema has it']), ({}, {'trigger t': 'a'}, frozenset(), ['trigger t: only the ORM schema has it']), ({'function f': 'a'}, {}, frozenset({'function f'}), []), ({'function f': 'a'}, {'function f': 'a'}, frozenset({'function f'}), ['function f: the ORM schema installs it now. Remove it from MIGRATION_ONLY']), ({}, {}, frozenset({'function f'}), ['function f: listed in MIGRATION_ONLY, but the migrated schema lacks it'])], ids=['equal', 'differ', 'migrated-only', 'orm-only', 'listed', 'listed-but-orm-has-it', 'listed-but-absent'])
def test_AC_ledger_14_7_the_comparison_names_each_difference(migrated: dict[str, str], orm: dict[str, str], migration_only: frozenset[str], expected: list[str]) -> None: assert [problem.splitlines()[0] for problem in _describe(migrated, orm, migration_only)] == expected
