from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src import reporting as reporting_service
from src.extraction.extension.prompts.csv_mapping import build_csv_mapping_prompt
from src.ledger import Account, AccountType, Direction, JournalLine
from src.reconciliation import RECONCILIATION_SEMANTIC_PROMPT, build_reconciliation_prompt
from src.reporting import (
    ReportError,
    _add_months,
    _iter_periods,
    _month_end,
    _month_start,
    _normalize_currency,
    _quantize_money,
    _quarter_start,
    _signed_amount,
)
from src.reporting.base.balance_sheet_calculator import (
    calculate_balance_sheet_equation,
    calculate_currency_translation_adjustment,
)
from src.reporting.base.cash_flow_calculator import calculate_cash_flow_bridge
from src.reporting.base.income_statement_calculator import calculate_income_statement_totals, calculate_line_total
from src.reporting.extension import reporting_calc
from src.reporting.extension._core import _line_total
from src.reporting.extension.income_statement import _fold_and_deduplicate_lines
from src.reporting.extension.reporting_calc import AnnualizedIncomeTotals, resolve_line_currency
from src.schemas.base import normalize_currency_code

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(
    ("kwargs", "expected_balanced", "expected_delta"),
    [
        (
            {
                "total_assets": Decimal("1000.00"),
                "total_liabilities": Decimal("300.00"),
                "total_equity": Decimal("500.00"),
                "net_income": Decimal("200.00"),
            },
            True,
            Decimal("0.00"),
        ),
        (
            {
                "total_assets": Decimal("1000.00"),
                "total_liabilities": Decimal("300.00"),
                "total_equity": Decimal("500.00"),
                "net_income": Decimal("150.00"),
            },
            False,
            Decimal("50.00"),
        ),
        (
            {
                "total_assets": Decimal("25737.69"),
                "total_liabilities": Decimal("0.00"),
                "total_equity": Decimal("10000.00"),
                "net_income": Decimal("15727.91"),
                "cta_adjustment": Decimal("9.78"),
            },
            True,
            Decimal("0.00"),
        ),
        (
            {
                "total_assets": Decimal("25637.69"),
                "total_liabilities": Decimal("0.00"),
                "total_equity": Decimal("10000.00"),
                "net_income": Decimal("15727.91"),
                "cta_adjustment": Decimal("9.78"),
            },
            False,
            Decimal("-100.00"),
        ),
    ],
)
def test_balance_sheet_equation_calculator(kwargs: dict, expected_balanced: bool, expected_delta: Decimal) -> None:
    totals = calculate_balance_sheet_equation(
        unrealized_fx=Decimal("0.00"), net_worth_adjustment=Decimal("0.00"), **kwargs
    )
    assert (totals.is_balanced, totals.equation_delta) == (expected_balanced, expected_delta)
    assert totals.total_liabilities_and_equity == (
        kwargs["total_liabilities"]
        + kwargs["total_equity"]
        + kwargs["net_income"]
        + kwargs.get("cta_adjustment", Decimal("0.00"))
    )


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "is_multicurrency": True,
                "pnl_translation_variance": Decimal("-42.09"),
                "unrealized_fx": Decimal("-652.24"),
                "equity_translation_variance": Decimal("-512.77"),
            },
            Decimal("97.38"),
        ),
        (
            {
                "is_multicurrency": True,
                "pnl_translation_variance": Decimal("0.00"),
                "unrealized_fx": Decimal("150.00"),
                "equity_translation_variance": Decimal("-50.00"),
            },
            Decimal("-200.00"),
        ),
        (
            {
                "is_multicurrency": True,
                "pnl_translation_variance": Decimal("0.00"),
                "unrealized_fx": Decimal("262.73"),
                "equity_translation_variance": Decimal("0.00"),
            },
            Decimal("0.00"),
        ),
        ({"is_multicurrency": True, "pnl_translation_variance": Decimal("9.78")}, Decimal("9.78")),
        (
            {
                "is_multicurrency": False,
                "pnl_translation_variance": Decimal("100.00"),
                "unrealized_fx": Decimal("50.00"),
                "equity_translation_variance": Decimal("25.00"),
            },
            Decimal("0.00"),
        ),
    ],
)
def test_currency_translation_adjustment_calculator(kwargs: dict, expected: Decimal) -> None:
    assert calculate_currency_translation_adjustment(**kwargs) == expected


def test_cta_rejects_unexpected_total_assets() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument 'total_assets'"):
        calculate_currency_translation_adjustment(is_multicurrency=True, total_assets=Decimal("1000.00"))


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {
                "beginning_cash": Decimal("10000.00"),
                "ending_cash": Decimal("11500.00"),
                "operating_total": Decimal("3000.00"),
                "investing_total": Decimal("-1000.00"),
                "financing_total": Decimal("-500.00"),
            },
            (Decimal("1500.00"), Decimal("1500.00"), Decimal("0.00"), True),
        ),
        (
            {
                "beginning_cash": Decimal("5000.00"),
                "ending_cash": Decimal("7200.00"),
                "operating_total": Decimal("2000.00"),
                "investing_total": Decimal("0.00"),
                "financing_total": Decimal("0.00"),
                "fx_effect": Decimal("200.00"),
            },
            (Decimal("2200.00"), Decimal("2000.00"), Decimal("0.00"), True),
        ),
        (
            {
                "beginning_cash": Decimal("0.00"),
                "ending_cash": Decimal("10000.00"),
                "operating_total": Decimal("0.00"),
                "investing_total": Decimal("0.00"),
                "financing_total": Decimal("0.00"),
                "opening_stock_adjustment": Decimal("10000.00"),
            },
            (Decimal("10000.00"), Decimal("0.00"), Decimal("0.00"), True),
        ),
        (
            {
                "beginning_cash": Decimal("10000.00"),
                "ending_cash": Decimal("15000.00"),
                "operating_total": Decimal("4000.00"),
                "investing_total": Decimal("0.00"),
                "financing_total": Decimal("0.00"),
            },
            (Decimal("5000.00"), Decimal("4000.00"), Decimal("1000.00"), False),
        ),
    ],
)
def test_cash_flow_bridge_calculator(kwargs: dict, expected: tuple[Decimal, Decimal, Decimal, bool]) -> None:
    bridge = calculate_cash_flow_bridge(**kwargs)
    assert (bridge.cash_delta, bridge.classified_activity, bridge.discrepancy, bridge.reconciles) == expected


@pytest.mark.parametrize(
    ("income", "expenses", "expected"),
    [
        (
            [{"amount": Decimal("5000.00")}, {"amount": Decimal("250.50")}],
            [{"amount": Decimal("1500.00")}, {"amount": Decimal("350.25")}],
            (Decimal("5250.50"), Decimal("1850.25"), Decimal("3400.25")),
        ),
        (
            [{"amount": Decimal("1200.00")}],
            [{"amount": Decimal("1500.00")}, {"amount": Decimal("300.00")}],
            (Decimal("1200.00"), Decimal("1800.00"), Decimal("-600.00")),
        ),
        ([], [], (Decimal("0.00"), Decimal("0.00"), Decimal("0.00"))),
        (
            [{"amount": Decimal("1000.00")}],
            [{"amount": Decimal("450.00")}],
            (Decimal("1000.00"), Decimal("450.00"), Decimal("550.00")),
        ),
    ],
)
def test_income_statement_and_line_total_calculators(income: list, expenses: list, expected: tuple) -> None:
    totals = calculate_income_statement_totals(income, expenses)
    assert (totals.total_income, totals.total_expenses, totals.net_income) == expected
    assert calculate_line_total([{"amount": "100.55"}, {"amount": Decimal("200.45")}]) == Decimal("301.00")
    assert _line_total([{"amount": "10.005"}, {"amount": Decimal("0.001")}, {"amount": "-2.50"}]) == Decimal("7.51")
    assert _line_total([]) == Decimal("0.00")


def test_reporting_calc_helpers_and_exports() -> None:
    for name in (
        "ReportError",
        "_signed_amount",
        "_quantize_money",
        "_combine_provenance",
        "_iter_periods",
        "_month_start",
        "_month_end",
        "_add_months",
    ):
        assert getattr(reporting_service, name) is getattr(reporting_calc, name)
    assert _normalize_currency(None) and _normalize_currency(" usd ") == "USD"
    assert normalize_currency_code("  sgd ") == "SGD"
    assert _signed_amount(AccountType.ASSET, Direction.DEBIT, Decimal("10")) == Decimal("10")
    assert _signed_amount(AccountType.ASSET, Direction.CREDIT, Decimal("10")) == Decimal("-10")
    assert _signed_amount(AccountType.LIABILITY, Direction.CREDIT, Decimal("10")) == Decimal("10")
    assert _signed_amount(AccountType.LIABILITY, Direction.DEBIT, Decimal("10")) == Decimal("-10")
    assert _quantize_money(Decimal("10.005")) == Decimal("10.00")
    assert reporting_calc.income_bucket("Monthly Salary") == "salary"
    assert reporting_calc.income_bucket("Year-end Bonus") == "bonus"
    assert reporting_calc.income_bucket("Dividend payout") == "dividend"
    assert reporting_calc.income_bucket("Groceries") is None
    assert reporting_calc._combine_provenance(["imported", "imported"]) == "imported"
    assert reporting_calc._combine_provenance(["imported", "manual"]) == "derived"
    sample = date(2024, 2, 15)
    assert (_month_start(sample), _month_end(sample), _quarter_start(sample)) == (
        date(2024, 2, 1),
        date(2024, 2, 29),
        date(2024, 1, 1),
    )
    assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert [(s.start, s.end) for s in _iter_periods(date(2024, 1, 1), date(2024, 1, 3), "daily")] == [
        (date(2024, 1, 1), date(2024, 1, 1)),
        (date(2024, 1, 2), date(2024, 1, 2)),
        (date(2024, 1, 3), date(2024, 1, 3)),
    ]
    assert [(s.start, s.end) for s in _iter_periods(date(2024, 1, 3), date(2024, 1, 10), "weekly")] == [
        (date(2024, 1, 1), date(2024, 1, 7)),
        (date(2024, 1, 8), date(2024, 1, 10)),
    ]
    assert [(s.start, s.end) for s in _iter_periods(date(2024, 1, 15), date(2024, 2, 2), "monthly")] == [
        (date(2024, 1, 1), date(2024, 1, 31)),
        (date(2024, 2, 1), date(2024, 2, 2)),
    ]
    with pytest.raises(ReportError, match="Unsupported period"):
        _iter_periods(date(2024, 1, 1), date(2024, 1, 2), "yearly")

    backend_src = Path(__file__).resolve().parents[2] / "src"
    assert "def _valuation_line_name" not in (backend_src / "reporting/extension/_core.py").read_text(encoding="utf-8")
    assert (backend_src / "pricing/extension/valuation.py").read_text(encoding="utf-8").count(
        "def _valuation_line_name"
    ) == 1


@pytest.mark.parametrize(
    ("raw_lines", "filter_zero", "expected"),
    [
        (
            [
                {"name": "Income - Other", "type": "income", "amount": Decimal("0.00"), "source_currency": "SGD"},
                {"name": "Income - Other", "type": "income", "amount": Decimal("150.00"), "source_currency": "SGD"},
                {"name": "Income - Salary", "type": "income", "amount": Decimal("5000.00"), "source_currency": "SGD"},
                {"name": "Expense - Other", "type": "expense", "amount": Decimal("0.00"), "source_currency": "SGD"},
            ],
            True,
            [("Income - Other", Decimal("150.00")), ("Income - Salary", Decimal("5000.00"))],
        ),
        (
            [
                {"name": "Income - Other", "type": "income", "amount": Decimal("0.00"), "source_currency": "SGD"},
                {"name": "Income - Other", "type": "income", "amount": Decimal("0.00"), "source_currency": "SGD"},
            ],
            False,
            [("Income - Other", Decimal("0.00"))],
        ),
        (
            [
                {
                    "name": "Fee",
                    "type": "expense",
                    "amount": Decimal("10.00"),
                    "source_currency": "SGD",
                    "economic_report_line_id": "econ-fee-1",
                },
                {
                    "name": "Fee",
                    "type": "expense",
                    "amount": Decimal("20.00"),
                    "source_currency": "SGD",
                    "economic_report_line_id": "econ-fee-2",
                },
                {
                    "name": "Fee",
                    "type": "expense",
                    "amount": Decimal("5.00"),
                    "source_currency": "SGD",
                    "economic_report_line_id": "econ-fee-1",
                },
            ],
            True,
            [("Fee", Decimal("15.00")), ("Fee", Decimal("20.00"))],
        ),
    ],
)
def test_fold_and_deduplicate_income_lines(raw_lines: list[dict], filter_zero: bool, expected: list[tuple]) -> None:
    folded = _fold_and_deduplicate_lines(raw_lines, filter_zero=filter_zero)
    assert [(line["name"], line["amount"]) for line in folded] == expected


def test_annualized_income_totals_and_resolve_line_currency() -> None:
    totals = AnnualizedIncomeTotals()
    totals.add("salary", Decimal("120000.00"))
    totals.add("bonus", Decimal("15000.00"))
    totals.add(None, Decimal("300.00"))
    assert (totals.salary, totals.bonus, totals.dividend, totals.total) == (
        Decimal("120000.00"),
        Decimal("15000.00"),
        Decimal("0.00"),
        Decimal("135300.00"),
    )
    for bad in ("total", "not_a_bucket"):
        with pytest.raises(ValueError, match="Unknown income bucket"):
            totals.add(bad, Decimal("1.00"))

    acct_usd = Account(name="Salary", type=AccountType.INCOME, currency="usd")
    acct_none = Account(name="Salary", type=AccountType.INCOME, currency=None)
    line_eur = JournalLine(direction=Direction.CREDIT, amount=Decimal("1.00"), currency="eur")
    line_none = JournalLine(direction=Direction.CREDIT, amount=Decimal("1.00"), currency=None)
    assert resolve_line_currency(line_eur, acct_usd, base_currency="SGD") == "EUR"
    assert resolve_line_currency(line_none, acct_usd, base_currency="SGD") == "USD"
    assert resolve_line_currency(line_none, acct_none, base_currency="sgd") == "SGD"


def test_prompts_csv_mapping_and_reconciliation() -> None:
    prompt = build_csv_mapping_prompt(["Date", "Description", "Amount"], [["2025-01-15", "Coffee Shop", "25.00"]])
    assert "Date | Description | Amount" in prompt and "Coffee Shop" in prompt and "Return your JSON mapping" in prompt
    capped = build_csv_mapping_prompt(["Date", "Desc"], [["row", "row"] for _ in range(10)])
    assert capped.count("row | row") == 5
    recon = build_reconciliation_prompt(
        txn_description="SALARY ACME CORP", entry_memo="Monthly payroll", date_diff_days=2, amount_match_pct=99.5
    )
    assert all(tok in recon for tok in ("SALARY ACME CORP", "Monthly payroll", "2 days apart", "similarity_score"))
    assert all(band in RECONCILIATION_SEMANTIC_PROMPT for band in ("90-100", "70-89", "50-69", "0-49"))
