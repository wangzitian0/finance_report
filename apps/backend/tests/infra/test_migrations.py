from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

import src.orm_registry  # noqa: F401  -- eager-imports every model module onto Base.metadata
from src.database import Base

# Paths relative to this test file: apps/backend/tests/infra/test_migrations.py
BACKEND_DIR = Path(__file__).parent.parent.parent
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"
SCRIPT_LOCATION = BACKEND_DIR / "migrations"


@pytest.fixture
def alembic_script():
    """Load the Alembic script directory configuration."""
    if not ALEMBIC_INI_PATH.exists():
        pytest.fail(f"alembic.ini not found at {ALEMBIC_INI_PATH}")

    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(SCRIPT_LOCATION))
    return ScriptDirectory.from_config(config)


def test_revision_id_length(alembic_script):
    """
    Ensure all revision IDs are within the 32-character limit of Alembic's default version table.
    Exceeding this causes 'sqlalchemy.exc.DataError: value too long for type character varying(32)'.
    """
    revisions = []
    # walk_revisions iterates from head to base
    for script in alembic_script.walk_revisions("base", "head"):
        revisions.append(script)
        assert len(script.revision) <= 32, (
            f"Revision ID '{script.revision}' is too long ({len(script.revision)} chars). "
            f"Max allowed is 32 chars to avoid DB truncation errors."
        )


def test_single_head(alembic_script):
    """
    Ensure the migration graph has only one head (linear history).
    Multiple heads indicate likely merge conflicts or diverging branches.
    """
    heads = alembic_script.get_heads()
    assert len(heads) == 1, f"Migration graph has multiple heads: {heads}. History must be linear."


def test_sqlalchemy_metadata_and_alembic_graph_are_valid(alembic_script):
    """AC1.2.3: SQLAlchemy models are registered and Alembic has a valid linear graph."""
    expected_tables = {
        "accounts",
        "statement_summaries",
        "atomic_transactions",
        "journal_entries",
        "journal_lines",
        "reconciliation_matches",
        "users",
    }

    assert expected_tables <= set(Base.metadata.tables)

    revisions = list(alembic_script.walk_revisions("base", "head"))
    assert revisions
    assert len(alembic_script.get_heads()) == 1
    assert any(revision.down_revision is None for revision in revisions)


def test_AC13_10_4_source_type_migration_handles_missing_legacy_enum_label():
    """AC-extraction.110.4: legacy source_type cleanup must tolerate production enum drift."""
    migration = SCRIPT_LOCATION / "versions" / "0018_source_type_priority.py"
    source = migration.read_text()

    assert "ADD VALUE IF NOT EXISTS 'bank_statement'" in source
    assert "source_type::text = 'bank_statement'" in source
    assert "WHERE source_type = 'bank_statement'" not in source


def test_AC13_10_4_retire_bank_statement_value_is_drift_tolerant():
    """AC-extraction.110.4: dropping the legacy bank_statement enum value must tolerate drift.

    0040 (#896) removes 'bank_statement' from journal_source_type_enum. It must
    (a) re-run the defensive data collapse first so the type rebuild cannot fail
    on a stray row, including uppercase/mixed-case legacy values, (b) only
    rebuild when the label is actually present, and (c) never compare with a raw
    enum literal that would error if the label is absent.
    """
    migration = SCRIPT_LOCATION / "versions" / "0040_retire_bank_stmt_source.py"
    source = migration.read_text()

    # Defensive, text-cast data collapse before any type surgery.
    assert "UPDATE journal_entries" in source
    assert "SET source_type = 'auto_parsed'" in source
    assert "WHERE lower(source_type::text) = 'bank_statement'" in source
    assert "WHEN lower(source_type::text) = 'bank_statement' THEN 'auto_parsed'" in source
    # Rebuild is guarded on the label actually existing (no-op otherwise).
    assert "e.enumlabel = 'bank_statement'" in source
    # Reversible: the label can be re-added without assuming its absence.
    assert "ADD VALUE IF NOT EXISTS 'bank_statement'" in source
    # Never a naive enum-literal comparison that errors when the label is gone.
    assert "WHERE source_type = 'bank_statement'" not in source
