"""AC-reporting.balance-sheet.2: Multi-currency IAS 21 CTA balancing test."""

from decimal import Decimal

from src.reporting.base.balance_sheet_calculator import (
    calculate_balance_sheet_equation,
    calculate_currency_translation_adjustment,
)


def test_ias21_cta_and_balance_sheet_equation_with_unrealized_fx():
    """Verify that CTA absorbed translation variance resolves equation delta to exactly 0.00.

    Case 4 scenario reproduction:
    Spot Assets = 25,417.10
    Spot Liabilities = 0.00
    Spot Equity = 20,173.72
    Average Net Income = 5,798.24
    Unrealized FX Gain/Loss = -652.24
    PnL Translation Variance = -42.09
    Equity Translation Variance = -512.77
    """
    pnl_var = Decimal("-42.09")
    ufx = Decimal("-652.24")
    equity_var = Decimal("-512.77")

    cta = calculate_currency_translation_adjustment(
        is_multicurrency=True,
        pnl_translation_variance=pnl_var,
        unrealized_fx=ufx,
        equity_translation_variance=equity_var,
    )
    # CTA = pnl_var - ufx + equity_var = -42.09 - (-652.24) + (-512.77) = 97.38
    assert cta == Decimal("97.38")

    totals = calculate_balance_sheet_equation(
        total_assets=Decimal("25417.10"),
        total_liabilities=Decimal("0.00"),
        total_equity=Decimal("20173.72"),
        net_income=Decimal("5798.24"),
        unrealized_fx=ufx,
        net_worth_adjustment=Decimal("0.00"),
        cta_adjustment=cta,
    )
    assert totals.equation_delta == Decimal("0.00")
    assert totals.is_balanced is True


def test_cta_when_pnl_translation_variance_is_zero_but_equity_or_ufx_differs():
    """When pnl_translation_variance is zero, CTA must not silently abort to 0.00 if ufx or eq_var exists."""
    cta = calculate_currency_translation_adjustment(
        is_multicurrency=True,
        pnl_translation_variance=Decimal("0.00"),
        unrealized_fx=Decimal("150.00"),
        equity_translation_variance=Decimal("-50.00"),
    )
    # 0 - 150 + (-50) = -200.00
    assert cta == Decimal("-200.00")


def test_cta_when_translation_variances_are_zero():
    """AC-reporting.balance-sheet.2: When translation variances are zero, CTA is strictly 0.00."""
    cta = calculate_currency_translation_adjustment(
        is_multicurrency=True,
        pnl_translation_variance=Decimal("0.00"),
        unrealized_fx=Decimal("262.73"),
        equity_translation_variance=Decimal("0.00"),
    )
    assert cta == Decimal("0.00")


def test_cta_when_not_multicurrency():
    """AC-reporting.balance-sheet.2: When single-currency, CTA must be 0.00 regardless of variance inputs."""
    cta = calculate_currency_translation_adjustment(
        is_multicurrency=False,
        pnl_translation_variance=Decimal("100.00"),
        unrealized_fx=Decimal("50.00"),
        equity_translation_variance=Decimal("25.00"),
    )
    assert cta == Decimal("0.00")
