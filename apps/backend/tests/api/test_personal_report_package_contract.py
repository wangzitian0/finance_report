"""Personal report package API contract coverage."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.models.journal import JournalEntrySourceType
from src.models.layer2 import AssetType, AtomicPosition
from src.models.layer3 import (
    CostBasisMethod,
    ManagedPosition,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
    PositionStatus,
)
from src.models.portfolio import DividendIncome, MarketDataOverride, PriceSource
from src.models.user import User
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
async def test_AC5_13_5_package_traceability_returns_dynamic_current_user_identifiers(
    db: AsyncSession,
    test_user: User,
):
    """AC5.13.5: Traceability returns current-user dynamic identifiers without cross-user leakage."""
    report_date = date(2026, 5, 31)
    statement_txn_id = uuid4()
    other_user = User(email=f"other-trace-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other_user)
    await db.flush()

    bank = Account(user_id=test_user.id, name="Trace Bank", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=test_user.id, name="Trace Salary", type=AccountType.INCOME, currency="SGD")
    investment = Account(user_id=test_user.id, name="Trace Brokerage", type=AccountType.ASSET, currency="SGD")
    other_income = Account(user_id=other_user.id, name="Other Income", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, income, investment, other_income])
    await db.flush()

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=report_date,
        memo="Traceable income",
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        source_id=statement_txn_id,
        status=JournalEntryStatus.POSTED,
    )
    other_source_id = uuid4()
    other_entry = JournalEntry(
        user_id=other_user.id,
        entry_date=report_date,
        memo="Other income",
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        source_id=other_source_id,
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([entry, other_entry])
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=bank.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=other_entry.id,
                account_id=other_income.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
        ]
    )

    position = ManagedPosition(
        user_id=test_user.id,
        account_id=investment.id,
        asset_identifier="TRACE",
        quantity=Decimal("10"),
        cost_basis=Decimal("100.00"),
        currency="SGD",
        acquisition_date=date(2026, 1, 1),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(position)
    await db.flush()

    atomic = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=report_date,
        asset_identifier="TRACE",
        broker="Trace Broker",
        quantity=Decimal("10"),
        market_value=Decimal("125.00"),
        currency="SGD",
        asset_type=AssetType.STOCK,
        dedup_hash=f"trace-{uuid4()}",
        source_documents={"documents": [{"doc_id": "brokerage-doc-trace", "doc_type": "brokerage_statement"}]},
    )
    manual = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of_date=report_date,
        value=Decimal("500000.00"),
        currency="SGD",
        source="Trace Property",
    )
    dividend = DividendIncome(
        user_id=test_user.id,
        position_id=position.id,
        payment_date=report_date,
        amount=Decimal("8.25"),
        currency="SGD",
    )
    price = MarketDataOverride(
        user_id=test_user.id,
        asset_identifier="TRACE",
        price_date=report_date,
        price=Decimal("12.50"),
        currency="SGD",
        source=PriceSource.MANUAL,
    )
    db.add_all([atomic, manual, dividend, price])
    await db.commit()

    response = await personal_report_package_traceability(
        start_date=date(2026, 5, 1),
        end_date=report_date,
        as_of_date=report_date,
        db=db,
        user_id=test_user.id,
    )
    lines = {line["line_id"]: line for line in response.model_dump(mode="json")["lines"]}

    total_assets = lines["balance_sheet.total_assets"]
    assert f"statement_transaction:{statement_txn_id}" in total_assets["source_anchor"]["identifiers"]
    assert f"manual_valuation_snapshot:{manual.id}" in total_assets["source_anchor"]["identifiers"]
    assert f"atomic_position:{atomic.id}" in total_assets["source_anchor"]["identifiers"]
    assert f"journal_entry:{entry.id}" in total_assets["ledger_anchor"]["identifiers"]

    investment_line = lines["investment_performance.market_value"]
    assert f"dividend_income:{dividend.id}" in investment_line["source_anchor"]["identifiers"]
    assert f"market_price:{price.id}" in investment_line["source_anchor"]["identifiers"]
    assert "brokerage_document:brokerage-doc-trace" in investment_line["source_anchor"]["identifiers"]

    all_identifiers = {
        identifier
        for line in lines.values()
        for anchor_name in ("source_anchor", "ledger_anchor")
        for identifier in line[anchor_name]["identifiers"]
    }
    assert f"statement_transaction:{other_source_id}" not in all_identifiers
