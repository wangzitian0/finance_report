"""Migration lock for #1969's active-head schema repair."""

from __future__ import annotations

import ast
from pathlib import Path


def test_AC_reconciliation_economic_disposition_2_migration_repairs_before_locking() -> None:
    """AC-reconciliation.economic-disposition.2: dirty history upgrades losslessly."""
    path = Path(__file__).resolve().parents[2] / "migrations/versions/0058_economic_disposition.py"
    source = path.read_text(encoding="utf-8")
    ast.parse(source)
    repair = source.index("WITH ranked AS")
    unique_index = source.index('"uq_reconciliation_matches_active_atomic_txn"')
    assert repair < unique_index
    assert "first_value(id)" in source
    assert "SET status = 'superseded'" in source
    assert "superseded_by_id = ranked.winner_id" in source
    assert "DROP" not in source[repair:unique_index]
