"""Falsifiable ownership guard for ManagedPosition, PositionStatus, and CostBasisMethod."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.database import Base
from src.portfolio import CostBasisMethod, ManagedPosition, PositionStatus

pytestmark = pytest.mark.no_db

_MOVED_SYMBOLS = frozenset({"ManagedPosition", "PositionStatus", "CostBasisMethod"})


def test_AC_portfolio_managed_position_ownership() -> None:
    """ManagedPosition, PositionStatus, and CostBasisMethod live in portfolio, not extraction."""
    import src.extraction as extraction_pkg
    import src.extraction.orm.layer3 as layer3_mod

    assert ManagedPosition.__tablename__ == "managed_positions"
    assert Base.metadata.tables["managed_positions"] is ManagedPosition.__table__
    assert ManagedPosition.__module__ == "src.portfolio.orm.portfolio"
    assert PositionStatus.__module__ == "src.portfolio.orm.portfolio"
    assert CostBasisMethod.__module__ == "src.portfolio.orm.portfolio"

    for sym in _MOVED_SYMBOLS:
        assert not hasattr(extraction_pkg, sym), f"src.extraction still exports {sym}"
        assert not hasattr(layer3_mod, sym), f"src.extraction.orm.layer3 still defines {sym}"

    repo_root = Path(__file__).resolve().parents[4]
    offenders: list[str] = []
    for search_root in (repo_root / "apps/backend/src", repo_root / "apps/backend/tests"):
        for path in sorted(search_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            rel = path.relative_to(repo_root).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in {
                    "src.extraction",
                    "src.extraction.orm.layer3",
                }:
                    for alias in node.names:
                        if alias.name in _MOVED_SYMBOLS or alias.name == "*":
                            offenders.append(f"{rel}:{node.lineno} imports {alias.name} from {node.module}")
    assert offenders == [], f"Unexpected extraction imports of portfolio position symbols: {offenders}"
