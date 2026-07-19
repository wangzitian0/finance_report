"""Ownership proof for pricing's legacy manual-valuation persistence adapter."""

from __future__ import annotations

import ast
from pathlib import Path

from src.database import Base
from src.pricing.orm.manual_valuation import ManualValuationSnapshot


def _dotted_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else None
    return None


def test_AC_pricing_manualvaluation_10_pricing_owns_the_manual_valuation_mapping() -> None:
    """AC-pricing.manualvaluation.10: pricing maps the legacy table exclusively."""
    repo_root = Path(__file__).resolve().parents[4]

    assert ManualValuationSnapshot.__tablename__ == "manual_valuation_snapshots"
    assert Base.metadata.tables["manual_valuation_snapshots"] is ManualValuationSnapshot.__table__

    production_sources = (repo_root / "apps/backend/src").rglob("*.py")
    offenders: set[str] = set()
    for path in production_sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        layer3_aliases: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "src.extraction.orm.layer3":
                        layer3_aliases.add(alias.asname or alias.name)
                continue
            if isinstance(node, ast.ImportFrom):
                if node.module == "src.extraction.orm.layer3" and any(
                    alias.name == "*" or alias.name.startswith("ManualValuation") for alias in node.names
                ):
                    offenders.add(path.relative_to(repo_root).as_posix())
                if node.module == "src.extraction.orm":
                    for alias in node.names:
                        if alias.name == "layer3":
                            layer3_aliases.add(alias.asname or alias.name)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            qualified_name = _dotted_name(node)
            if qualified_name is None:
                continue
            if any(qualified_name.startswith(f"{binding}.ManualValuation") for binding in layer3_aliases):
                offenders.add(path.relative_to(repo_root).as_posix())
    assert offenders == set()
