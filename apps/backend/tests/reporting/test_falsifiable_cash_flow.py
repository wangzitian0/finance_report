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
    """AC-reporting.cash-events.11: Dropping an activity in multi-currency cash flow MUST expose discrepancy.

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


@pytest.mark.asyncio
async def test_multicurrency_cash_bridge_absorbs_per_line_fx_rounding_residue(db: AsyncSession, test_user) -> None:
    """Per-event quantized foreign-currency line amounts do not leave a 0.01-0.02 rounding discrepancy (#2851)."""
    user_id = test_user.id
    cny_cash = Account(user_id=user_id, name="CNY Cash", type=AccountType.ASSET, currency="CNY", code="1012")
    cny_exp = Account(user_id=user_id, name="CNY Expense", type=AccountType.EXPENSE, currency="CNY", code="5012")
    db.add_all([cny_cash, cny_exp])
    await db.flush()

    db.add_all(
        [
            FxRate(
                base_currency="CNY",
                quote_currency="SGD",
                rate=Decimal("0.188304"),
                rate_date=date(2024, 1, 15),
                source="test",
            ),
            FxRate(
                base_currency="CNY",
                quote_currency="SGD",
                rate=Decimal("0.192490"),
                rate_date=date(2024, 2, 28),
                source="test",
            ),
        ]
    )
    await db.flush()

    # Three 10.00 CNY outflows on 2024-01-15:
    # Each line quantizes -10 * 0.188304 = -1.88304 -> -1.88 SGD (3 * -1.88 = -5.64 SGD).
    # Unrounded sum is -30 * 0.188304 = -5.64912 SGD, while ending cash is -30 * 0.192490 = -5.7747 -> -5.77 SGD.
    # Unrounded fx_effect is -30 * (0.192490 - 0.188304) = -0.12558 -> -0.13 SGD.
    # Without translation rounding absorption, (-5.77) - (-5.64 + -0.13) = 0.00 or with 4 events:
    # 4 * -1.88 = -7.52 SGD; ending = -40 * 0.192490 = -7.6996 -> -7.70 SGD;
    # fx_effect = -40 * 0.004186 = -0.16744 -> -0.17 SGD; -7.52 + -0.17 = -7.69 != -7.70 (0.01 discrepancy!).
    for idx in range(4):
        entry = JournalEntry(
            user_id=user_id,
            entry_date=date(2024, 1, 15),
            memo=f"CNY coffee {idx}",
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.flush()
        db.add_all(
            [
                JournalLine(
                    journal_entry_id=entry.id,
                    account_id=cny_exp.id,
                    direction=Direction.DEBIT,
                    amount=Decimal("10.00"),
                    currency="CNY",
                    fx_rate=Decimal("0.188304"),
                ),
                JournalLine(
                    journal_entry_id=entry.id,
                    account_id=cny_cash.id,
                    direction=Direction.CREDIT,
                    amount=Decimal("10.00"),
                    currency="CNY",
                    fx_rate=Decimal("0.188304"),
                ),
            ]
        )
    await db.commit()

    report = await generate_cash_flow(
        db,
        user_id,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 2, 28),
        currency="SGD",
        cash_account_ids=frozenset([cny_cash.id]),
    )
    assert report["cash_bridge"]["classified_activity"] == Decimal("-7.52")
    assert report["cash_bridge"]["cash_delta"] == Decimal("-7.70")
    assert report["cash_bridge"]["fx_effect"] == Decimal("-0.18")
    assert report["cash_bridge"]["discrepancy"] == Decimal("0.00")
    assert report["cash_bridge"]["reconciles"] is True
