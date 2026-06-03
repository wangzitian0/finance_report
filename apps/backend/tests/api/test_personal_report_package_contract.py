"""Personal report package API contract coverage."""

import pytest

from src.routers.reports import personal_report_package_contract, personal_report_package_notes


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
    assert sections["notes"]["status"] == "ready"
    assert sections["notes"]["blocking_issue"] is None
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


def test_AC5_11_1_package_contract_marks_annualized_schedule_ready():
    """AC5.11.1: Annualized income package section points to the ready schedule endpoint."""
    response = personal_report_package_contract()
    payload = response.model_dump(mode="json")

    sections = {section["section_id"]: section for section in payload["sections"]}
    section = sections["annualized_income_long_term"]
    assert section["status"] == "ready"
    assert section["blocking_issue"] is None
    assert section["source_endpoint"] == "/api/reports/package/annualized-income-schedule"


def test_AC5_12_1_package_notes_endpoint_returns_required_note_taxonomy():
    """AC5.12.1: Package notes endpoint returns standards-inspired disclosure notes."""
    response = personal_report_package_notes()
    payload = response.model_dump(mode="json")

    assert payload["section_id"] == "notes"
    assert payload["status"] == "ready"
    assert "not a regulated filing" in payload["non_compliance_statement"]
    assert "not legal advice" in payload["non_compliance_statement"]
    assert "not tax advice" in payload["non_compliance_statement"]

    notes = {note["note_id"]: note for note in payload["notes"]}
    assert list(notes) == [
        "basis-of-preparation",
        "reporting-period-and-currency",
        "valuation-basis",
        "investment-market-data",
        "source-confidence-review",
        "restricted-asset-treatment",
    ]
    assert notes["basis-of-preparation"]["owner_epic"] == "EPIC-005"
    assert notes["valuation-basis"]["owner_epic"] == "EPIC-011"
    assert notes["investment-market-data"]["owner_epic"] == "EPIC-017"
    assert notes["source-confidence-review"]["owner_epic"] == "EPIC-018"
    assert notes["basis-of-preparation"]["source_state"] == "package_contract"
    assert notes["valuation-basis"]["source_state"] == "manual_valuation_snapshots"
    assert "US GAAP compliant" not in payload["non_compliance_statement"]
    assert "HKEX filing" not in payload["non_compliance_statement"]


def test_AC5_12_2_package_contract_marks_notes_ready():
    """AC5.12.2: Package contract marks notes ready and points to the notes endpoint."""
    response = personal_report_package_contract()
    payload = response.model_dump(mode="json")

    section = {section["section_id"]: section for section in payload["sections"]}["notes"]
    assert section["status"] == "ready"
    assert section["blocking_issue"] is None
    assert section["source_endpoint"] == "/api/reports/package/notes"
