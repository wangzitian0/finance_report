from __future__ import annotations; import importlib.util; import os; from pathlib import Path; from types import ModuleType; from uuid import uuid4; import pytest_asyncio; from alembic.migration import MigrationContext; from alembic.operations import Operations; from sqlalchemy import text; from sqlalchemy.engine import Engine; from sqlalchemy.engine.url import make_url; from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine; import src.orm_registry; from src.advisor.orm.chat import ChatMessageRole, ChatSessionStatus; from src.database import Base; from src.ledger.orm.account import AccountType; from src.ledger.orm.journal import Direction, JournalEntryStatus; from src.llm.base import ProtocolFamily; _BACKEND_DIR = Path(__file__).resolve().parents[2]; _MIGRATION_PATH = _BACKEND_DIR / 'migrations' / 'versions' / '0064_enum_drift_cleanup.py'; _UPPERCASE_ORPHAN_DRIFT: dict[str, tuple[str, ...]] = {'chat_session_status_enum': ('ACTIVE', 'DELETED'), 'chat_message_role_enum': ('USER', 'ASSISTANT', 'SYSTEM'), 'journal_entry_status_enum': ('DRAFT', 'POSTED', 'RECONCILED', 'VOID')}; _LOWERCASE_ORPHAN_DRIFT: dict[str, tuple[str, ...]] = {'account_type_enum': ('asset', 'liability', 'equity', 'income', 'expense'), 'journal_line_direction_enum': ('debit', 'credit')}; _LLM_PROTOCOL_FAMILY_ENUM = 'llm_protocol_family_enum'; _LLM_PROTOCOL_FAMILY_WITHOUT_GEMINI = ('openai-compatible', 'anthropic-compatible', 'openrouter-compatible'); _PRE_UPGRADE_LABEL_SET: dict[str, set[str]] = {enum_name: set(canonical) | set(_UPPERCASE_ORPHAN_DRIFT.get(enum_name, ())) | set(_LOWERCASE_ORPHAN_DRIFT.get(enum_name, ())) for enum_name, canonical in (('chat_session_status_enum', ('active', 'deleted')), ('chat_message_role_enum', ('user', 'assistant', 'system')), ('journal_entry_status_enum', ('draft', 'posted', 'reconciled', 'void')), ('account_type_enum', ('ASSET', 'LIABILITY', 'EQUITY', 'INCOME', 'EXPENSE')), ('journal_line_direction_enum', ('DEBIT', 'CREDIT')))}; _CODE_ENUMS_UNDER_TEST = {'chat_session_status_enum': ChatSessionStatus, 'chat_message_role_enum': ChatMessageRole, 'journal_entry_status_enum': JournalEntryStatus, 'account_type_enum': AccountType, 'journal_line_direction_enum': Direction, _LLM_PROTOCOL_FAMILY_ENUM: ProtocolFamily}
def _load_migration_module() -> ModuleType: spec = importlib.util.spec_from_file_location('enum_drift_cleanup_0064_under_test', _MIGRATION_PATH); assert spec and spec.loader; module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
def _migration_step_runner(migration: ModuleType, step: str):
    def run(sync_conn: Engine) -> None:
        ctx = MigrationContext.configure(sync_conn); migration.op = Operations(ctx)
        with ctx.begin_transaction(): getattr(migration, step)()
    return run
async def _db_enum_labels(conn, enum_name: str) -> set[str]: result = await conn.execute(text('SELECT e.enumlabel FROM pg_type t JOIN pg_enum e ON t.oid = e.enumtypid WHERE t.typname = :name ORDER BY e.enumsortorder'), {'name': enum_name}); return {row[0] for row in result.fetchall()}
@pytest_asyncio.fixture
async def enum_drift_engine(worker_id):
    base_url = os.environ.get('DATABASE_URL', 'postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test_default')
    if 'localhost' in base_url: base_url = base_url.replace('localhost', '127.0.0.1')
    db_name = f'enum_drift_cleanup_test_{worker_id}_{uuid4().hex[:8]}'; url = make_url(base_url).set(database=db_name); admin_url = url.set(database='postgres'); admin_engine: AsyncEngine = create_async_engine(admin_url, isolation_level='AUTOCOMMIT')
    async with admin_engine.connect() as conn: await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose(); engine: AsyncEngine = create_async_engine(url, echo=False)
    try:
        async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose(); admin_engine = create_async_engine(admin_url, isolation_level='AUTOCOMMIT')
        async with admin_engine.connect() as conn: await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await admin_engine.dispose()
async def test_0064_enum_drift_cleanup_converges_db_enums_to_code_red_then_green(enum_drift_engine: AsyncEngine):
    code_side: dict[str, set[str]] = {enum_name: {member.value for member in enum_cls} for enum_name, enum_cls in _CODE_ENUMS_UNDER_TEST.items()}; engine = enum_drift_engine
    async with engine.begin() as conn:
        for (enum_name, orphans) in {**_UPPERCASE_ORPHAN_DRIFT, **_LOWERCASE_ORPHAN_DRIFT}.items():
            for orphan in orphans: await conn.execute(text(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{orphan}'"))
    async with engine.begin() as conn: await conn.execute(text(f'ALTER TYPE {_LLM_PROTOCOL_FAMILY_ENUM} RENAME TO {_LLM_PROTOCOL_FAMILY_ENUM}_pre64')); values = ', '.join((f"'{v}'" for v in _LLM_PROTOCOL_FAMILY_WITHOUT_GEMINI)); await conn.execute(text(f'CREATE TYPE {_LLM_PROTOCOL_FAMILY_ENUM} AS ENUM ({values})')); await conn.execute(text(f'ALTER TABLE llm_providers ALTER COLUMN protocol TYPE {_LLM_PROTOCOL_FAMILY_ENUM} USING protocol::text::{_LLM_PROTOCOL_FAMILY_ENUM}')); await conn.execute(text(f'DROP TYPE {_LLM_PROTOCOL_FAMILY_ENUM}_pre64'))
    async with engine.connect() as conn:
        for (enum_name, code_values) in code_side.items(): db_values = await _db_enum_labels(conn, enum_name); assert db_values != code_values, f'expected {enum_name} to be drifted before 0064 runs (red); db={sorted(db_values)} code={sorted(code_values)}'
    migration = _load_migration_module(); run_upgrade = _migration_step_runner(migration, 'upgrade')
    async with engine.connect() as conn: await conn.run_sync(run_upgrade); await conn.commit()
    async with engine.connect() as conn:
        for (enum_name, code_values) in code_side.items(): db_values = await _db_enum_labels(conn, enum_name); assert db_values == code_values, f'{enum_name} still diverges from code after 0064: db={sorted(db_values)} code={sorted(code_values)}'
    async with engine.connect() as conn: await conn.run_sync(run_upgrade); await conn.commit()
    async with engine.connect() as conn:
        for (enum_name, code_values) in code_side.items(): db_values = await _db_enum_labels(conn, enum_name); assert db_values == code_values
async def test_0064_downgrade_restores_pre_upgrade_label_set(enum_drift_engine: AsyncEngine):
    engine = enum_drift_engine
    async with engine.begin() as conn:
        for (enum_name, orphans) in {**_UPPERCASE_ORPHAN_DRIFT, **_LOWERCASE_ORPHAN_DRIFT}.items():
            for orphan in orphans: await conn.execute(text(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{orphan}'"))
    async with engine.connect() as conn:
        for (enum_name, pre_upgrade_labels) in _PRE_UPGRADE_LABEL_SET.items(): assert await _db_enum_labels(conn, enum_name) == pre_upgrade_labels
    migration = _load_migration_module(); run_upgrade = _migration_step_runner(migration, 'upgrade'); run_downgrade = _migration_step_runner(migration, 'downgrade')
    async with engine.connect() as conn: await conn.run_sync(run_upgrade); await conn.commit()
    async with engine.connect() as conn:
        for (enum_name, pre_upgrade_labels) in _PRE_UPGRADE_LABEL_SET.items(): db_values = await _db_enum_labels(conn, enum_name); assert db_values != pre_upgrade_labels, f'expected {enum_name} to NOT yet match the pre-upgrade set before downgrade() runs (red); db={sorted(db_values)} pre_upgrade={sorted(pre_upgrade_labels)}'
    async with engine.connect() as conn: await conn.run_sync(run_downgrade); await conn.commit()
    async with engine.connect() as conn:
        for (enum_name, pre_upgrade_labels) in _PRE_UPGRADE_LABEL_SET.items(): db_values = await _db_enum_labels(conn, enum_name); assert db_values == pre_upgrade_labels, f'downgrade() did not restore {enum_name} to its pre-upgrade label set: db={sorted(db_values)} pre_upgrade={sorted(pre_upgrade_labels)}'
    code_llm_values = {member.value for member in ProtocolFamily}
    async with engine.connect() as conn: db_llm_values = await _db_enum_labels(conn, _LLM_PROTOCOL_FAMILY_ENUM); assert db_llm_values == code_llm_values, f'llm_protocol_family_enum should be unaffected by downgrade(): db={sorted(db_llm_values)} code={sorted(code_llm_values)}'
