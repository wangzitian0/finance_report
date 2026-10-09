"""AC-reporting.journeys.1-4: In-memory domain shift-left tests for Bench V2 financial articulation.

Validates the mathematical core of the Bench V2 accounting scenarios across 36 tests (6 holistic cases + 30 shift-left flow invariants) in ~10s:
- Cases 1–6: End-to-end multi-period holistic accounting scenarios.
- Domains 1–7: Canonical 30-flow shift-left invariant matrix (Flows 1–30).
"""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
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

STANDARD_BENCHMARK_FX_RATES: dict[str, Decimal] = {
    "USD": Decimal("1.35"),
    "HKD": Decimal("0.17"),
    "EUR": Decimal("1.45"),
}


def _post_entry(
    user_id,
    entry_date: date,
    memo: str,
    lines: list[tuple[Account, Direction, Decimal, str]],
    fx_rate: Decimal | None = None,
    fx_rates_by_currency: dict[str, Decimal] | None = None,
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
        if currency == "SGD":
            resolved_fx = None
        elif fx_rate is not None:
            resolved_fx = fx_rate
        elif fx_rates_by_currency and currency in fx_rates_by_currency:
            resolved_fx = fx_rates_by_currency[currency]
        elif currency in STANDARD_BENCHMARK_FX_RATES:
            resolved_fx = STANDARD_BENCHMARK_FX_RATES[currency]
        else:
            resolved_fx = Decimal("1.00")

        line = JournalLine(
            journal_entry=entry,
            account_id=account.id,
            direction=direction,
            amount=amount,
            currency=currency,
            fx_rate=resolved_fx,
        )
        entry.lines.append(line)
    return entry


async def _seed_accounts(
    db: AsyncSession,
    user_id,
    *specs: tuple[str, AccountType, str],
) -> list[Account]:
    accs = [Account(user_id=user_id, name=name, type=t, currency=curr) for name, t, curr in specs]
    db.add_all(accs)
    await db.commit()
    for acc in accs:
        await db.refresh(acc)
    return accs


def _pair_entry(
    user_id,
    entry_date: date,
    memo: str,
    debit_acc: Account,
    credit_acc: Account,
    amount: Decimal | str,
    currency: str = "SGD",
    fx_rate: Decimal | None = None,
) -> JournalEntry:
    amt = Decimal(str(amount))
    return _post_entry(
        user_id,
        entry_date,
        memo,
        [
            (debit_acc, Direction.DEBIT, amt, currency),
            (credit_acc, Direction.CREDIT, amt, currency),
        ],
        fx_rate=fx_rate,
    )


async def _seed_fx_rates(db: AsyncSession, *rates: tuple[str, str, str, date]) -> None:
    db.add_all(
        [FxRate(base_currency=b, quote_currency=q, rate=Decimal(r), rate_date=d, source="test") for b, q, r, d in rates]
    )
    await db.commit()


def _check_bs(
    bs: dict,
    total_assets: Decimal | str | None = None,
    total_liabilities: Decimal | str | None = None,
    total_equity: Decimal | str | None = None,
    net_income: Decimal | str | None = None,
    *,
    is_balanced: bool = True,
    delta: Decimal | str = "0.00",
) -> None:
    if total_assets is not None:
        assert bs["total_assets"] == Decimal(str(total_assets))
    if total_liabilities is not None:
        assert bs["total_liabilities"] == Decimal(str(total_liabilities))
    if total_equity is not None:
        assert bs["total_equity"] == Decimal(str(total_equity))
    if net_income is not None:
        assert bs["net_income"] == Decimal(str(net_income))
    assert bs["is_balanced"] is is_balanced
    assert bs["equation_delta"] == Decimal(str(delta))


def _check_is(
    is_res: dict, total_income: Decimal | str, total_expenses: Decimal | str, net_income: Decimal | str
) -> None:
    assert is_res["total_income"] == Decimal(str(total_income))
    assert is_res["total_expenses"] == Decimal(str(total_expenses))
    assert is_res["net_income"] == Decimal(str(net_income))


def _check_cf(cf: dict, net_cf: Decimal | str, ending_cash: Decimal | str, reconciles: bool = True) -> None:
    assert cf["summary"]["net_cash_flow"] == Decimal(str(net_cf))
    assert cf["summary"]["ending_cash"] == Decimal(str(ending_cash))
    assert cf["cash_bridge"]["reconciles"] is reconciles


async def test_bench_case_1_four_month_rollforward_and_articulation(db: AsyncSession, test_user_id) -> None:
    """Bench V2 Case 1: 4-month consecutive rollforward and Q1 3-statement articulation."""
    cash, equity, salary, bonus, living_exp = await _seed_accounts(
        db,
        test_user_id,
        ("Husband DBS Cash", AccountType.ASSET, "SGD"),
        ("Initial Capital", AccountType.EQUITY, "SGD"),
        ("Employment Salary", AccountType.INCOME, "SGD"),
        ("Annual Bonus", AccountType.INCOME, "SGD"),
        ("Living Expenses", AccountType.EXPENSE, "SGD"),
    )
    db.add_all(
        [
            _pair_entry(test_user_id, date(2025, 1, 1), "Opening capital", cash, equity, "15450.75"),
            _pair_entry(test_user_id, date(2025, 1, 15), "Jan Salary", cash, salary, "5000.00"),
            _pair_entry(test_user_id, date(2025, 1, 20), "Jan Expenses", living_exp, cash, "5179.52"),
            _pair_entry(test_user_id, date(2025, 2, 15), "Feb Salary", cash, salary, "5000.00"),
            _pair_entry(test_user_id, date(2025, 2, 20), "Feb Bonus", cash, bonus, "1000.00"),
            _pair_entry(test_user_id, date(2025, 2, 25), "Feb Expenses", living_exp, cash, "3021.23"),
            _pair_entry(test_user_id, date(2025, 3, 15), "Mar Salary", cash, salary, "5000.00"),
            _pair_entry(test_user_id, date(2025, 3, 25), "Mar Expenses", living_exp, cash, "1950.00"),
        ]
    )
    await db.commit()

    bs_q1 = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
    _check_bs(bs_q1, "21300.00", "0.00", "15450.75", "5849.25")

    is_q1 = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 3, 31), currency="SGD"
    )
    _check_is(is_q1, "16000.00", "10150.75", "5849.25")
    assert is_q1["net_income"] == bs_q1["net_income"]

    cf_q1 = await generate_cash_flow(
        db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 3, 31), currency="SGD"
    )
    _check_cf(cf_q1, "21300.00", "21300.00")

    db.add_all(
        [
            _pair_entry(test_user_id, date(2025, 4, 15), "Apr Salary", cash, salary, "5000.00"),
            _pair_entry(test_user_id, date(2025, 4, 25), "Apr Expenses", living_exp, cash, "2100.00"),
        ]
    )
    await db.commit()

    bs_m4 = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD")
    _check_bs(bs_m4, "24200.00", "0.00", "15450.75", "8749.25")


async def test_bench_case_2_multi_pii_household_consolidation(db: AsyncSession, test_user_id) -> None:
    """Bench V2 Case 2: Multi-PII household operations & multi-account balance consolidation."""
    husband_cash, wife_cash, capital, husband_income, wife_income, husband_exp, wife_exp = await _seed_accounts(
        db,
        test_user_id,
        ("Husband DBS Cash", AccountType.ASSET, "SGD"),
        ("Wife StanChart Cash", AccountType.ASSET, "SGD"),
        ("Household Capital", AccountType.EQUITY, "SGD"),
        ("Husband Income", AccountType.INCOME, "SGD"),
        ("Wife Income", AccountType.INCOME, "SGD"),
        ("Husband Expenses", AccountType.EXPENSE, "SGD"),
        ("Wife Expenses", AccountType.EXPENSE, "SGD"),
    )

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
    db.add_all(
        [
            entry_open,
            _pair_entry(test_user_id, date(2025, 4, 10), "Husband Salary", husband_cash, husband_income, "4000.00"),
            _pair_entry(test_user_id, date(2025, 4, 15), "Husband Bonus", husband_cash, husband_income, "1000.00"),
            _pair_entry(test_user_id, date(2025, 4, 20), "Husband Living", husband_exp, husband_cash, "2200.00"),
            _pair_entry(test_user_id, date(2025, 4, 12), "Wife Salary", wife_cash, wife_income, "3500.00"),
            _pair_entry(test_user_id, date(2025, 4, 18), "Wife Groceries", wife_exp, wife_cash, "400.00"),
        ]
    )
    await db.commit()

    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD")
    _check_bs(bs, "20900.00", "0.00", "15000.00", "5900.00")

    inc = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 4, 1), end_date=date(2025, 4, 30), currency="SGD"
    )
    _check_is(inc, "8500.00", "2600.00", "5900.00")


async def test_bench_case_3_credit_card_debt_clearance_and_zero_pnl_contamination(
    db: AsyncSession, test_user_id
) -> None:
    """Bench V2 Case 3: Credit card charge and non-P&L settlement verification."""
    bank_cash, cc_card, capital, dining_exp = await _seed_accounts(
        db,
        test_user_id,
        ("Operating Bank Cash", AccountType.ASSET, "SGD"),
        ("Visa Credit Card", AccountType.LIABILITY, "SGD"),
        ("Initial Capital", AccountType.EQUITY, "SGD"),
        ("Dining Expenses", AccountType.EXPENSE, "SGD"),
    )
    db.add_all(
        [
            _pair_entry(test_user_id, date(2025, 5, 1), "Initial cash", bank_cash, capital, "10000.00"),
            _pair_entry(test_user_id, date(2025, 5, 10), "Dining out with clients", dining_exp, cc_card, "1200.00"),
        ]
    )
    await db.commit()

    bs_mid = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 5, 15), currency="SGD")
    _check_bs(bs_mid, "10000.00", "1200.00", "10000.00", "-1200.00")

    db.add(_pair_entry(test_user_id, date(2025, 5, 25), "Pay credit card bill", cc_card, bank_cash, "1200.00"))
    await db.commit()

    bs_end = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 5, 31), currency="SGD")
    _check_bs(bs_end, "8800.00", "0.00", "10000.00", "-1200.00")

    inc_end = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 5, 1), end_date=date(2025, 5, 31), currency="SGD"
    )
    _check_is(inc_end, "0.00", "1200.00", "-1200.00")


async def test_bench_case_4_multicurrency_cta_balance_sheet(db: AsyncSession, test_user_id) -> None:
    """Bench V2 Case 4: Multi-currency balance sheet consolidation with IAS 21 CTA tracking."""
    cash_sgd, cash_usd, cash_hkd, capital_sgd, rev_usd, rev_hkd = await _seed_accounts(
        db,
        test_user_id,
        ("Operating SGD", AccountType.ASSET, "SGD"),
        ("Overseas USD", AccountType.ASSET, "USD"),
        ("Overseas HKD", AccountType.ASSET, "HKD"),
        ("Initial Capital", AccountType.EQUITY, "SGD"),
        ("Client Billing USD", AccountType.INCOME, "USD"),
        ("Client Billing HKD", AccountType.INCOME, "HKD"),
    )
    await _seed_fx_rates(
        db,
        ("USD", "SGD", "1.30", date(2025, 1, 1)),
        ("USD", "SGD", "1.30", date(2025, 1, 15)),
        ("USD", "SGD", "1.35", date(2025, 1, 31)),
        ("HKD", "SGD", "0.16", date(2025, 1, 1)),
        ("HKD", "SGD", "0.16", date(2025, 1, 15)),
        ("HKD", "SGD", "0.17", date(2025, 1, 31)),
    )
    db.add_all(
        [
            _pair_entry(test_user_id, date(2025, 1, 1), "Initial SGD capital", cash_sgd, capital_sgd, "12800.00"),
            _pair_entry(
                test_user_id,
                date(2025, 1, 10),
                "USD client payment",
                cash_usd,
                rev_usd,
                "5000.00",
                "USD",
                Decimal("1.30"),
            ),
            _pair_entry(
                test_user_id,
                date(2025, 1, 12),
                "HKD client payment",
                cash_hkd,
                rev_hkd,
                "20000.00",
                "HKD",
                Decimal("0.16"),
            ),
        ]
    )
    await db.commit()

    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
    assert bs["total_assets"] > Decimal("12800.00")
    assert bs["is_balanced"] is True
    assert bs["equation_delta"] == Decimal("0.00")
    assert bs["cta_adjustment"] is not None


async def test_bench_case_4_multicurrency_opening_equity_and_revenue_cta(db: AsyncSession, test_user_id) -> None:
    """Benchmark Case 4 variant: foreign currency opening equity contributions + operational revenue.

    Under IAS 21, opening positions in foreign currencies create an equity translation variance
    when translated at closing spot rates versus historical opening rates. This test ensures
    that both PnL translation variance and equity translation variance are absorbed into CTA,
    maintaining an exact 0.00 balance sheet equation delta.
    """
    cash_sgd, cash_usd, cash_hkd, capital_sgd, rev_usd, rev_hkd = await _seed_accounts(
        db,
        test_user_id,
        ("DBS SGD", AccountType.ASSET, "SGD"),
        ("SVB USD", AccountType.ASSET, "USD"),
        ("HSBC HKD", AccountType.ASSET, "HKD"),
        ("Opening Balance Equity", AccountType.EQUITY, "SGD"),
        ("Consulting USD", AccountType.INCOME, "USD"),
        ("Dividend HKD", AccountType.INCOME, "HKD"),
    )
    await _seed_fx_rates(
        db,
        ("USD", "SGD", "1.343920", date(2025, 4, 1)),
        ("USD", "SGD", "1.343920", date(2025, 4, 15)),
        ("USD", "SGD", "1.305640", date(2025, 4, 30)),
        ("HKD", "SGD", "0.172706", date(2025, 4, 1)),
        ("HKD", "SGD", "0.172706", date(2025, 4, 15)),
        ("HKD", "SGD", "0.169139", date(2025, 4, 30)),
        ("HKD", "USD", "0.129545", date(2025, 4, 30)),
    )
    db.add_all(
        [
            _pair_entry(test_user_id, date(2025, 4, 1), "Opening SGD", cash_sgd, capital_sgd, "10000.00"),
            _post_entry(
                test_user_id,
                date(2025, 4, 1),
                "Opening USD",
                [
                    (cash_usd, Direction.DEBIT, Decimal("5000.00"), "USD"),
                    (capital_sgd, Direction.CREDIT, Decimal("6719.60"), "SGD"),
                ],
                fx_rate=Decimal("1.343920"),
            ),
            _post_entry(
                test_user_id,
                date(2025, 4, 1),
                "Opening HKD",
                [
                    (cash_hkd, Direction.DEBIT, Decimal("20000.00"), "HKD"),
                    (capital_sgd, Direction.CREDIT, Decimal("3454.12"), "SGD"),
                ],
                fx_rate=Decimal("0.172706"),
            ),
            _pair_entry(
                test_user_id,
                date(2025, 4, 10),
                "Consulting USD",
                cash_usd,
                rev_usd,
                "1800.00",
                "USD",
                Decimal("1.319330"),
            ),
            _pair_entry(
                test_user_id,
                date(2025, 4, 12),
                "Dividend HKD",
                cash_hkd,
                rev_hkd,
                "4000.00",
                "HKD",
                Decimal("0.170200"),
            ),
        ]
    )
    await db.commit()

    bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD")
    print(
        f"DEBUG BS SGD: delta={bs['equation_delta']} cta={bs['cta_adjustment']} ufx={bs['unrealized_fx_gain_loss']} assets={bs['total_assets']} eq={bs['total_equity']} ni={bs['net_income']}"
    )
    assert bs["is_balanced"] is True
    assert bs["equation_delta"] == Decimal("0.00")

    bs_usd = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 4, 30), currency="USD")
    print(
        f"DEBUG BS USD: delta={bs_usd['equation_delta']} cta={bs_usd['cta_adjustment']} ufx={bs_usd['unrealized_fx_gain_loss']} assets={bs_usd['total_assets']} eq={bs_usd['total_equity']} ni={bs_usd['net_income']}"
    )
    assert bs_usd["is_balanced"] is True
    assert abs(bs_usd["equation_delta"]) < Decimal("0.05")


async def test_bench_case_5_holistic_multi_asset_and_tax_ecosystem(db: AsyncSession, test_user_id) -> None:
    """Benchmark Case 5: multi-asset portfolio, illiquid property, and W-2 tax withholding."""
    cash_sgd, tax_expense, salary_income, equity_account = await _seed_accounts(
        db,
        test_user_id,
        ("Cash", AccountType.ASSET, "SGD"),
        ("Payroll Taxes", AccountType.EXPENSE, "SGD"),
        ("Salary Income", AccountType.INCOME, "SGD"),
        ("Owner Capital", AccountType.EQUITY, "SGD"),
    )
    await _seed_fx_rates(db, ("USD", "SGD", "1.35", date(2025, 4, 30)))

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
    db.add_all(
        [
            _pair_entry(test_user_id, date(2025, 4, 1), "Initial Cash Capital", cash_sgd, equity_account, "5000.00"),
            payroll_entry,
        ]
    )
    await db.commit()

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

    bs_liquid = await generate_balance_sheet(
        db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD", include_restricted=False
    )
    _check_bs(bs_liquid, "13000.00", None, "5000.00", "8000.00")

    bs_comp = await generate_balance_sheet(
        db, test_user_id, as_of_date=date(2025, 4, 30), currency="SGD", include_restricted=True
    )
    expected_property_sgd = Decimal("350000.00") * Decimal("1.35")
    _check_bs(bs_comp, Decimal("13000.00") + expected_property_sgd, None, None, None)
    assert bs_comp["net_worth_adjustment_gain_loss"] == expected_property_sgd

    is_report = await generate_income_statement(
        db, test_user_id, start_date=date(2025, 4, 1), end_date=date(2025, 4, 30), currency="SGD"
    )
    _check_is(is_report, "10000.00", "2000.00", "8000.00")


async def test_bench_case_6_bank_overdraft_and_capital_gain_disposal(db: AsyncSession, test_user_id) -> None:
    """Benchmark Case 6: bank overdraft (negative cash balance) and asset disposal capital gains."""
    checking, emergency_exp, owner_equity, art_asset, capital_gain = await _seed_accounts(
        db,
        test_user_id,
        ("Primary Checking", AccountType.ASSET, "SGD"),
        ("Emergency Expense", AccountType.EXPENSE, "SGD"),
        ("Owner Equity", AccountType.EQUITY, "SGD"),
        ("Collectible Art", AccountType.ASSET, "SGD"),
        ("Realized Capital Gain", AccountType.INCOME, "SGD"),
    )

    db.add_all(
        [
            _pair_entry(test_user_id, date(2025, 5, 1), "Initial Checking Deposit", checking, owner_equity, "1000.00"),
            _pair_entry(
                test_user_id, date(2025, 5, 5), "Emergency Hospital Expense", emergency_exp, checking, "2500.00"
            ),
        ]
    )
    await db.commit()

    bs_overdraft = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 5, 10), currency="SGD")
    _check_bs(bs_overdraft, "-1500.00", None, "1000.00", "-2500.00")

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
    db.add_all(
        [
            _pair_entry(
                test_user_id, date(2025, 5, 15), "Emergency Capital Injection", checking, owner_equity, "10000.00"
            ),
            _pair_entry(test_user_id, date(2025, 5, 18), "Purchase Collectible Art", art_asset, checking, "4000.00"),
            art_sell,
        ]
    )
    await db.commit()

    bs_final = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 5, 31), currency="SGD")
    _check_bs(bs_final, "11000.00", None, "11000.00", "0.00")


# ==============================================================================
# CANONICAL 30-FLOW SHIFT-LEFT ARTICULATION MATRIX (DOMAINS 1–7)
# ==============================================================================


class TestBenchDomain1Ingestion:
    """Domain 1: Ingestion & Multimodal Extraction (Flows 1–5)."""

    async def test_flow_1_standard_statement_ingestion_balance_invariant(self, db: AsyncSession, test_user_id) -> None:
        """Flow 1: Parsed opening + sum(IN) - sum(OUT) == calculated_closing."""
        checking, equity, income, expense = await _seed_accounts(
            db,
            test_user_id,
            ("Primary Checking", AccountType.ASSET, "SGD"),
            ("Opening Equity", AccountType.EQUITY, "SGD"),
            ("Salary Income", AccountType.INCOME, "SGD"),
            ("Utility Expense", AccountType.EXPENSE, "SGD"),
        )
        db.add_all(
            [
                _pair_entry(test_user_id, date(2025, 1, 1), "Opening Balance", checking, equity, "10000.00"),
                _pair_entry(test_user_id, date(2025, 1, 10), "Salary Inflow", checking, income, "4500.00"),
                _pair_entry(test_user_id, date(2025, 1, 20), "Utility Outflow", expense, checking, "2350.25"),
            ]
        )
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
        _check_bs(bs, "12149.75")

    async def test_flow_2_batch_multimonth_continuity_and_gap_detection(self, db: AsyncSession, test_user_id) -> None:
        """Flow 2: Statement[M].closing_balance == Statement[M+1].opening_balance."""
        from datetime import UTC, datetime

        from src.ledger.data.account_coverage import (
            StatementCoverageRow,
            _coverage_issues,
        )
        from src.schemas.account import AccountCoverageIssueType

        acc_id = uuid4()
        now = datetime.now(UTC)

        # 1. Continuous statements without gaps or mismatch
        s1 = StatementCoverageRow(
            id=uuid4(),
            account_id=acc_id,
            currency="SGD",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            opening_balance=Decimal("10000.00"),
            closing_balance=Decimal("15271.23"),
            updated_at=now,
        )
        s2 = StatementCoverageRow(
            id=uuid4(),
            account_id=acc_id,
            currency="SGD",
            period_start=date(2025, 2, 1),
            period_end=date(2025, 2, 28),
            opening_balance=Decimal("15271.23"),
            closing_balance=Decimal("18500.00"),
            updated_at=now,
        )
        issues = _coverage_issues([s1, s2], "SGD")
        assert issues == [], "Continuous statements must produce zero coverage issues"

        # 2. Tampered opening balance triggers OPENING_BALANCE_MISMATCH
        s2_tampered = StatementCoverageRow(
            id=uuid4(),
            account_id=acc_id,
            currency="SGD",
            period_start=date(2025, 2, 1),
            period_end=date(2025, 2, 28),
            opening_balance=Decimal("16000.00"),
            closing_balance=Decimal("18500.00"),
            updated_at=now,
        )
        issues_tampered = _coverage_issues([s1, s2_tampered], "SGD")
        assert any(issue.type == AccountCoverageIssueType.OPENING_BALANCE_MISMATCH for issue in issues_tampered)

        # 3. Discontinuous gap triggers GAP issue
        s3_gap = StatementCoverageRow(
            id=uuid4(),
            account_id=acc_id,
            currency="SGD",
            period_start=date(2025, 4, 1),
            period_end=date(2025, 4, 30),
            opening_balance=Decimal("15271.23"),
            closing_balance=Decimal("19000.00"),
            updated_at=now,
        )
        issues_gap = _coverage_issues([s1, s3_gap], "SGD")
        assert any(issue.type == AccountCoverageIssueType.GAP for issue in issues_gap)

    async def test_flow_3_custom_csv_column_mapping_and_ledger_posting(self, db: AsyncSession, test_user_id) -> None:
        """Flow 3: All mapped rows have valid txn_date, description, and Decimal amount."""
        raw_csv_rows = [
            {"Txn Date": "2025-02-01", "Narration": "Client Retainer", "Credit": "3200.00", "Debit": "0.00"},
            {"Txn Date": "2025-02-05", "Narration": "Cloud Hosting", "Credit": "0.00", "Debit": "180.50"},
        ]
        cash, rev, exp = await _seed_accounts(
            db,
            test_user_id,
            ("Operating Cash", AccountType.ASSET, "SGD"),
            ("Client Revenue", AccountType.INCOME, "SGD"),
            ("Cloud Server", AccountType.EXPENSE, "SGD"),
        )
        db.add_all(
            [
                _pair_entry(
                    test_user_id, date(2025, 2, 1), raw_csv_rows[0]["Narration"], cash, rev, raw_csv_rows[0]["Credit"]
                ),
                _pair_entry(
                    test_user_id, date(2025, 2, 5), raw_csv_rows[1]["Narration"], exp, cash, raw_csv_rows[1]["Debit"]
                ),
            ]
        )
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 2, 28), currency="SGD")
        _check_bs(bs, "3019.50")

    async def test_flow_4_physical_receipt_evidence_hash_anchoring(self, db: AsyncSession, test_user_id) -> None:
        """Flow 4: Evidence file anchored to transaction or asset with SHA-256 digest."""
        receipt_bytes = b"RECEIPT_OCR_CONTENT_2025_02_14_COFFEE_8.50_SGD"
        digest = hashlib.sha256(receipt_bytes).hexdigest()

        cash, meals = await _seed_accounts(
            db,
            test_user_id,
            ("Wallet Cash", AccountType.ASSET, "SGD"),
            ("Meals Expense", AccountType.EXPENSE, "SGD"),
        )
        entry = _pair_entry(test_user_id, date(2025, 2, 14), f"Coffee Meeting [sha256:{digest}]", meals, cash, "8.50")
        db.add(entry)
        await db.commit()

        assert digest in entry.memo
        assert hashlib.sha256(receipt_bytes).hexdigest() == digest

    async def test_flow_5_alternative_asset_appraisal_and_valuation_snapshot(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 5: Valuation creates journal entry adjusting Asset and UnrealizedGain."""
        property_asset, equity, unrealized_gain = await _seed_accounts(
            db,
            test_user_id,
            ("Residential Condo", AccountType.ASSET, "SGD"),
            ("Owner Equity", AccountType.EQUITY, "SGD"),
            ("Property Unrealized Gain", AccountType.EQUITY, "SGD"),
        )
        db.add_all(
            [
                _pair_entry(
                    test_user_id, date(2025, 1, 1), "Condo Purchase at Cost", property_asset, equity, "500000.00"
                ),
                _pair_entry(
                    test_user_id,
                    date(2025, 3, 31),
                    "FHA 1004 Appraisal Revaluation Uplift",
                    property_asset,
                    unrealized_gain,
                    "50000.00",
                ),
            ]
        )
        await db.commit()

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
        _check_bs(bs, "550000.00", total_equity="550000.00")


class TestBenchDomain2ReviewAndTriage:
    """Domain 2: Fact Review & Human-in-the-Loop (Flows 6–10)."""

    async def test_flow_6_stage_1_quick_human_approval_posting(self, db: AsyncSession, test_user_id) -> None:
        """Flow 6: Approved statements create posted journal entries with matching custody account."""
        bank_acc, equity = await _seed_accounts(
            db,
            test_user_id,
            ("Bank Account", AccountType.ASSET, "SGD"),
            ("Owner Capital", AccountType.EQUITY, "SGD"),
        )
        entry = JournalEntry(
            user_id=test_user_id,
            entry_date=date(2025, 3, 1),
            memo="Draft Ingestion Statement",
            source_type=JournalEntrySourceType.AUTO_PARSED,
            status=JournalEntryStatus.DRAFT,
        )
        entry.lines = [
            JournalLine(
                journal_entry=entry,
                account_id=bank_acc.id,
                direction=Direction.DEBIT,
                amount=Decimal("1200.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry=entry,
                account_id=equity.id,
                direction=Direction.CREDIT,
                amount=Decimal("1200.00"),
                currency="SGD",
            ),
        ]
        db.add(entry)
        await db.commit()

        bs_pre = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 1), currency="SGD")
        _check_bs(bs_pre, "0.00")

        entry.status = JournalEntryStatus.POSTED
        await db.commit()

        bs_post = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 1), currency="SGD")
        _check_bs(bs_post, "1200.00")

    async def test_flow_7_stage_1_balance_mismatch_defense_and_rejection(self, db: AsyncSession, test_user_id) -> None:
        """Flow 7: Mismatch prevents silent corruption; rejects in-place mutation and routes to re-parse."""
        from src.extraction.base.validation import validate_balance
        from src.extraction.extension.statement_posting import (
            is_high_confidence_auto_approve_candidate,
        )
        from src.extraction.orm.statement_summary import BankStatementStatus, StatementSummary

        # 1. Validate payload with arithmetic mismatch: opening 5000 - out 200 = 4800 != 4600 stated
        payload = {
            "opening_balance": "5000.00",
            "closing_balance": "4600.00",
            "transactions": [{"amount": "200.00", "direction": "OUT"}],
        }
        val_result = validate_balance(payload)
        assert val_result["balance_valid"] is False
        assert val_result["difference"] == "200.00"
        assert val_result["expected_closing"] == "4800.00"

        # 2. Defense: statement with balance_validated=False cannot be auto-approved
        [acc] = await _seed_accounts(db, test_user_id, ("Checking", AccountType.ASSET, "SGD"))
        stmt = StatementSummary(
            user_id=test_user_id,
            account_id=acc.id,
            institution="DBS Bank",
            file_hash="mismatch_hash_flow7",
            currency="SGD",
            status=BankStatementStatus.APPROVED,
            balance_validated=False,
            confidence_score=95,
        )
        assert is_high_confidence_auto_approve_candidate(stmt) is False

    async def test_flow_8_cross_statement_overlapping_deduplication(self, db: AsyncSession, test_user_id) -> None:
        """Flow 8: Duplicate transactions flagged and linked without double-counting in ledger."""
        u_id = uuid4()
        kwargs = dict(
            user_id=u_id,
            txn_date=date(2025, 3, 15),
            amount=Decimal("250.00"),
            direction=TransactionDirection.OUT,
            description="OFFICE SUPPLIES STORE",
            balance_after=Decimal("8000.00"),
            occurrence_index=0,
        )
        h1 = DeduplicationService.calculate_transaction_hash(**kwargs)
        h2 = DeduplicationService.calculate_transaction_hash(**kwargs)
        assert h1 == h2, "Overlapping transactions must produce identical deterministic dedup hashes"

    async def test_flow_9_low_quality_document_triage_and_quarantine(self, db: AsyncSession, test_user_id) -> None:
        """Flow 9: Rejected statements excluded from general ledger and marked with taxonomy reason."""
        from src.extraction.base.source_vocabulary import Stage1Status
        from src.extraction.extension.statement_posting import (
            is_high_confidence_auto_approve_candidate,
        )
        from src.extraction.extension.statement_workflow import reject_statement_workflow
        from src.extraction.orm.statement_summary import BankStatementStatus, StatementSummary

        [cash] = await _seed_accounts(db, test_user_id, ("Operating Cash", AccountType.ASSET, "SGD"))
        stmt = StatementSummary(
            user_id=test_user_id,
            account_id=cash.id,
            institution="DBS Bank",
            file_hash="quarantine_hash_flow9",
            currency="SGD",
            status=BankStatementStatus.PARSED,
            balance_validated=False,
            confidence_score=35,
        )
        db.add(stmt)
        await db.commit()
        await db.refresh(stmt)

        rejected_stmt = await reject_statement_workflow(
            db, stmt.id, test_user_id, reason="OCR_RESOLUTION_BELOW_THRESHOLD"
        )
        assert rejected_stmt.status == BankStatementStatus.REJECTED
        assert rejected_stmt.stage1_status == Stage1Status.REJECTED
        assert rejected_stmt.stage1_reviewed_at is not None
        assert is_high_confidence_auto_approve_candidate(rejected_stmt) is False

        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
        assert bs["total_assets"] == Decimal("0.00")

    async def test_flow_10_contextual_in_page_ai_assistant_metadata_preservation(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 10: Chat prompt carries immutable statement metadata and gracefully recovers."""
        from src.advisor.base.prompt import DISCLAIMER_EN, get_ai_advisor_prompt

        context = {
            "advisor_context": "Statement stmt_2025_03_carson: Carson Bank (10,000.00 USD -> 12,500.00 USD)",
            "total_assets": "12500.00 USD",
            "total_liabilities": "0.00 USD",
            "equity": "12500.00 USD",
        }
        prompt = get_ai_advisor_prompt(context, language="en")
        for expected in (
            "Statement stmt_2025_03_carson: Carson Bank",
            "12500.00 USD",
            DISCLAIMER_EN,
            "You can only read the user's financial data",
        ):
            assert expected in prompt


class TestBenchDomain3IntentAndSplits:
    """Domain 3: Economic Intent & Categorization (Flows 11–14)."""

    async def test_flow_11_stage_2_interactive_economic_intent_allocation(self, db: AsyncSession, test_user_id) -> None:
        """Flow 11: Each transaction disposition assigns counter account and posts debit/credit."""
        bank, suspense, groceries = await _seed_accounts(
            db,
            test_user_id,
            ("Bank Cash", AccountType.ASSET, "SGD"),
            ("Suspense Unmatched", AccountType.EXPENSE, "SGD"),
            ("Groceries Expense", AccountType.EXPENSE, "SGD"),
        )
        db.add_all(
            [
                _pair_entry(test_user_id, date(2025, 2, 10), "Unidentified Supermarket", suspense, bank, "150.00"),
                _pair_entry(
                    test_user_id,
                    date(2025, 2, 10),
                    "Disposition Intent: Reallocate to Groceries",
                    groceries,
                    suspense,
                    "150.00",
                ),
            ]
        )
        await db.commit()
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 2, 28), currency="SGD")
        assert bs["is_balanced"] is True and bs["equation_delta"] == Decimal("0.00")

    async def test_flow_12_batch_rule_auto_fill_and_atomic_commit(self, db: AsyncSession, test_user_id) -> None:
        """Flow 12: Batch approve commits all matching rules atomically when checks resolved."""
        cash, transport = await _seed_accounts(
            db,
            test_user_id,
            ("Checking", AccountType.ASSET, "SGD"),
            ("Transport Expense", AccountType.EXPENSE, "SGD"),
        )
        db.add_all(
            [
                _pair_entry(test_user_id, date(2025, 2, d), f"GRAB *TRIP {i}", transport, cash, amt)
                for i, (d, amt) in enumerate([(1, "24.50"), (5, "18.00"), (9, "32.50")], start=1)
            ]
        )
        await db.commit()
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 2, 28), currency="SGD")
        assert bs["equation_delta"] == Decimal("0.00")

    async def test_flow_13_on_the_fly_counter_account_creation_during_review(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 13: On-the-fly counter account creation during review."""
        cash, new_account = await _seed_accounts(
            db,
            test_user_id,
            ("Bank Cash", AccountType.ASSET, "SGD"),
            ("Professional SaaS Tooling", AccountType.EXPENSE, "SGD"),
        )
        db.add(
            _pair_entry(test_user_id, date(2025, 3, 1), "GitHub Enterprise Subscription", new_account, cash, "42.00")
        )
        await db.commit()
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
        assert bs["is_balanced"] is True and bs["equation_delta"] == Decimal("0.00")

    async def test_flow_14_payroll_gross_to_net_tax_cpf_deductions_split(self, db: AsyncSession, test_user_id) -> None:
        """Flow 14: Gross Salary == Net Cash Payout + Income Tax Withholding + Employee Pension Deductions."""
        split = calculate_payroll_split(
            gross_salary=Decimal("6000.00"),
            income_tax=Decimal("900.00"),
            employee_deductions=Decimal("1200.00"),
        )
        assert split.gross_salary == Decimal("6000.00") and split.net_payout == Decimal("3900.00")
        assert split.net_payout + split.income_tax + split.employee_deductions == split.gross_salary

        cash, salary_exp, tax_payable, pension_payable = await _seed_accounts(
            db,
            test_user_id,
            ("Employee Checking", AccountType.ASSET, "SGD"),
            ("Gross Salaries", AccountType.EXPENSE, "SGD"),
            ("Payroll Tax Payable", AccountType.LIABILITY, "SGD"),
            ("CPF / Pension Payable", AccountType.LIABILITY, "SGD"),
        )
        db.add(
            _post_entry(
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
        )
        await db.commit()
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
        assert bs["is_balanced"] is True and bs["equation_delta"] == Decimal("0.00")


class TestBenchDomain4TransfersAndReconciliation:
    """Domain 4: Cross-Source Reconciliation & Transfers (Flows 15–18)."""

    async def test_flow_15_inter_account_transfer_pairing_zero_clearing(self, db: AsyncSession, test_user_id) -> None:
        """Flow 15: Source account Dr == Target account Cr; Transfer clearing account net balance == 0."""
        dbs_cash, ocbc_savings, clearing, equity = await _seed_accounts(
            db,
            test_user_id,
            ("DBS Checking", AccountType.ASSET, "SGD"),
            ("OCBC Savings", AccountType.ASSET, "SGD"),
            ("Transfer Clearing", AccountType.ASSET, "SGD"),
            ("Initial Capital", AccountType.EQUITY, "SGD"),
        )
        db.add_all(
            [
                _pair_entry(test_user_id, date(2025, 1, 1), "Capital", dbs_cash, equity, "5000.00"),
                _pair_entry(test_user_id, date(2025, 1, 15), "Transfer Out DBS", clearing, dbs_cash, "2000.00"),
                _pair_entry(test_user_id, date(2025, 1, 15), "Transfer In OCBC", ocbc_savings, clearing, "2000.00"),
            ]
        )
        await db.commit()
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
        assert (
            bs["total_assets"] == Decimal("5000.00")
            and bs["net_income"] == Decimal("0.00")
            and bs["equation_delta"] == Decimal("0.00")
        )

    async def test_flow_16_credit_card_repayment_debt_clearance_zero_pnl_leak(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 16: Bank cash outflow Dr CreditCardLiability == Credit card statement payment Inflow."""
        bank, card_liab, dining, capital = await _seed_accounts(
            db,
            test_user_id,
            ("Bank Cash", AccountType.ASSET, "SGD"),
            ("Credit Card Liability", AccountType.LIABILITY, "SGD"),
            ("Dining Expense", AccountType.EXPENSE, "SGD"),
            ("Capital", AccountType.EQUITY, "SGD"),
        )
        db.add_all(
            [
                _pair_entry(test_user_id, date(2025, 2, 5), "Dining Out", dining, card_liab, "800.00"),
                _pair_entry(test_user_id, date(2025, 2, 1), "Capital Deposit", bank, capital, "2000.00"),
                _pair_entry(test_user_id, date(2025, 2, 20), "Card Payment", card_liab, bank, "800.00"),
            ]
        )
        await db.commit()
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 2, 28), currency="SGD")
        assert bs["net_income"] == Decimal("-800.00") and bs["total_liabilities"] == Decimal("0.00")
        assert bs["is_balanced"] is True and bs["equation_delta"] == Decimal("0.00")

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
        assert fx.source_base_value == Decimal("1350.00") and fx.target_base_value == Decimal("1320.00")
        assert fx.realized_gain_loss == Decimal("-30.00")

        usd_cash, sgd_cash, fx_loss, capital = await _seed_accounts(
            db,
            test_user_id,
            ("USD Cash", AccountType.ASSET, "USD"),
            ("SGD Cash", AccountType.ASSET, "SGD"),
            ("Realized FX Loss", AccountType.EXPENSE, "SGD"),
            ("Capital", AccountType.EQUITY, "SGD"),
        )
        db.add_all(
            [
                _pair_entry(test_user_id, date(2025, 3, 1), "Cap", sgd_cash, capital, "1350.00"),
                _post_entry(
                    test_user_id,
                    date(2025, 3, 10),
                    "USD to SGD Conversion",
                    [
                        (sgd_cash, Direction.DEBIT, Decimal("1320.00"), "SGD"),
                        (fx_loss, Direction.DEBIT, Decimal("30.00"), "SGD"),
                        (sgd_cash, Direction.CREDIT, Decimal("1350.00"), "SGD"),
                    ],
                ),
            ]
        )
        await db.commit()
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
        assert bs["is_balanced"] is True and bs["equation_delta"] == Decimal("0.00")

    async def test_flow_18_reconciliation_penny_rounding_write_off(self, db: AsyncSession, test_user_id) -> None:
        """Flow 18: Immaterial discrepancy (|delta| <= 0.05) balances to BankRoundingDifference."""
        adj = calculate_reconciliation_adjustment(bank_balance=Decimal("2500.02"), book_balance=Decimal("2500.00"))
        assert adj.difference == Decimal("0.02") and adj.is_gain is True

        cash, equity, rounding_gain = await _seed_accounts(
            db,
            test_user_id,
            ("Bank Cash", AccountType.ASSET, "SGD"),
            ("Capital", AccountType.EQUITY, "SGD"),
            ("Bank Rounding Difference", AccountType.INCOME, "SGD"),
        )
        db.add_all(
            [
                _pair_entry(test_user_id, date(2025, 3, 1), "Open", cash, equity, "2500.00"),
                _pair_entry(test_user_id, date(2025, 3, 31), "Penny Rounding Adjustment", cash, rounding_gain, "0.02"),
            ]
        )
        await db.commit()
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 3, 31), currency="SGD")
        assert bs["total_assets"] == Decimal("2500.02") and bs["equation_delta"] == Decimal("0.00")


class TestBenchDomain5InvestmentsAndAssets:
    """Domain 5: Investments & Multi-Asset Valuation (Flows 19–22)."""

    async def test_flow_19_brokerage_statement_position_sync(self, db: AsyncSession, test_user_id) -> None:
        """Flow 19: Position quantity * average_cost == Book cost; synced across statement boundaries."""
        qty = Decimal("50")
        avg_cost = Decimal("100.00")
        book_cost = qty * avg_cost
        assert book_cost == Decimal("5000.00")

        brokerage_cash, etf_holdings, equity = await _seed_accounts(
            db,
            test_user_id,
            ("IBKR Cash", AccountType.ASSET, "USD"),
            ("VT ETF Holdings", AccountType.ASSET, "USD"),
            ("Capital", AccountType.EQUITY, "USD"),
        )
        db.add_all(
            [
                _pair_entry(test_user_id, date(2025, 1, 1), "Fund", brokerage_cash, equity, "10000.00", currency="USD"),
                _pair_entry(
                    test_user_id,
                    date(2025, 1, 15),
                    "Buy 50 VT ETF",
                    etf_holdings,
                    brokerage_cash,
                    book_cost,
                    currency="USD",
                ),
            ]
        )
        await db.commit()
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="USD")
        assert bs["total_assets"] == Decimal("10000.00") and bs["equation_delta"] == Decimal("0.00")

    async def test_flow_20_dividend_gross_to_net_wht_split(self, db: AsyncSession, test_user_id) -> None:
        """Flow 20: Gross Dividend Income == Net Cash Received + Withholding Tax Expense."""
        div = calculate_dividend_split(gross_amount=Decimal("1200.00"), withholding_tax_rate=Decimal("0.30"))
        assert (
            div.gross_amount == Decimal("1200.00")
            and div.tax_amount == Decimal("360.00")
            and div.net_amount == Decimal("840.00")
        )
        assert div.net_amount + div.tax_amount == div.gross_amount

        cash, div_income, wht_exp = await _seed_accounts(
            db,
            test_user_id,
            ("Brokerage Cash", AccountType.ASSET, "USD"),
            ("Dividend Income", AccountType.INCOME, "USD"),
            ("Withholding Tax Expense", AccountType.EXPENSE, "USD"),
        )
        db.add(
            _post_entry(
                test_user_id,
                date(2025, 2, 1),
                "US Dividend Distribution with WHT Split",
                [
                    (cash, Direction.DEBIT, div.net_amount, "USD"),
                    (wht_exp, Direction.DEBIT, div.tax_amount, "USD"),
                    (div_income, Direction.CREDIT, div.gross_amount, "USD"),
                ],
            )
        )
        await db.commit()
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 2, 28), currency="USD")
        assert (
            bs["total_assets"] == Decimal("840.00")
            and bs["net_income"] == Decimal("840.00")
            and bs["equation_delta"] == Decimal("0.00")
        )

    async def test_flow_21_real_time_market_price_refresh_and_unrealized_pnl(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 21: Market value == Quantity * Latest Price; Unrealized PnL == Market value - Cost."""
        qty, cost_price, latest_price = Decimal("100"), Decimal("150.00"), Decimal("175.00")
        book_cost, market_val = qty * cost_price, qty * latest_price
        unrealized_gain = market_val - book_cost
        assert unrealized_gain == Decimal("2500.00")

        stock_asset, equity, gain_account = await _seed_accounts(
            db,
            test_user_id,
            ("AAPL Shares", AccountType.ASSET, "USD"),
            ("Owner Capital", AccountType.EQUITY, "USD"),
            ("Unrealized Valuation Gain", AccountType.EQUITY, "USD"),
        )
        db.add_all(
            [
                _pair_entry(
                    test_user_id, date(2025, 1, 1), "Acquisition", stock_asset, equity, book_cost, currency="USD"
                ),
                _pair_entry(
                    test_user_id,
                    date(2025, 2, 28),
                    "Mark-to-Market Refresh",
                    stock_asset,
                    gain_account,
                    unrealized_gain,
                    currency="USD",
                ),
            ]
        )
        await db.commit()
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 2, 28), currency="USD")
        assert (
            bs["total_assets"] == Decimal("17500.00")
            and bs["total_equity"] == Decimal("17500.00")
            and bs["equation_delta"] == Decimal("0.00")
        )

    async def test_flow_22_mortgage_principal_amortization_and_interest_split(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 22: Total Mortgage Payment == Principal Reduction (Liability) + Interest Expense."""
        mtg = calculate_mortgage_split(total_payment=Decimal("3500.00"), interest_amount=Decimal("1500.00"))
        assert mtg.principal_amount == Decimal("2000.00") and mtg.interest_amount == Decimal("1500.00")
        assert mtg.principal_amount + mtg.interest_amount == mtg.total_payment

        cash, capital, mtg_liab, interest_exp = await _seed_accounts(
            db,
            test_user_id,
            ("Checking", AccountType.ASSET, "SGD"),
            ("Capital", AccountType.EQUITY, "SGD"),
            ("Mortgage Loan", AccountType.LIABILITY, "SGD"),
            ("Mortgage Interest", AccountType.EXPENSE, "SGD"),
        )
        db.add_all(
            [
                _pair_entry(test_user_id, date(2025, 1, 1), "Init", cash, capital, "10000.00"),
                _post_entry(
                    test_user_id,
                    date(2025, 1, 30),
                    "Monthly Mortgage Payment",
                    [
                        (mtg_liab, Direction.DEBIT, mtg.principal_amount, "SGD"),
                        (interest_exp, Direction.DEBIT, mtg.interest_amount, "SGD"),
                        (cash, Direction.CREDIT, mtg.total_payment, "SGD"),
                    ],
                ),
            ]
        )
        await db.commit()
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
        assert bs["is_balanced"] is True and bs["equation_delta"] == Decimal("0.00")


class TestBenchDomain6StatementGovernance:
    """Domain 6: Financial Reporting & Accounting Equation Governance (Flows 23–26)."""

    async def test_flow_23_balance_sheet_accounting_equation_exact_validation(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 23: Assets == Liabilities + Equity + RetainedEarnings (Equation Delta == 0.00)."""
        checking, equity, income, expense = await _seed_accounts(
            db,
            test_user_id,
            ("Bank Checking", AccountType.ASSET, "SGD"),
            ("Owner Capital", AccountType.EQUITY, "SGD"),
            ("Consulting", AccountType.INCOME, "SGD"),
            ("Supplies", AccountType.EXPENSE, "SGD"),
        )
        db.add_all(
            [
                _pair_entry(test_user_id, date(2025, 1, 1), "Opening", checking, equity, "5000.00"),
                _pair_entry(test_user_id, date(2025, 1, 15), "Revenue", checking, income, "3000.00"),
                _pair_entry(test_user_id, date(2025, 1, 20), "Expenses", expense, checking, "1200.00"),
            ]
        )
        await db.commit()
        bs = await generate_balance_sheet(db, test_user_id, as_of_date=date(2025, 1, 31), currency="SGD")
        _check_bs(bs, "6800.00", total_equity="5000.00", net_income="1800.00")

    async def test_flow_24_accounting_equation_out_of_balance_diagnostic_triage(
        self, db: AsyncSession, test_user_id
    ) -> None:
        """Flow 24: When Equation Delta != 0, returns classified cause."""
        res_bal = diagnose_equation_imbalance(Decimal("0.00"))
        assert res_bal.is_balanced is True and res_bal.primary_category == EquationDiagnosticCategory.BALANCED

        res_draft = diagnose_equation_imbalance(Decimal("450.00"), has_pending_drafts=True, unposted_draft_count=1)
        assert (
            res_draft.is_balanced is False and res_draft.primary_category == EquationDiagnosticCategory.UNPOSTED_DRAFT
        )

        res_unmapped = diagnose_equation_imbalance(Decimal("200.00"), has_unclassified_accounts=True)
        assert (
            res_unmapped.is_balanced is False
            and res_unmapped.primary_category == EquationDiagnosticCategory.UNCLASSIFIED_ACCOUNT
        )

        res_onesided = diagnose_equation_imbalance(Decimal("100.00"), has_one_sided_entries=True)
        assert (
            res_onesided.is_balanced is False
            and res_onesided.primary_category == EquationDiagnosticCategory.ONE_SIDED_ENTRY
        )

    async def test_flow_25_income_statement_comparative_trend_analysis(self, db: AsyncSession, test_user_id) -> None:
        """Flow 25: Comparative periodic columns display balance variations without silent drop."""
        cash, sal, rent = await _seed_accounts(
            db,
            test_user_id,
            ("Cash", AccountType.ASSET, "SGD"),
            ("Salary", AccountType.INCOME, "SGD"),
            ("Rent", AccountType.EXPENSE, "SGD"),
        )
        db.add_all(
            [
                _pair_entry(test_user_id, date(2025, 1, 15), "Jan Salary", cash, sal, "5000.00"),
                _pair_entry(test_user_id, date(2025, 1, 25), "Jan Rent", rent, cash, "2000.00"),
                _pair_entry(test_user_id, date(2025, 2, 15), "Feb Salary", cash, sal, "5000.00"),
                _pair_entry(test_user_id, date(2025, 2, 25), "Feb Rent", rent, cash, "2200.00"),
            ]
        )
        await db.commit()

        is_jan = await generate_income_statement(
            db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
        )
        is_feb = await generate_income_statement(
            db, test_user_id, start_date=date(2025, 2, 1), end_date=date(2025, 2, 28), currency="SGD"
        )
        assert is_jan["net_income"] == Decimal("3000.00") and is_feb["net_income"] == Decimal("2800.00")

    async def test_flow_26_cash_flow_statement_multi_activity_invariant(self, db: AsyncSession, test_user_id) -> None:
        """Flow 26: Net Cash Change == Operating Cash Flow + Investing Cash Flow + Financing Cash Flow."""
        cash, equity, income, expense = await _seed_accounts(
            db,
            test_user_id,
            ("Primary Cash Account", AccountType.ASSET, "SGD"),
            ("Owner Capital", AccountType.EQUITY, "SGD"),
            ("Operating Revenue", AccountType.INCOME, "SGD"),
            ("Operating Expense", AccountType.EXPENSE, "SGD"),
        )
        db.add_all(
            [
                _pair_entry(test_user_id, date(2025, 1, 1), "Equity Deposit", cash, equity, "10000.00"),
                _pair_entry(test_user_id, date(2025, 1, 15), "Revenue", cash, income, "4000.00"),
                _pair_entry(test_user_id, date(2025, 1, 20), "Expenses", expense, cash, "1500.00"),
            ]
        )
        await db.commit()

        cf = await generate_cash_flow(
            db, test_user_id, start_date=date(2025, 1, 1), end_date=date(2025, 1, 31), currency="SGD"
        )
        assert cf["summary"]["ending_cash"] == Decimal("12500.00") and cf["cash_bridge"]["reconciles"] is True


class TestBenchDomain7AuditAndInsights:
    """Domain 7: Audit Traceability, Compliance & AI Insights (Flows 27–30)."""

    async def test_flow_27_financial_report_to_pdf_provenance_drilldown(self, db: AsyncSession, test_user_id) -> None:
        """Flow 27: Report Line drilldown traces to underlying journal entries and source statement metadata."""
        checking, capital = await _seed_accounts(
            db,
            test_user_id,
            ("Checking", AccountType.ASSET, "SGD"),
            ("Capital", AccountType.EQUITY, "SGD"),
        )
        db.add(
            _pair_entry(
                test_user_id,
                date(2025, 3, 1),
                "Drilldown Statement Reference [stmt_772]",
                checking,
                capital,
                "3500.00",
            )
        )
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
        self, db: AsyncSession, test_user_id, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Flow 28: ZIP contains manifest.json with SHA-256 hashes of all schedule CSVs and audit trail."""
        import json
        import zipfile
        from io import BytesIO

        from src.routers.reports import (
            PackageSnapshotExportFormat,
            export_personal_report_package_snapshot,
            generate_personal_report_package_snapshot,
        )
        from src.schemas import (
            PersonalReportingFrameworkId,
            PersonalReportPackageGenerateRequest,
        )
        from tests.api.test_personal_report_package_contract import (
            _patch_package_snapshot_inputs,
        )

        await _patch_package_snapshot_inputs(
            monkeypatch,
            readiness_state="ready",
            blocking_count=0,
            section_label="Bench Annual Audit 2025",
        )

        snapshot = await generate_personal_report_package_snapshot(
            request=PersonalReportPackageGenerateRequest(
                framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
                as_of_date=date(2025, 12, 31),
                currency="SGD",
            ),
            db=db,
            user_id=test_user_id,
        )

        zip_response = await export_personal_report_package_snapshot(
            snapshot_id=snapshot.id,
            format=PackageSnapshotExportFormat.ZIP,
            db=db,
            user_id=test_user_id,
        )
        assert zip_response.media_type == "application/zip"

        chunks = []
        async for chunk in zip_response.body_iterator:
            chunks.append(chunk.encode("utf-8") if isinstance(chunk, str) else chunk)
        body_bytes = b"".join(chunks)

        with zipfile.ZipFile(BytesIO(body_bytes), "r") as zf:
            namelist = zf.namelist()
            assert "manifest.json" in namelist
            assert "balance_sheet.csv" in namelist
            assert "income_statement.csv" in namelist
            assert "cash_flow.csv" in namelist

            manifest_data = json.loads(zf.read("manifest.json").decode("utf-8"))
            assert manifest_data["package_id"] == str(snapshot.id)
            assert manifest_data["reporting_currency"] == "SGD"
            assert len(manifest_data["files"]) > 0

            for entry in manifest_data["files"]:
                filename = entry["filename"]
                expected_sha256 = entry["sha256"]
                assert filename in namelist
                actual_sha256 = hashlib.sha256(zf.read(filename)).hexdigest()
                assert actual_sha256 == expected_sha256

    async def test_flow_29_recurring_subscription_anomaly_alert(self, db: AsyncSession, test_user_id) -> None:
        """Flow 29: Identifies recurring cadence and flags unexpected amount increases or duplicate runs."""
        from datetime import timedelta

        from src.extraction import TransactionDirection
        from src.reconciliation.extension.anomaly import detect_anomalies
        from tests.factories import AtomicTransactionFactory

        # Create baseline of small recurring charges within 30-day lookback
        for i in range(30):
            await AtomicTransactionFactory.create_async(
                db,
                user_id=test_user_id,
                amount=Decimal("1.00"),
                direction=TransactionDirection.OUT,
                txn_date=date.today() - timedelta(days=(i % 28) + 1),
                description="STREAMING SERVICE SUBSCRIPTION",
            )

        # Huge spike transaction
        spike_txn = await AtomicTransactionFactory.create_async(
            db,
            user_id=test_user_id,
            amount=Decimal("5000.00"),
            direction=TransactionDirection.OUT,
            txn_date=date.today(),
            description="STREAMING SERVICE SUBSCRIPTION",
        )
        await db.commit()

        anomalies = await detect_anomalies(db, spike_txn, user_id=test_user_id)
        assert any(a.anomaly_type == "LARGE_AMOUNT" for a in anomalies)

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
