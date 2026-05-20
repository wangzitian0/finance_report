"""Focused unit tests for reconciliation threshold and rerun behavior."""

from __future__ import annotations

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

from src.models import BankTransactionStatus, ReconciliationMatch, ReconciliationStatus  # noqa: E402
from src.services.reconciliation import MatchCandidate, execute_matching  # noqa: E402


class _ScalarResult:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[object]:
        return self._items


def _make_pending_txn() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        statement_id=uuid4(),
        txn_date=date(2024, 5, 20),
        description="Payroll transfer",
        amount=Decimal("100.00"),
        direction="IN",
        status=BankTransactionStatus.PENDING,
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
        ]
    )
    db.flush = AsyncMock()
    db.add = Mock()
    return db


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("score", "expected_status", "expected_txn_status", "expected_match_count"),
    [
        (85, ReconciliationStatus.AUTO_ACCEPTED, BankTransactionStatus.MATCHED, 1),
        (84, ReconciliationStatus.PENDING_REVIEW, BankTransactionStatus.PENDING, 1),
        (60, ReconciliationStatus.PENDING_REVIEW, BankTransactionStatus.PENDING, 1),
        (59, None, BankTransactionStatus.UNMATCHED, 0),
    ],
)
async def test_execute_matching_score_thresholds(
    score: int,
    expected_status: ReconciliationStatus | None,
    expected_txn_status: BankTransactionStatus,
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
        patch("src.services.reconciliation._validate_layer_consistency", new=AsyncMock()),
        patch("src.services.reconciliation.detect_transfer_pattern", return_value=False),
        patch("src.services.reconciliation.is_entry_balanced", return_value=True),
        patch("src.services.reconciliation.score_pattern", new=AsyncMock(return_value=0.0)),
        patch("src.services.reconciliation.calculate_match_score", new=AsyncMock(return_value=candidate)),
        patch("src.services.reconciliation.find_transfer_pairs", new=AsyncMock(return_value=[])),
        patch("src.services.reconciliation._get_existing_active_match", new=AsyncMock(return_value=None)),
    ):
        matches = await execute_matching(db, user_id=uuid4(), statement_id=txn.statement_id)

    assert len(matches) == expected_match_count
    assert txn.status == expected_txn_status

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
        bank_txn_id=txn.id,
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
        patch("src.services.reconciliation._validate_layer_consistency", new=AsyncMock()),
        patch("src.services.reconciliation.detect_transfer_pattern", return_value=False),
        patch("src.services.reconciliation.is_entry_balanced", return_value=True),
        patch("src.services.reconciliation.score_pattern", new=AsyncMock(return_value=0.0)),
        patch("src.services.reconciliation.calculate_match_score", new=AsyncMock(return_value=candidate)),
        patch("src.services.reconciliation.find_transfer_pairs", new=AsyncMock(return_value=[])),
        patch(
            "src.services.reconciliation._get_existing_active_match",
            new=AsyncMock(return_value=existing_match),
        ),
    ):
        matches = await execute_matching(db, user_id=uuid4(), statement_id=txn.statement_id)

    assert matches == []
    assert txn.status == BankTransactionStatus.PENDING
    assert existing_match.status == ReconciliationStatus.AUTO_ACCEPTED
    db.add.assert_not_called()
