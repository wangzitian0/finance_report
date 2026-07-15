"""Single-owner proof for confidence-tier rollup."""

from __future__ import annotations

import ast
from pathlib import Path

from src.ledger import worst_confidence_tier

BACKEND_SRC = Path(__file__).resolve().parents[2] / "src"


def test_AC_ledger_78_1_worst_confidence_tier_is_single_homed() -> None:
    """AC-ledger.78.1: one rank function serves reporting and advisor."""
    definitions: list[tuple[Path, str]] = []
    for package in ("ledger", "reporting", "advisor"):
        for path in (BACKEND_SRC / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "worst_confidence_tier" in node.name:
                    definitions.append((path, node.name))

    assert definitions == [(BACKEND_SRC / "ledger" / "orm" / "journal.py", "worst_confidence_tier")]
    assert worst_confidence_tier(["HIGH", "LOW", "TRUSTED"]) == "LOW"
    assert worst_confidence_tier(["HIGH", "UNAVAILABLE", "LOW"]) == "UNAVAILABLE"
    assert worst_confidence_tier([None], default="DETERMINISTIC") == "DETERMINISTIC"
