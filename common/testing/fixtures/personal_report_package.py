"""Representative fixture contract for the personal financial report package E2E."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from common.testing import money_amount
from common.testing.fixtures.portfolio_audit_package import PORTFOLIO_AUDIT_FIXTURE

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class BankFixture:
    csv_path: Path
    institution: str


@dataclass(frozen=True)
class BrokerageFixture:
    source: str
    institution: str


@dataclass(frozen=True)
class ManualComponentFixture:
    component_type: str
    source: str
    value: Decimal
    notes: str
    liquidity_class: str


@dataclass(frozen=True)
class ExpectedPackageOutputs:
    transaction_count: int
    period_start: date
    period_end: date
    income: Decimal
    expenses: Decimal
    net_income: Decimal
    bank_cash: Decimal
    manual_asset_total: Decimal
    manual_liability_total: Decimal
    restricted_fair_value_total: Decimal
    net_worth_adjustment_gain_loss: Decimal
    brokerage_market_value: Decimal
    brokerage_position_count: int
    dividend_income: Decimal
    market_price: Decimal
    market_price_date: date

    def total_assets(self, brokerage_value: Decimal) -> Decimal:
        return money_amount(brokerage_value + self.manual_asset_total + self.bank_cash)


@dataclass(frozen=True)
class RepresentativePackageFixture:
    bank: BankFixture
    brokerage: BrokerageFixture
    manual_components: tuple[ManualComponentFixture, ...]
    expected_outputs: ExpectedPackageOutputs
    required_note_ids: frozenset[str]
    required_traceability_line_ids: frozenset[str]

    @property
    def restricted_components(self) -> tuple[ManualComponentFixture, ...]:
        return tuple(
            c for c in self.manual_components if c.liquidity_class == "restricted"
        )

    def component(self, component_type: str, source: str) -> ManualComponentFixture:
        for c in self.manual_components:
            if c.component_type == component_type and c.source == source:
                return c
        raise KeyError(f"Unknown package fixture component: {component_type}/{source}")


def _expected_outputs(
    csv_path: Path, manual_components: tuple[ManualComponentFixture, ...]
) -> ExpectedPackageOutputs:
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"Representative package fixture has no bank rows: {csv_path}")
    amounts = [money_amount(r["Amount"]) for r in rows]
    income = sum((a for a in amounts if a > 0), Decimal("0.00"))
    expenses = sum((-a for a in amounts if a < 0), Decimal("0.00"))
    periods = {(r["Statement Period Start"], r["Statement Period End"]) for r in rows}
    if len(periods) != 1:
        raise ValueError(
            "Representative package fixture has conflicting statement periods"
        )
    start_s, end_s = periods.pop()
    by_class = lambda cls_set: sum(  # noqa: E731
        (c.value for c in manual_components if c.liquidity_class in cls_set),
        Decimal("0.00"),
    )
    asset_tot = by_class({"illiquid", "restricted"})
    liab_tot = by_class({"liability"})
    rest_tot = by_class({"restricted"})
    return ExpectedPackageOutputs(
        transaction_count=len(rows),
        period_start=date.fromisoformat(start_s),
        period_end=date.fromisoformat(end_s),
        income=money_amount(income),
        expenses=money_amount(expenses),
        net_income=money_amount(income - expenses),
        bank_cash=money_amount(income - expenses),
        manual_asset_total=money_amount(asset_tot),
        manual_liability_total=money_amount(liab_tot),
        restricted_fair_value_total=money_amount(rest_tot),
        net_worth_adjustment_gain_loss=money_amount(asset_tot - liab_tot),
        brokerage_market_value=PORTFOLIO_AUDIT_FIXTURE.report_package_market_value_sgd,
        brokerage_position_count=len(PORTFOLIO_AUDIT_FIXTURE.report_package_positions),
        dividend_income=PORTFOLIO_AUDIT_FIXTURE.expected_activity_totals.dividend_income_sgd,
        market_price=Decimal("12.50"),
        market_price_date=date(2026, 5, 31),
    )


_MANUAL_COMPONENTS = tuple(
    ManualComponentFixture(ct, src, Decimal(val), notes, cls)
    for ct, src, val, notes, cls in (
        (
            "property_value",
            "Family Home",
            "1100000.00",
            "Independent appraisal report reference A-12",
            "illiquid",
        ),
        (
            "mortgage_balance",
            "Home Loan",
            "360000.00",
            "Loan reference 2026-01",
            "liability",
        ),
        (
            "esop",
            "ACME ESOP",
            "85000.00",
            "ESOP vesting starts over 4 years",
            "restricted",
        ),
        ("rsu", "ACME RSU", "42000.00", "RSU vesting 25% annually", "restricted"),
        (
            "stock_options",
            "ACME Options",
            "29000.00",
            "Stock options cliff vest at 3 years",
            "restricted",
        ),
    )
)

_BANK_FIXTURE = BankFixture(
    csv_path=ROOT / "tests" / "e2e" / "fixtures" / "vision_hard_gate_statement.csv",
    institution="Personal Report Package Bank",
)

REPRESENTATIVE_PACKAGE_FIXTURE = RepresentativePackageFixture(
    bank=_BANK_FIXTURE,
    brokerage=BrokerageFixture("moomoo", "Moomoo Personal Package"),
    manual_components=_MANUAL_COMPONENTS,
    expected_outputs=_expected_outputs(_BANK_FIXTURE.csv_path, _MANUAL_COMPONENTS),
    required_note_ids=frozenset(
        {
            "basis-of-preparation",
            "reporting-period-and-currency",
            "valuation-basis",
            "investment-market-data",
            "source-confidence-review",
            "restricted-asset-treatment",
        }
    ),
    required_traceability_line_ids=frozenset(
        {
            "balance_sheet.total_assets",
            "income_statement.total_income",
            "income_statement.total_expenses",
            "cash_flow.net_cash_flow",
            "annualized_income_long_term.annualized_total",
        }
    ),
)
