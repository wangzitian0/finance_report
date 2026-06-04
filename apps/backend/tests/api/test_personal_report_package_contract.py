"""Personal report package API contract coverage."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    BankStatement,
    BankStatementStatus,
    BankStatementTransaction,
    CheckStatus,
    CheckType,
    ClassificationRule,
    ConsistencyCheck,
    Direction,
    FxRate,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    ReconciliationMatch,
    ReconciliationStatus,
    ReportSnapshot,
    ReportType,
    RuleType,
    Stage1Status,
)
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
    personal_report_package_readiness,
    personal_report_package_traceability,
)
from src.schemas import PersonalReportPackageReadinessResponse
from src.services.fx import FxRateError


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
        "framework_id": "selected supported personal reporting framework",
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


def _statement(
    user_id,
    *,
    status: BankStatementStatus = BankStatementStatus.APPROVED,
    account_id=None,
    stage1_status: Stage1Status | None = Stage1Status.APPROVED,
    balance_validated: bool | None = True,
    validation_error: str | None = None,
    updated_at: datetime | None = None,
) -> BankStatement:
    timestamp = updated_at or datetime.now(UTC)
    return BankStatement(
        user_id=user_id,
        account_id=account_id,
        file_path=f"s3://test/{uuid4()}.csv",
        file_hash=uuid4().hex,
        original_filename=f"{uuid4()}.csv",
        institution="Readiness Bank",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        status=status,
        balance_validated=balance_validated,
        validation_error=validation_error,
        stage1_status=stage1_status,
        created_at=timestamp,
        updated_at=timestamp,
    )


async def _ready_source_account(db: AsyncSession, user_id):
    account = Account(user_id=user_id, name=f"Ready Cash {uuid4()}", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()
    statement = _statement(user_id, account_id=account.id)
    db.add(statement)
    await db.flush()
    return account, statement


async def _report_snapshot(db: AsyncSession, user_id, *, updated_at: datetime) -> ReportSnapshot:
    rule = ClassificationRule(
        user_id=user_id,
        version_number=1,
        effective_date=date(2026, 1, 1),
        rule_name=f"readiness-{uuid4()}",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["readiness"]},
        created_by=user_id,
    )
    db.add(rule)
    await db.flush()
    snapshot = ReportSnapshot(
        user_id=user_id,
        report_type=ReportType.BALANCE_SHEET,
        as_of_date=date(2026, 5, 31),
        start_date=None,
        rule_version_id=rule.id,
        report_data={"total_assets": "100.00"},
        is_latest=True,
        created_at=updated_at,
        updated_at=updated_at,
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


@pytest.mark.asyncio
async def test_AC19_5_1_package_readiness_returns_draft_for_empty_user(
    db: AsyncSession,
    test_user: User,
):
    """AC19.5.1: Package readiness endpoint returns deterministic draft state for empty users."""
    response = await personal_report_package_readiness(db=db, user_id=test_user.id)
    payload = response.model_dump(mode="json")

    assert payload["package_id"] == "personal-financial-report-package"
    assert payload["state"] == "draft"
    assert payload["label"] == "Draft"
    assert payload["action_href"] == "/statements/upload"
    assert payload["blocking_count"] == 0
    assert payload["blockers"] == []
    assert payload["source_summary"]["statements"] == 0


def test_AC19_5_1_package_readiness_rejects_unknown_state_and_external_action_links():
    """AC19.5.1: Package readiness state and action links must be contract-bound."""
    with pytest.raises(ValidationError):
        PersonalReportPackageReadinessResponse(
            package_id="personal-financial-report-package",
            state="unknown",
            label="Unknown",
            action_href="/review",
            blocking_count=0,
            source_summary={},
        )

    with pytest.raises(ValueError, match="action_href must be an internal relative path"):
        PersonalReportPackageReadinessResponse(
            package_id="personal-financial-report-package",
            state="blocked",
            label="Blocked",
            action_href="https://example.com/review",
            blocking_count=1,
            blockers=[
                {
                    "code": "pending_review",
                    "label": "Pending source review",
                    "severity": "blocking",
                    "count": 1,
                    "reason": "Review required.",
                    "action_href": "/review",
                }
            ],
            source_summary={},
        )

    with pytest.raises(ValueError, match="action_href must be an internal relative path"):
        PersonalReportPackageReadinessResponse(
            package_id="personal-financial-report-package",
            state="blocked",
            label="Blocked",
            action_href="/review",
            blocking_count=1,
            blockers=[
                {
                    "code": "pending_review",
                    "label": "Pending source review",
                    "severity": "blocking",
                    "count": 1,
                    "reason": "Review required.",
                    "action_href": "//evil.example/review",
                }
            ],
            source_summary={},
        )


def _json_datetime(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_AC19_5_2_package_readiness_lists_actionable_blockers(
    db: AsyncSession,
    test_user: User,
):
    """AC19.5.2: Blocked readiness lists exact blocker categories and action links."""
    covered_account = Account(user_id=test_user.id, name="Covered Cash", type=AccountType.ASSET, currency="SGD")
    uncovered_account = Account(user_id=test_user.id, name="Uncovered Card", type=AccountType.LIABILITY, currency="SGD")
    processing_account = Account(
        user_id=test_user.id,
        name="Processing",
        code="1199",
        type=AccountType.ASSET,
        currency="SGD",
        is_system=True,
    )
    db.add_all([covered_account, uncovered_account, processing_account])
    await db.flush()

    rejected = _statement(
        test_user.id,
        status=BankStatementStatus.REJECTED,
        account_id=covered_account.id,
        stage1_status=Stage1Status.PENDING_REVIEW,
        balance_validated=False,
        validation_error="Closing balance mismatch",
    )
    approved = _statement(test_user.id, account_id=covered_account.id)
    db.add_all([rejected, approved])
    await db.flush()

    txn = BankStatementTransaction(
        statement_id=rejected.id,
        txn_date=date(2026, 5, 2),
        description="Needs reconciliation",
        amount=Decimal("25.00"),
        direction="DR",
        currency="SGD",
    )
    db.add(txn)
    await db.flush()
    db.add(
        ReconciliationMatch(
            bank_txn_id=txn.id,
            journal_entry_ids=[],
            match_score=60,
            score_breakdown={"amount": 60},
            status=ReconciliationStatus.PENDING_REVIEW,
        )
    )
    db.add(
        ConsistencyCheck(
            user_id=test_user.id,
            check_type=CheckType.ANOMALY,
            status=CheckStatus.PENDING,
            related_txn_ids=[str(txn.id)],
            details={"reason": "manual review"},
        )
    )
    processing_entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 5, 3),
        memo="Unpaired transfer",
        source_type=JournalEntrySourceType.SYSTEM,
        status=JournalEntryStatus.POSTED,
    )
    db.add(processing_entry)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=processing_entry.id,
            account_id=processing_account.id,
            direction=Direction.DEBIT,
            amount=Decimal("10.00"),
            currency="SGD",
        )
    )
    await db.flush()

    response = await personal_report_package_readiness(db=db, user_id=test_user.id)
    payload = response.model_dump(mode="json")

    assert payload["state"] == "blocked"
    assert payload["action_href"] == "/statements"
    blockers = {blocker["code"]: blocker for blocker in payload["blockers"]}
    assert set(blockers) == {
        "failed_parsing",
        "pending_review",
        "balance_mismatch",
        "reconciliation_blocked",
        "consistency_check_blocked",
        "processing_account_unresolved",
        "missing_source_coverage",
    }
    assert blockers["failed_parsing"]["action_href"] == "/statements"
    assert blockers["pending_review"]["action_href"] == "/review"
    assert blockers["reconciliation_blocked"]["action_href"] == "/reconciliation/review-queue"
    assert blockers["processing_account_unresolved"]["action_href"] == "/accounts/processing"
    assert blockers["missing_source_coverage"]["count"] == 1
    assert payload["blocking_count"] == sum(blocker["count"] for blocker in payload["blockers"])


@pytest.mark.asyncio
async def test_AC19_5_6_package_readiness_rejects_duplicate_processing_accounts(
    db: AsyncSession,
    test_user: User,
):
    """AC19.5.6: Duplicate Processing system accounts are data corruption, not arbitrary readiness input."""
    db.add_all(
        [
            Account(
                user_id=test_user.id,
                name="Processing A",
                code="1199",
                type=AccountType.ASSET,
                currency="SGD",
                is_system=True,
            ),
            Account(
                user_id=test_user.id,
                name="Processing B",
                code="1199",
                type=AccountType.ASSET,
                currency="SGD",
                is_system=True,
            ),
        ]
    )
    await db.flush()

    with pytest.raises(MultipleResultsFound):
        await personal_report_package_readiness(db=db, user_id=test_user.id)


@pytest.mark.asyncio
async def test_AC19_5_7_package_readiness_converts_processing_balance_before_zero_check(
    db: AsyncSession,
    test_user: User,
):
    """AC19.5.7: Processing readiness cannot net unlike currencies at raw nominal amount."""
    processing_account = Account(
        user_id=test_user.id,
        name="Processing",
        code="1199",
        type=AccountType.ASSET,
        currency="SGD",
        is_system=True,
    )
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 5, 3),
        memo="Mixed-currency processing balance",
        source_type=JournalEntrySourceType.SYSTEM,
        status=JournalEntryStatus.POSTED,
    )
    db.add_all(
        [
            processing_account,
            entry,
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.500000"),
                rate_date=date(2026, 5, 3),
                source="test",
            ),
        ]
    )
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=processing_account.id,
                direction=Direction.DEBIT,
                amount=Decimal("100.00"),
                currency="USD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=processing_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("100.00"),
                currency="SGD",
            ),
        ]
    )
    await db.flush()

    response = await personal_report_package_readiness(db=db, user_id=test_user.id)
    payload = response.model_dump(mode="json")
    blockers = {blocker["code"]: blocker for blocker in payload["blockers"]}

    assert payload["state"] == "blocked"
    assert blockers["processing_account_unresolved"]["count"] == 1
    assert "50.00" in blockers["processing_account_unresolved"]["reason"]
    assert "SGD" in blockers["processing_account_unresolved"]["reason"]


@pytest.mark.asyncio
async def test_AC19_8_8_package_readiness_blocks_when_processing_fx_conversion_fails(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC19.8.8: Missing FX for Processing lines produces a clear readiness blocker."""
    processing_account = Account(
        user_id=test_user.id,
        name="Processing",
        code="1199",
        type=AccountType.ASSET,
        currency="SGD",
        is_system=True,
    )
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 5, 3),
        memo="Processing line with missing FX",
        source_type=JournalEntrySourceType.SYSTEM,
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([processing_account, entry])
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=processing_account.id,
            direction=Direction.DEBIT,
            amount=Decimal("25.00"),
            currency="USD",
        )
    )
    await db.flush()

    async def raise_fx_error(*_args, **_kwargs):
        raise FxRateError("No FX rate available for USD/SGD on 2026-05-03")

    monkeypatch.setattr("src.services.report_readiness.convert_amount", raise_fx_error)

    response = await personal_report_package_readiness(db=db, user_id=test_user.id)
    payload = response.model_dump(mode="json")
    blockers = {blocker["code"]: blocker for blocker in payload["blockers"]}

    assert payload["state"] == "blocked"
    assert blockers["processing_account_unresolved"]["label"] == "Processing account unresolved"
    assert blockers["processing_account_unresolved"]["count"] == 1
    assert "cannot be converted to SGD" in blockers["processing_account_unresolved"]["reason"]
    assert "USD/SGD" in blockers["processing_account_unresolved"]["reason"]


@pytest.mark.asyncio
async def test_AC19_5_3_package_readiness_state_priority_and_snapshot_freshness(
    db: AsyncSession,
    test_user: User,
):
    """AC19.5.3: Readiness states are deterministic across processing, ready, generated, and stale."""
    processing = _statement(
        test_user.id,
        status=BankStatementStatus.PARSING,
        stage1_status=None,
        balance_validated=None,
    )
    db.add(processing)
    await db.flush()

    response = await personal_report_package_readiness(db=db, user_id=test_user.id)
    assert response.state == "processing"
    assert response.action_href == "/statements"

    processing.status = BankStatementStatus.APPROVED
    processing.stage1_status = Stage1Status.APPROVED
    processing.balance_validated = True
    _, statement = await _ready_source_account(db, test_user.id)
    await db.flush()

    response = await personal_report_package_readiness(db=db, user_id=test_user.id)
    assert response.state == "ready"

    source_time = datetime(2026, 5, 1, tzinfo=UTC)
    snapshot_time = datetime(2026, 5, 2, tzinfo=UTC)
    processing.updated_at = source_time
    statement.updated_at = source_time
    await _report_snapshot(db, test_user.id, updated_at=snapshot_time)
    await db.flush()

    response = await personal_report_package_readiness(db=db, user_id=test_user.id)
    assert response.state == "generated"
    assert response.generated_at == snapshot_time
    assert response.model_dump(mode="json")["generated_at"] == _json_datetime(snapshot_time)

    statement.updated_at = datetime(2026, 5, 3, tzinfo=UTC)
    await db.flush()
    response = await personal_report_package_readiness(db=db, user_id=test_user.id)
    assert response.state == "stale"
    assert response.stale_since == datetime(2026, 5, 3, tzinfo=UTC)
    assert response.model_dump(mode="json")["stale_since"] == _json_datetime(datetime(2026, 5, 3, tzinfo=UTC))


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
