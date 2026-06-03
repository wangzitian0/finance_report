"""Personal report package API contract coverage."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    BankStatement,
    BankStatementStatus,
    BankStatementTransaction,
    Direction,
    JournalEntry,
    JournalEntrySourceType,
    JournalEntryStatus,
    JournalLine,
)
from src.models.layer3 import ManualValuationComponentType, ManualValuationLiquidityClass, ManualValuationSnapshot
from src.routers.reports import (
    personal_report_package_contract,
    personal_report_package_notes,
    personal_report_package_traceability,
)


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
    assert sections["traceability_appendix"]["status"] == "ready"
    assert sections["traceability_appendix"]["blocking_issue"] is None


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


@pytest.mark.asyncio
async def test_AC5_13_1_package_traceability_endpoint_returns_section_line_anchors():
    """AC5.13.1: Package traceability endpoint returns source-to-ledger anchors per report line."""
    response = await personal_report_package_traceability()
    payload = response.model_dump(mode="json")

    assert payload["section_id"] == "traceability_appendix"
    assert payload["status"] == "ready"
    lines = {line["line_id"]: line for line in payload["lines"]}
    assert {
        "balance_sheet.total_assets",
        "income_statement.total_income",
        "cash_flow.net_cash_flow",
        "investment_performance.market_value",
        "annualized_income_long_term.restricted_fair_value_total",
    } <= set(lines)

    total_assets = lines["balance_sheet.total_assets"]
    assert total_assets["section_id"] == "balance_sheet"
    assert total_assets["source_state"] == "posted_reconciled_journal_lines_and_manual_valuations"
    assert total_assets["ledger_anchor"]["entry_statuses"] == ["posted", "reconciled"]
    assert "manual_valuation_snapshot_ids" in total_assets["source_anchor"]["identifier_fields"]
    assert total_assets["review_state"] == "trusted_or_explicit_manual_input"
    assert total_assets["confidence_tier"] == "TRUSTED"


@pytest.mark.asyncio
async def test_AC5_13_2_package_traceability_declares_completeness_warnings():
    """AC5.13.2: Traceability appendix exposes explicit completeness states where anchors are unavailable."""
    response = await personal_report_package_traceability()
    payload = response.model_dump(mode="json")

    lines = {line["line_id"]: line for line in payload["lines"]}
    assert lines["notes.non_compliance_statement"]["source_state"] == "package_contract"
    assert lines["notes.non_compliance_statement"]["ledger_anchor"]["state"] == "not_applicable"
    assert lines["notes.non_compliance_statement"]["confidence_tier"] == "UNAVAILABLE"

    warning_codes = {warning["code"] for warning in payload["completeness_warnings"]}
    assert {
        "missing_source_anchor",
        "manual_only_source",
        "stale_market_data",
        "duplicate_source_coverage",
        "overlapping_statement_period",
    } <= warning_codes

    for line in payload["lines"]:
        assert line["source_anchor"]["state"] in {"available", "not_applicable", "unavailable"}
        assert line["ledger_anchor"]["state"] in {"available", "not_applicable", "unavailable"}
        assert line["review_state"]
        assert line["confidence_tier"] in {"TRUSTED", "HIGH", "MEDIUM", "LOW", "UNAVAILABLE"}


@pytest.mark.asyncio
async def test_AC8_13_85_package_traceability_returns_dynamic_identifiers(
    client,
    db: AsyncSession,
    test_user,
):
    """AC8.13.85: Package traceability anchors include concrete source, ledger, and manual IDs."""
    bank_account = Account(user_id=test_user.id, name="Package Bank", type=AccountType.ASSET, currency="SGD")
    income_account = Account(user_id=test_user.id, name="Salary Income", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank_account, income_account])
    await db.flush()

    statement = BankStatement(
        user_id=test_user.id,
        account_id=bank_account.id,
        file_path="/tmp/package_fixture.csv",
        file_hash="package-fixture-hash",
        original_filename="package_fixture.csv",
        institution="Package Fixture Bank",
        account_last4="1234",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("1000.00"),
        status=BankStatementStatus.APPROVED,
        balance_validated=True,
    )
    db.add(statement)
    await db.flush()

    transaction = BankStatementTransaction(
        statement_id=statement.id,
        txn_date=date(2026, 5, 2),
        description="Package salary",
        amount=Decimal("1000.00"),
        direction="IN",
        currency="SGD",
    )
    db.add(transaction)
    await db.flush()

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 5, 2),
        memo="Package salary",
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        source_id=transaction.id,
        status=JournalEntryStatus.RECONCILED,
    )
    db.add(entry)
    await db.flush()
    bank_line = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank_account.id,
        direction=Direction.DEBIT,
        amount=Decimal("1000.00"),
        currency="SGD",
    )
    income_line = JournalLine(
        journal_entry_id=entry.id,
        account_id=income_account.id,
        direction=Direction.CREDIT,
        amount=Decimal("1000.00"),
        currency="SGD",
    )
    restricted_snapshot = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type=ManualValuationComponentType.RSU,
        liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
        as_of_date=date(2026, 5, 31),
        value=Decimal("42000.00"),
        currency="SGD",
        source="ACME RSU",
        notes="RSU vesting 25% annually",
    )
    db.add_all([bank_line, income_line, restricted_snapshot])
    await db.commit()

    response = await client.get(
        "/reports/package/traceability",
        params={
            "start_date": "2026-05-01",
            "end_date": "2026-05-31",
            "as_of_date": "2026-05-31",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    lines = {line["line_id"]: line for line in payload["lines"]}
    total_income = lines["income_statement.total_income"]
    assert str(statement.id) in total_income["source_anchor"]["identifiers"]
    assert str(transaction.id) in total_income["source_anchor"]["identifiers"]
    assert str(entry.id) in total_income["ledger_anchor"]["identifiers"]
    assert str(bank_line.id) in total_income["ledger_anchor"]["identifiers"]
    assert str(income_line.id) in total_income["ledger_anchor"]["identifiers"]

    restricted = lines["annualized_income_long_term.restricted_fair_value_total"]
    assert str(restricted_snapshot.id) in restricted["source_anchor"]["identifiers"]
    assert restricted["ledger_anchor"]["state"] == "not_applicable"
