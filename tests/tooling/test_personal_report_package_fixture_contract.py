"""Representative personal report package fixture contract tests."""

from decimal import Decimal

from tests.e2e.personal_report_package_fixture import PERSONAL_REPORT_PACKAGE_FIXTURE


def test_AC8_13_83_personal_report_package_fixture_has_exact_decimal_expected_outputs() -> None:
    """AC8.13.83: Representative package fixture exposes exact Decimal-safe expected outputs."""
    fixture = PERSONAL_REPORT_PACKAGE_FIXTURE

    assert fixture.transaction_count == 6
    assert fixture.period_start.isoformat() == "2026-05-02"
    assert fixture.period_end.isoformat() == "2026-05-19"
    assert fixture.income == Decimal("5600.00")
    assert fixture.expenses == Decimal("5600.00")
    assert fixture.net_income == Decimal("0.00")
    assert fixture.bank_cash == Decimal("0.00")
    assert fixture.restricted_fair_value_total == Decimal("156000.00")
    assert fixture.mortgage_liability == Decimal("360000.00")
    assert fixture.net_worth_adjustment_gain_loss == Decimal("896000.00")
    assert fixture.total_assets(Decimal("1234.56")) == Decimal("1257234.56")


def test_AC8_13_84_personal_report_package_fixture_covers_required_package_sections() -> None:
    """AC8.13.84: Fixture contract covers package sections, notes, and traceability appendix anchors."""
    fixture = PERSONAL_REPORT_PACKAGE_FIXTURE

    assert fixture.required_sections == {
        "balance_sheet",
        "income_statement",
        "cash_flow",
        "investment_performance",
        "annualized_income_long_term",
        "notes",
        "traceability_appendix",
    }
    assert {
        "basis-of-preparation",
        "reporting-period-and-currency",
        "valuation-basis",
        "investment-market-data",
        "source-confidence-review",
        "restricted-asset-treatment",
    } <= fixture.required_note_ids
    assert {
        "balance_sheet.total_assets",
        "income_statement.total_income",
        "income_statement.total_expenses",
        "cash_flow.net_cash_flow",
        "investment_performance.market_value",
        "annualized_income_long_term.annualized_total",
        "annualized_income_long_term.restricted_fair_value_total",
        "notes.non_compliance_statement",
    } <= fixture.required_traceability_lines
    assert {
        "missing_source_anchor",
        "manual_only_source",
        "stale_market_data",
        "duplicate_source_coverage",
        "overlapping_statement_period",
    } <= fixture.required_traceability_warnings
