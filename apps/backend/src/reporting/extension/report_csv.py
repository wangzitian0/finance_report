"""CSV rendering of the balance sheet, the income statement and the cash flow.

The renderers read a report as a mapping or as a typed response. The reports router and the
package archive use them. They moved out of the router with #2583 S11: the router keeps routing
and serialization glue only (AC-meta.delivery.1).
"""

from __future__ import annotations

import csv
from decimal import Decimal
from io import StringIO
from typing import Any

from pydantic import BaseModel


def _csv_val(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def render_balance_sheet_csv(bs: dict[str, Any] | BaseModel) -> str:
    output = StringIO()
    writer = csv.writer(output)
    _val = _csv_val

    as_of_date = _val(bs, "as_of_date")
    currency = _val(bs, "currency")
    if as_of_date:
        writer.writerow(["Balance Sheet", str(as_of_date), "", ""])
    writer.writerow(["section", "account", "amount", "currency"])
    for section, lines in (
        ("Assets", _val(bs, "assets", [])),
        ("Liabilities", _val(bs, "liabilities", [])),
        ("Equity", _val(bs, "equity", [])),
    ):
        for line in lines:
            writer.writerow([section, _val(line, "name"), _val(line, "amount"), currency])
    writer.writerow(["Total Assets", "", _val(bs, "total_assets"), currency])
    writer.writerow(["Total Liabilities", "", _val(bs, "total_liabilities"), currency])
    total_equity = _val(bs, "total_equity")
    net_income = _val(bs, "net_income") or Decimal("0.00")
    unrealized_fx = _val(bs, "unrealized_fx_gain_loss") or Decimal("0.00")
    cta_adj = _val(bs, "cta_adjustment") or Decimal("0.00")
    net_worth_adj = _val(bs, "net_worth_adjustment_gain_loss") or Decimal("0.00")
    writer.writerow(["Opening Equity", "", total_equity, currency])
    writer.writerow(["Net Income", "", net_income, currency])
    if unrealized_fx:
        writer.writerow(["Unrealized FX Gain/Loss", "", unrealized_fx, currency])
    if cta_adj:
        writer.writerow(["CTA Adjustment", "", cta_adj, currency])
    if net_worth_adj:
        writer.writerow(["Net Worth Adjustment", "", net_worth_adj, currency])
    ending_equity = (
        Decimal(str(total_equity))
        + Decimal(str(net_income))
        + Decimal(str(unrealized_fx))
        + Decimal(str(cta_adj))
        + Decimal(str(net_worth_adj))
    )
    writer.writerow(["Ending Total Equity", "", ending_equity, currency])
    total_liabilities = _val(bs, "total_liabilities")
    writer.writerow(["Total Liabilities and Equity", "", Decimal(str(total_liabilities)) + ending_equity, currency])
    return output.getvalue()


def render_income_statement_csv(is_stmt: dict[str, Any] | BaseModel) -> str:
    output = StringIO()
    writer = csv.writer(output)
    currency = _csv_val(is_stmt, "currency")
    writer.writerow(["section", "account", "amount", "currency"])
    for section, lines in (
        ("Income", _csv_val(is_stmt, "income", [])),
        ("Expenses", _csv_val(is_stmt, "expenses", [])),
    ):
        for line in lines:
            writer.writerow([section, _csv_val(line, "name"), _csv_val(line, "amount"), currency])
    writer.writerow(["Total Income", "", _csv_val(is_stmt, "total_income"), currency])
    writer.writerow(["Total Expenses", "", _csv_val(is_stmt, "total_expenses"), currency])
    writer.writerow(["Net Income", "", _csv_val(is_stmt, "net_income"), currency])
    return output.getvalue()


def render_cash_flow_csv(cf: dict[str, Any] | BaseModel) -> str:
    output = StringIO()
    writer = csv.writer(output)
    currency = _csv_val(cf, "currency")
    writer.writerow(["section", "account", "amount", "currency", "description"])
    for section, lines in (
        ("Operating", _csv_val(cf, "operating", [])),
        ("Investing", _csv_val(cf, "investing", [])),
        ("Financing", _csv_val(cf, "financing", [])),
    ):
        for line in lines:
            writer.writerow(
                [
                    section,
                    _csv_val(line, "subcategory"),
                    _csv_val(line, "amount"),
                    currency,
                    _csv_val(line, "description") or "",
                ]
            )
    summary = _csv_val(cf, "summary")
    writer.writerow(["Operating Activities", "", _csv_val(summary, "operating_activities"), currency, ""])
    writer.writerow(["Investing Activities", "", _csv_val(summary, "investing_activities"), currency, ""])
    writer.writerow(["Financing Activities", "", _csv_val(summary, "financing_activities"), currency, ""])
    writer.writerow(["Net Cash Flow", "", _csv_val(summary, "net_cash_flow"), currency, ""])
    proof_reasons = list(_csv_val(cf, "proof_reasons") or [])
    incomplete_coverage = "opening_coverage_starts_after_period" in proof_reasons
    beginning_label = "Known Beginning Cash" if incomplete_coverage else "Beginning Cash"
    writer.writerow([beginning_label, "", _csv_val(summary, "beginning_cash"), currency, ""])
    cash_bridge = _csv_val(cf, "cash_bridge")
    opening_adjustment = (
        _csv_val(cash_bridge, "opening_stock_adjustment", Decimal("0")) if cash_bridge else Decimal("0")
    )
    if opening_adjustment:
        writer.writerow(
            [
                "Opening balance adjustment",
                "",
                opening_adjustment,
                currency,
                "Opening balance recorded after the selected period begins",
            ]
        )
    writer.writerow(["Ending Cash", "", _csv_val(summary, "ending_cash"), currency, ""])
    if _csv_val(cf, "proof_state") == "unproven":
        writer.writerow(["Verification", "", "", "", "unproven: " + ", ".join(str(r) for r in proof_reasons)])
    return output.getvalue()
