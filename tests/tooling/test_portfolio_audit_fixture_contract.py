from decimal import Decimal
from pathlib import Path

from tools._lib.fixtures.portfolio_audit_package import PORTFOLIO_AUDIT_FIXTURE

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_AC17_12_1_portfolio_fixture_contract_covers_multi_broker_multi_currency_inputs() -> (
    None
):
    """AC-portfolio.fixtures.1: AC17.12.1: Portfolio fixture contract covers multi-broker, multi-currency audit inputs."""
    fixture = PORTFOLIO_AUDIT_FIXTURE

    assert fixture.period_start.isoformat() == "2026-01-01"
    assert fixture.period_end.isoformat() == "2026-01-31"
    assert (
        min(row.activity_date for row in fixture.activity_rows) >= fixture.period_start
    )
    assert max(row.activity_date for row in fixture.activity_rows) == fixture.period_end
    assert all(
        fixture.period_start <= row.activity_date <= fixture.period_end
        for row in fixture.activity_rows
    )
    assert fixture.source_bases == frozenset(
        {"moomoo_margin_history", "moomoo_statement", "futu_statement"}
    )

    assert {position.broker for position in fixture.expected_positions} == {
        "Moomoo",
        "Futu",
    }
    assert {position.currency for position in fixture.expected_positions} == {
        "SGD",
        "USD",
        "HKD",
    }
    assert {position.asset_type for position in fixture.expected_positions} == {
        "money_market",
        "stock",
        "other",
    }

    by_asset = {
        position.asset_identifier: position for position in fixture.expected_positions
    }
    assert by_asset["FULLERTON_SGD_CASH_FUND"].market_value == Decimal("1250.50")
    assert by_asset["PONY"].quantity == Decimal("36")
    assert by_asset["PONY"].market_value == Decimal("358.01")
    assert by_asset["FUTU_STOCK_AND_OPTIONS"].market_value == Decimal("43210.00")


def test_AC17_12_2_portfolio_fixture_pins_activity_rows_without_raw_documents() -> None:
    """AC-portfolio.fixtures.2: AC17.12.2: Portfolio fixture pins sanitized trade, dividend, fee, and valuation activity rows."""
    fixture = PORTFOLIO_AUDIT_FIXTURE

    assert all(
        row.source_document_id.startswith("synthetic-") for row in fixture.activity_rows
    )
    assert all("input/" not in row.source_document_id for row in fixture.activity_rows)
    assert {row.activity_type for row in fixture.activity_rows} >= {
        "BUY",
        "DIVIDEND",
        "FEE",
        "VALUATION",
    }
    assert {row.currency for row in fixture.activity_rows} == {"SGD", "USD", "HKD"}

    buy_notional_usd = sum(
        (
            row.amount
            for row in fixture.activity_rows
            if row.activity_type == "BUY" and row.currency == "USD"
        ),
        Decimal("0.00"),
    )
    dividend_income_sgd = sum(
        (
            row.amount
            for row in fixture.activity_rows
            if row.activity_type == "DIVIDEND" and row.currency == "SGD"
        ),
        Decimal("0.00"),
    )
    fees_usd = -sum(
        (
            row.amount
            for row in fixture.activity_rows
            if row.activity_type == "FEE" and row.currency == "USD"
        ),
        Decimal("0.00"),
    )
    market_value_by_currency = {
        currency: sum(
            (
                position.market_value
                for position in fixture.expected_positions
                if position.currency == currency
            ),
            Decimal("0.00"),
        )
        for currency in {position.currency for position in fixture.expected_positions}
    }
    position_activity_keys = {
        (row.source_document_id, row.asset_identifier) for row in fixture.activity_rows
    }

    assert fixture.expected_activity_totals.buy_notional_usd == buy_notional_usd
    assert fixture.expected_activity_totals.dividend_income_sgd == dividend_income_sgd
    assert fixture.expected_activity_totals.fees_usd == fees_usd
    assert (
        fixture.expected_activity_totals.market_value_by_currency
        == market_value_by_currency
    )
    assert all(
        (position.source_document_id, position.asset_identifier)
        in position_activity_keys
        for position in fixture.expected_positions
    )
    assert fixture.expected_activity_totals.buy_notional_usd == Decimal("358.01")
    assert fixture.expected_activity_totals.dividend_income_sgd == Decimal("88.25")
    assert fixture.expected_activity_totals.fees_usd == Decimal("0.33")
    assert fixture.expected_activity_totals.market_value_by_currency == {
        "SGD": Decimal("1250.50"),
        "USD": Decimal("358.01"),
        "HKD": Decimal("43210.00"),
    }
    assert fixture.expected_activity_totals.reporting_market_value_sgd == Decimal(
        "9079.51"
    )
    assert [
        position.asset_identifier for position in fixture.report_package_positions
    ] == ["FULLERTON_SGD_CASH_FUND"]
    assert fixture.report_package_market_value_sgd == Decimal("1250.50")


def test_AC17_12_3_personal_package_references_expanded_portfolio_fixture_contract() -> (
    None
):
    """AC-portfolio.fixtures.3: AC17.12.3: Personal package fixture consumes expanded portfolio expected outputs."""
    personal_fixture = read("tools/_lib/fixtures/personal_report_package.py")

    assert "from tools._lib.fixtures.portfolio_audit_package import" in personal_fixture
    assert "PORTFOLIO_AUDIT_FIXTURE" in personal_fixture
    assert (
        "brokerage_market_value=PORTFOLIO_AUDIT_FIXTURE.report_package_market_value_sgd"
        in personal_fixture
    )
    assert (
        "brokerage_position_count=len(PORTFOLIO_AUDIT_FIXTURE.report_package_positions)"
        in personal_fixture
    )
