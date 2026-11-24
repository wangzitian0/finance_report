"""Revision 0081 drops the per-user LLM provider tables and their enum types (#2953 stage 3).

Each test clones a database that sits at revision 0080 and runs the real Alembic chain on the clone.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from tests.extraction._statement_run_helpers import BACKEND_DIR, migration_db_url, run_alembic

pytestmark = pytest.mark.no_db

_BEFORE = "0080_stmt_institution_nullable"
_REVISION = "0081_drop_llm_provider_layer"
_TABLES = ("llm_providers", "llm_scene_bindings")
_ENUMS = ("llm_protocol_family_enum", "llm_scene_enum", "llm_reasoning_effort_enum")


def _admin() -> Engine:
    return create_engine(migration_db_url("postgres").replace("+asyncpg", ""), isolation_level="AUTOCOMMIT")


def _create_database(name: str, template: str | None = None) -> None:
    with _admin().connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"' + (f' TEMPLATE "{template}"' if template else "")))


def _drop_database(name: str) -> None:
    with _admin().connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture(scope="module")
def template_at_0080() -> Iterator[str]:
    name = f"fr_2953_template_{uuid4().hex[:10]}"
    _create_database(name)
    try:
        run_alembic(migration_db_url(name), "upgrade", _BEFORE)
        yield name
    finally:
        _drop_database(name)


@pytest.fixture
def clone(template_at_0080: str) -> Iterator[tuple[str, Engine]]:
    name = f"fr_2953_clone_{uuid4().hex[:10]}"
    _create_database(name, template=template_at_0080)
    engine = create_engine(migration_db_url(name).replace("+asyncpg", ""))
    try:
        yield migration_db_url(name), engine
    finally:
        engine.dispose()
        _drop_database(name)


def _existing(engine: Engine) -> tuple[set[str], set[str]]:
    with engine.connect() as connection:
        tables = {t for t in _TABLES if connection.execute(text("SELECT to_regclass(:t)"), {"t": t}).scalar()}
        enums = set(
            connection.execute(text("SELECT typname FROM pg_type WHERE typname = ANY(:names)"), {"names": list(_ENUMS)})
            .scalars()
            .all()
        )
    return tables, enums


def _version(engine: Engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _schema(engine: Engine) -> dict[str, object]:
    """The columns, indexes, constraints and enum labels of the two tables, keyed by name, not by position."""
    with engine.connect() as connection:
        columns = connection.execute(
            text(
                "SELECT table_name, column_name, udt_name, is_nullable, column_default, character_maximum_length "
                "FROM information_schema.columns WHERE table_name = ANY(:t) ORDER BY 1, 2"
            ),
            {"t": list(_TABLES)},
        ).all()
        indexes = connection.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = ANY(:t) ORDER BY 1"),
            {"t": list(_TABLES)},
        ).all()
        constraints = connection.execute(
            text(
                "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid::regclass::text = ANY(:t) ORDER BY 1, 2"
            ),
            {"t": list(_TABLES)},
        ).all()
        labels = connection.execute(
            text(
                "SELECT t.typname, e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
                "WHERE t.typname = ANY(:names) ORDER BY t.typname, e.enumsortorder"
            ),
            {"names": list(_ENUMS)},
        ).all()
    return {
        "columns": [tuple(r) for r in columns],
        "indexes": [tuple(r) for r in indexes],
        "constraints": [tuple(r) for r in constraints],
        "enum_labels": [tuple(r) for r in labels],
    }


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


def _insert_provider(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO llm_providers (id, label, protocol, api_key_ciphertext, api_key_version, created_at, "
                "updated_at) VALUES (:id, 'stored', 'openai-compatible', 'x', 1, NOW(), NOW())"
            ),
            {"id": uuid4()},
        )


def _insert_binding(engine: Engine) -> None:
    with engine.begin() as connection:
        provider_id = connection.execute(text("SELECT id FROM llm_providers LIMIT 1")).scalar_one()
        connection.execute(
            text(
                "INSERT INTO llm_scene_bindings (id, scene, provider_id, model, reasoning, prefer_free, "
                "fallback_model_ids, created_at, updated_at) VALUES (:id, 'advisor.chat', :provider, 'm', 'high', "
                "false, '', NOW(), NOW())"
            ),
            {"id": uuid4(), "provider": provider_id},
        )


def test_the_clone_holds_the_two_tables_and_three_enums_before_the_upgrade(clone) -> None:
    _, engine = clone
    assert _existing(engine) == (set(_TABLES), set(_ENUMS))
    assert _version(engine) == _BEFORE


def test_the_upgrade_drops_both_tables_and_the_three_enums(clone) -> None:
    url, engine = clone
    run_alembic(url, "upgrade", _REVISION)
    assert (_existing(engine), _version(engine)) == ((set(), set()), _REVISION)


@pytest.mark.parametrize(
    ("rows", "messages"),
    [
        (("provider",), ["llm_providers holds 1 row", "llm_scene_bindings holds 0 row"]),
        (("provider", "binding"), ["llm_providers holds 1 row", "llm_scene_bindings holds 1 row"]),
    ],
    ids=["a provider", "a provider and a binding"],
)
def test_a_row_in_either_table_stops_the_upgrade_and_keeps_both_tables(clone, rows, messages) -> None:
    url, engine = clone
    _insert_provider(engine)
    if "binding" in rows:
        _insert_binding(engine)
    with pytest.raises(AssertionError) as stopped:
        run_alembic(url, "upgrade", _REVISION)
    assert all(message in str(stopped.value) for message in messages)
    assert (_existing(engine), _version(engine)) == ((set(_TABLES), set(_ENUMS)), _BEFORE)
    assert _count(engine, "llm_providers") == 1


def test_the_downgrade_restores_the_schema_of_revision_0080(clone) -> None:
    url, engine = clone
    before = _schema(engine)
    assert before["constraints"] and before["indexes"] and before["enum_labels"]
    run_alembic(url, "upgrade", _REVISION)
    run_alembic(url, "downgrade", _BEFORE)
    assert _schema(engine) == before
    assert _version(engine) == _BEFORE


def test_no_orm_model_maps_the_dropped_tables() -> None:
    import src.orm_registry  # noqa: F401
    from src.database import Base

    assert not set(_TABLES) & set(Base.metadata.tables)
    assert not set(_ENUMS) & {
        c.type.name for t in Base.metadata.tables.values() for c in t.columns if hasattr(c.type, "name")
    }


def test_a_row_that_commits_while_the_upgrade_waits_for_the_lock_is_not_dropped(clone) -> None:
    """The upgrade locks the tables before it counts. A writer that commits during the wait is seen by the count."""
    url, engine = clone
    name = engine.url.database
    env = {**os.environ, "DATABASE_URL": url, "ENVIRONMENT": "testing"}
    with engine.connect() as writer:
        writer.execute(
            text(
                "INSERT INTO llm_providers (id, label, protocol, api_key_ciphertext, api_key_version, created_at, "
                "updated_at) VALUES (:id, 'late', 'openai-compatible', 'x', 1, NOW(), NOW())"
            ),
            {"id": uuid4()},
        )
        upgrade = subprocess.Popen(
            [sys.executable, "-m", "alembic", "upgrade", _REVISION],
            cwd=BACKEND_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                with engine.connect() as probe:
                    waiting = probe.execute(
                        text("SELECT COUNT(*) FROM pg_stat_activity WHERE datname = :n AND wait_event_type = 'Lock'"),
                        {"n": name},
                    ).scalar_one()
                if waiting:
                    break
                time.sleep(0.2)
            else:
                pytest.fail("the upgrade never waited for a lock")
            writer.commit()
        finally:
            output = upgrade.communicate(timeout=120)[0]
    assert upgrade.returncode != 0 and "llm_providers holds 1 row" in output, output
    assert (_existing(engine), _version(engine), _count(engine, "llm_providers")) == (
        (set(_TABLES), set(_ENUMS)),
        _BEFORE,
        1,
    )


def test_the_upgrade_runs_on_a_database_that_has_no_such_tables(clone) -> None:
    url, engine = clone
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE llm_scene_bindings"))
        connection.execute(text("DROP TABLE llm_providers"))
        for enum_name in _ENUMS:
            connection.execute(text(f"DROP TYPE {enum_name}"))
    run_alembic(url, "upgrade", _REVISION)
    assert (_existing(engine), _version(engine)) == ((set(), set()), _REVISION)


def test_the_upgrade_runs_again_after_a_downgrade(clone) -> None:
    url, engine = clone
    run_alembic(url, "upgrade", _REVISION)
    run_alembic(url, "downgrade", _BEFORE)
    run_alembic(url, "upgrade", _REVISION)
    assert (_existing(engine), _version(engine)) == ((set(), set()), _REVISION)
