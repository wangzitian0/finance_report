"""Synthetic portfolio fixture contract derived from local brokerage input structures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from common.testing import money_amount


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
            p
            for p in self.expected_positions
            if p.source_document_id == "synthetic-moomoo-statement-2026-01"
        )

    @property
    def report_package_market_value_sgd(self) -> Decimal:
        return money_amount(
            sum(
                (
                    p.market_value
                    for p in self.report_package_positions
                    if p.currency == "SGD"
                ),
                Decimal("0.00"),
            ),
            currency="SGD",
        )


def _margin_row(
    qty: str, amt: str, total: str, fee: str, fill_time: str
) -> dict[str, str]:
    return {
        "Side": "BUY",
        "Symbol": "PONY",
        "Name": "Pony AI Inc ADR",
        "Fill Qty": qty,
        "Fill Amount": amt,
        "Currency": "USD",
        "Total": total,
        "Commission": "0.00",
        "Platform Fees": fee,
        "Fill Time": fill_time,
        "Sector": "Technology",
        "Geography": "US",
    }


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
        "margin_history_rows": [
            _margin_row("12", "123.45", "123.56", "0.11", "2026-01-02 09:35:21"),
            _margin_row("24", "234.56", "234.78", "0.22", "2026-01-02 09:36:44"),
        ],
    },
    expected_positions=(
        PortfolioExpectedPosition(
            "Moomoo",
            "FULLERTON_SGD_CASH_FUND",
            Decimal("1250.50"),
            Decimal("1250.50"),
            "SGD",
            "money_market",
            "synthetic-moomoo-statement-2026-01",
            "Cash",
            "SG",
        ),
        PortfolioExpectedPosition(
            "Moomoo",
            "PONY",
            Decimal("36"),
            Decimal("358.01"),
            "USD",
            "stock",
            "synthetic-moomoo-margin-history-2026-01",
            "Technology",
            "US",
        ),
        PortfolioExpectedPosition(
            "Futu",
            "FUTU_STOCK_AND_OPTIONS",
            Decimal("1"),
            Decimal("43210.00"),
            "HKD",
            "other",
            "synthetic-futu-statement-2026-01",
            "Mixed",
            "HK",
        ),
    ),
    activity_rows=(
        PortfolioActivityRow(
            "moomoo_statement",
            "synthetic-moomoo-statement-2026-01",
            "VALUATION",
            date(2026, 1, 31),
            "FULLERTON_SGD_CASH_FUND",
            Decimal("1250.50"),
            "SGD",
        ),
        PortfolioActivityRow(
            "moomoo_margin_history",
            "synthetic-moomoo-margin-history-2026-01",
            "BUY",
            date(2026, 1, 2),
            "PONY",
            Decimal("358.01"),
            "USD",
            Decimal("0.33"),
        ),
        PortfolioActivityRow(
            "moomoo_statement",
            "synthetic-moomoo-statement-2026-01",
            "DIVIDEND",
            date(2026, 1, 20),
            "TSM",
            Decimal("88.25"),
            "SGD",
        ),
        PortfolioActivityRow(
            "moomoo_margin_history",
            "synthetic-moomoo-margin-history-2026-01",
            "FEE",
            date(2026, 1, 2),
            "PONY",
            Decimal("-0.33"),
            "USD",
            Decimal("0.33"),
        ),
        PortfolioActivityRow(
            "futu_statement",
            "synthetic-futu-statement-2026-01",
            "VALUATION",
            date(2026, 1, 31),
            "FUTU_STOCK_AND_OPTIONS",
            Decimal("43210.00"),
            "HKD",
        ),
    ),
    expected_activity_totals=PortfolioExpectedActivityTotals(
        buy_notional_usd=Decimal("358.01"),
        dividend_income_sgd=Decimal("88.25"),
        fees_usd=Decimal("0.33"),
        market_value_by_currency=_MARKET_VALUE_BY_CURRENCY,
        reporting_market_value_sgd=money_amount(
            _MARKET_VALUE_BY_CURRENCY["SGD"]
            + _MARKET_VALUE_BY_CURRENCY["USD"] * Decimal("1.35")
            + _MARKET_VALUE_BY_CURRENCY["HKD"] * Decimal("0.17"),
            currency="SGD",
        ),
    ),
)
