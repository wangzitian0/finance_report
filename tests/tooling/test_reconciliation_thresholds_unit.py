"""Focused unit tests for reconciliation threshold and rerun behavior.

AC4.6.1 AC4.6.2: Score thresholds and amount boundaries are enforced.
"""

from __future__ import annotations

import importlib
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "backend"))

import src.orm_registry  # noqa: E402, F401  -- register all ORM mappers before relationship config
from src.reconciliation import ReconciliationMatch, ReconciliationStatus  # noqa: E402


def _load_reconciliation_module():
    """Load reconciliation matching module under the package-model location."""
    return importlib.import_module("src.reconciliation.extension.matching")


reconciliation_module = _load_reconciliation_module()
MatchCandidate = reconciliation_module.MatchCandidate
execute_matching = reconciliation_module.execute_matching


class _ScalarResult:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def scalars(self) -> _ScalarResult:
        return self

    def __iter__(self):
        return iter(self._items)

    def all(self) -> list[object]:
        return self._items

    def scalar_one_or_none(self) -> object | None:
        if not self._items:
            return None
        return self._items[0]


def _make_pending_txn() -> SimpleNamespace:
    # Mimics a pending Layer-2 AtomicTransaction (no per-row status column).
    return SimpleNamespace(
        id=uuid4(),
        statement_id=uuid4(),
        txn_date=date(2024, 5, 20),
        description="Payroll transfer",
        amount=Decimal("100.00"),
        direction="IN",
    )


def _make_entry() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        entry_date=date(2024, 5, 20),
        memo="Payroll transfer",
    )


def _make_db(*, txn: object, entry: object) -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult([txn]),
            _ScalarResult([entry]),
            _ScalarResult([]),
        ]
    )
    db.flush = AsyncMock()
    db.add = Mock()
    return db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "expected_status", "expected_match_count"),
    [
        (85, ReconciliationStatus.AUTO_ACCEPTED, 1),
        (84, ReconciliationStatus.PENDING_REVIEW, 1),
        (60, ReconciliationStatus.PENDING_REVIEW, 1),
        (59, None, 0),
    ],
)
async def test_execute_matching_score_thresholds(
    score: int,
    expected_status: ReconciliationStatus | None,
    expected_match_count: int,
) -> None:
    """AC4.3.1 · AC4.3.2 · Scores map to auto-accept, review, and unmatched bands."""
    txn = _make_pending_txn()
    entry = _make_entry()
    db = _make_db(txn=txn, entry=entry)

    candidate = MatchCandidate(
        journal_entry_ids=[],
        score=score,
        breakdown={"amount": 100.0},
    )

    with (
        patch.object(
            reconciliation_module, "detect_transfer_pattern", return_value=False
        ),
        patch.object(reconciliation_module, "is_entry_balanced", return_value=True),
        patch.object(
            reconciliation_module, "score_pattern", new=AsyncMock(return_value=0.0)
        ),
        patch.object(
            reconciliation_module,
            "calculate_match_score",
            new=AsyncMock(return_value=candidate),
        ),
        patch.object(
            reconciliation_module, "find_transfer_pairs", new=AsyncMock(return_value=[])
        ),
        patch.object(
            reconciliation_module,
            "_get_existing_active_match",
            new=AsyncMock(return_value=None),
        ),
    ):
        matches = await execute_matching(db, user_id=uuid4())

    assert len(matches) == expected_match_count
    # bank-txn.status is no longer mutated under the Layer-2 read path (Stage 3 removes it)

    if expected_status is None:
        db.add.assert_not_called()
        return

    db.add.assert_called_once()
    created_match = db.add.call_args.args[0]
    assert isinstance(created_match, ReconciliationMatch)
    assert created_match.status == expected_status
    assert created_match.match_score == score
    assert matches[0] is created_match


@pytest.mark.asyncio
async def test_execute_matching_rerun_is_idempotent_for_same_match() -> None:
    """AC4.6.2 · Rerunning reconciliation with the same winning entry creates no duplicate match."""
    txn = _make_pending_txn()
    entry = _make_entry()
    db = _make_db(txn=txn, entry=entry)

    existing_match = ReconciliationMatch(
        atomic_txn_id=txn.id,
        journal_entry_ids=[str(entry.id)],
        match_score=92,
        score_breakdown={"amount": 100.0},
        status=ReconciliationStatus.AUTO_ACCEPTED,
    )
    candidate = MatchCandidate(
        journal_entry_ids=[str(entry.id)],
        score=92,
        breakdown={"amount": 100.0},
    )

    with (
        patch.object(
            reconciliation_module, "detect_transfer_pattern", return_value=False
        ),
        patch.object(reconciliation_module, "is_entry_balanced", return_value=True),
        patch.object(
            reconciliation_module, "score_pattern", new=AsyncMock(return_value=0.0)
        ),
        patch.object(
            reconciliation_module,
            "calculate_match_score",
            new=AsyncMock(return_value=candidate),
        ),
        patch.object(
            reconciliation_module, "find_transfer_pairs", new=AsyncMock(return_value=[])
        ),
        patch.object(
            reconciliation_module,
            "_get_existing_active_match",
            new=AsyncMock(return_value=existing_match),
        ),
    ):
        matches = await execute_matching(db, user_id=uuid4())

    assert matches == []
    assert existing_match.status == ReconciliationStatus.AUTO_ACCEPTED
    db.add.assert_not_called()
