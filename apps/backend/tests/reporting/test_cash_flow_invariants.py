"""Flow 26: Cash Flow Statement Direct Method Multi-Activity Invariant Verification.

Validates:
1. Real database execution with zero monkeypatching of generate_cash_flow.
2. Full multi-activity coverage:
   - Operating: Cash revenue inflow, operating expense outflow
   - Investing: Fixed/alternative asset purchase outflow, asset disposal inflow
   - Financing: Loan drawdown inflow, loan principal repayment outflow
3. Invariant equations:
   - net_operating + net_investing + net_financing == net_cash_change
   - beginning_cash + net_cash_change == ending_cash
   - ending_cash == sum(account balances of all cash & equivalent accounts)
   - cash_bridge.reconciles is True and proof_state == "proven"
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import Money
from src.identity import User
from src.ledger import (
    Account,
    AccountType,
    Entry,
    calculate_account_balance,
    post_entry,
)
from src.reporting import generate_cash_flow


async def _create_account(
    db: AsyncSession,
    user_id,
    name: str,
    account_type: AccountType,
    code: str,
    currency: str = "SGD",
) -> Account:
    account = Account(
        user_id=user_id,
        name=name,
        code=code,
        type=account_type,
        currency=currency,
        is_active=True,
    )
    db.add(account)
    await db.flush()
    return account


@pytest.mark.asyncio
async def test_flow26_cash_flow_direct_method_invariants(db: AsyncSession, test_user: User):
    """Flow 26: Complete Direct Method cash flow verification across three activities.

    Invariants tested:
    1. net_operating + net_investing + net_financing == net_cash_change
    2. beginning_cash + net_cash_change == ending_cash
    3. ending_cash == sum of period-end balances of all cash & equivalent accounts (1000, 1001)
    """
    user_id = test_user.id
    period_start = date(2026, 1, 1)
    period_end = date(2026, 1, 31)

    # 1. Accounts setup: Two cash accounts (Cash on Hand 1000, Bank Checking 1001)
    cash_hand = await _create_account(db, user_id, "Cash on Hand", AccountType.ASSET, "1000")
    cash_bank = await _create_account(db, user_id, "Bank Checking Account", AccountType.ASSET, "1001")
    equity_opening = await _create_account(db, user_id, "Opening Balance Equity", AccountType.EQUITY, "3000")

    # Operating accounts
    revenue = await _create_account(db, user_id, "Consulting Revenue", AccountType.INCOME, "4000")
    office_expense = await _create_account(db, user_id, "Office Supplies Expense", AccountType.EXPENSE, "5000")

    # Investing accounts
    equipment = await _create_account(db, user_id, "Office Equipment", AccountType.ASSET, "1500")
    investments = await _create_account(db, user_id, "Marketable Securities", AccountType.ASSET, "1200")
    capital_gains = await _create_account(db, user_id, "Realized Capital Gains", AccountType.INCOME, "4100")

    # Financing accounts
    loan_payable = await _create_account(db, user_id, "Bank Loan Payable", AccountType.LIABILITY, "2100")

    # 2. Beginning cash: Set initial balances prior to period (2025-12-31) via anchored system entries
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2025, 12, 31),
        memo="Initial Cash on Hand",
        entry=Entry.transfer(
            debit=cash_hand.id,
            credit=equity_opening.id,
            money=Money(Decimal("2000.00"), "SGD"),
        ),
        base_currency="SGD",
        operation="flow26-init-cash-hand",
    )
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2025, 12, 31),
        memo="Initial Bank Checking",
        entry=Entry.transfer(
            debit=cash_bank.id,
            credit=equity_opening.id,
            money=Money(Decimal("8000.00"), "SGD"),
        ),
        base_currency="SGD",
        operation="flow26-init-cash-bank",
    )
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2025, 12, 31),
        memo="Initial Securities Holding",
        entry=Entry.transfer(
            debit=investments.id,
            credit=equity_opening.id,
            money=Money(Decimal("5000.00"), "SGD"),
        ),
        base_currency="SGD",
        operation="flow26-init-investments",
    )

    # 3. Operating Activities within period:
    # 3a. Cash revenue inflow: +$6,000 into bank
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 5),
        memo="Client Project Retainer",
        entry=Entry.transfer(
            debit=cash_bank.id,
            credit=revenue.id,
            money=Money(Decimal("6000.00"), "SGD"),
        ),
        base_currency="SGD",
        operation="operating-revenue",
    )
    # 3b. Operating expense outflow: -$1,800 paid from bank
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 10),
        memo="Office Supplies & Software Subscriptions",
        entry=Entry.transfer(
            debit=office_expense.id,
            credit=cash_bank.id,
            money=Money(Decimal("1800.00"), "SGD"),
        ),
        base_currency="SGD",
        operation="operating-expense",
    )
    # Expected net operating = +6000 - 1800 = +4200.00

    # 4. Investing Activities within period:
    # 4a. Fixed asset purchase outflow: -$3,500 paid from cash_bank
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 12),
        memo="Purchase Ergonomic Workstations",
        entry=Entry.transfer(
            debit=equipment.id,
            credit=cash_bank.id,
            money=Money(Decimal("3500.00"), "SGD"),
            event_type="investment_buy",
        ),
        base_currency="SGD",
        operation="investing-fixed-asset-purchase",
    )
    # 4b. Investment disposal inflow: +$2,500 into cash_bank ($2,000 cost basis disposed + $500 realized gain)
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 15),
        memo="Partial Sale of Securities",
        entry=Entry.of(
            Entry.transfer(
                debit=cash_bank.id,
                credit=investments.id,
                money=Money(Decimal("2500.00"), "SGD"),
                event_type="investment_sell",
            ).legs[0],
            Entry.transfer(
                debit=cash_bank.id,
                credit=investments.id,
                money=Money(Decimal("2000.00"), "SGD"),
                event_type="investment_sell",
            ).legs[1],
            Entry.transfer(
                debit=cash_bank.id,
                credit=capital_gains.id,
                money=Money(Decimal("500.00"), "SGD"),
                event_type="investment_realized_pnl",
            ).legs[1],
        ),
        base_currency="SGD",
        operation="investing-securities-sale",
    )
    # Expected net investing = -3500 + 2500 = -1000.00

    # 5. Financing Activities within period:
    # 5a. Bank loan borrowed inflow: +$10,000 into cash_bank
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 18),
        memo="Short-term Bank Credit Facility Drawdown",
        entry=Entry.transfer(
            debit=cash_bank.id,
            credit=loan_payable.id,
            money=Money(Decimal("10000.00"), "SGD"),
            event_type="loan_drawdown",
        ),
        base_currency="SGD",
        operation="financing-loan-drawdown",
    )
    # 5b. Repay loan principal outflow: -$4,000 from cash_bank
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 25),
        memo="Amortization Principal Repayment",
        entry=Entry.transfer(
            debit=loan_payable.id,
            credit=cash_bank.id,
            money=Money(Decimal("4000.00"), "SGD"),
            event_type="loan_repayment",
        ),
        base_currency="SGD",
        operation="financing-loan-repayment",
    )
    # Expected net financing = +10000 - 4000 = +6000.00

    await db.commit()

    # 6. Execute REAL generate_cash_flow
    cash_accounts = [cash_hand, cash_bank]
    cash_account_ids = frozenset(acc.id for acc in cash_accounts)

    report = await generate_cash_flow(
        db,
        user_id,
        start_date=period_start,
        end_date=period_end,
        currency="SGD",
        cash_account_ids=cash_account_ids,
    )

    # 7. Extract real summary values
    summary = report["summary"]
    net_operating = summary["operating_activities"]
    net_investing = summary["investing_activities"]
    net_financing = summary["financing_activities"]
    net_cash_change = summary["net_cash_flow"]
    beginning_cash = summary["beginning_cash"]
    ending_cash = summary["ending_cash"]

    # 8. Exact expected calculations
    expected_beginning = Decimal("10000.00")
    expected_net_operating = Decimal("4200.00")  # +6000 (inflow) - 1800 (outflow)
    expected_net_investing = Decimal("-1000.00")  # -3500 (buy) + 2500 (sell)
    expected_net_financing = Decimal("6000.00")  # +10000 (borrow) - 4000 (repay)
    expected_net_cash_change = expected_net_operating + expected_net_investing + expected_net_financing  # +9200.00
    expected_ending = expected_beginning + expected_net_cash_change  # 19200.00

    # 9. Assert section subtotals match exact transaction math
    assert net_operating == expected_net_operating, f"Operating: {net_operating} != {expected_net_operating}"
    assert net_investing == expected_net_investing, f"Investing: {net_investing} != {expected_net_investing}"
    assert net_financing == expected_net_financing, f"Financing: {net_financing} != {expected_net_financing}"
    assert net_cash_change == expected_net_cash_change, f"Net change: {net_cash_change} != {expected_net_cash_change}"
    assert beginning_cash == expected_beginning, f"Beginning: {beginning_cash} != {expected_beginning}"
    assert ending_cash == expected_ending, f"Ending: {ending_cash} != {expected_ending}"

    # 10. Core Invariant 1: Direct-method sum equals net cash change
    assert net_operating + net_investing + net_financing == net_cash_change

    # 11. Core Invariant 2: Beginning cash + Net change equals Ending cash
    assert beginning_cash + net_cash_change == ending_cash

    # 12. Core Invariant 3: Ending cash strictly equals sum of all cash account balances in general ledger
    ledger_cash_balances = [await calculate_account_balance(db, acc.id, user_id) for acc in cash_accounts]
    total_ledger_ending_cash = sum(ledger_cash_balances, Decimal("0.00"))
    assert ending_cash == total_ledger_ending_cash, (
        f"Ending cash {ending_cash} deviates from ledger balances {total_ledger_ending_cash}"
    )

    # 13. Bridge reconciliation invariant
    cash_bridge = report["cash_bridge"]
    assert cash_bridge["reconciles"] is True
    assert cash_bridge["cash_delta"] == net_cash_change
    assert cash_bridge["unclassified_cash"] == Decimal("0.00")
    assert cash_bridge["fx_effect"] == Decimal("0.00")
    assert cash_bridge["discrepancy"] == Decimal("0.00")

    # 14. Activity lists non-empty and accurately classified
    assert len(report["operating"]) >= 2
    assert len(report["investing"]) >= 2
    assert len(report["financing"]) >= 2
    assert report["proof_state"] == "proven"
    assert report["proof_reasons"] == []


@pytest.mark.asyncio
async def test_flow26_cash_flow_bridge_exposes_discrepancy_when_imbalanced(
    db: AsyncSession, test_user: User, monkeypatch
):
    """Issue #2067: Single currency cash bridge must have fx_effect == 0 and expose discrepancy if not balancing."""
    import src.reporting.extension.cash_flow as cf_mod

    user_id = test_user.id
    period_start = date(2026, 2, 1)
    period_end = date(2026, 2, 28)

    cash_acc = await _create_account(db, user_id, "Checking Imbalance Test", AccountType.ASSET, "1002")
    revenue = await _create_account(db, user_id, "Sales Imbalance Test", AccountType.INCOME, "4001")

    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 2, 10),
        memo="Inflow",
        entry=Entry.transfer(
            debit=cash_acc.id,
            credit=revenue.id,
            money=Money(Decimal("500.00"), "SGD"),
        ),
        base_currency="SGD",
        operation="cf-inflow-test",
    )
    await db.commit()

    # Normal single-currency report
    report = await generate_cash_flow(
        db,
        user_id,
        start_date=period_start,
        end_date=period_end,
        currency="SGD",
        cash_account_ids=frozenset([cash_acc.id]),
    )
    assert report["cash_bridge"]["fx_effect"] == Decimal("0.00")
    assert report["cash_bridge"]["discrepancy"] == Decimal("0.00")
    assert report["cash_bridge"]["reconciles"] is True

    # If classified activity does not sum to cash_delta, it must NOT be absorbed by fx_effect.
    # Discrepancy must be non-zero and reconciles must be False.
    monkeypatch.setattr(cf_mod, "_line_total", lambda items: Decimal("0.00"))

    imbalanced_report = await generate_cash_flow(
        db,
        user_id,
        start_date=period_start,
        end_date=period_end,
        currency="SGD",
        cash_account_ids=frozenset([cash_acc.id]),
    )
    assert imbalanced_report["cash_bridge"]["fx_effect"] == Decimal("0.00")
    assert imbalanced_report["cash_bridge"]["discrepancy"] == Decimal("500.00")
    assert imbalanced_report["cash_bridge"]["reconciles"] is False
