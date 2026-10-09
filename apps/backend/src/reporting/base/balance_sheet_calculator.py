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
    total_assets: Decimal | None = None,
    total_liabilities: Decimal | None = None,
    total_equity: Decimal | None = None,
    net_income: Decimal | None = None,
    net_worth_adjustment: Decimal | None = None,
) -> Decimal:
    """Calculate the Foreign Currency Translation Adjustment (CTA).

    Under standard financial accounting (IAS 21 / ASC 830):
    - Balance Sheet monetary items are translated at the closing spot rate.
    - Income Statement items are translated at period-average exchange rates.
    - Equity items are recorded at historical rates.
    - The variance between spot-translated net assets and unadjusted equity components
      is recognized in equity as a cumulative translation adjustment (CTA) reserve
      under IAS 21 paragraph 39.

    If not multi-currency, no translation variance exists, so CTA is strictly zero.
    """
    if not is_multicurrency:
        return Decimal("0.00")

    if total_assets is not None and total_equity is not None:
        unadjusted = (
            (total_liabilities or Decimal("0.00"))
            + total_equity
            + (net_income or Decimal("0.00"))
            + (unrealized_fx or Decimal("0.00"))
            + (net_worth_adjustment or Decimal("0.00"))
        )
        return to_money(total_assets - unadjusted)

    if not pnl_translation_variance and not equity_translation_variance:
        return Decimal("0.00")

    pnl_var = pnl_translation_variance or Decimal("0.00")
    ufx = unrealized_fx or Decimal("0.00")
    eq_var = equity_translation_variance or Decimal("0.00")
    return to_money(pnl_var - ufx + eq_var)


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
