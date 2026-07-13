"""Representative fixture contract for the personal financial report package E2E."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from common.testing import money_amount
from tools._lib.fixtures.portfolio_audit_package import PORTFOLIO_AUDIT_FIXTURE

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
            component
            for component in self.manual_components
            if component.liquidity_class == "restricted"
        )

    def component(self, component_type: str, source: str) -> ManualComponentFixture:
        for component in self.manual_components:
            if (
                component.component_type == component_type
                and component.source == source
            ):
                return component
        raise KeyError(f"Unknown package fixture component: {component_type}/{source}")


def _bank_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"Representative package fixture has no bank rows: {csv_path}")
    return rows


def _expected_outputs(
    csv_path: Path, manual_components: tuple[ManualComponentFixture, ...]
) -> ExpectedPackageOutputs:
    rows = _bank_rows(csv_path)
    amounts = [money_amount(row["Amount"]) for row in rows]
    income = sum((amount for amount in amounts if amount > 0), Decimal("0.00"))
    expenses = sum((-amount for amount in amounts if amount < 0), Decimal("0.00"))
    period_dates = sorted(date.fromisoformat(row["Date"]) for row in rows)
    manual_asset_total = sum(
        (
            component.value
            for component in manual_components
            if component.liquidity_class in {"illiquid", "restricted"}
        ),
        Decimal("0.00"),
    )
    manual_liability_total = sum(
        (
            component.value
            for component in manual_components
            if component.liquidity_class == "liability"
        ),
        Decimal("0.00"),
    )
    restricted_total = sum(
        (
            component.value
            for component in manual_components
            if component.liquidity_class == "restricted"
        ),
        Decimal("0.00"),
    )
    return ExpectedPackageOutputs(
        transaction_count=len(rows),
        period_start=period_dates[0],
        period_end=period_dates[-1],
        income=money_amount(income),
        expenses=money_amount(expenses),
        net_income=money_amount(income - expenses),
        bank_cash=money_amount(income - expenses),
        manual_asset_total=money_amount(manual_asset_total),
        manual_liability_total=money_amount(manual_liability_total),
        restricted_fair_value_total=money_amount(restricted_total),
        net_worth_adjustment_gain_loss=money_amount(
            manual_asset_total - manual_liability_total
        ),
        brokerage_market_value=PORTFOLIO_AUDIT_FIXTURE.report_package_market_value_sgd,
        brokerage_position_count=len(PORTFOLIO_AUDIT_FIXTURE.report_package_positions),
        dividend_income=PORTFOLIO_AUDIT_FIXTURE.expected_activity_totals.dividend_income_sgd,
        market_price=Decimal("12.50"),
        market_price_date=date(2026, 5, 31),
    )


_MANUAL_COMPONENTS = (
    ManualComponentFixture(
        component_type="property_value",
        source="Family Home",
        value=Decimal("1100000.00"),
        notes="Independent appraisal report reference A-12",
        liquidity_class="illiquid",
    ),
    ManualComponentFixture(
        component_type="mortgage_balance",
        source="Home Loan",
        value=Decimal("360000.00"),
        notes="Loan reference 2026-01",
        liquidity_class="liability",
    ),
    ManualComponentFixture(
        component_type="esop",
        source="ACME ESOP",
        value=Decimal("85000.00"),
        notes="ESOP vesting starts over 4 years",
        liquidity_class="restricted",
    ),
    ManualComponentFixture(
        component_type="rsu",
        source="ACME RSU",
        value=Decimal("42000.00"),
        notes="RSU vesting 25% annually",
        liquidity_class="restricted",
    ),
    ManualComponentFixture(
        component_type="stock_options",
        source="ACME Options",
        value=Decimal("29000.00"),
        notes="Stock options cliff vest at 3 years",
        liquidity_class="restricted",
    ),
)

_BANK_FIXTURE = BankFixture(
    csv_path=ROOT / "tests" / "e2e" / "fixtures" / "vision_hard_gate_statement.csv",
    institution="Personal Report Package Bank",
)

REPRESENTATIVE_PACKAGE_FIXTURE = RepresentativePackageFixture(
    bank=_BANK_FIXTURE,
    brokerage=BrokerageFixture(source="moomoo", institution="Moomoo Personal Package"),
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
