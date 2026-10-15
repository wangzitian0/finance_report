"""Pure calculation core for Balance Sheet equation and currency translation adjustment."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from src.audit.money import to_money


@dataclass(frozen=True)
class BalanceSheetTotals:
    """Immutable calculation outcome of a balance sheet evaluation."""

    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    net_income: Decimal
    unrealized_fx: Decimal
    net_worth_adjustment: Decimal
    cta_adjustment: Decimal
    total_liabilities_and_equity: Decimal
    equation_delta: Decimal
    is_balanced: bool


def calculate_currency_translation_adjustment(
    *,
    is_multicurrency: bool,
    pnl_translation_variance: Decimal | None = None,
    unrealized_fx: Decimal | None = None,
    equity_translation_variance: Decimal | None = None,
) -> Decimal:
    """Calculate the Foreign Currency Translation Adjustment (CTA).

    Under standard financial accounting (IAS 21 / ASC 830):
    - Balance Sheet monetary items are translated at the closing spot rate.
    - Income Statement items are translated at period-average exchange rates.
    - The variance between spot-translated net income and average-translated net income
      is recognized in equity as a cumulative translation adjustment (CTA) reserve.
    - When balance sheet presentation separates unrealized FX revaluation, CTA represents
      the net translation adjustment required so the accounting equation holds without
      circularly plugging balance sheet totals.

    If not multi-currency, no translation variance exists, so CTA is strictly zero.
    CTA is determined strictly from translation variances and unrealized FX rather
    than circularly plugging balance sheet totals.
    """
    if not is_multicurrency or (not pnl_translation_variance and not equity_translation_variance):
        return Decimal("0.00")

    pnl_var = pnl_translation_variance or Decimal("0.00")
    ufx = unrealized_fx or Decimal("0.00")
    eq_var = equity_translation_variance or Decimal("0.00")
    return to_money(pnl_var - ufx + eq_var)


#: Largest rounding error that one quantized money figure can carry: half of one cent.
HALF_CENT = Decimal("0.005")


def absorb_translation_rounding(
    *,
    cta_adjustment: Decimal,
    residual: Decimal,
    rounded_figure_count: int,
) -> Decimal:
    """Move a cent-level rounding residual of a translated report into the CTA reserve (#2473).

    Each account line is rounded to the cent. Net income, unrealized FX and CTA are
    rounded from unrounded sums. The two sides can differ by a few cents although the
    unrounded books balance. The residual is a rounding artefact of translation, so
    the translation reserve takes it.

    The residual moves only when it fits the rounding bound: half a cent for each
    rounded figure. A larger residual is a real imbalance and stays in the equation delta.
    """
    if residual == 0 or abs(residual) > HALF_CENT * rounded_figure_count:
        return cta_adjustment
    return to_money(cta_adjustment + residual)


def calculate_balance_sheet_equation(
    *,
    total_assets: Decimal,
    total_liabilities: Decimal,
    total_equity: Decimal,
    net_income: Decimal,
    unrealized_fx: Decimal,
    net_worth_adjustment: Decimal,
    cta_adjustment: Decimal = Decimal("0.00"),
    balance_tolerance: Decimal = Decimal("0.05"),
) -> BalanceSheetTotals:
    """Evaluate the balance sheet accounting equation with zero side-effects.

    Assets == Liabilities + Equity + NetIncome + UnrealizedFX + NetWorthAdjustment + CTA
    """
    total_liabilities_and_equity = to_money(
        total_liabilities + total_equity + net_income + unrealized_fx + net_worth_adjustment + cta_adjustment
    )

    delta = to_money(total_assets - total_liabilities_and_equity)
    is_balanced = abs(delta) <= balance_tolerance

    return BalanceSheetTotals(
        total_assets=to_money(total_assets),
        total_liabilities=to_money(total_liabilities),
        total_equity=to_money(total_equity),
        net_income=to_money(net_income),
        unrealized_fx=to_money(unrealized_fx),
        net_worth_adjustment=to_money(net_worth_adjustment),
        cta_adjustment=to_money(cta_adjustment),
        total_liabilities_and_equity=total_liabilities_and_equity,
        equation_delta=delta,
        is_balanced=is_balanced,
    )
