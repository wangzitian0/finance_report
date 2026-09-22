"""Proves ``migrations/versions/0064_enum_drift_cleanup.py`` converges every
drifted Postgres enum type to exactly the code-declared label set -- red before
the migration runs, green after.

Context: infra2's ``tools/pre_deploy_schema_check.py`` (the #698 pre-deploy schema
gate, wired into the deploy path by infra2 PR #783) compares live Postgres enum
labels against ``src.database.Base.metadata`` 1:1 and blocks any deploy on a
mismatch. An independent live-probe (direct psql against both real databases,
read-only) found staging and prod both failing this gate on pre-existing drift:
``0063_enum_case_compat`` had added legacy-uppercase orphan labels alongside the
current lowercase ones for three enum types (both environments), prod additionally
carried legacy-lowercase orphans predating 0007's enum-name normalization for two
more, and ``llm_protocol_family_enum`` was missing a value
(``ProtocolFamily.GOOGLE_GEMINI``) the code side had already added with no
migration to match (both environments). See ``0064_enum_drift_cleanup.py``'s module
docstring for the full accounting, including that zero live rows in either
environment hold any orphan label -- verified before writing the migration, not
assumed.

This test runs against its own disposable database rather than the shared
per-worker schema ``tests/conftest.py``'s ``db``/``db_engine`` fixtures provide:
0064 performs real type-rebuild DDL (CREATE TYPE/DROP TYPE, ALTER TABLE ... ALTER
COLUMN TYPE), and isolating it here means that DDL can never leak into an unrelated
test even transiently, and this test needs no cleanup discipline beyond dropping
its own database.
"""

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
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import src.orm_registry  # noqa: F401 -- eager-imports every model module onto Base.metadata
from src.advisor.orm.chat import ChatMessageRole, ChatSessionStatus
from src.database import Base
from src.ledger.orm.account import AccountType
from src.ledger.orm.journal import Direction, JournalEntryStatus
from src.llm.base import ProtocolFamily

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = _BACKEND_DIR / "migrations" / "versions" / "0064_enum_drift_cleanup.py"

# Mirrors 0063_enum_case_compat.py's ENUM_VALUES_TO_ENSURE for the 3 enum types that
# carry uppercase orphans in BOTH real staging and prod (0064's module docstring).
_UPPERCASE_ORPHAN_DRIFT: dict[str, tuple[str, ...]] = {
    "chat_session_status_enum": ("ACTIVE", "DELETED"),
    "chat_message_role_enum": ("USER", "ASSISTANT", "SYSTEM"),
    "journal_entry_status_enum": ("DRAFT", "POSTED", "RECONCILED", "VOID"),
}

# Mirrors the PROD-ONLY legacy-lowercase orphan drift (0064's module docstring);
# staging never carried these.
_LOWERCASE_ORPHAN_DRIFT: dict[str, tuple[str, ...]] = {
    "account_type_enum": ("asset", "liability", "equity", "income", "expense"),
    "journal_line_direction_enum": ("debit", "credit"),
}

_LLM_PROTOCOL_FAMILY_ENUM = "llm_protocol_family_enum"
_LLM_PROTOCOL_FAMILY_WITHOUT_GEMINI = (
    "openai-compatible",
    "anthropic-compatible",
    "openrouter-compatible",
)

# The full pre-upgrade (0063-drifted) label SET for each of the 5 enums 0064
# rebuilds -- canonical labels plus their orphans, exactly what downgrade() must
# restore. Full-set equality (not a weaker "orphan is present" check) is what
# schema-reversible means here.
_PRE_UPGRADE_LABEL_SET: dict[str, set[str]] = {
    enum_name: set(canonical)
    | set(_UPPERCASE_ORPHAN_DRIFT.get(enum_name, ()))
    | set(_LOWERCASE_ORPHAN_DRIFT.get(enum_name, ()))
    for enum_name, canonical in (
        ("chat_session_status_enum", ("active", "deleted")),
        ("chat_message_role_enum", ("user", "assistant", "system")),
        ("journal_entry_status_enum", ("draft", "posted", "reconciled", "void")),
        ("account_type_enum", ("ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE")),
        ("journal_line_direction_enum", ("DEBIT", "CREDIT")),
    )
}

# The 6 enum types 0064 touches, mapped to their code-side authoritative Enum class.
_CODE_ENUMS_UNDER_TEST = {
    "chat_session_status_enum": ChatSessionStatus,
    "chat_message_role_enum": ChatMessageRole,
    "journal_entry_status_enum": JournalEntryStatus,
    "account_type_enum": AccountType,
    "journal_line_direction_enum": Direction,
    _LLM_PROTOCOL_FAMILY_ENUM: ProtocolFamily,
}


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("enum_drift_cleanup_0064_under_test", _MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _migration_step_runner(migration: ModuleType, step: str):
    """A ``conn.run_sync``-compatible callable that runs ``migration.upgrade()`` or
    ``migration.downgrade()`` against the sync-facing connection, bound through a
    real ``MigrationContext`` transaction (required for ``autocommit_block()`` to
    work -- it asserts a managed transaction is open)."""

    def run(sync_conn: Engine) -> None:
        ctx = MigrationContext.configure(sync_conn)
        migration.op = Operations(ctx)
        with ctx.begin_transaction():
            getattr(migration, step)()

    return run


async def _db_enum_labels(conn, enum_name: str) -> set[str]:
    result = await conn.execute(
        text(
            "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e ON t.oid = e.enumtypid "
            "WHERE t.typname = :name ORDER BY e.enumsortorder"
        ),
        {"name": enum_name},
    )
    return {row[0] for row in result.fetchall()}


@pytest_asyncio.fixture
async def enum_drift_engine(worker_id):
    """A disposable database + engine, independent of the shared per-worker schema.

    Built with the exact same ``Base.metadata.create_all`` the real per-worker
    schema fixture uses (``tests/conftest.py::_schema_engine``), so the pre-drift
    baseline this test starts from is identical to what every other test starts
    from -- the only difference is this database is thrown away afterward instead
    of being shared.
    """
    base_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/finance_report_test_default",
    )
    if "localhost" in base_url:
        base_url = base_url.replace("localhost", "127.0.0.1")
    db_name = f"enum_drift_cleanup_test_{worker_id}_{uuid4().hex[:8]}"
    url = make_url(base_url).set(database=db_name)
    admin_url = url.set(database="postgres")

    admin_engine: AsyncEngine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin_engine.connect() as conn:
        await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    await admin_engine.dispose()

    engine: AsyncEngine = create_async_engine(url, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose()
        admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        await admin_engine.dispose()


async def test_0064_enum_drift_cleanup_converges_db_enums_to_code_red_then_green(
    enum_drift_engine: AsyncEngine,
):
    """0064 must make the DB label set of every enum it touches IDENTICAL to the
    code side -- the same bidirectional comparison infra2's pre-deploy schema gate
    runs (#698 / infra2 PR #783).

    Red: after simulating 0063_enum_case_compat's mistake (uppercase orphans, both
    environments), the prod-only legacy-lowercase orphans, and the independent
    llm_protocol_family_enum forward-gap (code declares 'google-gemini', DB was
    never migrated to add it), every one of the 6 affected enums provably diverges
    from the code side.

    Green: after running 0064's ``upgrade()`` against the same database, every one
    of those 6 enums' DB label set exactly equals the code side -- zero
    discrepancies, matching what an actual gate run against the live-fixed
    databases would report.
    """
    code_side: dict[str, set[str]] = {
        enum_name: {member.value for member in enum_cls} for enum_name, enum_cls in _CODE_ENUMS_UNDER_TEST.items()
    }

    engine = enum_drift_engine

    # --- Simulate the pre-0064 drift on this fresh, otherwise-undrifted schema ---
    async with engine.begin() as conn:
        for enum_name, orphans in {**_UPPERCASE_ORPHAN_DRIFT, **_LOWERCASE_ORPHAN_DRIFT}.items():
            for orphan in orphans:
                await conn.execute(text(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{orphan}'"))

    async with engine.begin() as conn:
        # llm_protocol_family_enum: rebuild without 'google-gemini' -- simulates the
        # code side having added a value with no migration ever adding the DB label.
        await conn.execute(text(f"ALTER TYPE {_LLM_PROTOCOL_FAMILY_ENUM} RENAME TO {_LLM_PROTOCOL_FAMILY_ENUM}_pre64"))
        values = ", ".join(f"'{v}'" for v in _LLM_PROTOCOL_FAMILY_WITHOUT_GEMINI)
        await conn.execute(text(f"CREATE TYPE {_LLM_PROTOCOL_FAMILY_ENUM} AS ENUM ({values})"))
        await conn.execute(
            text(
                f"ALTER TABLE llm_providers ALTER COLUMN protocol TYPE {_LLM_PROTOCOL_FAMILY_ENUM} "
                f"USING protocol::text::{_LLM_PROTOCOL_FAMILY_ENUM}"
            )
        )
        await conn.execute(text(f"DROP TYPE {_LLM_PROTOCOL_FAMILY_ENUM}_pre64"))

    # --- Red: DB and code diverge for every one of these enums ---
    async with engine.connect() as conn:
        for enum_name, code_values in code_side.items():
            db_values = await _db_enum_labels(conn, enum_name)
            assert db_values != code_values, (
                f"expected {enum_name} to be drifted before 0064 runs (red); "
                f"db={sorted(db_values)} code={sorted(code_values)}"
            )

    # --- Run the migration under test ---
    migration = _load_migration_module()
    run_upgrade = _migration_step_runner(migration, "upgrade")

    async with engine.connect() as conn:
        await conn.run_sync(run_upgrade)
        await conn.commit()

    # --- Green: DB now matches code exactly for every one of these enums ---
    async with engine.connect() as conn:
        for enum_name, code_values in code_side.items():
            db_values = await _db_enum_labels(conn, enum_name)
            assert db_values == code_values, (
                f"{enum_name} still diverges from code after 0064: db={sorted(db_values)} code={sorted(code_values)}"
            )

    # --- Idempotent: re-running upgrade() against the now-clean database is a
    #     no-op and does not error (this migration must be safely re-runnable). ---
    async with engine.connect() as conn:
        await conn.run_sync(run_upgrade)
        await conn.commit()

    async with engine.connect() as conn:
        for enum_name, code_values in code_side.items():
            db_values = await _db_enum_labels(conn, enum_name)
            assert db_values == code_values


async def test_0064_downgrade_restores_pre_upgrade_label_set(enum_drift_engine: AsyncEngine):
    """downgrade() must restore the EXACT pre-0064 (0063-drifted) label set for the
    5 orphan-label enums it rebuilds -- full label-SET equality, the same strength
    as the upgrade red/green assertions above, not a weaker "the orphan label is
    present again" check.

    Schema-reversible, NOT data-reversible (see ``0064_enum_drift_cleanup.py``'s
    ``downgrade()`` docstring): this test only proves the enum TYPE's label set
    round-trips. It does not assert anything about row-level casing, because
    upgrade()'s defensive UPDATE has nothing to normalize in this test's synthetic
    setup (no rows are inserted) -- matching the live databases, where that UPDATE
    was independently verified to affect 0 rows.

    ``llm_protocol_family_enum`` is deliberately excluded from the "restores
    exactly" assertion: downgrade() cannot remove its additive 'google-gemini'
    label (Postgres has no DROP VALUE) and is not supposed to -- that label stays,
    proven separately below.
    """
    engine = enum_drift_engine

    # --- Simulate the pre-0064 drift, same as the upgrade test ---
    async with engine.begin() as conn:
        for enum_name, orphans in {**_UPPERCASE_ORPHAN_DRIFT, **_LOWERCASE_ORPHAN_DRIFT}.items():
            for orphan in orphans:
                await conn.execute(text(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{orphan}'"))

    # Sanity: the simulated drift actually matches what downgrade() must restore,
    # before any migration step runs.
    async with engine.connect() as conn:
        for enum_name, pre_upgrade_labels in _PRE_UPGRADE_LABEL_SET.items():
            assert await _db_enum_labels(conn, enum_name) == pre_upgrade_labels

    migration = _load_migration_module()
    run_upgrade = _migration_step_runner(migration, "upgrade")
    run_downgrade = _migration_step_runner(migration, "downgrade")

    # --- upgrade(): rebuilds each enum down to just its canonical labels ---
    async with engine.connect() as conn:
        await conn.run_sync(run_upgrade)
        await conn.commit()

    # --- Red: right after upgrade(), the label set does NOT yet match the
    #     pre-upgrade (0063-drifted) set -- downgrade() has not run yet. This is
    #     the literal red checkpoint for the round-trip this test proves. ---
    async with engine.connect() as conn:
        for enum_name, pre_upgrade_labels in _PRE_UPGRADE_LABEL_SET.items():
            db_values = await _db_enum_labels(conn, enum_name)
            assert db_values != pre_upgrade_labels, (
                f"expected {enum_name} to NOT yet match the pre-upgrade set before "
                f"downgrade() runs (red); db={sorted(db_values)} pre_upgrade={sorted(pre_upgrade_labels)}"
            )

    # --- Run downgrade() ---
    async with engine.connect() as conn:
        await conn.run_sync(run_downgrade)
        await conn.commit()

    # --- Green: downgrade() restored the EXACT pre-upgrade label set for every
    #     one of the 5 rebuilt enums -- full set equality. ---
    async with engine.connect() as conn:
        for enum_name, pre_upgrade_labels in _PRE_UPGRADE_LABEL_SET.items():
            db_values = await _db_enum_labels(conn, enum_name)
            assert db_values == pre_upgrade_labels, (
                f"downgrade() did not restore {enum_name} to its pre-upgrade label set: "
                f"db={sorted(db_values)} pre_upgrade={sorted(pre_upgrade_labels)}"
            )

    # --- llm_protocol_family_enum: downgrade() never touches it; the additive
    #     'google-gemini' label from upgrade() stays (no DROP VALUE in Postgres). ---
    code_llm_values = {member.value for member in ProtocolFamily}
    async with engine.connect() as conn:
        db_llm_values = await _db_enum_labels(conn, _LLM_PROTOCOL_FAMILY_ENUM)
        assert db_llm_values == code_llm_values, (
            f"llm_protocol_family_enum should be unaffected by downgrade(): "
            f"db={sorted(db_llm_values)} code={sorted(code_llm_values)}"
        )
