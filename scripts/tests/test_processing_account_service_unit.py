"""Focused unit tests for processing account pairing and visibility helpers."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "backend"))

from src.models import (  # noqa: E402
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.services.processing_account import (  # noqa: E402
    _calculate_pair_confidence,
    find_transfer_pairs,
    get_processing_balance,
    list_processing_transfer_legs,
)


class _ScalarUniqueResult:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def scalars(self) -> _ScalarUniqueResult:
        return self

    def unique(self) -> _ScalarUniqueResult:
        return self

    def all(self) -> list[object]:
        return self._items


def _make_transfer_entry(
    *,
    user_id,
    processing_account_id,
    other_account_id,
    other_account_name: str,
    amount: Decimal,
    entry_date: date,
    memo: str,
    processing_direction: Direction,
) -> JournalEntry:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        status=JournalEntryStatus.POSTED,
        source_type=JournalEntrySourceType.SYSTEM,
    )
    processing_line = JournalLine(
        journal_entry=entry,
        account_id=processing_account_id,
        direction=processing_direction,
        amount=amount,
        currency="SGD",
    )
    other_line = JournalLine(
        journal_entry=entry,
        account_id=other_account_id,
        direction=Direction.CREDIT if processing_direction == Direction.DEBIT else Direction.DEBIT,
        amount=amount,
        currency="SGD",
    )
    other_line.account = Account(
        id=other_account_id,
        user_id=user_id,
        name=other_account_name,
        code="1001",
        type=AccountType.ASSET,
        currency="SGD",
    )
    entry.lines.extend([processing_line, other_line])
    return entry


@pytest.mark.asyncio
async def test_find_transfer_pairs_delayed_transfer_auto_pairs() -> None:
    """AC15.6.4 · Delayed transfers within three days still auto-pair through Processing."""
    user_id = uuid4()
    processing_account = SimpleNamespace(id=uuid4(), currency="SGD")
    out_entry = _make_transfer_entry(
        user_id=user_id,
        processing_account_id=processing_account.id,
        other_account_id=uuid4(),
        other_account_name="Cash",
        amount=Decimal("100.00"),
        entry_date=date(2024, 5, 1),
        memo="Transfer to savings",
        processing_direction=Direction.DEBIT,
    )
    in_entry = _make_transfer_entry(
        user_id=user_id,
        processing_account_id=processing_account.id,
        other_account_id=uuid4(),
        other_account_name="Savings",
        amount=Decimal("100.00"),
        entry_date=date(2024, 5, 4),
        memo="Transfer to savings",
        processing_direction=Direction.CREDIT,
    )

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarUniqueResult([out_entry, in_entry]))

    with patch(
        "src.services.processing_account.get_or_create_processing_account",
        new=AsyncMock(return_value=processing_account),
    ):
        pairs = await find_transfer_pairs(db, user_id, threshold=85)

    assert len(pairs) == 1
    assert pairs[0].confidence >= 85
    assert pairs[0].score_breakdown["date"] == 85.0


@pytest.mark.asyncio
async def test_find_transfer_pairs_keeps_partial_match_in_review_band() -> None:
    """AC15.4.3 · Partial transfer matches stay visible for review instead of auto-pairing."""
    user_id = uuid4()
    processing_account = SimpleNamespace(id=uuid4(), currency="SGD")
    out_entry = _make_transfer_entry(
        user_id=user_id,
        processing_account_id=processing_account.id,
        other_account_id=uuid4(),
        other_account_name="Cash",
        amount=Decimal("100.00"),
        entry_date=date(2024, 5, 1),
        memo="Wire to reserve",
        processing_direction=Direction.DEBIT,
    )
    in_entry = _make_transfer_entry(
        user_id=user_id,
        processing_account_id=processing_account.id,
        other_account_id=uuid4(),
        other_account_name="Reserve",
        amount=Decimal("100.00"),
        entry_date=date(2024, 5, 8),
        memo="Wire from reserve",
        processing_direction=Direction.CREDIT,
    )

    confidence, _ = _calculate_pair_confidence(out_entry, in_entry, processing_account.id)
    assert 60 <= confidence < 85

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarUniqueResult([out_entry, in_entry]))

    with patch(
        "src.services.processing_account.get_or_create_processing_account",
        new=AsyncMock(return_value=processing_account),
    ):
        review_pairs = await find_transfer_pairs(db, user_id, threshold=60)
        auto_pairs = await find_transfer_pairs(db, user_id, threshold=85)

    assert len(review_pairs) == 1
    assert review_pairs[0].confidence == confidence
    assert auto_pairs == []


@pytest.mark.asyncio
async def test_find_transfer_pairs_rejects_unmatched_pair() -> None:
    """AC15.6.5 · Clearly unmatched transfers stay unpaired and visible in Processing."""
    user_id = uuid4()
    processing_account = SimpleNamespace(id=uuid4(), currency="SGD")
    out_entry = _make_transfer_entry(
        user_id=user_id,
        processing_account_id=processing_account.id,
        other_account_id=uuid4(),
        other_account_name="Cash",
        amount=Decimal("100.00"),
        entry_date=date(2024, 5, 1),
        memo="Move to reserve",
        processing_direction=Direction.DEBIT,
    )
    in_entry = _make_transfer_entry(
        user_id=user_id,
        processing_account_id=processing_account.id,
        other_account_id=uuid4(),
        other_account_name="Brokerage",
        amount=Decimal("55.00"),
        entry_date=date(2024, 5, 20),
        memo="Payroll settlement",
        processing_direction=Direction.CREDIT,
    )

    confidence, breakdown = _calculate_pair_confidence(out_entry, in_entry, processing_account.id)
    assert confidence < 60
    assert breakdown["amount"] < 70.0

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarUniqueResult([out_entry, in_entry]))

    with patch(
        "src.services.processing_account.get_or_create_processing_account",
        new=AsyncMock(return_value=processing_account),
    ):
        pairs = await find_transfer_pairs(db, user_id, threshold=60)

    assert pairs == []


@pytest.mark.asyncio
async def test_processing_balance_uses_decimal_net_balance() -> None:
    """AC15.3.1 · Processing balance keeps unpaired funds visible as a Decimal net balance."""
    processing_account = SimpleNamespace(id=uuid4(), currency="SGD")
    debit_line = SimpleNamespace(direction=Direction.DEBIT, amount=Decimal("120.00"))
    credit_line = SimpleNamespace(direction=Direction.CREDIT, amount=Decimal("35.00"))

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarUniqueResult([debit_line, credit_line]))

    with patch(
        "src.services.processing_account.get_or_create_processing_account",
        new=AsyncMock(return_value=processing_account),
    ):
        balance = await get_processing_balance(db, uuid4())

    assert balance == Decimal("85.00")
    assert isinstance(balance, Decimal)


@pytest.mark.asyncio
async def test_list_processing_transfer_legs_keeps_unpaired_status_visible() -> None:
    """AC15.7.3 · AC15.7.4 · Pending Processing legs retain unmatched source/destination visibility."""
    today = date.today()
    user_id = uuid4()
    processing_account = SimpleNamespace(id=uuid4(), currency="SGD")
    out_entry = _make_transfer_entry(
        user_id=user_id,
        processing_account_id=processing_account.id,
        other_account_id=uuid4(),
        other_account_name="Cash",
        amount=Decimal("250.00"),
        entry_date=today - timedelta(days=9),
        memo="Wire out",
        processing_direction=Direction.DEBIT,
    )
    in_entry = _make_transfer_entry(
        user_id=user_id,
        processing_account_id=processing_account.id,
        other_account_id=uuid4(),
        other_account_name="Savings",
        amount=Decimal("75.00"),
        entry_date=today - timedelta(days=2),
        memo="Wire in",
        processing_direction=Direction.CREDIT,
    )

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_ScalarUniqueResult([out_entry, in_entry]))

    with patch(
        "src.services.processing_account.get_or_create_processing_account",
        new=AsyncMock(return_value=processing_account),
    ):
        legs = await list_processing_transfer_legs(db, user_id)

    assert len(legs) == 2
    out_leg = next(leg for leg in legs if leg["amount"] == Decimal("250.00"))
    in_leg = next(leg for leg in legs if leg["amount"] == Decimal("75.00"))

    assert out_leg["from_account"] == "Cash"
    assert "unmatched" in out_leg["to_account"].lower()
    assert out_leg["days_outstanding"] == 9

    assert "unmatched" in in_leg["from_account"].lower()
    assert in_leg["to_account"] == "Savings"
    assert in_leg["days_outstanding"] == 2
