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
    repo_root = Path(__file__).resolve().parents[4]
    assert (
        ManualValuationSnapshot.__tablename__,
        Base.metadata.tables["manual_valuation_snapshots"] is ManualValuationSnapshot.__table__,
    ) == ("manual_valuation_snapshots", True)
    offenders: set[str] = set()
    for path in (repo_root / "apps/backend/src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "layer3" not in text:
            continue
        tree = ast.parse(text, filename=str(path))
        aliases: set[str] = set()
        rel = path.relative_to(repo_root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                aliases.update(a.asname or a.name for a in node.names if a.name == "src.extraction.orm.layer3")
            elif isinstance(node, ast.ImportFrom):
                if node.module == "src.extraction.orm.layer3" and any(
                    a.name == "*" or a.name.startswith("ManualValuation") for a in node.names
                ):
                    offenders.add(rel)
                if node.module == "src.extraction.orm":
                    aliases.update(a.asname or a.name for a in node.names if a.name == "layer3")
            elif (
                isinstance(node, ast.Attribute)
                and (q := _dotted_name(node))
                and any(q.startswith(f"{b}.ManualValuation") for b in aliases)
            ):
                offenders.add(rel)
    assert offenders == set()
