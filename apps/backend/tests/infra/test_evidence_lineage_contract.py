"""Evidence Graph foundation contract tests."""

from pathlib import Path

import pytest

from src.models.evidence import EvidenceEdge, EvidenceNode

REPO_ROOT = Path(__file__).parents[4]
SSOT_PATH = REPO_ROOT / "docs" / "ssot" / "evidence-lineage.md"

pytestmark = pytest.mark.no_db


def test_AC18_7_1_evidence_lineage_ssot_defines_graph_semantics():
    """AC-extraction.1807.1: AC18.7.1: Evidence lineage SSOT defines node, edge, identity, and traversal semantics."""
    source = SSOT_PATH.read_text()

    assert "node = auditable state" in source
    assert "edge = transformation or calculation process" in source
    assert "user_id + node_kind + entity_type + entity_id" in source
    assert "user_id + from_node_id + to_node_id + relation" in source
    assert "The default maximum traversal depth is 6" in source


def test_AC18_7_3_evidence_lineage_models_expose_jsonb_user_owned_graph_tables():
    """AC-extraction.1807.3: AC18.7.3: Evidence lineage models expose user-owned graph tables with JSONB properties."""
    assert EvidenceNode.__tablename__ == "evidence_nodes"
    assert EvidenceEdge.__tablename__ == "evidence_edges"
    assert EvidenceNode.__table__.c.user_id.foreign_keys
    assert EvidenceEdge.__table__.c.user_id.foreign_keys
    assert EvidenceNode.__table__.c.properties.type.__class__.__name__ == "JSONB"
    assert EvidenceEdge.__table__.c.properties.type.__class__.__name__ == "JSONB"
    assert "uq_evidence_nodes_user_entity" in {constraint.name for constraint in EvidenceNode.__table__.constraints}
    assert "uq_evidence_edges_user_relation" in {constraint.name for constraint in EvidenceEdge.__table__.constraints}
