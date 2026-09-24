"""AC-reporting.balance-sheet.1: Pure domain unit tests for balance sheet equation calculation and CTA."""

from decimal import Decimal

from src.reporting.base.balance_sheet_calculator import (
    calculate_balance_sheet_equation,
    calculate_currency_translation_adjustment,
)


def test_balanced_single_currency_evaluation():
    """Single currency with perfect balance evaluates to is_balanced=True with zero delta."""
    totals = calculate_balance_sheet_equation(
        total_assets=Decimal("1000.00"),
        total_liabilities=Decimal("300.00"),
        total_equity=Decimal("500.00"),
        net_income=Decimal("200.00"),
        unrealized_fx=Decimal("0.00"),
        net_worth_adjustment=Decimal("0.00"),
        cta_adjustment=Decimal("0.00"),
    )
    assert totals.is_balanced is True
    assert totals.equation_delta == Decimal("0.00")
    assert totals.total_assets == Decimal("1000.00")
    assert totals.total_liabilities_and_equity == Decimal("1000.00")


def test_imbalanced_single_currency_evaluation():
    """Single currency with an unadjusted imbalance detects is_balanced=False and exact delta."""
    totals = calculate_balance_sheet_equation(
        total_assets=Decimal("1000.00"),
        total_liabilities=Decimal("300.00"),
        total_equity=Decimal("500.00"),
        net_income=Decimal("150.00"),  # 50.00 short
        unrealized_fx=Decimal("0.00"),
        net_worth_adjustment=Decimal("0.00"),
    )
    assert totals.is_balanced is False
    assert totals.equation_delta == Decimal("50.00")


def test_multicurrency_cta_resolution():
    """Foreign currency translation variance (e.g. Benchmark Case 4: 9.78 SGD) is resolved by CTA."""
    # Case 4 hand calculation:
    # Assets: 25,737.69
    # Liabilities: 0.00
    # Equity: 10,000.00
    # Net Income: 15,727.91
    # Unrealized FX: 0.00
    # Net Worth Adjustment: 0.00
    # Variance due to Spot vs Average rate on foreign currency: 9.78 SGD
    cta = calculate_currency_translation_adjustment(
        total_assets=Decimal("25737.69"),
        total_liabilities=Decimal("0.00"),
        total_equity=Decimal("10000.00"),
        net_income=Decimal("15727.91"),
        unrealized_fx=Decimal("0.00"),
        net_worth_adjustment=Decimal("0.00"),
        is_multicurrency=True,
    )
    assert cta == Decimal("9.78")

    totals = calculate_balance_sheet_equation(
        total_assets=Decimal("25737.69"),
        total_liabilities=Decimal("0.00"),
        total_equity=Decimal("10000.00"),
        net_income=Decimal("15727.91"),
        unrealized_fx=Decimal("0.00"),
        net_worth_adjustment=Decimal("0.00"),
        cta_adjustment=cta,
    )
    assert totals.is_balanced is True
    assert totals.equation_delta == Decimal("0.00")
    assert totals.cta_adjustment == Decimal("9.78")


def test_single_currency_ignores_cta():
    """Single currency transactions strictly do not synthesize CTA adjustment."""
    cta = calculate_currency_translation_adjustment(
        total_assets=Decimal("1000.00"),
        total_liabilities=Decimal("200.00"),
        total_equity=Decimal("700.00"),
        net_income=Decimal("100.00"),
        unrealized_fx=Decimal("0.00"),
        net_worth_adjustment=Decimal("0.00"),
        is_multicurrency=False,
    )
    assert cta == Decimal("0.00")
