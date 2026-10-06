"""AC-reporting.journeys.1-4: In-memory domain shift-left tests for financial report calculation engines.

Covers:
- AC-reporting.journeys.1: Balance sheet equation holds (Assets = Liabilities + Equity).
- AC-reporting.journeys.2: Income statement computes revenues, expenses, and net income accurately.
- AC-reporting.journeys.3: Cash flow statement reconciles operating, investing, and financing flows.
- AC-reporting.journeys.4: Multi-period reporting navigates currency translation adjustment (IAS 21 CTA).
- AC-testing.journeys.4, AC-testing.must-have.7
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.reporting.base.balance_sheet_calculator import (
    calculate_balance_sheet_equation,
    calculate_currency_translation_adjustment,
)
from src.reporting.base.cash_flow_calculator import calculate_cash_flow_bridge
from src.reporting.base.income_statement_calculator import (
    calculate_income_statement_totals,
)

pytestmark = pytest.mark.no_db


def test_balance_sheet_accounting_equation_articulation() -> None:
    """AC-reporting.journeys.1, AC-testing.journeys.4, AC-testing.must-have.7:
    Balance sheet calculation satisfies fundamental accounting equation.
    """
    total_assets = Decimal("250000.00")
    total_liabilities = Decimal("80000.00")
    total_equity = Decimal("150000.00")
    net_income = Decimal("20000.00")

    totals = calculate_balance_sheet_equation(
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        total_equity=total_equity,
        net_income=net_income,
        unrealized_fx=Decimal("0.00"),
        net_worth_adjustment=Decimal("0.00"),
    )

    assert totals.is_balanced is True
    assert totals.equation_delta == Decimal("0.00")
    assert totals.total_assets == Decimal("250000.00")
    assert totals.total_liabilities_and_equity == Decimal("250000.00")


def test_income_statement_revenues_expenses_net_income() -> None:
    """AC-reporting.journeys.2:
    Income statement correctly computes total income, operating expenses, and net income.
    """
    income_lines = [
        {"name": "Client Consulting", "amount": Decimal("15000.00")},
        {"name": "Bank Interest", "amount": Decimal("250.00")},
    ]
    expense_lines = [
        {"name": "Office Rent", "amount": Decimal("3500.00")},
        {"name": "Software Subscriptions", "amount": Decimal("750.00")},
        {"name": "Professional Services", "amount": Decimal("1000.00")},
    ]

    totals = calculate_income_statement_totals(income_lines, expense_lines)

    assert totals.total_income == Decimal("15250.00")
    assert totals.total_expenses == Decimal("5250.00")
    assert totals.net_income == Decimal("10000.00")
    assert totals.net_income == totals.total_income - totals.total_expenses


def test_cash_flow_bridge_reconciliation() -> None:
    """AC-reporting.journeys.3:
    Cash flow bridge satisfies cash_delta == operating + investing + financing activity.
    """
    beginning_cash = Decimal("50000.00")
    ending_cash = Decimal("65000.00")
    operating = Decimal("20000.00")
    investing = Decimal("-8000.00")
    financing = Decimal("3000.00")

    bridge = calculate_cash_flow_bridge(
        beginning_cash=beginning_cash,
        ending_cash=ending_cash,
        operating_total=operating,
        investing_total=investing,
        financing_total=financing,
    )

    assert bridge.reconciles is True
    assert bridge.discrepancy == Decimal("0.00")
    assert bridge.cash_delta == Decimal("15000.00")
    assert bridge.classified_activity == Decimal("15000.00")


def test_multi_period_reporting_and_cta_adjustment() -> None:
    """AC-reporting.journeys.4:
    Multi-currency IAS 21 CTA translation preserves balance sheet articulation across foreign currencies.
    """
    cta = calculate_currency_translation_adjustment(
        is_multicurrency=True,
        pnl_translation_variance=Decimal("450.00"),
        unrealized_fx=Decimal("50.00"),
        equity_translation_variance=Decimal("100.00"),
    )
    # CTA = 450 - 50 + 100 = 500.00
    assert cta == Decimal("500.00")

    # In single currency mode, CTA is strictly zero
    cta_single = calculate_currency_translation_adjustment(
        is_multicurrency=False,
        pnl_translation_variance=Decimal("450.00"),
    )
    assert cta_single == Decimal("0.00")
