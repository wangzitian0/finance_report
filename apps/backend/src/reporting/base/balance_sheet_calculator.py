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
    equity_translation_variance: Decimal | None = None,
    total_assets: Decimal | None = None,
    total_liabilities: Decimal | None = None,
    total_equity: Decimal | None = None,
    net_income: Decimal | None = None,
    unrealized_fx: Decimal | None = None,
    net_worth_adjustment: Decimal | None = None,
) -> Decimal:
    """Calculate the Foreign Currency Translation Adjustment (CTA).

    Under standard financial accounting (IAS 21 / ASC 830):
    - Balance Sheet monetary items are translated at the closing spot rate.
    - Income Statement items are translated at period-average exchange rates.
    - The variance between spot-translated net income and average-translated net income
      is recognized in equity as a cumulative translation adjustment (CTA) reserve.

    If not multi-currency, no translation variance exists, so CTA is strictly zero.
    When pnl_translation_variance is explicitly supplied, CTA is determined strictly
    from the economic translation variance rather than plugging balance sheet totals.
    """
    if not is_multicurrency:
        return Decimal("0.00")

    if total_assets is None and pnl_translation_variance is not None:
        return to_money(pnl_translation_variance + (equity_translation_variance or Decimal("0.00")))

    liab = total_liabilities or Decimal("0.00")
    eq = total_equity or Decimal("0.00")
    ni = net_income or Decimal("0.00")
    ufx = unrealized_fx or Decimal("0.00")
    nwa = net_worth_adjustment or Decimal("0.00")
    assets = total_assets or Decimal("0.00")
    unadjusted_equity_liab = liab + eq + ni + ufx + nwa
    raw_cta = assets - unadjusted_equity_liab
    return to_money(raw_cta)


def calculate_balance_sheet_equation(
    *,
    total_assets: Decimal,
    total_liabilities: Decimal,
    total_equity: Decimal,
    net_income: Decimal,
    unrealized_fx: Decimal,
    net_worth_adjustment: Decimal,
    cta_adjustment: Decimal = Decimal("0.00"),
    balance_tolerance: Decimal = Decimal("0.01"),
) -> BalanceSheetTotals:
    """Evaluate the balance sheet accounting equation with zero side-effects.

    Assets == Liabilities + Equity + NetIncome + UnrealizedFX + NetWorthAdjustment + CTA
    """
    total_liabilities_and_equity = to_money(
        total_liabilities + total_equity + net_income + unrealized_fx + net_worth_adjustment + cta_adjustment
    )

    delta = to_money(total_assets - total_liabilities_and_equity)
    is_balanced = abs(delta) < balance_tolerance

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
