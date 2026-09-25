"""AC-reporting.cash-events.11: Adversarial falsifiable tests for multi-currency cash bridge."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import src.reporting.extension.cash_flow as cf_mod
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from src.pricing.orm.market_data import FxRate
from src.reporting.extension.cash_flow import generate_cash_flow


@pytest.mark.asyncio
async def test_multicurrency_cash_bridge_exposes_discrepancy_on_missing_activity(
    db: AsyncSession, test_user, monkeypatch
):
    """AC-reporting.cash-events.9: Dropping an activity in multi-currency cash flow MUST expose discrepancy.

    Proves that fx_effect does not blind plug and mask missing/corrupted cash flow activities.
    """
    user_id = test_user.id
    period_start = date(2026, 1, 1)
    period_end = date(2026, 1, 31)

    usd_cash = Account(user_id=user_id, name="USD Checking", type=AccountType.ASSET, currency="USD", is_active=True)
    usd_revenue = Account(
        user_id=user_id, name="USD Consulting", type=AccountType.INCOME, currency="USD", is_active=True
    )
    db.add_all([usd_cash, usd_revenue])
    db.add_all(
        [
            FxRate(
                base_currency="USD", quote_currency="SGD", rate=Decimal("1.30"), rate_date=period_start, source="test"
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.35"),
                rate_date=date(2026, 1, 15),
                source="test",
            ),
            FxRate(
                base_currency="USD", quote_currency="SGD", rate=Decimal("1.40"), rate_date=period_end, source="test"
            ),
        ]
    )
    await db.flush()

    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2026, 1, 15),
        memo="Client Retainer USD",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=usd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="USD",
                fx_rate=Decimal("1.35"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=usd_revenue.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="USD",
                fx_rate=Decimal("1.35"),
            ),
        ]
    )
    await db.commit()

    # Normal report:
    # Operating: 100 USD @ 1.35 = 135.00 SGD
    # Ending cash: 100 USD @ 1.40 = 140.00 SGD
    # FX effect on cash: 100 * (1.40 - 1.35) = 5.00 SGD
    # Bridge: 135.00 + 5.00 = 140.00 SGD -> reconciles=True, discrepancy=0.00
    report = await generate_cash_flow(
        db,
        user_id,
        start_date=period_start,
        end_date=period_end,
        currency="SGD",
        cash_account_ids=frozenset([usd_cash.id]),
    )
    assert report["cash_bridge"]["classified_activity"] == Decimal("135.00")
    assert report["cash_bridge"]["fx_effect"] == Decimal("5.00")
    assert report["cash_bridge"]["cash_delta"] == Decimal("140.00")
    assert report["cash_bridge"]["discrepancy"] == Decimal("0.00")
    assert report["cash_bridge"]["reconciles"] is True

    # MUTATION: Simulate dropped/corrupted classified activity (e.g. _line_total returns 0)
    monkeypatch.setattr(cf_mod, "_line_total", lambda items: Decimal("0.00"))

    corrupted_report = await generate_cash_flow(
        db,
        user_id,
        start_date=period_start,
        end_date=period_end,
        currency="SGD",
        cash_account_ids=frozenset([usd_cash.id]),
    )

    # In corrupted report:
    # classified_activity is 0.00 (dropped!)
    # fx_effect MUST NOT absorb the missing 135.00! It must remain 5.00!
    # discrepancy MUST be 135.00, and reconciles MUST be False!
    assert corrupted_report["cash_bridge"]["fx_effect"] == Decimal("5.00"), (
        f"fx_effect must remain independent 5.00, got {corrupted_report['cash_bridge']['fx_effect']}"
    )
    assert corrupted_report["cash_bridge"]["discrepancy"] == Decimal("135.00")
    assert corrupted_report["cash_bridge"]["reconciles"] is False
