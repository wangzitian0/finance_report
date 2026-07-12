"""Report-layer opening-balance gate (EPIC-002 AC2.16.4, issue #1481).

Axiom B: confidence is a measured property and we never present a structurally
incomplete total as trusted. When a user has posted activity but no opening
balance, the balance sheet and net-worth allocation aggregate to a HIGH tier even
though the starting position is missing (the asset line equals only the period's
net flow). These tests assert the report layer degrades the aggregate tier to LOW
and emits an ``opening_balance_warnings`` entry until an opening balance exists.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.audit import JournalEntrySourceType
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.ledger.extension.accounting import post_opening_balance_entry
from src.reporting import generate_balance_sheet
from src.reporting.extension.net_worth import get_net_worth_allocation_schedule

AS_OF = date(2026, 4, 30)


async def _post_high_confidence_activity(db, user_id, *, cash: Account, income: Account) -> None:
    """Post a HIGH-tier (user_confirmed) asset inflow with no opening balance."""
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2026, 3, 1),
        memo="confirmed inflow",
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("1000.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()


async def _accounts(db, user_id) -> tuple[Account, Account]:
    cash = Account(user_id=user_id, name="Bank", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=user_id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, income])
    await db.flush()
    return cash, income


@pytest.mark.asyncio
async def test_AC2_16_4_balance_sheet_degrades_tier_and_warns_when_opening_balance_missing(db, test_user) -> None:
    """AC-reporting.opening-balance.1: AC2.16.4: a HIGH-tier balance sheet is degraded to LOW and warns when the
    opening balance is missing — the total is structurally incomplete."""
    cash, income = await _accounts(db, test_user.id)
    await _post_high_confidence_activity(db, test_user.id, cash=cash, income=income)

    report = await generate_balance_sheet(db, test_user.id, as_of_date=AS_OF)

    # Without the gate the single rated line (user_confirmed) rolls up to HIGH.
    assert report["confidence_tier"] == "LOW"
    warnings = report["opening_balance_warnings"]
    assert warnings, "expected an opening-balance warning when none is recorded"
    assert any(w.get("type") == "missing_opening_balance" for w in warnings)


@pytest.mark.asyncio
async def test_AC2_16_4_balance_sheet_clears_warning_once_opening_balance_recorded(db, test_user) -> None:
    """AC-reporting.opening-balance.2: AC2.16.4: recording an opening balance clears the warning."""
    cash, income = await _accounts(db, test_user.id)
    await _post_high_confidence_activity(db, test_user.id, cash=cash, income=income)
    await post_opening_balance_entry(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={cash.id: Decimal("500.00")},
        currency="SGD",
        memo="Opening balances",
    )
    await db.commit()

    report = await generate_balance_sheet(db, test_user.id, as_of_date=AS_OF)

    assert report["opening_balance_warnings"] == []


@pytest.mark.asyncio
async def test_AC2_16_4_net_worth_allocation_surfaces_opening_balance_warning(db, test_user) -> None:
    """AC-reporting.opening-balance.3: AC2.16.4: the net-worth allocation surface carries the same signal."""
    cash, income = await _accounts(db, test_user.id)
    await _post_high_confidence_activity(db, test_user.id, cash=cash, income=income)

    allocation = await get_net_worth_allocation_schedule(db, test_user.id, as_of_date=AS_OF)

    assert allocation["confidence_tier"] == "LOW"
    assert allocation["opening_balance_warnings"], "expected the warning on net-worth allocation too"
