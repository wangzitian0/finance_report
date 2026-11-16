"""Migration 0076: one live answer for each row and rule version, and superseded answers stay as history (#2994)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.extraction.test_statement_runs import _alembic, _database_url

PRIOR_REVISION = "0075_drop_ping_state"
LIVE_KEY_REVISION = "0076_txn_classif_live_unique"
INDEX = "uq_txn_classification_version"
INSERT = text(
    "INSERT INTO transaction_classification (id, atomic_txn_id, rule_version_id, status, created_at, updated_at) "
    "VALUES (:id, :txn, :rule, CAST(:status AS classification_status_enum), NOW(), NOW())"
)


def _index_definition(connection) -> str | None:
    return connection.execute(
        text("SELECT indexdef FROM pg_indexes WHERE tablename = 'transaction_classification' AND indexname = :name"),
        {"name": INDEX},
    ).scalar_one_or_none()


def _is_constraint(connection) -> bool:
    return bool(
        connection.execute(
            text("SELECT count(*) FROM pg_constraint WHERE conname = :name AND contype = 'u'"), {"name": INDEX}
        ).scalar_one()
    )


def _count(connection) -> int:
    return connection.execute(text("SELECT count(*) FROM transaction_classification")).scalar_one()


@pytest.mark.no_db
def test_AC_extraction_2994_143_the_migration_keeps_one_live_answer_and_the_downgrade_stops_on_history():
    """AC-extraction.2994.143: Upgrade makes the key partial; downgrade stops while a pair has history."""
    name = f"fr_ac_2994_143_{uuid4().hex[:12]}"
    admin = create_engine(_database_url("postgres").replace("+asyncpg", ""), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    database_url = _database_url(name)
    engine = create_engine(database_url.replace("+asyncpg", ""))
    user_id, txn_id, rule_id, other_txn_id = uuid4(), uuid4(), uuid4(), uuid4()
    first, second, third, fourth = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        _alembic(database_url, "upgrade", PRIOR_REVISION)
        with engine.begin() as connection:
            assert _is_constraint(connection) and _index_definition(connection) is not None
            connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, ai_settings, created_at, updated_at) "
                    "VALUES (:id, :email, 'generated-hash', CAST('{}' AS jsonb), NOW(), NOW())"
                ),
                {"id": user_id, "email": f"migration-{user_id.hex}@example.test"},
            )
            for identifier in (txn_id, other_txn_id):
                connection.execute(
                    text(
                        "INSERT INTO atomic_transactions (id, user_id, txn_date, amount, direction, description, "
                        "currency, dedup_hash, source_documents, created_at, updated_at) VALUES (:id, :user_id, "
                        "'2026-01-02', 12.50, 'OUT', 'Grab ride', 'SGD', :hash, CAST('[]' AS jsonb), NOW(), NOW())"
                    ),
                    {"id": identifier, "user_id": user_id, "hash": identifier.hex},
                )
            connection.execute(
                text(
                    "INSERT INTO classification_rules (id, user_id, version_number, effective_date, is_active, "
                    "rule_name, rule_type, rule_config, created_by, created_at, updated_at) VALUES (:id, :user_id, 1, "
                    "'2026-01-01', false, 'model', 'ml_model', CAST('{}' AS jsonb), :user_id, NOW(), NOW())"
                ),
                {"id": rule_id, "user_id": user_id},
            )
            connection.execute(INSERT, {"id": first, "txn": txn_id, "rule": rule_id, "status": "applied"})
        with pytest.raises(IntegrityError), engine.begin() as connection:  # the full key holds before the upgrade
            connection.execute(INSERT, {"id": uuid4(), "txn": txn_id, "rule": rule_id, "status": "superseded"})

        _alembic(database_url, "upgrade", LIVE_KEY_REVISION)

        with engine.connect() as connection:
            definition = _index_definition(connection)
            assert not _is_constraint(connection), "the constraint is replaced by an index"
            assert definition is not None
            assert "UNIQUE INDEX" in definition and "(atomic_txn_id, rule_version_id)" in definition
            assert "draft" in definition and "applied" in definition and "superseded" not in definition, definition
            assert _count(connection) == 1, "the upgrade changes no row"
        with pytest.raises(IntegrityError, match=INDEX), engine.begin() as connection:  # a second live answer
            connection.execute(INSERT, {"id": uuid4(), "txn": txn_id, "rule": rule_id, "status": "draft"})
        with engine.begin() as connection:  # superseded answers beside the live one are history
            connection.execute(INSERT, {"id": second, "txn": txn_id, "rule": rule_id, "status": "superseded"})
            connection.execute(INSERT, {"id": third, "txn": txn_id, "rule": rule_id, "status": "superseded"})
            connection.execute(INSERT, {"id": fourth, "txn": other_txn_id, "rule": rule_id, "status": "draft"})

        with pytest.raises(AssertionError, match="Downgrade stopped: 1 row and rule version pairs"):
            _alembic(database_url, "downgrade", PRIOR_REVISION)
        with engine.connect() as connection:
            assert not _is_constraint(connection) and _index_definition(connection) is not None, "nothing changed"
            assert _count(connection) == 4

        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM transaction_classification WHERE id IN (:a, :b)"), {"a": second, "b": third}
            )
        _alembic(database_url, "downgrade", PRIOR_REVISION)
        with engine.connect() as connection:
            assert _is_constraint(connection), "the full unique constraint is back"
            assert _count(connection) == 2
        with pytest.raises(IntegrityError, match=INDEX), engine.begin() as connection:
            connection.execute(INSERT, {"id": uuid4(), "txn": txn_id, "rule": rule_id, "status": "superseded"})

        _alembic(database_url, "upgrade", LIVE_KEY_REVISION)
        with engine.connect() as connection:
            assert not _is_constraint(connection) and _index_definition(connection) is not None
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
