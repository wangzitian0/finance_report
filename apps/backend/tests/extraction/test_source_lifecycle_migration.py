"""Migration contract for #1970's retired source lifecycle state."""

from __future__ import annotations

import ast
from pathlib import Path


def test_AC_extraction_source_lifecycle_4_migration_is_additive() -> None:
    """AC-extraction.source-lifecycle.4: retirement adds states without data deletion."""
    path = Path(__file__).resolve().parents[2] / "migrations/versions/0059_source_lifecycle.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assignments = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {"revision", "down_revision"}
    }
    assert assignments == {
        "revision": "0059_source_lifecycle",
        "down_revision": "0058_economic_disposition",
    }
    assert "ALTER TYPE statement_summary_status_enum ADD VALUE IF NOT EXISTS 'retired'" in source
    assert "ALTER TYPE document_status_enum ADD VALUE IF NOT EXISTS 'retired'" in source
    assert "DELETE FROM" not in source
    assert "DROP TABLE" not in source
