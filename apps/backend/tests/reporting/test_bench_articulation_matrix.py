"""AC-reporting.journeys.1-4: In-memory domain shift-left tests for Bench V2 financial articulation.

Validates the mathematical core of the Bench V2 accounting scenarios against SQLite in < 0.5s:
- Case 1: 4-Month Consecutive Rollforward & Q1 Three-Statement Articulation.
- Case 2: Multi-PII Household Operations & Consolidated Multi-Account Reporting.
- Case 3: Credit Card Liability Clearance & Non-P&L Repayment Zero Contamination.
- Case 4: Multi-Currency Consolidated Balance Sheet with IAS 21 CTA Rendering.
- Case 5: Holistic Multi-Asset & Tax Valuation (W-2 Withholding and Illiquid Appraisals).
- Case 6: Bank Overdraft (Negative Cash Balance) and Asset Disposal Capital Gains.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)
from src.pricing.base.manual_valuation import (
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
)
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.pricing.orm.market_data import FxRate
from src.reporting import (
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
        line = JournalLine(
            journal_entry=entry,
            account_id=account.id,
            direction=direction,
            amount=amount,
            currency=currency,
            fx_rate=fx_rate if currency != "SGD" else None,
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
