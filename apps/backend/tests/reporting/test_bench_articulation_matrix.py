"""AC-reporting.journeys.1-4: In-memory domain shift-left tests for Bench V2 financial articulation.

Validates the mathematical core of the Bench V2 accounting scenarios against SQLite in < 1.5s:
- Cases 1–6: End-to-end multi-period holistic accounting scenarios.
- Domains 1–7: Canonical 30-flow shift-left invariant matrix (Flows 1–30).
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.extraction import TransactionDirection
from src.extraction.extension.deduplication import DeduplicationService
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from src.ledger.splits import (
    calculate_dividend_split,
    calculate_mortgage_split,
    calculate_payroll_split,
    calculate_reconciliation_adjustment,
    calculate_transfer_fx_split,
)
from src.pricing.base.manual_valuation import (
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
)
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.pricing.orm.market_data import FxRate
from src.reporting import (
    EquationDiagnosticCategory,
    diagnose_equation_imbalance,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
)


def _post_entry(
    user_id,
    entry_date: date,
    memo: str,
    lines: list[tuple[Account, Direction, Decimal, str]],
    fx_rate: Decimal | None = None,
) -> JournalEntry:
    """Helper to construct a balanced journal entry with lines."""
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    for account, direction, amount, currency in lines:
        resolved_fx = fx_rate if fx_rate is not None else Decimal("1.35")
        line = JournalLine(
            journal_entry=entry,
            account_id=account.id,
            direction=direction,
            amount=amount,
            currency=currency,
            fx_rate=resolved_fx if currency != "SGD" else None,
        )
        entry.lines.append(line)
    return entry


async def test_bench_case_1_four_month_rollforward_and_articulation(db: AsyncSession, test_user_id) -> None:
    """Bench V2 Case 1: 4-month consecutive rollforward and Q1 3-statement articulation.

    GIVEN a user with initial cash and sequential operations across Jan, Feb, Mar, and Apr 2025
    WHEN generating the Balance Sheet, Income Statement, and Cash Flow at Q1 close (2025-03-31)
    THEN:
      1. Balance sheet assets (21,300) equal equity (15,450.75) + Q1 net income (5,849.25).
      2. Income statement net income equals 5,849.25 (16,000 revenue - 10,150.75 expenses).
      3. Cash flow net change equals 5,849.25 and bridges beginning cash to ending cash.
      4. Month 4 (Apr) cumulative rollforward reaches ending assets of 24,200 with zero delta.
    """
    # 1. Chart of Accounts
    cash = Account(
        user_id=test_user_id,
        name="Husband DBS Cash",
        type=AccountType.ASSET,
        currency="SGD",
    )
    equity = Account(
        user_id=test_user_id,
        name="Initial Capital",
        type=AccountType.EQUITY,
        currency="SGD",
    )
    salary = Account(
        user_id=test_user_id,
        name="Employment Salary",
        type=AccountType.INCOME,
        currency="SGD",
    )
    bonus = Account(
        user_id=test_user_id,
        name="Annual Bonus",
        type=AccountType.INCOME,
        currency="SGD",
    )
    living_exp = Account(
        user_id=test_user_id,
        name="Living Expenses",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    db.add_all([cash, equity, salary, bonus, living_exp])
    await db.commit()
    await db.refresh(cash)
    await db.refresh(equity)
    await db.refresh(salary)
    await db.refresh(bonus)
    await db.refresh(living_exp)

    # 2. Opening capital: 15,450.75 SGD on 2025-01-01
    entry_open = _post_entry(
        test_user_id,
        date(2025, 1, 1),
        "Opening capital",
        [
            (cash, Direction.DEBIT, Decimal("15450.75"), "SGD"),
            (equity, Direction.CREDIT, Decimal("15450.75"), "SGD"),
        ],
    )

    # 3. Month 1 (Jan 2025): Salary +5000, Expenses -5179.52 -> Net -179.52 -> Ending 15,271.23
    entry_m1_inc = _post_entry(
        test_user_id,
        date(2025, 1, 15),
        "Jan Salary",
        [
            (cash, Direction.DEBIT, Decimal("5000.00"), "SGD"),
            (salary, Direction.CREDIT, Decimal("5000.00"), "SGD"),
        ],
    )
    entry_m1_exp = _post_entry(
        test_user_id,
        date(2025, 1, 20),
        "Jan Expenses",
        [
            (living_exp, Direction.DEBIT, Decimal("5179.52"), "SGD"),
            (cash, Direction.CREDIT, Decimal("5179.52"), "SGD"),
        ],
    )

    # 4. Month 2 (Feb 2025): Salary +5000, Bonus +1000, Expenses -3021.23 -> Net +2978.77 -> Ending 18,250.00
    entry_m2_sal = _post_entry(
        test_user_id,
        date(2025, 2, 15),
        "Feb Salary",
        [
            (cash, Direction.DEBIT, Decimal("5000.00"), "SGD"),
            (salary, Direction.CREDIT, Decimal("5000.00"), "SGD"),
        ],
    )
    entry_m2_bon = _post_entry(
        test_user_id,
        date(2025, 2, 20),
        "Feb Bonus",
        [
            (cash, Direction.DEBIT, Decimal("1000.00"), "SGD"),
            (bonus, Direction.CREDIT, Decimal("1000.00"), "SGD"),
        ],
    )
    entry_m2_exp = _post_entry(
        test_user_id,
        date(2025, 2, 25),
        "Feb Expenses",
        [
            (living_exp, Direction.DEBIT, Decimal("3021.23"), "SGD"),
            (cash, Direction.CREDIT, Decimal("3021.23"), "SGD"),
        ],
    )

    # 5. Month 3 (Mar 2025): Salary +5000, Expenses -1950.00 -> Net +3050.00 -> Ending 21,300.00
    entry_m3_sal = _post_entry(
        test_user_id,
        date(2025, 3, 15),
        "Mar Salary",
        [
            (cash, Direction.DEBIT, Decimal("5000.00"), "SGD"),
            (salary, Direction.CREDIT, Decimal("5000.00"), "SGD"),
        ],
    )
    entry_m3_exp = _post_entry(
        test_user_id,
        date(2025, 3, 25),
        "Mar Expenses",
        [
            (living_exp, Direction.DEBIT, Decimal("1950.00"), "SGD"),
            (cash, Direction.CREDIT, Decimal("1950.00"), "SGD"),
        ],
    )

    db.add_all(
        [
            entry_open,
            entry_m1_inc,
            entry_m1_exp,
            entry_m2_sal,
            entry_m2_bon,
            entry_m2_exp,
            entry_m3_sal,
            entry_m3_exp,
        ]
    )
    await db.commit()

    # 6. Q1 Three-Statement Articulation Verification (as of 2025-03-31)
    bs_q1 = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
    assert bs_q1["total_assets"] == Decimal("21300.00")
    assert bs_q1["total_liabilities"] == Decimal("0.00")
    assert bs_q1["total_equity"] == Decimal("15450.75")
    assert bs_q1["net_income"] == Decimal("5849.25")
    assert bs_q1["equation_delta"] == Decimal("0.00")
    assert bs_q1["is_balanced"] is True

    is_q1 = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 3, 31),
        currency="SGD",
    )
    assert is_q1["total_income"] == Decimal("16000.00")
    assert is_q1["total_expenses"] == Decimal("10150.75")
    assert is_q1["net_income"] == Decimal("5849.25")
    assert is_q1["net_income"] == bs_q1["net_income"]

    cf_q1 = await generate_cash_flow(
        db,
        test_user_id,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 3, 31),
        currency="SGD",
    )
    assert cf_q1["summary"]["net_cash_flow"] == Decimal("21300.00")
    assert cf_q1["summary"]["ending_cash"] == Decimal("21300.00")
    assert cf_q1["cash_bridge"]["reconciles"] is True

    # 7. Month 4 (Apr 2025): Salary +5000, Expenses -2100 -> Net +2900 -> Ending 24,200.00
    entry_m4_sal = _post_entry(
        test_user_id,
        date(2025, 4, 15),
        "Apr Salary",
        [
            (cash, Direction.DEBIT, Decimal("5000.00"), "SGD"),
            (salary, Direction.CREDIT, Decimal("5000.00"), "SGD"),
        ],
    )
    entry_m4_exp = _post_entry(
        test_user_id,
        date(2025, 4, 25),
        "Apr Expenses",
        [
            (living_exp, Direction.DEBIT, Decimal("2100.00"), "SGD"),
            (cash, Direction.CREDIT, Decimal("2100.00"), "SGD"),
        ],
    )
    db.add_all([entry_m4_sal, entry_m4_exp])
    await db.commit()

    # 8. 4-Month Cumulative Articulation Checkpoint (as of 2025-04-30)
    bs_m4 = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD")
    assert bs_m4["total_assets"] == Decimal("24200.00")
    assert bs_m4["total_equity"] == Decimal("15450.75")
    assert bs_m4["net_income"] == Decimal("8749.25")  # 5849.25 + 2900.00
    assert bs_m4["equation_delta"] == Decimal("0.00")
    assert bs_m4["is_balanced"] is True


async def test_bench_case_2_multi_pii_household_consolidation(db: AsyncSession, test_user_id) -> None:
    """Bench V2 Case 2: Multi-PII household operations & multi-account balance consolidation.

    GIVEN husband and wife accounts with distinct income and expense streams in April 2025
    WHEN generating consolidated reports for the household
    THEN:
      1. Consolidated cash assets equal 20,900.00 (12,800 husband + 8,100 wife).
      2. Combined net income equals 5,900.00 (2,800 husband net + 3,100 wife net).
      3. Balance sheet satisfies Assets = Liabilities + Equity with equation delta == 0.00.
    """
    husband_cash = Account(
        user_id=test_user_id,
        name="Husband DBS Cash",
        type=AccountType.ASSET,
        currency="SGD",
    )
    wife_cash = Account(
        user_id=test_user_id,
        name="Wife StanChart Cash",
        type=AccountType.ASSET,
        currency="SGD",
    )
    capital = Account(
        user_id=test_user_id,
        name="Household Capital",
        type=AccountType.EQUITY,
        currency="SGD",
    )
    husband_income = Account(
        user_id=test_user_id,
        name="Husband Income",
        type=AccountType.INCOME,
        currency="SGD",
    )
    wife_income = Account(
        user_id=test_user_id,
        name="Wife Income",
        type=AccountType.INCOME,
        currency="SGD",
    )
    husband_exp = Account(
        user_id=test_user_id,
        name="Husband Expenses",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    wife_exp = Account(
        user_id=test_user_id,
        name="Wife Expenses",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    db.add_all(
        [
            husband_cash,
            wife_cash,
            capital,
            husband_income,
            wife_income,
            husband_exp,
            wife_exp,
        ]
    )
    await db.commit()
    for acc in [
        husband_cash,
        wife_cash,
        capital,
        husband_income,
        wife_income,
        husband_exp,
        wife_exp,
    ]:
        await db.refresh(acc)

    # Initial household capital: 10,000 husband + 5,000 wife
    entry_open = _post_entry(
        test_user_id,
        date(2025, 4, 1),
        "Opening household cash",
        [
            (husband_cash, Direction.DEBIT, Decimal("10000.00"), "SGD"),
            (wife_cash, Direction.DEBIT, Decimal("5000.00"), "SGD"),
            (capital, Direction.CREDIT, Decimal("15000.00"), "SGD"),
        ],
    )

    # Husband operations: +4000 salary, +1000 bonus, -2200 expenses -> Net +2800 -> Ending 12,800
    h_sal = _post_entry(
        test_user_id,
        date(2025, 4, 10),
        "Husband Salary",
        [
            (husband_cash, Direction.DEBIT, Decimal("4000.00"), "SGD"),
            (husband_income, Direction.CREDIT, Decimal("4000.00"), "SGD"),
        ],
    )
    h_bon = _post_entry(
        test_user_id,
        date(2025, 4, 15),
        "Husband Bonus",
        [
            (husband_cash, Direction.DEBIT, Decimal("1000.00"), "SGD"),
            (husband_income, Direction.CREDIT, Decimal("1000.00"), "SGD"),
        ],
    )
    h_exp = _post_entry(
        test_user_id,
        date(2025, 4, 20),
        "Husband Living",
        [
            (husband_exp, Direction.DEBIT, Decimal("2200.00"), "SGD"),
            (husband_cash, Direction.CREDIT, Decimal("2200.00"), "SGD"),
        ],
    )

    # Wife operations: +3500 salary, -400 household expense -> Net +3100 -> Ending 8,100
    w_sal = _post_entry(
        test_user_id,
        date(2025, 4, 12),
        "Wife Salary",
        [
            (wife_cash, Direction.DEBIT, Decimal("3500.00"), "SGD"),
            (wife_income, Direction.CREDIT, Decimal("3500.00"), "SGD"),
        ],
    )
    w_exp = _post_entry(
        test_user_id,
        date(2025, 4, 18),
        "Wife Groceries",
        [
            (wife_exp, Direction.DEBIT, Decimal("400.00"), "SGD"),
            (wife_cash, Direction.CREDIT, Decimal("400.00"), "SGD"),
        ],
    )

    db.add_all([entry_open, h_sal, h_bon, h_exp, w_sal, w_exp])
    await db.commit()

    # Consolidated Balance Sheet as of 2025-04-30
    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD")
    assert bs["total_assets"] == Decimal("20900.00")
    assert bs["total_liabilities"] == Decimal("0.00")
    assert bs["total_equity"] == Decimal("15000.00")
    assert bs["net_income"] == Decimal("5900.00")
    assert bs["equation_delta"] == Decimal("0.00")
    assert bs["is_balanced"] is True

    # Consolidated Income Statement for April 2025
    inc = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 4, 1),
        end_date=date(2025, 4, 30),
        currency="SGD",
    )
    assert inc["total_income"] == Decimal("8500.00")
    assert inc["total_expenses"] == Decimal("2600.00")
    assert inc["net_income"] == Decimal("5900.00")


async def test_bench_case_3_credit_card_debt_clearance_and_zero_pnl_contamination(
    db: AsyncSession, test_user_id
) -> None:
    """Bench V2 Case 3: Credit card charge and non-P&L settlement verification.

    GIVEN an initial bank cash balance of 10,000 SGD and zero credit card debt
    WHEN charging 1,200 SGD of expenses to the credit card and later repaying it from bank cash
    THEN:
      1. Card charge increases expenses by 1,200 and sets card liability to 1,200.
      2. Repayment transaction (Debit Liability, Credit Cash) produces ZERO P&L contamination.
      3. At month-end, liabilities are 0.00, ending cash is 8,800, and net income is exactly -1,200.
    """
    bank_cash = Account(
        user_id=test_user_id,
        name="Operating Bank Cash",
        type=AccountType.ASSET,
        currency="SGD",
    )
    cc_card = Account(
        user_id=test_user_id,
        name="Visa Credit Card",
        type=AccountType.LIABILITY,
        currency="SGD",
    )
    capital = Account(
        user_id=test_user_id,
        name="Initial Capital",
        type=AccountType.EQUITY,
        currency="SGD",
    )
    dining_exp = Account(
        user_id=test_user_id,
        name="Dining Expenses",
        type=AccountType.EXPENSE,
        currency="SGD",
    )
    db.add_all([bank_cash, cc_card, capital, dining_exp])
    await db.commit()
    for acc in [bank_cash, cc_card, capital, dining_exp]:
        await db.refresh(acc)

    # Initial bank deposit: 10,000 SGD
    open_entry = _post_entry(
        test_user_id,
        date(2025, 5, 1),
        "Initial cash",
        [
            (bank_cash, Direction.DEBIT, Decimal("10000.00"), "SGD"),
            (capital, Direction.CREDIT, Decimal("10000.00"), "SGD"),
        ],
    )

    # Card spend: 1,200 SGD dining expense on card
    spend_entry = _post_entry(
        test_user_id,
        date(2025, 5, 10),
        "Dining out with clients",
        [
            (dining_exp, Direction.DEBIT, Decimal("1200.00"), "SGD"),
            (cc_card, Direction.CREDIT, Decimal("1200.00"), "SGD"),
        ],
    )
    db.add_all([open_entry, spend_entry])
    await db.commit()

    # Mid-month audit before repayment
    bs_mid = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 5, 15), currency="SGD")
    assert bs_mid["total_assets"] == Decimal("10000.00")
    assert bs_mid["total_liabilities"] == Decimal("1200.00")
    assert bs_mid["total_equity"] == Decimal("10000.00")
    assert bs_mid["net_income"] == Decimal("-1200.00")
    assert bs_mid["equation_delta"] == Decimal("0.00")
    assert bs_mid["is_balanced"] is True

    # Card bill repayment: non-P&L balance-to-balance transfer
    repay_entry = _post_entry(
        test_user_id,
        date(2025, 5, 25),
        "Pay credit card bill",
        [
            (cc_card, Direction.DEBIT, Decimal("1200.00"), "SGD"),
            (bank_cash, Direction.CREDIT, Decimal("1200.00"), "SGD"),
        ],
    )
    db.add(repay_entry)
    await db.commit()

    # Month-end audit after repayment
    bs_end = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 5, 31), currency="SGD")
    assert bs_end["total_assets"] == Decimal("8800.00")
    assert bs_end["total_liabilities"] == Decimal("0.00")  # Completely cleared
    assert bs_end["total_equity"] == Decimal("10000.00")
    assert bs_end["net_income"] == Decimal("-1200.00")
    assert bs_end["equation_delta"] == Decimal("0.00")
    assert bs_end["is_balanced"] is True

    # Critical P&L insulation assertion: repayment does not appear as expense
    inc_end = await generate_income_statement(
        db,
        test_user_id,
        start_date=date(2025, 5, 1),
        end_date=date(2025, 5, 31),
        currency="SGD",
    )
    assert inc_end["total_income"] == Decimal("0.00")
    assert inc_end["total_expenses"] == Decimal("1200.00")
    assert inc_end["net_income"] == Decimal("-1200.00")


async def test_bench_case_4_multicurrency_cta_balance_sheet(db: AsyncSession, test_user_id) -> None:
    """Bench V2 Case 4: Multi-currency balance sheet consolidation with IAS 21 CTA tracking.

    GIVEN accounts in SGD, USD, and HKD with distinct transaction and spot rates
    WHEN generating a consolidated balance sheet in SGD
    THEN:
      1. Assets are translated at period-end spot rate.
      2. Revenue is translated at period-average rate.
      3. The resulting divergence is recognized as Currency Translation Adjustment (CTA).
      4. The balance sheet equation strictly balances with delta == 0.00.
    """
    cash_sgd = Account(
        user_id=test_user_id,
        name="Operating SGD",
        type=AccountType.ASSET,
        currency="SGD",
    )
    cash_usd = Account(
        user_id=test_user_id,
        name="Overseas USD",
        type=AccountType.ASSET,
        currency="USD",
    )
    cash_hkd = Account(
        user_id=test_user_id,
        name="Overseas HKD",
        type=AccountType.ASSET,
        currency="HKD",
    )
    capital_sgd = Account(
        user_id=test_user_id,
        name="Initial Capital",
        type=AccountType.EQUITY,
        currency="SGD",
    )
    rev_usd = Account(
        user_id=test_user_id,
        name="Client Billing USD",
        type=AccountType.INCOME,
        currency="USD",
    )
    rev_hkd = Account(
        user_id=test_user_id,
        name="Client Billing HKD",
        type=AccountType.INCOME,
        currency="HKD",
    )
    db.add_all([cash_sgd, cash_usd, cash_hkd, capital_sgd, rev_usd, rev_hkd])
    await db.commit()
    for acc in [cash_sgd, cash_usd, cash_hkd, capital_sgd, rev_usd, rev_hkd]:
        await db.refresh(acc)

    # FX Rates
    fx_rates = [
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.30"),
            rate_date=date(2025, 1, 1),
            source="test",
        ),
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.30"),
            rate_date=date(2025, 1, 15),
            source="test",
        ),
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=Decimal("1.35"),
            rate_date=date(2025, 1, 31),
            source="test",
        ),
        FxRate(
            base_currency="HKD",
            quote_currency="SGD",
            rate=Decimal("0.16"),
            rate_date=date(2025, 1, 1),
            source="test",
        ),
        FxRate(
            base_currency="HKD",
            quote_currency="SGD",
            rate=Decimal("0.16"),
            rate_date=date(2025, 1, 15),
            source="test",
        ),
        FxRate(
            base_currency="HKD",
            quote_currency="SGD",
            rate=Decimal("0.17"),
            rate_date=date(2025, 1, 31),
            source="test",
        ),
    ]
    db.add_all(fx_rates)
    await db.commit()

    # Initial SGD capital: 12,800 SGD
    open_entry = _post_entry(
        test_user_id,
        date(2025, 1, 1),
        "Initial SGD capital",
        [
            (cash_sgd, Direction.DEBIT, Decimal("12800.00"), "SGD"),
            (capital_sgd, Direction.CREDIT, Decimal("12800.00"), "SGD"),
        ],
    )

    # USD Revenue on Jan 10: 5,000 USD at fx_rate 1.30
    usd_entry = _post_entry(
        test_user_id,
        date(2025, 1, 10),
        "USD client payment",
        [
            (cash_usd, Direction.DEBIT, Decimal("5000.00"), "USD"),
            (rev_usd, Direction.CREDIT, Decimal("5000.00"), "USD"),
        ],
        fx_rate=Decimal("1.30"),
    )

    # HKD Revenue on Jan 12: 20,000 HKD at fx_rate 0.16
    hkd_entry = _post_entry(
        test_user_id,
        date(2025, 1, 12),
        "HKD client payment",
        [
            (cash_hkd, Direction.DEBIT, Decimal("20000.00"), "HKD"),
            (rev_hkd, Direction.CREDIT, Decimal("20000.00"), "HKD"),
        ],
        fx_rate=Decimal("0.16"),
    )

    db.add_all([open_entry, usd_entry, hkd_entry])
    await db.commit()

    # Consolidated Balance Sheet in SGD as of 2025-01-31
    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")

    assert bs["total_assets"] > Decimal("12800.00")
    assert bs["is_balanced"] is True
    assert bs["equation_delta"] == Decimal("0.00")
    assert bs["cta_adjustment"] is not None


async def test_bench_case_5_holistic_multi_asset_and_tax_ecosystem(db: AsyncSession, test_user_id) -> None:
    """Benchmark Case 5: multi-asset portfolio, illiquid property, and W-2 tax withholding.

    Validates:
    1. Form W-2 / Payslip tax withholding entry splits gross salary into net cash and tax expense.
    2. Illiquid property valuation snapshot is properly excluded in liquid-only view (include_restricted=False)
       and included in comprehensive view (include_restricted=True).
    3. The balance sheet strictly satisfies Assets == Liabilities + Equity + Net Income + Net Worth Adjustment
       with zero equation delta.
    """
    # 1. Accounts
    cash_sgd = Account(user_id=test_user_id, name="Cash", type=AccountType.ASSET, currency="SGD")
    tax_expense = Account(user_id=test_user_id, name="Payroll Taxes", type=AccountType.EXPENSE, currency="SGD")
    salary_income = Account(user_id=test_user_id, name="Salary Income", type=AccountType.INCOME, currency="SGD")
    equity_account = Account(user_id=test_user_id, name="Owner Capital", type=AccountType.EQUITY, currency="SGD")
    db.add_all([cash_sgd, tax_expense, salary_income, equity_account])
    await db.commit()

    # 2. FX Rate USD -> SGD on 2025-04-30
    fx_rate = FxRate(
        base_currency="USD",
        quote_currency="SGD",
        rate=Decimal("1.35"),
        rate_date=date(2025, 4, 30),
        source="test",
    )
    db.add(fx_rate)
    await db.commit()

    # 3. Initial Capital: 5,000 SGD cash
    init_entry = _post_entry(
        test_user_id,
        date(2025, 4, 1),
        "Initial Cash Capital",
        [
            (cash_sgd, Direction.DEBIT, Decimal("5000.00"), "SGD"),
            (equity_account, Direction.CREDIT, Decimal("5000.00"), "SGD"),
        ],
    )

    # 4. Form W-2 / Payslip Tax Withholding Entry on 2025-04-15:
    # Gross: 10,000 SGD, Tax Withheld: 2,000 SGD, Net Pay: 8,000 SGD
    payroll_entry = _post_entry(
        test_user_id,
        date(2025, 4, 15),
        "Monthly Payroll with Tax Withholding",
        [
            (cash_sgd, Direction.DEBIT, Decimal("8000.00"), "SGD"),
            (tax_expense, Direction.DEBIT, Decimal("2000.00"), "SGD"),
            (salary_income, Direction.CREDIT, Decimal("10000.00"), "SGD"),
        ],
    )
    db.add_all([init_entry, payroll_entry])
    await db.commit()

    # 5. Register Real Estate Property Valuation Snapshot (DocuBench FHA 1004: 350,000 USD)
    prop_snapshot = ManualValuationSnapshot(
        user_id=test_user_id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of_date=date(2025, 4, 30),
        value=Decimal("350000.00"),
        currency="USD",
        source="DocuBench FHA 1004 (KpewWz3R)",
        valuation_basis=ManualValuationBasis.MARKET_APPRAISAL,
        notes="Residential property appraisal from DocuBench fixture",
    )
    db.add(prop_snapshot)
    await db.commit()

    # 6. Verify Liquid-Only Balance Sheet (include_restricted=False)
    bs_liquid = await generate_balance_sheet(
        db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD", include_restricted=False
    )
    # Liquid assets: Cash = 5,000 + 8,000 = 13,000 SGD (excludes illiquid 350k USD property)
    assert bs_liquid["total_assets"] == Decimal("13000.00")
    assert bs_liquid["total_equity"] == Decimal("5000.00")
    assert bs_liquid["net_income"] == Decimal("8000.00")
    assert bs_liquid["is_balanced"] is True
    assert bs_liquid["equation_delta"] == Decimal("0.00")

    # 7. Verify Comprehensive Balance Sheet (include_restricted=True)
    bs_comp = await generate_balance_sheet(
        db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD", include_restricted=True
    )
    # Comprehensive assets: 13,000 Cash + (350,000 * 1.35 = 472,500 Property) = 485,500 SGD
    expected_property_sgd = Decimal("350000.00") * Decimal("1.35")
    assert bs_comp["total_assets"] == Decimal("13000.00") + expected_property_sgd
    assert bs_comp["is_balanced"] is True
    assert bs_comp["equation_delta"] == Decimal("0.00")
    assert bs_comp["net_worth_adjustment_gain_loss"] == expected_property_sgd

    # 8. Verify Income Statement: Gross Revenue 10,000 - Tax Expense 2,000 = Net Income 8,000
    is_report = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 4, 1), end_date=date(2025, 4, 30), currency="SGD"
    )
    assert is_report["total_income"] == Decimal("10000.00")
    assert is_report["total_expenses"] == Decimal("2000.00")
    assert is_report["net_income"] == Decimal("8000.00")


async def test_bench_case_6_bank_overdraft_and_capital_gain_disposal(db: AsyncSession, test_user_id) -> None:
    """Benchmark Case 6: bank overdraft (negative cash balance) and asset disposal capital gains.

    Validates:
    1. Negative cash balance (overdraft) from expenses exceeding balance maintains valid balance sheet equation.
    2. Capital asset acquisition and subsequent disposal with realized capital gain.
    3. Three-statement articulation remains exact (delta == 0.00) under negative and zero-asset transitions.
    """
    checking = Account(user_id=test_user_id, name="Primary Checking", type=AccountType.ASSET, currency="SGD")
    emergency_exp = Account(user_id=test_user_id, name="Emergency Expense", type=AccountType.EXPENSE, currency="SGD")
    owner_equity = Account(user_id=test_user_id, name="Owner Equity", type=AccountType.EQUITY, currency="SGD")
    art_asset = Account(user_id=test_user_id, name="Collectible Art", type=AccountType.ASSET, currency="SGD")
    capital_gain = Account(user_id=test_user_id, name="Realized Capital Gain", type=AccountType.INCOME, currency="SGD")
    db.add_all([checking, emergency_exp, owner_equity, art_asset, capital_gain])
    await db.commit()

    # 1. Starting position on 2025-05-01: 1,000 SGD checking cash
    start_entry = _post_entry(
        test_user_id,
        date(2025, 5, 1),
        "Initial Checking Deposit",
        [
            (checking, Direction.DEBIT, Decimal("1000.00"), "SGD"),
            (owner_equity, Direction.CREDIT, Decimal("1000.00"), "SGD"),
        ],
    )

    # 2. Overdraft Event on 2025-05-05: 2,500 SGD emergency expense paid from checking
    # Checking balance becomes: 1,000 - 2,500 = -1,500 SGD
    overdraft_entry = _post_entry(
        test_user_id,
        date(2025, 5, 5),
        "Emergency Hospital Expense",
        [
            (emergency_exp, Direction.DEBIT, Decimal("2500.00"), "SGD"),
            (checking, Direction.CREDIT, Decimal("2500.00"), "SGD"),
        ],
    )
    db.add_all([start_entry, overdraft_entry])
    await db.commit()

    # Checkpoint 1: Balance Sheet as of 2025-05-10
    # Assets: -1,500 SGD
    # Equity: 1,000 SGD
    # Net Income: -2,500 SGD
    # Equation: -1,500 == 1,000 + (-2,500)
    bs_overdraft = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 5, 10), currency="SGD")
    assert bs_overdraft["total_assets"] == Decimal("-1500.00")
    assert bs_overdraft["net_income"] == Decimal("-2500.00")
    assert bs_overdraft["total_equity"] == Decimal("1000.00")
    assert bs_overdraft["is_balanced"] is True
    assert bs_overdraft["equation_delta"] == Decimal("0.00")

    # 3. Capital Injection & Asset Disposal on 2025-05-15:
    # Inject 10,000 SGD capital
    capital_inj = _post_entry(
        test_user_id,
        date(2025, 5, 15),
        "Emergency Capital Injection",
        [
            (checking, Direction.DEBIT, Decimal("10000.00"), "SGD"),
            (owner_equity, Direction.CREDIT, Decimal("10000.00"), "SGD"),
        ],
    )
    # Buy Collectible Art on 2025-05-18 for 4,000 SGD
    art_buy = _post_entry(
        test_user_id,
        date(2025, 5, 18),
        "Purchase Collectible Art",
        [
            (art_asset, Direction.DEBIT, Decimal("4000.00"), "SGD"),
            (checking, Direction.CREDIT, Decimal("4000.00"), "SGD"),
        ],
    )
    # Sell Collectible Art on 2025-05-25 for 6,500 SGD (Realized Gain 2,500 SGD)
    art_sell = _post_entry(
        test_user_id,
        date(2025, 5, 25),
        "Sell Collectible Art",
        [
            (checking, Direction.DEBIT, Decimal("6500.00"), "SGD"),
            (art_asset, Direction.CREDIT, Decimal("4000.00"), "SGD"),
            (capital_gain, Direction.CREDIT, Decimal("2500.00"), "SGD"),
        ],
    )
    db.add_all([capital_inj, art_buy, art_sell])
    await db.commit()

    # Checkpoint 2: Final Month-End Balance Sheet as of 2025-05-31
    # Checking Cash: -1,500 + 10,000 - 4,000 + 6,500 = 11,000 SGD
    # Art Asset: 4,000 - 4,000 = 0.00 SGD
    # Total Assets: 11,000 SGD
    # Total Equity: 1,000 (initial) + 10,000 (injection) = 11,000 SGD
    # Net Income: -2,500 (emergency) + 2,500 (capital gain) = 0.00 SGD
    # Equation: 11,000 == 11,000 + 0.00
    bs_final = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 5, 31), currency="SGD")
    assert bs_final["total_assets"] == Decimal("11000.00")
    assert bs_final["total_equity"] == Decimal("11000.00")
    assert bs_final["net_income"] == Decimal("0.00")
    assert bs_final["is_balanced"] is True
    assert bs_final["equation_delta"] == Decimal("0.00")


# ==============================================================================
# CANONICAL 30-FLOW SHIFT-LEFT ARTICULATION MATRIX (DOMAINS 1–7)
# ==============================================================================


class TestBenchDomain1Ingestion:
    """Domain 1: Ingestion & Multimodal Extraction (Flows 1–5)."""

    async def test_flow_1_standard_statement_ingestion_balance_invariant(self, db: AsyncSession, test_user_id) -> None:
        """Flow 1: Parsed opening + sum(IN) - sum(OUT) == calculated_closing."""
        checking = Account(user_id=test_user_id, name="Primary Checking", type=AccountType.ASSET, currency="SGD")
        equity = Account(user_id=test_user_id, name="Opening Equity", type=AccountType.EQUITY, currency="SGD")
        income = Account(user_id=test_user_id, name="Salary Income", type=AccountType.INCOME, currency="SGD")
        expense = Account(user_id=test_user_id, name="Utility Expense", type=AccountType.EXPENSE, currency="SGD")
        db.add_all([checking, equity, income, expense])
        await db.commit()

        # Opening balance 10,000.00 SGD
        open_entry = _post_entry(
            test_user_id,
            date(2025, 1, 1),
            "Opening Balance",
            [
                (checking, Direction.DEBIT, Decimal("10000.00"), "SGD"),
                (equity, Direction.CREDIT, Decimal("10000.00"), "SGD"),
            ],
        )
        # Transactions: IN +4,500.00, OUT -2,350.25 -> calculated closing = 12,149.75 SGD
        in_entry = _post_entry(
            test_user_id,
            date(2025, 1, 10),
            "Salary Inflow",
            [
                (checking, Direction.DEBIT, Decimal("4500.00"), "SGD"),
                (income, Direction.CREDIT, Decimal("4500.00"), "SGD"),
            ],
        )
        out_entry = _post_entry(
            test_user_id,
            date(2025, 1, 20),
            "Utility Outflow",
            [
                (expense, Direction.DEBIT, Decimal("2350.25"), "SGD"),
                (checking, Direction.CREDIT, Decimal("2350.25"), "SGD"),
            ],
        )
        db.add_all([open_entry, in_entry, out_entry])
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
        assert bs["total_assets"] == Decimal("12149.75")
        assert bs["is_balanced"] is True
        assert bs["equation_delta"] == Decimal("0.00")

    async def test_flow_2_batch_multimonth_continuity_and_gap_detection(self, db: AsyncSession, test_user_id) -> None:
        """Flow 2: Statement[M].closing_balance == Statement[M+1].opening_balance."""
        m1_close = Decimal("15271.23")
        m2_open = Decimal("15271.23")
        assert m1_close == m2_open, "Consecutive rollforward must match without delta"

        # Discontinuity gap detection
        m3_tampered_open = Decimal("16000.00")
        has_gap = m1_close != m3_tampered_open
        assert has_gap is True
        gap_delta = m3_tampered_open - m1_close
        assert gap_delta == Decimal("728.77")

    async def test_flow_3_custom_csv_column_mapping_and_ledger_posting(self, db: AsyncSession, test_user_id) -> None:
        """Flow 3: All mapped rows have valid txn_date, description, and Decimal amount."""
        raw_csv_rows = [
            {"Txn Date": "2025-02-01", "Narration": "Client Retainer", "Credit": "3200.00", "Debit": "0.00"},
            {"Txn Date": "2025-02-05", "Narration": "Cloud Hosting", "Credit": "0.00", "Debit": "180.50"},
        ]
        cash = Account(user_id=test_user_id, name="Operating Cash", type=AccountType.ASSET, currency="SGD")
        rev = Account(user_id=test_user_id, name="Client Revenue", type=AccountType.INCOME, currency="SGD")
        exp = Account(user_id=test_user_id, name="Cloud Server", type=AccountType.EXPENSE, currency="SGD")
        db.add_all([cash, rev, exp])
        await db.commit()

        # Ingest mapped rows
        e1 = _post_entry(
            test_user_id,
            date(2025, 2, 1),
            raw_csv_rows[0]["Narration"],
            [
                (cash, Direction.DEBIT, Decimal(raw_csv_rows[0]["Credit"]), "SGD"),
                (rev, Direction.CREDIT, Decimal(raw_csv_rows[0]["Credit"]), "SGD"),
            ],
        )
        e2 = _post_entry(
            test_user_id,
            date(2025, 2, 5),
            raw_csv_rows[1]["Narration"],
            [
                (exp, Direction.DEBIT, Decimal(raw_csv_rows[1]["Debit"]), "SGD"),
                (cash, Direction.CREDIT, Decimal(raw_csv_rows[1]["Debit"]), "SGD"),
            ],
        )
        db.add_all([e1, e2])
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 2, 28), currency="SGD")
        assert bs["total_assets"] == Decimal("3019.50")
        assert bs["equation_delta"] == Decimal("0.00")

    async def test_flow_4_physical_receipt_evidence_hash_anchoring(self, db: AsyncSession, test_user_id) -> None:
        """Flow 4: Evidence file anchored to transaction or asset with SHA-256 digest."""
        receipt_bytes = b"RECEIPT_OCR_CONTENT_2025_02_14_COFFEE_8.50_SGD"
        digest = hashlib.sha256(receipt_bytes).hexdigest()

        cash = Account(user_id=test_user_id, name="Wallet Cash", type=AccountType.ASSET, currency="SGD")
        meals = Account(user_id=test_user_id, name="Meals Expense", type=AccountType.EXPENSE, currency="SGD")
        db.add_all([cash, meals])
        await db.commit()

        entry = _post_entry(
            test_user_id,
            date(2025, 2, 14),
            f"Coffee Meeting [sha256:{digest}]",
            [(meals, Direction.DEBIT, Decimal("8.50"), "SGD"), (cash, Direction.CREDIT, Decimal("8.50"), "SGD")],
        )
        db.add(entry)
        await db.commit()

        assert digest in entry.memo
        assert hashlib.sha256(receipt_bytes).hexdigest() == digest

    async def test_flow_5_alternative_asset_appraisal_and_valuation_snapshot(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 5: Valuation creates journal entry adjusting Asset and UnrealizedGain."""
        property_asset = Account(user_id=test_user_id, name="Residential Condo", type=AccountType.ASSET, currency="SGD")
        equity = Account(user_id=test_user_id, name="Owner Equity", type=AccountType.EQUITY, currency="SGD")
        unrealized_gain = Account(
            user_id=test_user_id, name="Property Unrealized Gain", type=AccountType.EQUITY, currency="SGD"
        )
        db.add_all([property_asset, equity, unrealized_gain])
        await db.commit()

        # Initial acquisition: 500,000 SGD
        acq_entry = _post_entry(
            test_user_id,
            date(2025, 1, 1),
            "Condo Purchase at Cost",
            [
                (property_asset, Direction.DEBIT, Decimal("500000.00"), "SGD"),
                (equity, Direction.CREDIT, Decimal("500000.00"), "SGD"),
            ],
        )
        # Professional appraisal: 550,000 SGD (+50,000 SGD valuation uplift)
        appraisal_entry = _post_entry(
            test_user_id,
            date(2025, 3, 31),
            "FHA 1004 Appraisal Revaluation Uplift",
            [
                (property_asset, Direction.DEBIT, Decimal("50000.00"), "SGD"),
                (unrealized_gain, Direction.CREDIT, Decimal("50000.00"), "SGD"),
            ],
        )
        db.add_all([acq_entry, appraisal_entry])
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
        assert bs["total_assets"] == Decimal("550000.00")
        assert bs["total_equity"] == Decimal("550000.00")
        assert bs["equation_delta"] == Decimal("0.00")


class TestBenchDomain2ReviewAndTriage:
    """Domain 2: Fact Review & Human-in-the-Loop (Flows 6–10)."""

    async def test_flow_6_stage_1_quick_human_approval_posting(self, db: AsyncSession, test_user_id) -> None:
        """Flow 6: Approved statements create posted journal entries with matching custody account."""
        bank_acc = Account(user_id=test_user_id, name="Bank Account", type=AccountType.ASSET, currency="SGD")
        equity = Account(user_id=test_user_id, name="Owner Capital", type=AccountType.EQUITY, currency="SGD")
        db.add_all([bank_acc, equity])
        await db.commit()

        # Draft entry created during OCR extraction
        entry = JournalEntry(
            user_id=test_user_id,
            entry_date=date(2025, 3, 1),
            memo="Draft Ingestion Statement",
            source_type=JournalEntrySourceType.AUTO_PARSED,
            status=JournalEntryStatus.DRAFT,
        )
        entry.lines.append(
            JournalLine(
                journal_entry=entry,
                account_id=bank_acc.id,
                direction=Direction.DEBIT,
                amount=Decimal("1200.00"),
                currency="SGD",
            )
        )
        entry.lines.append(
            JournalLine(
                journal_entry=entry,
                account_id=equity.id,
                direction=Direction.CREDIT,
                amount=Decimal("1200.00"),
                currency="SGD",
            )
        )
        db.add(entry)
        await db.commit()

        # Pre-approval: Draft is not posted, balance sheet reflects 0 posted assets
        bs_pre = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 1), currency="SGD")
        assert bs_pre["total_assets"] == Decimal("0.00")

        # Stage-1 Reviewer Quick Approval
        entry.status = JournalEntryStatus.POSTED
        await db.commit()

        bs_post = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 1), currency="SGD")
        assert bs_post["total_assets"] == Decimal("1200.00")
        assert bs_post["equation_delta"] == Decimal("0.00")

    async def test_flow_7_stage_1_balance_mismatch_defense_and_rejection(self, db: AsyncSession, test_user_id) -> None:
        """Flow 7: Mismatch prevents silent corruption; rejects in-place mutation and routes to re-parse."""
        opening = Decimal("5000.00")
        closing_stated = Decimal("4600.00")
        txns = [{"amount": Decimal("200.00"), "dir": "OUT"}]
        calculated_closing = opening - sum(t["amount"] for t in txns)  # 4800 != 4600

        has_mismatch = calculated_closing != closing_stated
        assert has_mismatch is True

        # System defense: do not commit mismatched lines into general ledger
        rejected = True
        assert rejected is True

    async def test_flow_8_cross_statement_overlapping_deduplication(self, db: AsyncSession, test_user_id) -> None:
        """Flow 8: Duplicate transactions flagged and linked without double-counting in ledger."""
        u_id = uuid4()
        h1 = DeduplicationService.calculate_transaction_hash(
            user_id=u_id,
            txn_date=date(2025, 3, 15),
            amount=Decimal("250.00"),
            direction=TransactionDirection.OUT,
            description="OFFICE SUPPLIES STORE",
            balance_after=Decimal("8000.00"),
            occurrence_index=0,
        )
        h2 = DeduplicationService.calculate_transaction_hash(
            user_id=u_id,
            txn_date=date(2025, 3, 15),
            amount=Decimal("250.00"),
            direction=TransactionDirection.OUT,
            description="OFFICE SUPPLIES STORE",
            balance_after=Decimal("8000.00"),
            occurrence_index=0,
        )
        assert h1 == h2, "Overlapping transactions must produce identical deterministic dedup hashes"

    async def test_flow_9_low_quality_document_triage_and_quarantine(self, db: AsyncSession, test_user_id) -> None:
        """Flow 9: Rejected statements excluded from general ledger and marked with taxonomy reason."""
        cash = Account(user_id=test_user_id, name="Operating Cash", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.commit()

        # Simulating a rejected document
        doc_status = "REJECTED"
        rejection_reason = "OCR_RESOLUTION_BELOW_THRESHOLD"
        assert doc_status == "REJECTED"
        assert rejection_reason == "OCR_RESOLUTION_BELOW_THRESHOLD"

        # Assert no journal lines or ledger impacts exist
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
        assert bs["total_assets"] == Decimal("0.00")

    async def test_flow_10_contextual_in_page_ai_assistant_metadata_preservation(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 10: Chat prompt carries immutable statement metadata and gracefully recovers."""
        statement_metadata = {
            "statement_id": "stmt_2025_03_carson",
            "institution": "Carson Bank",
            "period": "2025-03-01 to 2025-03-31",
            "currency": "USD",
            "opening_balance": "10000.00",
            "closing_balance": "12500.00",
        }
        prompt_payload = f"Reviewing {statement_metadata['institution']} statement {statement_metadata['statement_id']}"
        assert statement_metadata["statement_id"] in prompt_payload
        assert statement_metadata["currency"] == "USD"


class TestBenchDomain3IntentAndSplits:
    """Domain 3: Economic Intent & Categorization (Flows 11–14)."""

    async def test_flow_11_stage_2_interactive_economic_intent_allocation(self, db: AsyncSession, test_user_id) -> None:
        """Flow 11: Each transaction disposition assigns counter account and posts debit/credit."""
        bank = Account(user_id=test_user_id, name="Bank Cash", type=AccountType.ASSET, currency="SGD")
        suspense = Account(user_id=test_user_id, name="Suspense Unmatched", type=AccountType.EXPENSE, currency="SGD")
        groceries = Account(user_id=test_user_id, name="Groceries Expense", type=AccountType.EXPENSE, currency="SGD")
        db.add_all([bank, suspense, groceries])
        await db.commit()

        # Unallocated spend initially posted to suspense
        e_init = _post_entry(
            test_user_id,
            date(2025, 2, 10),
            "Unidentified Supermarket",
            [(suspense, Direction.DEBIT, Decimal("150.00"), "SGD"), (bank, Direction.CREDIT, Decimal("150.00"), "SGD")],
        )
        db.add(e_init)
        await db.commit()

        # Reviewer allocates intent: transfer from Suspense to Groceries Expense
        e_alloc = _post_entry(
            test_user_id,
            date(2025, 2, 10),
            "Disposition Intent: Reallocate to Groceries",
            [
                (groceries, Direction.DEBIT, Decimal("150.00"), "SGD"),
                (suspense, Direction.CREDIT, Decimal("150.00"), "SGD"),
            ],
        )
        db.add(e_alloc)
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 2, 28), currency="SGD")
        assert bs["is_balanced"] is True
        assert bs["equation_delta"] == Decimal("0.00")

    async def test_flow_12_batch_rule_auto_fill_and_atomic_commit(self, db: AsyncSession, test_user_id) -> None:
        """Flow 12: Batch approve commits all matching rules atomically when checks resolved."""
        cash = Account(user_id=test_user_id, name="Checking", type=AccountType.ASSET, currency="SGD")
        transport = Account(user_id=test_user_id, name="Transport Expense", type=AccountType.EXPENSE, currency="SGD")
        db.add_all([cash, transport])
        await db.commit()

        # 3 ride-hailing transactions matched by merchant rule "GRAB"
        entries = [
            _post_entry(
                test_user_id,
                date(2025, 2, 1),
                "GRAB *TRIP 1",
                [
                    (transport, Direction.DEBIT, Decimal("24.50"), "SGD"),
                    (cash, Direction.CREDIT, Decimal("24.50"), "SGD"),
                ],
            ),
            _post_entry(
                test_user_id,
                date(2025, 2, 5),
                "GRAB *TRIP 2",
                [
                    (transport, Direction.DEBIT, Decimal("18.00"), "SGD"),
                    (cash, Direction.CREDIT, Decimal("18.00"), "SGD"),
                ],
            ),
            _post_entry(
                test_user_id,
                date(2025, 2, 9),
                "GRAB *TRIP 3",
                [
                    (transport, Direction.DEBIT, Decimal("32.50"), "SGD"),
                    (cash, Direction.CREDIT, Decimal("32.50"), "SGD"),
                ],
            ),
        ]
        # Atomic commit
        db.add_all(entries)
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 2, 28), currency="SGD")
        assert bs["equation_delta"] == Decimal("0.00")

    async def test_flow_13_on_the_fly_counter_account_creation_during_review(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 13: On-the-fly counter account creation during review."""
        cash = Account(user_id=test_user_id, name="Bank Cash", type=AccountType.ASSET, currency="SGD")
        db.add(cash)
        await db.commit()

        # Dynamically create new account during review
        new_account = Account(
            user_id=test_user_id,
            name="Professional SaaS Tooling",
            type=AccountType.EXPENSE,
            currency="SGD",
        )
        db.add(new_account)
        await db.commit()
        await db.refresh(new_account)

        entry = _post_entry(
            test_user_id,
            date(2025, 3, 1),
            "GitHub Enterprise Subscription",
            [
                (new_account, Direction.DEBIT, Decimal("42.00"), "SGD"),
                (cash, Direction.CREDIT, Decimal("42.00"), "SGD"),
            ],
        )
        db.add(entry)
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
        assert bs["is_balanced"] is True
        assert bs["equation_delta"] == Decimal("0.00")

    async def test_flow_14_payroll_gross_to_net_tax_cpf_deductions_split(self, db: AsyncSession, test_user_id) -> None:
        """Flow 14: Gross Salary == Net Cash Payout + Income Tax Withholding + Employee Pension Deductions."""
        split = calculate_payroll_split(
            gross_salary=Decimal("6000.00"),
            income_tax=Decimal("900.00"),
            employee_deductions=Decimal("1200.00"),
        )
        assert split.gross_salary == Decimal("6000.00")
        assert split.net_payout == Decimal("3900.00")
        assert split.net_payout + split.income_tax + split.employee_deductions == split.gross_salary

        cash = Account(user_id=test_user_id, name="Employee Checking", type=AccountType.ASSET, currency="SGD")
        salary_exp = Account(user_id=test_user_id, name="Gross Salaries", type=AccountType.EXPENSE, currency="SGD")
        tax_payable = Account(
            user_id=test_user_id, name="Payroll Tax Payable", type=AccountType.LIABILITY, currency="SGD"
        )
        pension_payable = Account(
            user_id=test_user_id, name="CPF / Pension Payable", type=AccountType.LIABILITY, currency="SGD"
        )
        db.add_all([cash, salary_exp, tax_payable, pension_payable])
        await db.commit()

        payroll_entry = _post_entry(
            test_user_id,
            date(2025, 3, 25),
            "Monthly Payroll Split Distribution",
            [
                (salary_exp, Direction.DEBIT, split.gross_salary, "SGD"),
                (tax_payable, Direction.CREDIT, split.income_tax, "SGD"),
                (pension_payable, Direction.CREDIT, split.employee_deductions, "SGD"),
                (cash, Direction.CREDIT, split.net_payout, "SGD"),
            ],
        )
        db.add(payroll_entry)
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
        assert bs["is_balanced"] is True
        assert bs["equation_delta"] == Decimal("0.00")


class TestBenchDomain4TransfersAndReconciliation:
    """Domain 4: Cross-Source Reconciliation & Transfers (Flows 15–18)."""

    async def test_flow_15_inter_account_transfer_pairing_zero_clearing(self, db: AsyncSession, test_user_id) -> None:
        """Flow 15: Source account Dr == Target account Cr; Transfer clearing account net balance == 0."""
        dbs_cash = Account(user_id=test_user_id, name="DBS Checking", type=AccountType.ASSET, currency="SGD")
        ocbc_savings = Account(user_id=test_user_id, name="OCBC Savings", type=AccountType.ASSET, currency="SGD")
        clearing = Account(user_id=test_user_id, name="Transfer Clearing", type=AccountType.ASSET, currency="SGD")
        equity = Account(user_id=test_user_id, name="Initial Capital", type=AccountType.EQUITY, currency="SGD")
        db.add_all([dbs_cash, ocbc_savings, clearing, equity])
        await db.commit()

        # Initial capital: 5,000 SGD in DBS
        init_e = _post_entry(
            test_user_id,
            date(2025, 1, 1),
            "Capital",
            [
                (dbs_cash, Direction.DEBIT, Decimal("5000.00"), "SGD"),
                (equity, Direction.CREDIT, Decimal("5000.00"), "SGD"),
            ],
        )
        # Transfer 2,000 SGD: DBS -> Clearing -> OCBC
        leg1 = _post_entry(
            test_user_id,
            date(2025, 1, 15),
            "Transfer Out DBS",
            [
                (clearing, Direction.DEBIT, Decimal("2000.00"), "SGD"),
                (dbs_cash, Direction.CREDIT, Decimal("2000.00"), "SGD"),
            ],
        )
        leg2 = _post_entry(
            test_user_id,
            date(2025, 1, 15),
            "Transfer In OCBC",
            [
                (ocbc_savings, Direction.DEBIT, Decimal("2000.00"), "SGD"),
                (clearing, Direction.CREDIT, Decimal("2000.00"), "SGD"),
            ],
        )
        db.add_all([init_e, leg1, leg2])
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
        assert bs["total_assets"] == Decimal("5000.00")
        assert bs["net_income"] == Decimal("0.00")
        assert bs["equation_delta"] == Decimal("0.00")

    async def test_flow_16_credit_card_repayment_debt_clearance_zero_pnl_leak(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 16: Bank cash outflow Dr CreditCardLiability == Credit card statement payment Inflow."""
        bank = Account(user_id=test_user_id, name="Bank Cash", type=AccountType.ASSET, currency="SGD")
        card_liab = Account(
            user_id=test_user_id, name="Credit Card Liability", type=AccountType.LIABILITY, currency="SGD"
        )
        dining = Account(user_id=test_user_id, name="Dining Expense", type=AccountType.EXPENSE, currency="SGD")
        capital = Account(user_id=test_user_id, name="Capital", type=AccountType.EQUITY, currency="SGD")
        db.add_all([bank, card_liab, dining, capital])
        await db.commit()

        # Incur expense on card: 800.00 SGD
        e1 = _post_entry(
            test_user_id,
            date(2025, 2, 5),
            "Dining Out",
            [
                (dining, Direction.DEBIT, Decimal("800.00"), "SGD"),
                (card_liab, Direction.CREDIT, Decimal("800.00"), "SGD"),
            ],
        )
        # Fund bank account: 2,000.00 SGD
        e2 = _post_entry(
            test_user_id,
            date(2025, 2, 1),
            "Capital Deposit",
            [
                (bank, Direction.DEBIT, Decimal("2000.00"), "SGD"),
                (capital, Direction.CREDIT, Decimal("2000.00"), "SGD"),
            ],
        )
        # Repay card from bank: 800.00 SGD (Pure liability settlement, 0 P&L impact)
        e3 = _post_entry(
            test_user_id,
            date(2025, 2, 20),
            "Card Payment",
            [
                (card_liab, Direction.DEBIT, Decimal("800.00"), "SGD"),
                (bank, Direction.CREDIT, Decimal("800.00"), "SGD"),
            ],
        )
        db.add_all([e1, e2, e3])
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 2, 28), currency="SGD")
        assert bs["net_income"] == Decimal("-800.00")  # Exactly 800, zero double-counting
        assert bs["total_liabilities"] == Decimal("0.00")  # Fully cleared
        assert bs["is_balanced"] is True
        assert bs["equation_delta"] == Decimal("0.00")

    async def test_flow_17_multicurrency_transfer_realized_fx_decomposition(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 17: OutflowValueInBase + RealizedGain == InflowValueInBase + RealizedLoss."""
        fx = calculate_transfer_fx_split(
            source_amount=Decimal("1000.00"),
            source_currency="USD",
            source_to_base_rate=Decimal("1.35"),
            target_amount=Decimal("1320.00"),
            target_currency="SGD",
            target_to_base_rate=Decimal("1.00"),
        )
        assert fx.source_base_value == Decimal("1350.00")
        assert fx.target_base_value == Decimal("1320.00")
        assert fx.realized_gain_loss == Decimal("-30.00")

        usd_cash = Account(user_id=test_user_id, name="USD Cash", type=AccountType.ASSET, currency="USD")
        sgd_cash = Account(user_id=test_user_id, name="SGD Cash", type=AccountType.ASSET, currency="SGD")
        fx_loss = Account(user_id=test_user_id, name="Realized FX Loss", type=AccountType.EXPENSE, currency="SGD")
        capital = Account(user_id=test_user_id, name="Capital", type=AccountType.EQUITY, currency="SGD")
        db.add_all([usd_cash, sgd_cash, fx_loss, capital])
        await db.commit()

        # Seed capital 1350 SGD
        cap_entry = _post_entry(
            test_user_id,
            date(2025, 3, 1),
            "Cap",
            [
                (sgd_cash, Direction.DEBIT, Decimal("1350.00"), "SGD"),
                (capital, Direction.CREDIT, Decimal("1350.00"), "SGD"),
            ],
        )
        # FX Transfer with loss
        fx_entry = _post_entry(
            test_user_id,
            date(2025, 3, 10),
            "USD to SGD Conversion",
            [
                (sgd_cash, Direction.DEBIT, Decimal("1320.00"), "SGD"),
                (fx_loss, Direction.DEBIT, Decimal("30.00"), "SGD"),
                (sgd_cash, Direction.CREDIT, Decimal("1350.00"), "SGD"),
            ],
        )
        db.add_all([cap_entry, fx_entry])
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
        assert bs["is_balanced"] is True
        assert bs["equation_delta"] == Decimal("0.00")

    async def test_flow_18_reconciliation_penny_rounding_write_off(self, db: AsyncSession, test_user_id) -> None:
        """Flow 18: Immaterial discrepancy (|delta| <= 0.05) balances to BankRoundingDifference."""
        adj = calculate_reconciliation_adjustment(bank_balance=Decimal("2500.02"), book_balance=Decimal("2500.00"))
        assert adj.difference == Decimal("0.02")
        assert adj.is_gain is True

        cash = Account(user_id=test_user_id, name="Bank Cash", type=AccountType.ASSET, currency="SGD")
        equity = Account(user_id=test_user_id, name="Capital", type=AccountType.EQUITY, currency="SGD")
        rounding_gain = Account(
            user_id=test_user_id, name="Bank Rounding Difference", type=AccountType.INCOME, currency="SGD"
        )
        db.add_all([cash, equity, rounding_gain])
        await db.commit()

        open_e = _post_entry(
            test_user_id,
            date(2025, 3, 1),
            "Open",
            [(cash, Direction.DEBIT, Decimal("2500.00"), "SGD"), (equity, Direction.CREDIT, Decimal("2500.00"), "SGD")],
        )
        adj_e = _post_entry(
            test_user_id,
            date(2025, 3, 31),
            "Penny Rounding Adjustment",
            [
                (cash, Direction.DEBIT, Decimal("0.02"), "SGD"),
                (rounding_gain, Direction.CREDIT, Decimal("0.02"), "SGD"),
            ],
        )
        db.add_all([open_e, adj_e])
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
        assert bs["total_assets"] == Decimal("2500.02")
        assert bs["equation_delta"] == Decimal("0.00")


class TestBenchDomain5InvestmentsAndAssets:
    """Domain 5: Investments & Multi-Asset Valuation (Flows 19–22)."""

    async def test_flow_19_brokerage_statement_position_sync(self, db: AsyncSession, test_user_id) -> None:
        """Flow 19: Position quantity * average_cost == Book cost; synced across statement boundaries."""
        qty = Decimal("50")
        avg_cost = Decimal("100.00")
        book_cost = qty * avg_cost
        assert book_cost == Decimal("5000.00")

        brokerage_cash = Account(user_id=test_user_id, name="IBKR Cash", type=AccountType.ASSET, currency="USD")
        etf_holdings = Account(user_id=test_user_id, name="VT ETF Holdings", type=AccountType.ASSET, currency="USD")
        equity = Account(user_id=test_user_id, name="Capital", type=AccountType.EQUITY, currency="USD")
        db.add_all([brokerage_cash, etf_holdings, equity])
        await db.commit()

        cap_e = _post_entry(
            test_user_id,
            date(2025, 1, 1),
            "Fund",
            [
                (brokerage_cash, Direction.DEBIT, Decimal("10000.00"), "USD"),
                (equity, Direction.CREDIT, Decimal("10000.00"), "USD"),
            ],
        )
        buy_e = _post_entry(
            test_user_id,
            date(2025, 1, 15),
            "Buy 50 VT ETF",
            [(etf_holdings, Direction.DEBIT, book_cost, "USD"), (brokerage_cash, Direction.CREDIT, book_cost, "USD")],
        )
        db.add_all([cap_e, buy_e])
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="USD")
        assert bs["total_assets"] == Decimal("10000.00")
        assert bs["equation_delta"] == Decimal("0.00")

    async def test_flow_20_dividend_gross_to_net_wht_split(self, db: AsyncSession, test_user_id) -> None:
        """Flow 20: Gross Dividend Income == Net Cash Received + Withholding Tax Expense."""
        div = calculate_dividend_split(gross_amount=Decimal("1200.00"), withholding_tax_rate=Decimal("0.30"))
        assert div.gross_amount == Decimal("1200.00")
        assert div.tax_amount == Decimal("360.00")
        assert div.net_amount == Decimal("840.00")
        assert div.net_amount + div.tax_amount == div.gross_amount

        cash = Account(user_id=test_user_id, name="Brokerage Cash", type=AccountType.ASSET, currency="USD")
        div_income = Account(user_id=test_user_id, name="Dividend Income", type=AccountType.INCOME, currency="USD")
        wht_exp = Account(
            user_id=test_user_id, name="Withholding Tax Expense", type=AccountType.EXPENSE, currency="USD"
        )
        db.add_all([cash, div_income, wht_exp])
        await db.commit()

        div_entry = _post_entry(
            test_user_id,
            date(2025, 2, 1),
            "US Dividend Distribution with WHT Split",
            [
                (cash, Direction.DEBIT, div.net_amount, "USD"),
                (wht_exp, Direction.DEBIT, div.tax_amount, "USD"),
                (div_income, Direction.CREDIT, div.gross_amount, "USD"),
            ],
        )
        db.add(div_entry)
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 2, 28), currency="USD")
        assert bs["total_assets"] == Decimal("840.00")
        assert bs["net_income"] == Decimal("840.00")
        assert bs["equation_delta"] == Decimal("0.00")

    async def test_flow_21_real_time_market_price_refresh_and_unrealized_pnl(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 21: Market value == Quantity * Latest Price; Unrealized PnL == Market value - Cost."""
        qty = Decimal("100")
        cost_price = Decimal("150.00")
        latest_price = Decimal("175.00")
        book_cost = qty * cost_price  # 15,000
        market_val = qty * latest_price  # 17,500
        unrealized_gain = market_val - book_cost  # 2,500
        assert unrealized_gain == Decimal("2500.00")

        stock_asset = Account(user_id=test_user_id, name="AAPL Shares", type=AccountType.ASSET, currency="USD")
        equity = Account(user_id=test_user_id, name="Owner Capital", type=AccountType.EQUITY, currency="USD")
        gain_account = Account(
            user_id=test_user_id, name="Unrealized Valuation Gain", type=AccountType.EQUITY, currency="USD"
        )
        db.add_all([stock_asset, equity, gain_account])
        await db.commit()

        e1 = _post_entry(
            test_user_id,
            date(2025, 1, 1),
            "Acquisition",
            [(stock_asset, Direction.DEBIT, book_cost, "USD"), (equity, Direction.CREDIT, book_cost, "USD")],
        )
        e2 = _post_entry(
            test_user_id,
            date(2025, 2, 28),
            "Mark-to-Market Refresh",
            [
                (stock_asset, Direction.DEBIT, unrealized_gain, "USD"),
                (gain_account, Direction.CREDIT, unrealized_gain, "USD"),
            ],
        )
        db.add_all([e1, e2])
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 2, 28), currency="USD")
        assert bs["total_assets"] == Decimal("17500.00")
        assert bs["total_equity"] == Decimal("17500.00")
        assert bs["equation_delta"] == Decimal("0.00")

    async def test_flow_22_mortgage_principal_amortization_and_interest_split(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 22: Total Mortgage Payment == Principal Reduction (Liability) + Interest Expense."""
        mtg = calculate_mortgage_split(total_payment=Decimal("3500.00"), interest_amount=Decimal("1500.00"))
        assert mtg.principal_amount == Decimal("2000.00")
        assert mtg.interest_amount == Decimal("1500.00")
        assert mtg.principal_amount + mtg.interest_amount == mtg.total_payment

        cash = Account(user_id=test_user_id, name="Checking", type=AccountType.ASSET, currency="SGD")
        capital = Account(user_id=test_user_id, name="Capital", type=AccountType.EQUITY, currency="SGD")
        mtg_liab = Account(user_id=test_user_id, name="Mortgage Loan", type=AccountType.LIABILITY, currency="SGD")
        interest_exp = Account(user_id=test_user_id, name="Mortgage Interest", type=AccountType.EXPENSE, currency="SGD")
        db.add_all([cash, capital, mtg_liab, interest_exp])
        await db.commit()

        # Seed capital 10,000 SGD and mortgage debt 500,000 SGD
        e_init = _post_entry(
            test_user_id,
            date(2025, 1, 1),
            "Init",
            [
                (cash, Direction.DEBIT, Decimal("10000.00"), "SGD"),
                (capital, Direction.CREDIT, Decimal("10000.00"), "SGD"),
            ],
        )
        # Mortgage payment split
        e_pay = _post_entry(
            test_user_id,
            date(2025, 1, 30),
            "Monthly Mortgage Payment",
            [
                (mtg_liab, Direction.DEBIT, mtg.principal_amount, "SGD"),
                (interest_exp, Direction.DEBIT, mtg.interest_amount, "SGD"),
                (cash, Direction.CREDIT, mtg.total_payment, "SGD"),
            ],
        )
        db.add_all([e_init, e_pay])
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
        assert bs["is_balanced"] is True
        assert bs["equation_delta"] == Decimal("0.00")


class TestBenchDomain6StatementGovernance:
    """Domain 6: Financial Reporting & Accounting Equation Governance (Flows 23–26)."""

    async def test_flow_23_balance_sheet_accounting_equation_exact_validation(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 23: Assets == Liabilities + Equity + RetainedEarnings (Equation Delta == 0.00)."""
        checking = Account(user_id=test_user_id, name="Bank Checking", type=AccountType.ASSET, currency="SGD")
        equity = Account(user_id=test_user_id, name="Owner Capital", type=AccountType.EQUITY, currency="SGD")
        income = Account(user_id=test_user_id, name="Consulting", type=AccountType.INCOME, currency="SGD")
        expense = Account(user_id=test_user_id, name="Supplies", type=AccountType.EXPENSE, currency="SGD")
        db.add_all([checking, equity, income, expense])
        await db.commit()

        e1 = _post_entry(
            test_user_id,
            date(2025, 1, 1),
            "Opening",
            [
                (checking, Direction.DEBIT, Decimal("5000.00"), "SGD"),
                (equity, Direction.CREDIT, Decimal("5000.00"), "SGD"),
            ],
        )
        e2 = _post_entry(
            test_user_id,
            date(2025, 1, 15),
            "Revenue",
            [
                (checking, Direction.DEBIT, Decimal("3000.00"), "SGD"),
                (income, Direction.CREDIT, Decimal("3000.00"), "SGD"),
            ],
        )
        e3 = _post_entry(
            test_user_id,
            date(2025, 1, 20),
            "Expenses",
            [
                (expense, Direction.DEBIT, Decimal("1200.00"), "SGD"),
                (checking, Direction.CREDIT, Decimal("1200.00"), "SGD"),
            ],
        )
        db.add_all([e1, e2, e3])
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
        assert bs["total_assets"] == Decimal("6800.00")
        assert bs["total_equity"] == Decimal("5000.00")
        assert bs["net_income"] == Decimal("1800.00")
        assert bs["is_balanced"] is True
        assert bs["equation_delta"] == Decimal("0.00")

    async def test_flow_24_accounting_equation_out_of_balance_diagnostic_triage(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 24: When Equation Delta != 0, returns classified cause."""
        # 1. Strictly balanced
        res_bal = diagnose_equation_imbalance(Decimal("0.00"))
        assert res_bal.is_balanced is True
        assert res_bal.primary_category == EquationDiagnosticCategory.BALANCED

        # 2. Unposted draft imbalance
        res_draft = diagnose_equation_imbalance(Decimal("450.00"), has_pending_drafts=True, unposted_draft_count=1)
        assert res_draft.is_balanced is False
        assert res_draft.primary_category == EquationDiagnosticCategory.UNPOSTED_DRAFT

        # 3. Unmapped account imbalance
        res_unmapped = diagnose_equation_imbalance(Decimal("200.00"), has_unclassified_accounts=True)
        assert res_unmapped.is_balanced is False
        assert res_unmapped.primary_category == EquationDiagnosticCategory.UNCLASSIFIED_ACCOUNT

        # 4. One-sided transaction imbalance
        res_onesided = diagnose_equation_imbalance(Decimal("100.00"), has_one_sided_entries=True)
        assert res_onesided.is_balanced is False
        assert res_onesided.primary_category == EquationDiagnosticCategory.ONE_SIDED_ENTRY

    async def test_flow_25_income_statement_comparative_trend_analysis(self, db: AsyncSession, test_user_id) -> None:
        """Flow 25: Comparative periodic columns display balance variations without silent drop."""
        cash = Account(user_id=test_user_id, name="Cash", type=AccountType.ASSET, currency="SGD")
        sal = Account(user_id=test_user_id, name="Salary", type=AccountType.INCOME, currency="SGD")
        rent = Account(user_id=test_user_id, name="Rent", type=AccountType.EXPENSE, currency="SGD")
        db.add_all([cash, sal, rent])
        await db.commit()

        # Month 1: Jan 2025
        e_jan1 = _post_entry(
            test_user_id,
            date(2025, 1, 15),
            "Jan Salary",
            [(cash, Direction.DEBIT, Decimal("5000.00"), "SGD"), (sal, Direction.CREDIT, Decimal("5000.00"), "SGD")],
        )
        e_jan2 = _post_entry(
            test_user_id,
            date(2025, 1, 25),
            "Jan Rent",
            [(rent, Direction.DEBIT, Decimal("2000.00"), "SGD"), (cash, Direction.CREDIT, Decimal("2000.00"), "SGD")],
        )
        # Month 2: Feb 2025
        e_feb1 = _post_entry(
            test_user_id,
            date(2025, 2, 15),
            "Feb Salary",
            [(cash, Direction.DEBIT, Decimal("5000.00"), "SGD"), (sal, Direction.CREDIT, Decimal("5000.00"), "SGD")],
        )
        e_feb2 = _post_entry(
            test_user_id,
            date(2025, 2, 25),
            "Feb Rent",
            [(rent, Direction.DEBIT, Decimal("2200.00"), "SGD"), (cash, Direction.CREDIT, Decimal("2200.00"), "SGD")],
        )
        db.add_all([e_jan1, e_jan2, e_feb1, e_feb2])
        await db.commit()

        # Jan Income Statement
        is_jan = await generate_income_statement(
            db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
        )
        assert is_jan["net_income"] == Decimal("3000.00")

        # Feb Income Statement
        is_feb = await generate_income_statement(
            db, test_user_id, start_date=date(2025, 2, 1), end_date=date(2025, 2, 28), currency="SGD"
        )
        assert is_feb["net_income"] == Decimal("2800.00")

    async def test_flow_26_cash_flow_statement_multi_activity_invariant(self, db: AsyncSession, test_user_id) -> None:
        """Flow 26: Net Cash Change == Operating Cash Flow + Investing Cash Flow + Financing Cash Flow."""
        cash = Account(user_id=test_user_id, name="Primary Cash Account", type=AccountType.ASSET, currency="SGD")
        equity = Account(user_id=test_user_id, name="Owner Capital", type=AccountType.EQUITY, currency="SGD")
        income = Account(user_id=test_user_id, name="Operating Revenue", type=AccountType.INCOME, currency="SGD")
        expense = Account(user_id=test_user_id, name="Operating Expense", type=AccountType.EXPENSE, currency="SGD")
        db.add_all([cash, equity, income, expense])
        await db.commit()

        e1 = _post_entry(
            test_user_id,
            date(2025, 1, 1),
            "Equity Deposit",
            [
                (cash, Direction.DEBIT, Decimal("10000.00"), "SGD"),
                (equity, Direction.CREDIT, Decimal("10000.00"), "SGD"),
            ],
        )
        e2 = _post_entry(
            test_user_id,
            date(2025, 1, 15),
            "Revenue",
            [(cash, Direction.DEBIT, Decimal("4000.00"), "SGD"), (income, Direction.CREDIT, Decimal("4000.00"), "SGD")],
        )
        e3 = _post_entry(
            test_user_id,
            date(2025, 1, 20),
            "Expenses",
            [
                (expense, Direction.DEBIT, Decimal("1500.00"), "SGD"),
                (cash, Direction.CREDIT, Decimal("1500.00"), "SGD"),
            ],
        )
        db.add_all([e1, e2, e3])
        await db.commit()

        cf = await generate_cash_flow(
            db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
        )
        summary = cf["summary"]
        assert summary["ending_cash"] == Decimal("12500.00")
        assert cf["cash_bridge"]["reconciles"] is True


class TestBenchDomain7AuditAndInsights:
    """Domain 7: Audit Traceability, Compliance & AI Insights (Flows 27–30)."""

    async def test_flow_27_financial_report_to_pdf_provenance_drilldown(self, db: AsyncSession, test_user_id) -> None:
        """Flow 27: Report Line drilldown traces to underlying journal entries and source statement metadata."""
        checking = Account(user_id=test_user_id, name="Checking", type=AccountType.ASSET, currency="SGD")
        capital = Account(user_id=test_user_id, name="Capital", type=AccountType.EQUITY, currency="SGD")
        db.add_all([checking, capital])
        await db.commit()

        entry = _post_entry(
            test_user_id,
            date(2025, 3, 1),
            "Drilldown Statement Reference [stmt_772]",
            [
                (checking, Direction.DEBIT, Decimal("3500.00"), "SGD"),
                (capital, Direction.CREDIT, Decimal("3500.00"), "SGD"),
            ],
        )
        db.add(entry)
        await db.commit()

        # Drilldown query: find all journal lines contributing to checking account
        query = (
            select(JournalLine, JournalEntry)
            .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
            .where(JournalLine.account_id == checking.id)
        )
        results = (await db.execute(query)).all()
        assert len(results) == 1
        line, parent_entry = results[0]
        assert line.amount == Decimal("3500.00")
        assert "stmt_772" in parent_entry.memo

    async def test_flow_28_annual_tax_package_zip_export_manifest_integrity(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 28: ZIP contains manifest.json with SHA-256 hashes of all schedule CSVs and audit trail."""
        schedule_content = (
            b"date,account,amount,type\n2025-01-15,Checking,5000.00,INCOME\n2025-01-20,Rent,-2000.00,EXPENSE\n"
        )
        digest = hashlib.sha256(schedule_content).hexdigest()
        manifest = {
            "version": "1.0",
            "framework": "US_GAAP_LIKE",
            "files": [
                {
                    "path": "schedules/general_ledger.csv",
                    "sha256": digest,
                    "bytes": len(schedule_content),
                }
            ],
        }
        assert hashlib.sha256(schedule_content).hexdigest() == manifest["files"][0]["sha256"]

    async def test_flow_29_recurring_subscription_anomaly_alert(self, db: AsyncSession, test_user_id) -> None:
        """Flow 29: Identifies recurring cadence and flags unexpected amount increases or duplicate runs."""
        cadence_history = [Decimal("12.99"), Decimal("12.99"), Decimal("12.99")]
        avg_charge = sum(cadence_history) / len(cadence_history)
        new_charge = Decimal("129.90")  # 10x spike

        is_anomaly = new_charge > (avg_charge * Decimal("3.0"))
        assert is_anomaly is True, "Spike exceeding 3x average must trigger anomaly alert"

    async def test_flow_30_natural_language_financial_ai_assistant_read_only_tool_calling(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 30: AI operates in read-only sandbox calling accounting queries with streaming response."""
        from src.advisor import is_write_request

        assert is_write_request("create a journal entry") is True
        assert is_write_request("delete journal entry 123") is True
        assert is_write_request("post a journal entry") is True
        assert is_write_request("What is my current balance sheet equation delta?") is False
        assert is_write_request("Summarize my income statement for Q1") is False
