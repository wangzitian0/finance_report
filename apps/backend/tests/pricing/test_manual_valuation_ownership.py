"""Ownership proof for pricing's legacy manual-valuation persistence adapter."""

from __future__ import annotations

import ast
from pathlib import Path

from src.database import Base
from src.pricing.orm.manual_valuation import ManualValuationSnapshot


def test_AC_pricing_manualvaluation_10_pricing_owns_the_manual_valuation_mapping() -> None:
    """AC-pricing.manualvaluation.10: pricing maps the legacy table exclusively."""
    repo_root = Path(__file__).resolve().parents[4]

    assert ManualValuationSnapshot.__tablename__ == "manual_valuation_snapshots"
    assert Base.metadata.tables["manual_valuation_snapshots"] is ManualValuationSnapshot.__table__

    production_sources = (repo_root / "apps/backend/src").rglob("*.py")
    offenders = []
    for path in production_sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module != "src.extraction.orm.layer3":
                continue
            if any(alias.name.startswith("ManualValuation") for alias in node.names):
                offenders.append(path.relative_to(repo_root).as_posix())
    assert offenders == []
