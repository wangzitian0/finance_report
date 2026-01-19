from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

# Paths relative to this test file: apps/backend/tests/test_migrations.py
BACKEND_DIR = Path(__file__).parent.parent
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
