"""Evidence Graph migration contract tests."""

from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).parent.parent.parent
MIGRATION_PATH = BACKEND_DIR / "migrations" / "versions" / "0025_add_evidence_lineage.py"

pytestmark = pytest.mark.no_db


def test_AC18_7_2_evidence_lineage_migration_creates_tables_and_indexes():
    """AC18.7.2: Evidence lineage migration creates graph tables and traversal indexes."""
    source = MIGRATION_PATH.read_text()

    assert 'op.create_table("evidence_nodes"' in source
    assert 'op.create_table("evidence_edges"' in source
    assert "uq_evidence_nodes_user_entity" in source
    assert "uq_evidence_edges_user_relation" in source
    assert "idx_evidence_edges_user_from" in source
    assert "idx_evidence_edges_user_to" in source
    assert "idx_evidence_edges_user_relation_from" in source
    assert "idx_evidence_edges_user_relation_to" in source
