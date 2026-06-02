"""Personal report package API contract coverage."""

import pytest

from src.routers.reports import personal_report_package_contract


@pytest.fixture(autouse=True)
def patch_database_connection():
    """This contract endpoint is static and does not need a test database."""
    yield


def test_AC5_9_1_package_contract_endpoint_defines_required_sections():
    """AC5.9.1: Package contract endpoint defines stable required sections."""
    response = personal_report_package_contract()
    payload = response.model_dump(mode="json")
    assert payload["package_id"] == "personal-financial-report-package"
    assert payload["version"] == "1.0"

    sections = {section["section_id"]: section for section in payload["sections"]}
    assert list(sections) == [
        "balance_sheet",
        "income_statement",
        "cash_flow",
        "investment_performance",
        "annualized_income_long_term",
        "notes",
        "traceability_appendix",
    ]

    assert sections["balance_sheet"]["label"] == "Balance Sheet"
    assert sections["balance_sheet"]["source_endpoint"] == "/api/reports/balance-sheet"
    assert sections["investment_performance"]["owner_epic"] == "EPIC-017"
    assert sections["annualized_income_long_term"]["blocking_issue"] == "#566"
    assert sections["notes"]["blocking_issue"] == "#571"
    assert sections["traceability_appendix"]["blocking_issue"] == "#572"


def test_AC5_9_2_package_contract_marks_decimal_totals_and_period_semantics():
    """AC5.9.2: Contract exposes Decimal-safe totals and date semantics."""
    response = personal_report_package_contract()
    payload = response.model_dump(mode="json")
    assert payload["period_semantics"] == {
        "start_date": "required for period sections",
        "end_date": "required for period sections",
        "as_of_date": "required for point-in-time sections",
        "currency": "ISO-4217 code; defaults to base currency when omitted",
        "decimal_serialization": "string",
    }

    sections = {section["section_id"]: section for section in payload["sections"]}
    assert sections["balance_sheet"]["period_type"] == "as_of"
    assert sections["income_statement"]["period_type"] == "period"
    assert sections["cash_flow"]["period_type"] == "period"
    assert sections["balance_sheet"]["decimal_total_fields"] == [
        "total_assets",
        "total_liabilities",
        "total_equity",
        "equation_delta",
    ]
    assert "annualized_total" in sections["annualized_income_long_term"]["decimal_total_fields"]

    assert payload["export_contract"]["formats"] == ["json", "csv"]
    assert payload["export_contract"]["csv_columns"] == [
        "package_id",
        "section_id",
        "line_id",
        "label",
        "amount",
        "currency",
        "source_state",
    ]
