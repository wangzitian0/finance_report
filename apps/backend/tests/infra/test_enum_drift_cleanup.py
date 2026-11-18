from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import src.orm_registry
from src.advisor.orm.chat import ChatMessageRole, ChatSessionStatus
from src.database import Base
from src.ledger.orm.account import AccountType
from src.ledger.orm.journal import Direction, JournalEntryStatus
from src.llm.base import ProtocolFamily

_MIGRATION_PATH = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0064_enum_drift_cleanup.py"
_ORPHAN_DRIFT = {
    "chat_session_status_enum": ("ACTIVE", "DELETED"),
    "chat_message_role_enum": ("USER", "ASSISTANT", "SYSTEM"),
    "journal_entry_status_enum": ("DRAFT", "POSTED", "RECONCILED", "VOID"),
    "account_type_enum": ("asset", "liability", "equity", "income", "expense"),
    "journal_line_direction_enum": ("debit", "credit"),
}
_LLM_ENUM = "llm_protocol_family_enum"
_CODE_ENUMS = {"chat_session_status_enum": ChatSessionStatus, "chat_message_role_enum": ChatMessageRole, "journal_entry_status_enum": JournalEntryStatus, "account_type_enum": AccountType, "journal_line_direction_enum": Direction, _LLM_ENUM: ProtocolFamily}
_PRE_LABELS = {k: {m.value for m in v} | set(_ORPHAN_DRIFT[k]) for k, v in _CODE_ENUMS.items() if k != _LLM_ENUM}


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("enum_drift_cleanup_0064_under_test", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run_step(engine: AsyncEngine, migration: ModuleType, step: str) -> None:
    def run(sync_conn) -> None:
        ctx = MigrationContext.configure(sync_conn)
        migration.op = Operations(ctx)
        with ctx.begin_transaction():
            getattr(migration, step)()

    async with engine.connect() as conn:
        await conn.run_sync(run)
        await conn.commit()


async def _labels(engine: AsyncEngine, enum_name: str) -> set[str]:
    sql = text("SELECT e.enumlabel FROM pg_type t JOIN pg_enum e ON t.oid = e.enumtypid WHERE t.typname = :name ORDER BY e.enumsortorder")
    async with engine.connect() as conn:
        return {row[0] for row in (await conn.execute(sql, {"name": enum_name})).fetchall()}


@pytest_asyncio.fixture
async def enum_drift_engine(worker_id):
    base_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test_default").replace("localhost", "127.0.0.1")
    db_name = f"enum_drift_cleanup_test_{worker_id}_{uuid4().hex[:8]}"
    url = make_url(base_url).set(database=db_name)
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin.dispose()
    engine = create_async_engine(url, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose()
        admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await admin.dispose()


async def test_0064_enum_drift_cleanup_upgrade_and_downgrade_roundtrip(enum_drift_engine: AsyncEngine):
    async with enum_drift_engine.begin() as conn:
        for enum_name, orphans in _ORPHAN_DRIFT.items():
            for orphan in orphans:
                await conn.execute(text(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{orphan}'"))
        for sql in (f"ALTER TYPE {_LLM_ENUM} RENAME TO {_LLM_ENUM}_pre64", f"CREATE TYPE {_LLM_ENUM} AS ENUM ('openai-compatible', 'anthropic-compatible', 'openrouter-compatible')", f"ALTER TABLE llm_providers ALTER COLUMN protocol TYPE {_LLM_ENUM} USING protocol::text::{_LLM_ENUM}", f"DROP TYPE {_LLM_ENUM}_pre64"):
            await conn.execute(text(sql))

    code_side = {name: {m.value for m in cls} for name, cls in _CODE_ENUMS.items()}
    for name, pre in _PRE_LABELS.items():
        assert await _labels(enum_drift_engine, name) == pre
    assert await _labels(enum_drift_engine, _LLM_ENUM) != code_side[_LLM_ENUM]

    migration = _load_migration()
    for _ in range(2):
        await _run_step(enum_drift_engine, migration, "upgrade")
        for name, values in code_side.items():
            assert await _labels(enum_drift_engine, name) == values

    await _run_step(enum_drift_engine, migration, "downgrade")
    for name, pre in _PRE_LABELS.items():
        assert await _labels(enum_drift_engine, name) == pre
    assert await _labels(enum_drift_engine, _LLM_ENUM) == code_side[_LLM_ENUM]
