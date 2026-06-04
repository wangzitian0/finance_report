"""Synthetic portfolio fixture contract derived from local brokerage input structures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class PortfolioExpectedPosition:
    broker: str
    asset_identifier: str
    quantity: Decimal
    market_value: Decimal
    currency: str
    asset_type: str
    source_document_id: str
    sector: str | None = None
    geography: str | None = None


@dataclass(frozen=True)
class PortfolioActivityRow:
    source_basis: str
    source_document_id: str
    activity_type: str
    activity_date: date
    asset_identifier: str
    amount: Decimal
    currency: str
    fee_amount: Decimal = Decimal("0.00")


@dataclass(frozen=True)
class PortfolioExpectedActivityTotals:
    buy_notional_usd: Decimal
    dividend_income_sgd: Decimal
    fees_usd: Decimal
    market_value_by_currency: dict[str, Decimal]
    reporting_market_value_sgd: Decimal


@dataclass(frozen=True)
class PortfolioAuditFixture:
    period_start: date
    period_end: date
    source_bases: frozenset[str]
    margin_history_payload: dict[str, object]
    expected_positions: tuple[PortfolioExpectedPosition, ...]
    activity_rows: tuple[PortfolioActivityRow, ...]
    expected_activity_totals: PortfolioExpectedActivityTotals

    @property
    def report_package_positions(self) -> tuple[PortfolioExpectedPosition, ...]:
        return tuple(
            position
            for position in self.expected_positions
            if position.source_document_id == "synthetic-moomoo-statement-2026-01"
        )

    @property
    def report_package_market_value_sgd(self) -> Decimal:
        return sum(
            (
                position.market_value
                for position in self.report_package_positions
                if position.currency == "SGD"
            ),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))


_MARGIN_HISTORY_ROWS = (
    {
        "Side": "BUY",
        "Symbol": "PONY",
        "Name": "Pony AI Inc ADR",
        "Fill Qty": "12",
        "Fill Amount": "123.45",
        "Currency": "USD",
        "Total": "123.56",
        "Commission": "0.00",
        "Platform Fees": "0.11",
        "Fill Time": "2026-01-02 09:35:21",
        "Sector": "Technology",
        "Geography": "US",
    },
    {
        "Side": "BUY",
        "Symbol": "PONY",
        "Name": "Pony AI Inc ADR",
        "Fill Qty": "24",
        "Fill Amount": "234.56",
        "Currency": "USD",
        "Total": "234.78",
        "Commission": "0.00",
        "Platform Fees": "0.22",
        "Fill Time": "2026-01-02 09:36:44",
        "Sector": "Technology",
        "Geography": "US",
    },
)

_EXPECTED_POSITIONS = (
    PortfolioExpectedPosition(
        broker="Moomoo",
        asset_identifier="FULLERTON_SGD_CASH_FUND",
        quantity=Decimal("1250.50"),
        market_value=Decimal("1250.50"),
        currency="SGD",
        asset_type="money_market",
        source_document_id="synthetic-moomoo-statement-2026-01",
        sector="Cash",
        geography="SG",
    ),
    PortfolioExpectedPosition(
        broker="Moomoo",
        asset_identifier="PONY",
        quantity=Decimal("36"),
        market_value=Decimal("358.01"),
        currency="USD",
        asset_type="stock",
        source_document_id="synthetic-moomoo-margin-history-2026-01",
        sector="Technology",
        geography="US",
    ),
    PortfolioExpectedPosition(
        broker="Futu",
        asset_identifier="FUTU_STOCK_AND_OPTIONS",
        quantity=Decimal("1"),
        market_value=Decimal("43210.00"),
        currency="HKD",
        asset_type="other",
        source_document_id="synthetic-futu-statement-2026-01",
        sector="Mixed",
        geography="HK",
    ),
)

_ACTIVITY_ROWS = (
    PortfolioActivityRow(
        source_basis="moomoo_statement",
        source_document_id="synthetic-moomoo-statement-2026-01",
        activity_type="VALUATION",
        activity_date=date(2026, 1, 31),
        asset_identifier="FULLERTON_SGD_CASH_FUND",
        amount=Decimal("1250.50"),
        currency="SGD",
    ),
    PortfolioActivityRow(
        source_basis="moomoo_margin_history",
        source_document_id="synthetic-moomoo-margin-history-2026-01",
        activity_type="BUY",
        activity_date=date(2026, 1, 2),
        asset_identifier="PONY",
        amount=Decimal("358.01"),
        currency="USD",
        fee_amount=Decimal("0.33"),
    ),
    PortfolioActivityRow(
        source_basis="moomoo_statement",
        source_document_id="synthetic-moomoo-statement-2026-01",
        activity_type="DIVIDEND",
        activity_date=date(2026, 1, 20),
        asset_identifier="TSM",
        amount=Decimal("88.25"),
        currency="SGD",
    ),
    PortfolioActivityRow(
        source_basis="moomoo_margin_history",
        source_document_id="synthetic-moomoo-margin-history-2026-01",
        activity_type="FEE",
        activity_date=date(2026, 1, 2),
        asset_identifier="PONY",
        amount=Decimal("-0.33"),
        currency="USD",
        fee_amount=Decimal("0.33"),
    ),
    PortfolioActivityRow(
        source_basis="futu_statement",
        source_document_id="synthetic-futu-statement-2026-01",
        activity_type="VALUATION",
        activity_date=date(2026, 1, 31),
        asset_identifier="FUTU_STOCK_AND_OPTIONS",
        amount=Decimal("43210.00"),
        currency="HKD",
    ),
)

_MARKET_VALUE_BY_CURRENCY = {
    "SGD": Decimal("1250.50"),
    "USD": Decimal("358.01"),
    "HKD": Decimal("43210.00"),
}

PORTFOLIO_AUDIT_FIXTURE = PortfolioAuditFixture(
    period_start=date(2026, 1, 1),
    period_end=date(2026, 1, 31),
    source_bases=frozenset(
        {"moomoo_margin_history", "moomoo_statement", "futu_statement"}
    ),
    margin_history_payload={
        "institution": "Moomoo",
        "statement": {"period_end": "2026-01-02", "currency": "USD"},
        "margin_history_rows": list(_MARGIN_HISTORY_ROWS),
    },
    expected_positions=_EXPECTED_POSITIONS,
    activity_rows=_ACTIVITY_ROWS,
    expected_activity_totals=PortfolioExpectedActivityTotals(
        buy_notional_usd=Decimal("358.01"),
        dividend_income_sgd=Decimal("88.25"),
        fees_usd=Decimal("0.33"),
        market_value_by_currency=_MARKET_VALUE_BY_CURRENCY,
        reporting_market_value_sgd=_money(
            _MARKET_VALUE_BY_CURRENCY["SGD"]
            + _MARKET_VALUE_BY_CURRENCY["USD"] * Decimal("1.35")
            + _MARKET_VALUE_BY_CURRENCY["HKD"] * Decimal("0.17")
        ),
    ),
)
