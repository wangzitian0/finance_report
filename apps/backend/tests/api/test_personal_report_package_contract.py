"""Personal report package API contract coverage."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from common.testing.ac_proof import ac_proof
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.ext.asyncio import AsyncSession

from src.deps import PaginationParams
from src.identity import User
from src.models.account import Account, AccountType
from src.models.consistency_check import CheckStatus, CheckType, ConsistencyCheck
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AssetType, AtomicPosition, AtomicTransaction, TransactionDirection
from src.models.layer3 import (
    ClassificationRule,
    CostBasisMethod,
    ManagedPosition,
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
    PositionStatus,
    RuleType,
)
from src.models.layer4 import ReportSnapshot, ReportType
from src.models.market_data import FxRate
from src.models.portfolio import DividendIncome, MarketDataOverride, PriceSource
from src.models.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.models.statement_enums import BankStatementStatus, Stage1Status
from src.models.statement_summary import StatementSummary
from src.routers.reports import (
    ExportFormat,
    ExportReportType,
    PackageSnapshotExportFormat,
    export_personal_report_package_snapshot,
    export_report,
    generate_personal_report_package_snapshot,
    get_personal_report_package_snapshot,
    list_personal_report_package_snapshots,
    personal_report_package_contract,
    personal_report_package_notes,
    personal_report_package_readiness,
    personal_report_package_traceability,
)
from src.schemas import PersonalReportingFrameworkId, PersonalReportPackageReadinessResponse
from src.services.deduplication import dual_write_layer2
from src.services.evidence_graph_integration import EvidenceGraphIntegrationService
from src.services.fx import FxRateError
from src.services.report_traceability import (
    _add_anchor_details,
    _append_blocker,
    _journal_source_anchor_detail,
    _ledger_anchor_detail,
    _source_document_details,
)
from src.services.review_queue import create_entry_from_txn
from tests.factories import UserFactory


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
        "selected_framework_id",
        "framework_policy_result_id",
        "framework_policy_matrix_version",
        "evidence_bundle_references",
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


async def test_AC5_17_2_package_csv_export_streams_contract_rows(monkeypatch):
    """AC5.17.2: Package CSV export returns contract columns and traceability rows."""

    class DummyDb:
        async def commit(self) -> None:
            return None

    async def fake_policy(**kwargs):
        anchor = SimpleNamespace(anchor_type="source_document", source_id="stmt-1")
        return SimpleNamespace(
            result_id="policy-us-gaap-like",
            matrix_version="v1",
            decisions=[SimpleNamespace(evidence_anchors=[anchor])],
            gaps=[],
        )

    async def fake_traceability(**kwargs):
        return SimpleNamespace(
            lines=[
                SimpleNamespace(
                    section_id="balance_sheet",
                    line_id="cash",
                    label="Cash",
                    source_state="ledger_posted",
                )
            ]
        )

    monkeypatch.setattr(
        "src.routers.reports.personal_report_package_framework_policy",
        fake_policy,
    )
    monkeypatch.setattr(
        "src.routers.reports.personal_report_package_traceability",
        fake_traceability,
    )

    response = await export_report(
        report_type=ExportReportType.PACKAGE,
        format=ExportFormat.CSV,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        currency="SGD",
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        db=DummyDb(),
        user_id=uuid4(),
    )
    body = "".join([chunk async for chunk in response.body_iterator])

    assert "personal-report-package-personal_us_gaap_like.csv" in response.headers["content-disposition"]
    assert body.splitlines()[0].startswith("package_id,section_id,line_id,label")
    assert "personal-financial-report-package,balance_sheet,cash,Cash,,SGD,ledger_posted" in body
    assert "source_document:stmt-1" in body


async def _read_streaming_body(response) -> str:
    return "".join([chunk async for chunk in response.body_iterator])


def _package_snapshot_sections(label: str = "Total Assets") -> dict:
    return {
        "balance_sheet": {"total_assets": "100.00", "currency": "SGD"},
        "income_statement": {"net_income": "25.00", "currency": "SGD"},
        "cash_flow": {"summary": {"net_cash_flow": "25.00"}, "currency": "SGD"},
        "investment_performance": {"market_value": "75.00", "currency": "SGD"},
        "annualized_income_long_term": {
            "income": {"annualized_total": "120000.00", "currency": "SGD"},
            "restricted_fair_value_total": "0.00",
        },
        "notes": personal_report_package_notes().model_dump(mode="json"),
        "traceability_appendix": {
            "section_id": "traceability_appendix",
            "label": "Traceability Appendix",
            "status": "ready",
            "lines": [
                {
                    "line_id": "balance_sheet.total_assets",
                    "section_id": "balance_sheet",
                    "label": label,
                    "amount_field": "total_assets",
                    "currency_field": "currency",
                    "source_state": "ledger_posted",
                    "source_anchor": {
                        "state": "available",
                        "source_types": ["bank_statement"],
                        "identifiers": ["source_document:stmt-1"],
                    },
                    "ledger_anchor": {
                        "state": "available",
                        "entry_statuses": ["posted"],
                        "identifiers": ["journal_line:line-1"],
                    },
                    "review_state": "trusted",
                    "confidence_tier": "TRUSTED",
                    "source_classes": ["bank_statement"],
                    "proof_level": "ledger",
                    "anchor_count": 2,
                    "blocker_codes": [],
                }
            ],
            "completeness_warnings": [],
        },
    }


async def _patch_package_snapshot_inputs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    readiness_state: str,
    blocking_count: int,
    section_label: str = "Total Assets",
) -> None:
    async def fake_readiness(*_args, **_kwargs):
        return {
            "package_id": "personal-financial-report-package",
            "state": readiness_state,
            "label": readiness_state.title(),
            "action_href": "/reports/package",
            "blocking_count": blocking_count,
            "blockers": [],
            "source_summary": {"statements": 1},
            "source_trust_summary": {
                "source_classes": ["bank_statement"],
                "deterministic_pr_source_classes": ["bank_statement"],
                "post_merge_llm_ocr_source_classes": [],
                "manual_trusted_source_classes": [],
                "gap_source_classes": [],
                "blocker_codes": [],
            },
        }

    async def fake_policy(*_args, **_kwargs):
        anchor = {
            "anchor_id": "source_document:stmt-1",
            "anchor_type": "source_document",
            "source_system": "uploaded_documents",
            "source_id": "stmt-1",
            "description": "Statement",
        }
        return SimpleNamespace(
            result_id="policy-result:test",
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            matrix_version="1.0",
            report_period_start=date(2025, 1, 1),
            report_period_end=date(2025, 12, 31),
            generated_at=date(2025, 12, 31),
            required_statements=["balance_sheet", "income_statement", "cash_flow"],
            decisions=[SimpleNamespace(evidence_anchors=[SimpleNamespace(**anchor)])],
            gaps=[],
            model_dump=lambda mode="json": {
                "result_id": "policy-result:test",
                "framework_id": "personal_us_gaap_like",
                "matrix_version": "1.0",
                "report_period_start": "2025-01-01",
                "report_period_end": "2025-12-31",
                "generated_at": "2025-12-31",
                "required_statements": ["balance_sheet", "income_statement", "cash_flow"],
                "decisions": [{"evidence_anchors": [anchor]}],
                "gaps": [],
            },
        )

    async def fake_sections(*_args, **_kwargs):
        return _package_snapshot_sections(section_label)

    monkeypatch.setattr("src.routers.reports.get_personal_report_package_readiness", fake_readiness)
    monkeypatch.setattr("src.routers.reports.derive_user_framework_policy_result", fake_policy)
    monkeypatch.setattr("src.routers.reports._personal_report_package_section_payloads", fake_sections)


async def test_AC5_19_1_package_generate_creates_draft_or_trusted_snapshot(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC5.19.1: Package generation freezes context and gates draft/trusted state by readiness."""
    await _patch_package_snapshot_inputs(monkeypatch, readiness_state="blocked", blocking_count=1)

    draft = await generate_personal_report_package_snapshot(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        as_of_date=date(2025, 12, 31),
        currency="SGD",
        db=db,
        user_id=test_user.id,
    )

    draft_payload = draft.model_dump(mode="json")
    assert draft_payload["status"] == "draft"
    assert draft_payload["framework_id"] == "personal_us_gaap_like"
    assert draft_payload["currency"] == "SGD"
    assert draft_payload["readiness_state"] == "blocked"
    assert draft_payload["payload"]["readiness"]["state"] == "blocked"
    assert draft_payload["payload"]["source_trust_summary"]["source_classes"] == ["bank_statement"]
    assert "traceability_appendix" in draft_payload["payload"]["section_payloads"]
    assert "balance_sheet" in draft_payload["payload"]["section_payloads"]

    await _patch_package_snapshot_inputs(monkeypatch, readiness_state="ready", blocking_count=0)
    trusted = await generate_personal_report_package_snapshot(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        as_of_date=date(2025, 12, 31),
        currency="SGD",
        db=db,
        user_id=test_user.id,
    )

    assert trusted.status == "trusted"
    assert trusted.readiness_state == "ready"
    latest_rows = (
        (
            await db.execute(
                select(ReportSnapshot)
                .where(ReportSnapshot.user_id == test_user.id)
                .where(ReportSnapshot.report_type == ReportType.PACKAGE)
                .where(ReportSnapshot.is_latest.is_(True))
            )
        )
        .scalars()
        .all()
    )
    assert [row.id for row in latest_rows] == [trusted.id]


async def test_AC5_19_2_package_snapshot_get_is_user_scoped_and_immutable(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC5.19.2: Package snapshots list/get by user and reopen the frozen payload."""
    await _patch_package_snapshot_inputs(monkeypatch, readiness_state="ready", blocking_count=0, section_label="Frozen")
    snapshot = await generate_personal_report_package_snapshot(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        as_of_date=date(2025, 12, 31),
        currency="SGD",
        db=db,
        user_id=test_user.id,
    )
    await db.flush()

    other_user_id = (await UserFactory.create_async(db)).id
    db.add(
        ReportSnapshot(
            user_id=other_user_id,
            report_type=ReportType.PACKAGE,
            as_of_date=date(2025, 12, 31),
            start_date=date(2025, 1, 1),
            report_data={
                "status": "trusted",
                "framework_id": "personal_us_gaap_like",
                "currency": "SGD",
                "readiness_state": "ready",
                "payload": {"package_id": "personal-financial-report-package", "section_payloads": {}},
            },
            is_latest=True,
        )
    )
    await db.flush()

    await _patch_package_snapshot_inputs(
        monkeypatch, readiness_state="ready", blocking_count=0, section_label="Live Changed"
    )
    listed = await list_personal_report_package_snapshots(db=db, user_id=test_user.id, pagination=PaginationParams())
    assert [item.id for item in listed] == [snapshot.id]

    reopened = await get_personal_report_package_snapshot(snapshot_id=snapshot.id, db=db, user_id=test_user.id)
    assert reopened.payload["section_payloads"]["traceability_appendix"]["lines"][0]["label"] == "Frozen"

    with pytest.raises(HTTPException) as exc_info:
        await get_personal_report_package_snapshot(snapshot_id=snapshot.id, db=db, user_id=other_user_id)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Package snapshot not found"


async def test_AC5_19_3_package_snapshot_exports_are_snapshot_derived(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC5.19.3: Package JSON and CSV exports stream saved snapshot data only."""
    await _patch_package_snapshot_inputs(
        monkeypatch, readiness_state="ready", blocking_count=0, section_label="Frozen CSV"
    )
    snapshot = await generate_personal_report_package_snapshot(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        as_of_date=date(2025, 12, 31),
        currency="SGD",
        db=db,
        user_id=test_user.id,
    )

    await _patch_package_snapshot_inputs(
        monkeypatch, readiness_state="ready", blocking_count=0, section_label="Live Changed"
    )
    json_response = await export_personal_report_package_snapshot(
        snapshot_id=snapshot.id,
        format=PackageSnapshotExportFormat.JSON,
        db=db,
        user_id=test_user.id,
    )
    csv_response = await export_personal_report_package_snapshot(
        snapshot_id=snapshot.id,
        format=PackageSnapshotExportFormat.CSV,
        db=db,
        user_id=test_user.id,
    )

    json_body = await _read_streaming_body(json_response)
    csv_body = await _read_streaming_body(csv_response)

    assert "Frozen CSV" in json_body
    assert "Live Changed" not in json_body
    assert "personal-report-package" in json_response.headers["content-disposition"]
    assert csv_body.splitlines()[0].startswith("package_id,section_id,line_id,label")
    assert "Frozen CSV" in csv_body
    assert "source_document:stmt-1" in csv_body
    assert "Live Changed" not in csv_body


def _statement(
    user_id,
    *,
    status: BankStatementStatus = BankStatementStatus.APPROVED,
    account_id=None,
    stage1_status: Stage1Status | None = Stage1Status.APPROVED,
    balance_validated: bool | None = True,
    validation_error: str | None = None,
    updated_at: datetime | None = None,
) -> StatementSummary:
    timestamp = updated_at or datetime.now(UTC)
    return StatementSummary(
        user_id=user_id,
        account_id=account_id,
        file_hash=uuid4().hex,
        institution="Readiness Bank",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
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

    txn = AtomicTransaction(
        user_id=test_user.id,
        txn_date=date(2026, 5, 2),
        description="Needs reconciliation",
        amount=Decimal("25.00"),
        direction=TransactionDirection.OUT,
        currency="SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[],
    )
    db.add(txn)
    await db.flush()
    db.add(
        ReconciliationMatch(
            atomic_txn_id=txn.id,
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
                fx_rate=Decimal("1.000000"),
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
    offset_account = Account(
        user_id=test_user.id,
        name="Processing Offset",
        type=AccountType.EQUITY,
        currency="USD",
    )
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 5, 3),
        memo="Processing line with missing FX",
        source_type=JournalEntrySourceType.SYSTEM,
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([processing_account, offset_account, entry])
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=processing_account.id,
                direction=Direction.DEBIT,
                amount=Decimal("25.00"),
                currency="USD",
                fx_rate=Decimal("1.000000"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=offset_account.id,
                direction=Direction.CREDIT,
                amount=Decimal("25.00"),
                currency="USD",
                fx_rate=Decimal("1.000000"),
            ),
        ]
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
    # An in-flight PARSING summary is not confirmed data: it must not count as a
    # report input / statement source.
    assert response.model_dump(mode="json")["source_summary"]["statements"] == 0

    processing_account = Account(
        user_id=test_user.id,
        name=f"Processing Cash {uuid4()}",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(processing_account)
    await db.flush()
    processing.account_id = processing_account.id
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


@ac_proof(
    "personal-package-source-trust-pr",
    ac_ids=["AC19.9.1", "AC8.14.3"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=[
        "bank_statement",
        "brokerage_statement",
        "property_statement",
        "liability_statement",
        "esop_rsu_plan",
        "csv_export",
        "manual_record",
    ],
    issue="#696",
)
async def test_AC19_9_1_package_readiness_reports_source_trust_summary(
    db: AsyncSession,
    test_user: User,
):
    """AC19.9.1 AC8.14.3: Package readiness reports deterministic source trust coverage."""
    report_date = date(2026, 5, 31)
    await _ready_source_account(db, test_user.id)
    db.add(
        Account(
            user_id=test_user.id,
            name="Uncovered Trust Liability",
            type=AccountType.LIABILITY,
            currency="SGD",
        )
    )
    db.add(
        JournalEntry(
            user_id=test_user.id,
            entry_date=report_date,
            memo="Manual source trust anchor",
            source_type=JournalEntrySourceType.MANUAL,
            status=JournalEntryStatus.POSTED,
        )
    )
    db.add(
        AtomicPosition(
            user_id=test_user.id,
            snapshot_date=report_date,
            asset_identifier="TRUST",
            broker="Trust Broker",
            quantity=Decimal("10"),
            market_value=Decimal("125.00"),
            currency="SGD",
            asset_type=AssetType.STOCK,
            dedup_hash=f"trust-{uuid4()}",
            source_documents={"documents": [{"doc_id": "trust-brokerage-doc", "doc_type": "brokerage_statement"}]},
        )
    )
    db.add_all(
        [
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.PROPERTY_VALUE,
                liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
                as_of_date=report_date,
                value=Decimal("500000.00"),
                currency="SGD",
                source="Trust Property",
                notes="Independent appraisal basis",
            ),
            ManualValuationSnapshot(
                user_id=test_user.id,
                component_type=ManualValuationComponentType.RSU,
                liquidity_class=ManualValuationLiquidityClass.RESTRICTED,
                as_of_date=report_date,
                value=Decimal("42000.00"),
                currency="SGD",
                source="Trust RSU",
                notes="25% annual vesting",
            ),
            MarketDataOverride(
                user_id=test_user.id,
                asset_identifier="TRUST",
                price_date=report_date,
                price=Decimal("12.50"),
                currency="SGD",
                source=PriceSource.MANUAL,
            ),
        ]
    )
    await db.flush()

    response = await personal_report_package_readiness(db=db, user_id=test_user.id)
    payload = response.model_dump(mode="json")
    trust = payload["source_trust_summary"]

    assert {
        "bank_statement",
        "brokerage_statement",
        "property_statement",
        "liability_statement",
        "esop_rsu_plan",
        "csv_export",
        "manual_record",
    } <= set(trust["source_classes"])
    assert {
        "bank_statement",
        "brokerage_statement",
        "property_statement",
        "liability_statement",
        "esop_rsu_plan",
        "csv_export",
        "manual_record",
    } <= set(trust["deterministic_pr_source_classes"])
    assert {"bank_statement", "brokerage_statement"} <= set(trust["post_merge_llm_ocr_source_classes"])
    assert {"property_statement", "liability_statement", "esop_rsu_plan", "manual_record"} <= set(
        trust["manual_trusted_source_classes"]
    )
    assert "missing_source_coverage" in trust["blocker_codes"]
    assert "manual_record" in trust["gap_source_classes"]


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
    assert total_assets["source_classes"] == ["bank_statement", "brokerage_statement", "manual_record"]
    assert total_assets["proof_level"] == "hybrid"
    assert total_assets["anchor_count"] == 0


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
        assert line["proof_level"]
        assert isinstance(line["source_classes"], list)
        assert isinstance(line["blocker_codes"], list)


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
    other_bank = Account(user_id=other_user.id, name="Other Bank", type=AccountType.ASSET, currency="SGD")
    other_income = Account(user_id=other_user.id, name="Other Income", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, income, investment, other_bank, other_income])
    await db.flush()

    document = UploadedDocument(
        user_id=test_user.id,
        file_path="s3://trace/statement.csv",
        file_hash=f"trace-{uuid4().hex}",
        original_filename="trace-statement.csv",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(document)
    await db.flush()
    statement = StatementSummary(
        user_id=test_user.id,
        account_id=bank.id,
        uploaded_document_id=document.id,
        file_hash=document.file_hash,
        institution="Trace Bank",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=report_date,
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("100.00"),
        status=BankStatementStatus.APPROVED,
        balance_validated=True,
        stage1_status=Stage1Status.APPROVED,
    )
    db.add(statement)
    await db.flush()
    db.add(
        AtomicTransaction(
            id=statement_txn_id,
            user_id=test_user.id,
            txn_date=report_date,
            description="Traceable income",
            amount=Decimal("100.00"),
            direction=TransactionDirection.IN,
            currency="SGD",
            dedup_hash=uuid4().hex + uuid4().hex,
            source_documents=[{"doc_id": str(document.id), "doc_type": DocumentType.BANK_STATEMENT.value}],
        )
    )

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
                account_id=other_bank.id,
                direction=Direction.DEBIT,
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
    assert f"atomic_transaction:{statement_txn_id}" in total_assets["source_anchor"]["identifiers"]
    assert any(
        detail["source_kind"] == "atomic_transaction"
        and detail["source_id"] == str(statement_txn_id)
        and detail["source_type"] == "atomic_transaction"
        and detail["amount"] == "100.00"
        and detail["currency"] == "SGD"
        and detail["review_state"] == "reviewed_source"
        and detail["confidence_tier"] == "HIGH"
        and detail["contribution_basis"] == "journal_entry_source_amount"
        and detail["journal_entry_id"] == str(entry.id)
        and detail["account_id"] == str(bank.id)
        and detail["account_type"] == "ASSET"
        and detail["identifier"] == f"atomic_transaction:{statement_txn_id}"
        for detail in total_assets["source_anchor"]["details"]
    )
    assert f"manual_valuation_snapshot:{manual.id}" in total_assets["source_anchor"]["identifiers"]
    assert total_assets["anchor_count"] > 0
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
    assert f"atomic_transaction:{other_source_id}" not in all_identifiers


async def test_AC11_9_10_package_traceability_surfaces_manual_valuation_basis(
    db: AsyncSession,
    test_user: User,
):
    """AC11.9.10: Traceability appendix surfaces each manual snapshot's valuation_basis."""
    report_date = date(2026, 5, 31)

    with_basis = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of_date=report_date,
        value=Decimal("500000.00"),
        currency="SGD",
        source="Appraised Property",
        valuation_basis=ManualValuationBasis.MARKET_APPRAISAL,
    )
    without_basis = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type=ManualValuationComponentType.LONG_TERM_SAVINGS,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of_date=report_date,
        value=Decimal("12000.00"),
        currency="SGD",
        source="Legacy Savings",
        valuation_basis=None,
    )
    db.add_all([with_basis, without_basis])
    await db.commit()

    response = await personal_report_package_traceability(
        start_date=date(2026, 5, 1),
        end_date=report_date,
        as_of_date=report_date,
        db=db,
        user_id=test_user.id,
    )
    lines = {line["line_id"]: line for line in response.model_dump(mode="json")["lines"]}
    details = {
        detail["source_id"]: detail
        for detail in lines["balance_sheet.total_assets"]["source_anchor"]["details"]
        if detail["source_kind"] == "manual_valuation_snapshot"
    }

    assert details[str(with_basis.id)]["valuation_basis"] == "market_appraisal"
    assert details[str(without_basis.id)]["valuation_basis"] == "unspecified"


def test_AC19_10_1_source_anchor_resolver_requires_typed_source_membership():
    """AC19.10.1: Source resolver does not infer source type from a bare UUID."""
    user_id = uuid4()
    account = Account(id=uuid4(), user_id=user_id, name="Resolver Bank", type=AccountType.ASSET, currency="SGD")
    line = JournalLine(
        id=uuid4(),
        journal_entry_id=uuid4(),
        account_id=account.id,
        direction=Direction.DEBIT,
        amount=Decimal("42.00"),
        currency="SGD",
    )
    unknown_source_id = uuid4()
    entry = JournalEntry(
        id=uuid4(),
        user_id=user_id,
        entry_date=date(2026, 5, 31),
        memo="Resolver source",
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        source_id=unknown_source_id,
        status=JournalEntryStatus.POSTED,
    )

    unknown_detail = _journal_source_anchor_detail(
        entry,
        line,
        account,
        statement_txn_ids=set(),
        atomic_txn_ids=set(),
    )
    assert unknown_detail["identifier"] == f"unknown_source:{unknown_source_id}"
    assert unknown_detail["source_kind"] == "unknown_source"
    assert unknown_detail["source_type"] == "user_confirmed"

    statement_detail = _journal_source_anchor_detail(
        entry,
        line,
        account,
        statement_txn_ids={unknown_source_id},
        atomic_txn_ids=set(),
    )
    assert statement_detail["identifier"] == f"statement_transaction:{unknown_source_id}"
    assert statement_detail["source_kind"] == "bank_statement_transaction"
    assert statement_detail["source_type"] == "bank_statement"


def test_AC19_10_1_source_anchor_resolver_covers_manual_atomic_and_entry_fallbacks():
    """AC19.10.1: Resolver emits typed details for each supported source class."""
    user_id = uuid4()
    account = Account(id=uuid4(), user_id=user_id, name="Resolver Asset", type=AccountType.ASSET, currency="SGD")
    line = JournalLine(
        id=uuid4(),
        journal_entry_id=uuid4(),
        account_id=account.id,
        direction=Direction.DEBIT,
        amount=Decimal("42.00"),
        currency="SGD",
    )

    manual_entry = JournalEntry(
        id=uuid4(),
        user_id=user_id,
        entry_date=date(2026, 5, 31),
        memo="Manual resolver source",
        source_type=JournalEntrySourceType.MANUAL,
        source_id=None,
        status=JournalEntryStatus.POSTED,
    )
    manual_detail = _journal_source_anchor_detail(
        manual_entry,
        line,
        account,
        statement_txn_ids=set(),
        atomic_txn_ids=set(),
    )
    assert manual_detail["identifier"] == f"manual_journal_entry:{manual_entry.id}"
    assert manual_detail["source_kind"] == "manual_journal_entry"
    assert manual_detail["source_id"] == str(manual_entry.id)
    assert manual_detail["review_state"] == "explicit_manual_input"
    assert manual_detail["confidence_tier"] == "TRUSTED"

    atomic_source_id = uuid4()
    atomic_entry = JournalEntry(
        id=uuid4(),
        user_id=user_id,
        entry_date=date(2026, 5, 31),
        memo="Atomic resolver source",
        source_type=JournalEntrySourceType.AUTO_MATCHED,
        source_id=atomic_source_id,
        status=JournalEntryStatus.RECONCILED,
    )
    atomic_detail = _journal_source_anchor_detail(
        atomic_entry,
        line,
        account,
        statement_txn_ids=set(),
        atomic_txn_ids={atomic_source_id},
    )
    assert atomic_detail["identifier"] == f"atomic_transaction:{atomic_source_id}"
    assert atomic_detail["source_kind"] == "atomic_transaction"
    assert atomic_detail["source_type"] == "atomic_transaction"
    assert atomic_detail["review_state"] == "auto_matched"

    generated_entry = JournalEntry(
        id=uuid4(),
        user_id=user_id,
        entry_date=date(2026, 5, 31),
        memo="Generated resolver source",
        source_type=JournalEntrySourceType.SYSTEM,
        source_id=None,
        status=JournalEntryStatus.POSTED,
    )
    generated_detail = _journal_source_anchor_detail(
        generated_entry,
        line,
        account,
        statement_txn_ids=set(),
        atomic_txn_ids=set(),
    )
    assert generated_detail["identifier"] == f"journal_entry:{generated_entry.id}"
    assert generated_detail["source_kind"] == "journal_entry"
    assert generated_detail["source_type"] == "system"


def test_AC19_10_1_anchor_detail_helpers_keep_auditable_deduped_payloads():
    """AC19.10.1: Anchor details remain typed, deduped, and blocker-aware."""
    user_id = uuid4()
    account = Account(id=uuid4(), user_id=user_id, name="Ledger Asset", type=AccountType.ASSET, currency="SGD")
    entry = JournalEntry(
        id=uuid4(),
        user_id=user_id,
        entry_date=date(2026, 5, 31),
        memo="Ledger detail",
        source_type=JournalEntrySourceType.AUTO_PARSED,
        status=JournalEntryStatus.POSTED,
    )
    line = JournalLine(
        id=uuid4(),
        journal_entry_id=entry.id,
        account_id=account.id,
        direction=Direction.DEBIT,
        amount=Decimal("11.00"),
        currency="SGD",
    )
    ledger_detail = _ledger_anchor_detail(entry, line, account)
    assert ledger_detail["identifier"] == f"journal_line:{line.id}"
    assert ledger_detail["source_kind"] == "journal_line"
    assert ledger_detail["review_state"] == "unreviewed_auto_parse"
    assert ledger_detail["account_type"] == "ASSET"

    document_details = _source_document_details(
        {
            "documents": [
                {"doc_id": "doc-1", "doc_type": "brokerage_statement"},
                {"ignored": True},
            ]
        },
        contribution_basis="market_value_support",
    )
    assert document_details == [
        {
            "identifier": "brokerage_document:doc-1",
            "source_kind": "uploaded_document",
            "source_id": "doc-1",
            "source_type": "brokerage_statement",
            "amount": None,
            "currency": None,
            "review_state": "imported_or_reviewed_payload",
            "confidence_tier": "HIGH",
            "contribution_basis": "market_value_support",
        }
    ]
    assert _source_document_details(None, contribution_basis="ignored") == []

    lines_by_id = {
        "line": {
            "source_anchor": {"identifiers": [], "details": []},
            "ledger_anchor": {"identifiers": [], "details": []},
            "anchor_count": 0,
            "blocker_codes": ["existing"],
        }
    }
    _add_anchor_details(lines_by_id, "line", "source_anchor", [*document_details, *document_details])
    _add_anchor_details(lines_by_id, "missing", "source_anchor", document_details)
    _append_blocker(lines_by_id["line"], "unknown_source_anchor")
    _append_blocker(lines_by_id["line"], "existing")

    assert lines_by_id["line"]["source_anchor"]["identifiers"] == ["brokerage_document:doc-1"]
    assert len(lines_by_id["line"]["source_anchor"]["details"]) == 1
    assert lines_by_id["line"]["anchor_count"] == 1
    assert lines_by_id["line"]["blocker_codes"] == ["existing", "unknown_source_anchor"]


async def test_AC18_8_4_AC18_8_7_package_traceability_resolves_report_line_to_source_document(
    db: AsyncSession,
    test_user: User,
):
    """AC18.8.4 AC18.8.7: Report traceability resolves a ledger-backed line to an Evidence Graph source document."""
    report_date = date(2026, 5, 31)
    bank = Account(user_id=test_user.id, name="Evidence Trace Bank", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.flush()

    file_hash = f"evidence-trace-{uuid4().hex}"
    statement = StatementSummary(
        user_id=test_user.id,
        account_id=bank.id,
        file_hash=file_hash,
        institution="Trace Bank",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=report_date,
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("120.00"),
        status=BankStatementStatus.APPROVED,
        balance_validated=True,
        stage1_status=Stage1Status.APPROVED,
    )
    txn = AtomicTransaction(
        user_id=test_user.id,
        txn_date=report_date,
        description="Evidence graph income",
        amount=Decimal("120.00"),
        direction=TransactionDirection.IN,
        currency="SGD",
        reference="EG-INC",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[],
    )

    await dual_write_layer2(
        db=db,
        user_id=test_user.id,
        statement=statement,
        transactions=[txn],
        original_filename="evidence-statement.csv",
        document_type=DocumentType.BANK_STATEMENT,
    )
    await db.flush()

    atomic_txn = (
        await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id))
    ).scalar_one()
    entry = await create_entry_from_txn(
        db,
        atomic_txn,
        user_id=test_user.id,
        auto_post=True,
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        preloaded_statement=statement,
        preloaded_bank_account=bank,
    )
    await db.flush()
    await db.refresh(entry, ["lines"])
    # Record the AtomicTransaction -> JournalEntry lineage so traceability can resolve
    # the upstream UploadedDocument source via the Evidence Graph.
    await EvidenceGraphIntegrationService().record_journal_posting(
        db,
        user_id=test_user.id,
        atomic_transaction=atomic_txn,
        journal_entry=entry,
    )
    await db.commit()

    uploaded_doc = (
        await db.execute(select(UploadedDocument).where(UploadedDocument.user_id == test_user.id))
    ).scalar_one()

    traceability = await personal_report_package_traceability(
        start_date=date(2026, 5, 1),
        end_date=report_date,
        as_of_date=report_date,
        db=db,
        user_id=test_user.id,
    )
    lines = {line["line_id"]: line for line in traceability.model_dump(mode="json")["lines"]}
    total_income = lines["income_statement.total_income"]

    assert f"uploaded_document:{uploaded_doc.id}" in total_income["source_anchor"]["identifiers"]
    assert f"atomic_transaction:{atomic_txn.id}" in total_income["source_anchor"]["identifiers"]
    assert any(
        detail["source_kind"] == "uploaded_document"
        and detail["source_id"] == str(uploaded_doc.id)
        and detail["contribution_basis"] == "evidence_graph_upstream"
        for detail in total_income["source_anchor"]["details"]
    )
    assert any(detail["journal_entry_id"] == str(entry.id) for detail in total_income["ledger_anchor"]["details"])


async def test_AC19_10_1_unknown_journal_source_ids_are_not_reported_as_statement_transactions(
    db: AsyncSession,
    test_user: User,
):
    """AC18.8.5 AC19.10.1: Unknown journal source IDs remain explicit blockers, not fake statement anchors."""
    report_date = date(2026, 5, 31)
    bank = Account(user_id=test_user.id, name="Unknown Source Bank", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=test_user.id, name="Unknown Source Income", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, income])
    await db.flush()

    unknown_source_id = uuid4()
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=report_date,
        memo="Income with unsupported source",
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        source_id=unknown_source_id,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=bank.id,
                direction=Direction.DEBIT,
                amount=Decimal("88.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=income.id,
                direction=Direction.CREDIT,
                amount=Decimal("88.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()

    traceability = await personal_report_package_traceability(
        start_date=date(2026, 5, 1),
        end_date=report_date,
        as_of_date=report_date,
        db=db,
        user_id=test_user.id,
    )
    lines = {line["line_id"]: line for line in traceability.model_dump(mode="json")["lines"]}
    total_income = lines["income_statement.total_income"]

    assert f"statement_transaction:{unknown_source_id}" not in total_income["source_anchor"]["identifiers"]
    assert f"unknown_source:{unknown_source_id}" in total_income["source_anchor"]["identifiers"]
    assert "unknown_source_anchor" in total_income["blocker_codes"]
    assert any(
        detail["source_kind"] == "unknown_source"
        and detail["source_id"] == str(unknown_source_id)
        and detail["amount"] == "88.00"
        for detail in total_income["source_anchor"]["details"]
    )

    readiness = await personal_report_package_readiness(db=db, user_id=test_user.id)
    readiness_payload = readiness.model_dump(mode="json")
    blockers = {blocker["code"]: blocker for blocker in readiness_payload["blockers"]}
    assert readiness_payload["state"] == "blocked"
    assert blockers["unknown_source_anchor"]["count"] == 1
    assert "unknown_source_anchor" in readiness_payload["source_trust_summary"]["blocker_codes"]
