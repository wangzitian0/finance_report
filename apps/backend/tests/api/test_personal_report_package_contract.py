"""Personal report package API contract coverage."""

import csv
from datetime import UTC, date, datetime
from decimal import Decimal
from io import StringIO
from uuid import uuid4

import pytest
from common.testing.ac_proof import ac_proof
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.audit.orm.trace_record import TraceRecordRow
from src.config import settings
from src.deps import PaginationParams
from src.extraction import DocumentType, EconomicIntent, ExtractedTransactionRow, UploadedDocument
from src.extraction.extension.deduplication import DeduplicationService, dual_write_layer2
from src.extraction.extension.evidence_graph_integration import EvidenceGraphIntegrationService
from src.extraction.extension.review_queue import create_entry_from_txn
from src.extraction.orm.layer2 import AssetType, AtomicPosition, AtomicTransaction, TransactionDirection
from src.extraction.orm.layer3 import (
    CostBasisMethod,
    ManagedPosition,
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    ManualValuationSnapshot,
    PositionStatus,
)
from src.extraction.orm.statement_enums import BankStatementStatus, Stage1Status
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    JournalLineContribution,
    ResolvedJournalContribution,
)
from src.ledger.extension.anchored_posting import submit_system_journal_entry
from src.portfolio import DividendIncome
from src.pricing import MarketDataOverride, PriceSource
from src.reporting import (
    PERSONAL_REPORT_PACKAGE_CONTRACT,
    PERSONAL_REPORT_PACKAGE_NOTES,
    PackageAssembler,
    PackageSectionContribution,
    ReportSnapshot,
    ReportType,
    build_personal_report_package_traceability_payload,
)
from src.routers.reports import (
    PackageSnapshotExportFormat,
    export_personal_report_package_snapshot,
    generate_personal_report_package_snapshot,
    get_personal_report_package_snapshot,
    list_personal_report_package_snapshots,
)
from src.schemas import (
    PersonalReportingFrameworkId,
    PersonalReportPackageContractResponse,
    PersonalReportPackageDocument,
    PersonalReportPackageDocumentLifecycle,
    PersonalReportPackageGenerateRequest,
    PersonalReportPackageNotesResponse,
    PersonalReportPackageTraceabilityResponse,
)
from tests.factories import UserFactory
from tests.statement_ingestion import anchored_reviewed_posting_inputs


@pytest.fixture(autouse=True)
def patch_database_connection():
    """This contract endpoint is static and does not need a test database."""
    yield


def _package_contract_fixture(
    framework_id: PersonalReportingFrameworkId | None = None,
) -> PersonalReportPackageContractResponse:
    payload = dict(PERSONAL_REPORT_PACKAGE_CONTRACT)
    payload["selected_framework_id"] = framework_id.value if framework_id else None
    return PersonalReportPackageContractResponse.model_validate(payload)


def _package_notes_fixture() -> PersonalReportPackageNotesResponse:
    return PersonalReportPackageNotesResponse.model_validate(PERSONAL_REPORT_PACKAGE_NOTES)


async def _traceability_payload(
    db: AsyncSession,
    *,
    user_id,
    start_date: date,
    end_date: date,
    as_of_date: date,
) -> dict:
    """Use the package's contribution collector, never raw traceability reads."""
    contributions = await PackageAssembler()._contributions(
        db,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        as_of_date=as_of_date,
    )
    return await build_personal_report_package_traceability_payload(contributions=contributions)


def test_AC5_9_1_package_contract_defines_required_sections():
    """AC-reporting.package-contract.1: package document embeds stable required sections."""
    response = _package_contract_fixture()
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
    assert sections["investment_performance"]["owner_epic"] == "EPIC-017"
    assert sections["notes"]["status"] == "ready"
    assert sections["notes"]["blocking_issue"] is None
    assert sections["traceability_appendix"]["status"] == "ready"
    assert sections["traceability_appendix"]["blocking_issue"] is None


def test_AC5_9_2_package_contract_marks_decimal_totals_and_period_semantics():
    """AC-reporting.package-contract.2: AC5.9.2: Contract exposes Decimal-safe totals and date semantics."""
    response = _package_contract_fixture()
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
        "input_decision_references",
    ]


def test_AC5_11_1_package_contract_marks_annualized_schedule_ready():
    """AC-reporting.package-annualized.1: Annualized schedule is an embedded package section."""
    response = _package_contract_fixture()
    payload = response.model_dump(mode="json")

    sections = {section["section_id"]: section for section in payload["sections"]}
    section = sections["annualized_income_long_term"]
    assert section["status"] == "ready"
    assert section["blocking_issue"] is None


def test_AC5_12_1_package_notes_endpoint_returns_required_note_taxonomy():
    """AC-reporting.package-notes.1: AC5.12.1: Package notes endpoint returns standards-inspired disclosure notes."""
    response = _package_notes_fixture()
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
    """AC-reporting.package-notes.2: Package contract marks notes as an embedded ready section."""
    response = _package_contract_fixture()
    payload = response.model_dump(mode="json")

    section = {section["section_id"]: section for section in payload["sections"]}["notes"]
    assert section["status"] == "ready"
    assert section["blocking_issue"] is None


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
        "notes": _package_notes_fixture().model_dump(mode="json"),
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
                    "anchor_count": 2,
                    "blocker_codes": [],
                },
                {
                    "line_id": "notes.non_compliance_statement",
                    "section_id": "notes",
                    "label": "Package Non-Compliance Statement",
                    "amount_field": None,
                    "currency_field": None,
                    "source_state": "package_contract",
                    "source_anchor": {
                        "state": "available",
                        "source_types": ["package_contract"],
                        "identifiers": ["package_contract:personal-financial-report-package"],
                    },
                    "ledger_anchor": {
                        "state": "not_applicable",
                        "entry_statuses": [],
                        "identifiers": [],
                    },
                    "anchor_count": 1,
                    "blocker_codes": [],
                },
            ],
            "completeness_warnings": [],
        },
    }


def _package_document(
    *,
    readiness_state: str,
    blocking_count: int,
    section_label: str,
    lifecycle: PersonalReportPackageDocumentLifecycle,
    snapshot_id,
    frozen_at,
) -> PersonalReportPackageDocument:
    readiness = {
        "package_id": "personal-financial-report-package",
        "state": readiness_state,
        "label": readiness_state.title(),
        "action_href": "/reports/package",
        "blocking_count": blocking_count,
        "blockers": [],
        "input_coverage": {
            "manifest_decision_count": 1,
            "authoritative_input_count": 1,
            "unproven_input_count": 0,
        },
    }
    return PersonalReportPackageDocument.model_validate(
        {
            "schema_version": "2",
            "lifecycle": lifecycle,
            "snapshot_id": snapshot_id,
            "generated_at": datetime(2025, 12, 31, tzinfo=UTC),
            "frozen_at": frozen_at,
            "package_id": "personal-financial-report-package",
            # A fixture without a persisted package Decision can only be draft,
            # regardless of the projected readiness label.
            "status": "draft",
            "context": {
                "framework_id": "personal_us_gaap_like",
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "as_of_date": "2025-12-31",
                "currency": "SGD",
            },
            "contract": _package_contract_fixture(PersonalReportingFrameworkId.US_GAAP_LIKE),
            "readiness": readiness,
            "framework_policy": {
                "result_id": "policy-result:test",
                "framework_id": "personal_us_gaap_like",
                "matrix_version": "1.0",
                "report_period_start": "2025-01-01",
                "report_period_end": "2025-12-31",
                "generated_at": "2025-12-31",
                "required_statements": ["balance_sheet", "income_statement", "cash_flow"],
                "decisions": [],
                "gaps": [],
            },
            "input_manifest": [
                {
                    "decision_id": str(uuid4()),
                    "input_refs": ["source_document:stmt-1"],
                    "target_kind": "journal_command",
                    "target_id": "entry-1",
                    "target_version": "1",
                    "assertion_kind": "ledger_authority",
                    "assertion_id": "fixture",
                    "assertion_version": "1",
                    "authority_tier": "CODE-ONLY",
                }
            ],
            "sections": {
                "balance_sheet": {
                    "as_of_date": "2025-12-31",
                    "currency": "SGD",
                    "assets": [],
                    "liabilities": [],
                    "equity": [],
                    "total_assets": "100.00",
                    "total_liabilities": "0.00",
                    "total_equity": "100.00",
                    "net_income": "25.00",
                    "unrealized_fx_gain_loss": "0.00",
                    "net_worth_adjustment_gain_loss": "0.00",
                    "equation_delta": "0.00",
                    "is_balanced": True,
                },
                "income_statement": {
                    "start_date": "2025-01-01",
                    "end_date": "2025-12-31",
                    "currency": "SGD",
                    "income": [],
                    "expenses": [],
                    "total_income": "125.00",
                    "total_expenses": "100.00",
                    "net_income": "25.00",
                    "trends": [],
                },
                "cash_flow": {
                    "start_date": "2025-01-01",
                    "end_date": "2025-12-31",
                    "currency": "SGD",
                    "operating": [],
                    "investing": [],
                    "financing": [],
                    "summary": {
                        "operating_activities": "25.00",
                        "investing_activities": "0.00",
                        "financing_activities": "0.00",
                        "net_cash_flow": "25.00",
                        "beginning_cash": "75.00",
                        "ending_cash": "100.00",
                    },
                },
                "investment_performance": {
                    "period_start": "2025-01-01",
                    "period_end": "2025-12-31",
                    "as_of_date": "2025-12-31",
                    "currency": "SGD",
                    "xirr": "0.00",
                    "time_weighted_return": "0.00",
                    "money_weighted_return": "0.00",
                    "realized_pnl": "0.00",
                    "unrealized_pnl": "0.00",
                    "dividend_income": "0.00",
                    "dividend_yield": "0.00",
                    "holdings": [],
                    "allocation": [],
                    "data_freshness": {"latest_price_date": None, "market_data_provider": None, "stale": False},
                    "source_links": ["source_document:stmt-1"],
                    "notes": [],
                },
                "annualized_income_long_term": {
                    "section_id": "annualized_income_long_term",
                    "label": "Annualized Income & Long-Term Compensation",
                    "as_of_date": "2025-12-31",
                    "trailing_period_start": "2025-01-01",
                    "trailing_period_end": "2025-12-31",
                    "trailing_period_days": 365,
                    "income": {
                        "annualized_salary": "100.00",
                        "annualized_bonus": "0.00",
                        "annualized_dividend": "0.00",
                        "annualized_total": "100.00",
                        "currency": "SGD",
                        "calculation_basis": "fixture",
                    },
                    "restricted_holdings": [],
                    "restricted_fair_value_total": "0.00",
                    "restricted_fair_value_total_currency": "SGD",
                    "net_worth_treatment": {
                        "liquid_net_worth_default": "exclude_restricted_holdings",
                        "restricted_wealth_basis": "fixture",
                        "include_restricted_query": "/api/reports/balance-sheet?include_restricted=true",
                        "exclude_restricted_query": "/api/reports/balance-sheet?include_restricted=false",
                    },
                    "notes": [],
                },
                "notes": _package_notes_fixture().model_dump(mode="json"),
                "traceability_appendix": _package_snapshot_sections(section_label)["traceability_appendix"],
            },
        }
    )


async def _patch_package_snapshot_inputs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    readiness_state: str,
    blocking_count: int,
    section_label: str = "Total Assets",
) -> None:
    class FakePackageAssembler:
        async def assemble(self, *_args, **kwargs) -> PersonalReportPackageDocument:
            return _package_document(
                readiness_state=readiness_state,
                blocking_count=blocking_count,
                section_label=section_label,
                lifecycle=kwargs["lifecycle"],
                snapshot_id=kwargs["snapshot_id"],
                frozen_at=kwargs["frozen_at"],
            )

    async def skip_market_data_refresh(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr("src.routers.reports.PackageAssembler", FakePackageAssembler)
    monkeypatch.setattr("src.routers.reports._ensure_report_market_data_fresh", skip_market_data_refresh)


async def _install_trace_anchored_package_fixture(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fault_after_trace_flush: bool = False,
) -> None:
    asset = Account(user_id=test_user.id, name="Anchored cash", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=test_user.id, name="Anchored income", type=AccountType.INCOME, currency="SGD")
    db.add_all([asset, income])
    await db.flush()
    entry = await submit_system_journal_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2025, 6, 30),
        memo="Package authority fixture",
        lines_data=[
            {
                "account_id": asset.id,
                "direction": Direction.DEBIT,
                "amount": Decimal("100.00"),
                "currency": "SGD",
            },
            {
                "account_id": income.id,
                "direction": Direction.CREDIT,
                "amount": Decimal("100.00"),
                "currency": "SGD",
            },
        ],
        base_currency="SGD",
        operation=f"pkg-{uuid4().hex[:8]}",
    )
    await db.commit()

    fixture = _package_document(
        readiness_state="blocked",
        blocking_count=1,
        section_label="Anchored",
        lifecycle=PersonalReportPackageDocumentLifecycle.PREVIEW,
        snapshot_id=None,
        frozen_at=None,
    )
    assert entry.decision_anchor_id is not None
    fixture_line = fixture.sections.traceability_appendix.lines[0]
    fixture_line.ledger_anchor.identifiers = [f"journal_entry:{entry.id}"]
    fixture_line.ledger_anchor.details = [
        {
            "identifier": f"journal_entry:{entry.id}",
            "review_state": "current_authoritative_decision",
            "decision_id": str(entry.decision_anchor_id),
        }
    ]

    async def fixture_policy(*_args, **_kwargs):
        return fixture.framework_policy

    async def fixture_sections(*_args, **_kwargs):
        return fixture.sections

    async def skip_market_data_refresh(*_args, **_kwargs) -> None:
        return None

    async def fault_after_package_trace_flush(*_args, **_kwargs) -> None:
        raise RuntimeError("fault_after_package_trace_flush")

    monkeypatch.setattr("src.routers.reports.PackageAssembler", PackageAssembler)
    monkeypatch.setattr("src.routers.reports._ensure_report_market_data_fresh", skip_market_data_refresh)
    monkeypatch.setattr(
        "src.reporting.extension.package_document.derive_user_framework_policy_result",
        fixture_policy,
    )
    monkeypatch.setattr(PackageAssembler, "_sections", fixture_sections)
    if fault_after_trace_flush:
        monkeypatch.setattr(PackageAssembler, "_after_trace_flush", fault_after_package_trace_flush)


@ac_proof(
    "personal-package-document-pr",
    ac_ids=[
        "AC-reporting.package-snapshot.1",
        "AC-reporting.package-document.3",
        "AC-testing.trust-mirrors.3",
    ],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    # These fixture categories describe the source paths mirrored by the
    # deployed package journey. Package authority itself comes only from the
    # contribution decisions asserted below, never from these labels.
    source_classes=[
        "bank_statement",
        "brokerage_statement",
        "property_statement",
        "liability_statement",
        "esop_rsu_plan",
        "csv_export",
        "manual_record",
    ],
    issue="#567",
)
async def test_AC5_19_1_package_generate_creates_draft_or_trusted_snapshot(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-reporting.package-snapshot.1 AC-reporting.package-document.3 AC-testing.trust-mirrors.3: generate one typed document and trust it only through its persisted manifest decision."""
    await _patch_package_snapshot_inputs(monkeypatch, readiness_state="blocked", blocking_count=1)

    draft = await generate_personal_report_package_snapshot(
        request=PersonalReportPackageGenerateRequest(
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            as_of_date=date(2025, 12, 31),
            currency="SGD",
        ),
        db=db,
        user_id=test_user.id,
    )

    assert draft.status == "draft"
    assert draft.framework_id == PersonalReportingFrameworkId.US_GAAP_LIKE
    assert draft.currency == "SGD"
    assert draft.readiness_state == "blocked"
    assert draft.document.lifecycle is PersonalReportPackageDocumentLifecycle.FROZEN
    assert draft.document.readiness.state == "blocked"
    assert draft.document.readiness.input_coverage.manifest_decision_count == 1
    assert draft.document.sections.traceability_appendix.section_id == "traceability_appendix"
    assert draft.document.sections.balance_sheet.total_assets == Decimal("100.00")

    await _install_trace_anchored_package_fixture(db, test_user, monkeypatch)
    trusted = await generate_personal_report_package_snapshot(
        request=PersonalReportPackageGenerateRequest(
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            as_of_date=date(2025, 12, 31),
            currency="SGD",
        ),
        db=db,
        user_id=test_user.id,
    )

    assert trusted.status == "trusted"
    assert trusted.readiness_state == "ready"
    assert trusted.document.package_decision_id is not None
    assert len(trusted.document.input_manifest) == 1
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


async def test_AC_extraction_disposition_7_frozen_package_persists_trace_bound_policy_snapshot(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-extraction.disposition.7: package disclosure is a frozen policy snapshot, never a live config read."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    monkeypatch.setattr(settings, "git_commit_sha", "a" * 40)
    await _install_trace_anchored_package_fixture(db, test_user, monkeypatch)

    snapshot = await generate_personal_report_package_snapshot(
        request=PersonalReportPackageGenerateRequest(
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            as_of_date=date(2025, 12, 31),
            currency="SGD",
        ),
        db=db,
        user_id=test_user.id,
    )
    policy = snapshot.document.statement_disposition_policy
    assert policy is not None
    assert policy.model_dump(mode="json") == {
        "schema_version": "1",
        "policy_version": "disposition-v1",
        "mode": "enforce",
        "machine_confidence_threshold": "0.85",
        "pnl_effect_confidence_threshold": "0.85",
        "unknown_intent_outcome": "review",
        "ambiguous_intent_outcome": "review",
        "live_llm_proposals_enabled": False,
        "deployment_git_sha": "a" * 40,
        "semantic_digest": policy.semantic_digest,
    }
    note = next(
        note for note in snapshot.document.sections.notes.notes if note.note_id == "statement-disposition-policy"
    )
    assert note.source_state == "frozen_runtime_policy_snapshot"
    assert "disposition-v1" in note.disclosure
    assert "a" * 40 in note.disclosure

    monkeypatch.setattr(settings, "git_commit_sha", "b" * 40)
    reopened = await get_personal_report_package_snapshot(snapshot_id=snapshot.id, db=db, user_id=test_user.id)
    assert reopened.document.statement_disposition_policy == policy
    reopened_note = next(
        note for note in reopened.document.sections.notes.notes if note.note_id == "statement-disposition-policy"
    )
    assert reopened_note.disclosure == note.disclosure


async def test_AC_reporting_package_document_5_trace_and_snapshot_rollback_together(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-reporting.package-document.5: package trace and snapshot share one rollback boundary."""
    await _install_trace_anchored_package_fixture(
        db,
        test_user,
        monkeypatch,
        fault_after_trace_flush=True,
    )
    user_id = test_user.id

    with pytest.raises(RuntimeError, match="fault_after_package_trace_flush"):
        await generate_personal_report_package_snapshot(
            request=PersonalReportPackageGenerateRequest(
                framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
                as_of_date=date(2025, 12, 31),
                currency="SGD",
            ),
            db=db,
            user_id=test_user.id,
        )
    await db.rollback()

    package_trace_count = await db.scalar(
        select(func.count(TraceRecordRow.id))
        .where(TraceRecordRow.scope_id == str(user_id))
        .where(TraceRecordRow.target_kind == "personal_report_package")
    )
    package_snapshot_count = await db.scalar(
        select(func.count(ReportSnapshot.id))
        .where(ReportSnapshot.user_id == user_id)
        .where(ReportSnapshot.report_type == ReportType.PACKAGE)
    )
    assert package_trace_count == 0
    assert package_snapshot_count == 0


async def test_AC5_19_2_package_snapshot_get_is_user_scoped_and_immutable(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-reporting.package-snapshot.2: AC5.19.2: Package snapshots list/get by user and reopen the frozen payload."""
    await _patch_package_snapshot_inputs(monkeypatch, readiness_state="ready", blocking_count=0, section_label="Frozen")
    snapshot = await generate_personal_report_package_snapshot(
        request=PersonalReportPackageGenerateRequest(
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            as_of_date=date(2025, 12, 31),
            currency="SGD",
        ),
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
    assert reopened.document.sections.traceability_appendix.lines[0].label == "Frozen"

    with pytest.raises(HTTPException) as exc_info:
        await get_personal_report_package_snapshot(snapshot_id=snapshot.id, db=db, user_id=other_user_id)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Package snapshot not found"


async def test_AC_reporting_package_document_4_exports_the_selected_frozen_document(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
):
    """AC-reporting.package-document.4 AC-reporting.package-snapshot.3: export reads only the selected frozen document."""
    await _patch_package_snapshot_inputs(
        monkeypatch, readiness_state="ready", blocking_count=0, section_label="Frozen CSV"
    )
    snapshot = await generate_personal_report_package_snapshot(
        request=PersonalReportPackageGenerateRequest(
            framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
            as_of_date=date(2025, 12, 31),
            currency="SGD",
        ),
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
    csv_rows = list(csv.DictReader(StringIO(csv_body)))
    disclosure_row = next(row for row in csv_rows if row["line_id"] == "notes.non_compliance_statement")
    assert disclosure_row["amount"] == ""
    assert disclosure_row["currency"] == ""
    assert '"schema_version": "2"' in json_body
    assert '"document"' in json_body


async def test_AC5_13_1_package_traceability_endpoint_returns_section_line_anchors(db: AsyncSession, test_user: User):
    """AC-reporting.package-traceability.1 · AC-reporting.trust-signals.3: AC5.13.1: Package traceability endpoint returns source-to-ledger anchors per report line."""
    report_date = date.today()
    response = PersonalReportPackageTraceabilityResponse.model_validate(
        await _traceability_payload(
            db,
            user_id=test_user.id,
            start_date=report_date,
            end_date=report_date,
            as_of_date=report_date,
        )
    )
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
    assert total_assets["anchor_count"] == 0


async def test_AC5_13_2_package_traceability_declares_completeness_warnings(db: AsyncSession, test_user: User):
    """AC-reporting.package-traceability.2: AC5.13.2: Traceability appendix exposes explicit completeness states where anchors are unavailable."""
    report_date = date.today()
    response = PersonalReportPackageTraceabilityResponse.model_validate(
        await _traceability_payload(
            db,
            user_id=test_user.id,
            start_date=report_date,
            end_date=report_date,
            as_of_date=report_date,
        )
    )
    payload = response.model_dump(mode="json")

    lines = {line["line_id"]: line for line in payload["lines"]}
    assert lines["notes.non_compliance_statement"]["source_state"] == "package_contract"
    assert lines["notes.non_compliance_statement"]["ledger_anchor"]["state"] == "not_applicable"

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
        assert isinstance(line["blocker_codes"], list)


async def test_AC5_13_5_package_traceability_returns_dynamic_current_user_identifiers(
    db: AsyncSession,
    test_user: User,
):
    """AC-reporting.package-traceability.4: AC5.13.5: Traceability returns current-user dynamic identifiers without cross-user leakage."""
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

    response = PersonalReportPackageTraceabilityResponse.model_validate(
        await _traceability_payload(
            db,
            user_id=test_user.id,
            start_date=date(2026, 5, 1),
            end_date=report_date,
            as_of_date=report_date,
        )
    )
    lines = {line["line_id"]: line for line in response.model_dump(mode="json")["lines"]}

    total_assets = lines["balance_sheet.total_assets"]
    assert f"pricing_observation:{manual.id}" in total_assets["source_anchor"]["identifiers"]
    assert any(
        detail["source_kind"] == "pricing_valuation_observation"
        and detail["source_id"] == str(manual.id)
        and detail["amount"] == "500000.00"
        and detail["currency"] == "SGD"
        and detail["review_state"] == "unproven"
        and detail["reason_code"] == "missing_observation_decision"
        for detail in total_assets["source_anchor"]["details"]
    )
    assert any(
        detail["journal_entry_id"] == str(entry.id)
        and detail["source_kind"] == "journal_line"
        and detail["review_state"] == "unproven"
        for detail in total_assets["ledger_anchor"]["details"]
    )
    assert f"atomic_transaction:{statement_txn_id}" not in total_assets["source_anchor"]["identifiers"]

    investment_line = lines["investment_performance.market_value"]
    assert investment_line["source_anchor"]["identifiers"] == []
    assert f"atomic_position:{atomic.id}" not in investment_line["source_anchor"]["identifiers"]
    assert f"dividend_income:{dividend.id}" not in investment_line["source_anchor"]["identifiers"]
    assert f"market_price:{price.id}" not in investment_line["source_anchor"]["identifiers"]

    all_identifiers = {
        identifier
        for line in lines.values()
        for anchor_name in ("source_anchor", "ledger_anchor")
        for identifier in line[anchor_name]["identifiers"]
    }
    assert not any(str(other_entry.id) in identifier for identifier in all_identifiers)


async def test_AC11_9_10_package_traceability_surfaces_manual_valuation_basis(
    db: AsyncSession,
    test_user: User,
):
    """AC-pricing.manualvaluation.9: AC11.9.10: Traceability appendix surfaces each manual snapshot's valuation_basis."""
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

    response = PersonalReportPackageTraceabilityResponse.model_validate(
        await _traceability_payload(
            db,
            user_id=test_user.id,
            start_date=date(2026, 5, 1),
            end_date=report_date,
            as_of_date=report_date,
        )
    )
    lines = {line["line_id"]: line for line in response.model_dump(mode="json")["lines"]}
    details = {
        detail["source_id"]: detail
        for detail in lines["balance_sheet.total_assets"]["source_anchor"]["details"]
        if detail["source_kind"] == "pricing_valuation_observation"
    }

    assert details[str(with_basis.id)]["valuation_basis"] == "market_appraisal"
    assert details[str(without_basis.id)]["valuation_basis"] == "unspecified"


async def test_AC19_10_1_traceability_renders_only_ledger_owned_source_membership():
    """AC-reporting.package-document.7: a journal's opaque source id cannot become a statement claim."""
    journal_line = JournalLineContribution(
        line_id=uuid4(),
        account_id=uuid4(),
        account_type=AccountType.INCOME,
        direction=Direction.CREDIT,
        amount=Decimal("42.00"),
        currency="SGD",
    )
    journal = ResolvedJournalContribution(
        entry_id=uuid4(),
        entry_date=date(2026, 5, 31),
        lines=(journal_line,),
        state="unproven",
        reason_code="missing_current_decision_anchor",
        decision_id=None,
    )
    contribution = PackageSectionContribution(
        contribution_type="ledger_command",
        section_ids=("balance_sheet", "income_statement", "traceability_appendix"),
        payload=journal,
        state=journal.state,
        decision_id=journal.decision_id,
        input_refs=journal.input_refs,
        reason_code=journal.reason_code,
    )

    payload = await build_personal_report_package_traceability_payload(contributions=(contribution,))
    lines = {line["line_id"]: line for line in payload["lines"]}
    income = lines["income_statement.total_income"]
    assert income["source_anchor"].get("identifiers", []) == []
    assert income["ledger_anchor"]["identifiers"] == [f"journal_line:{journal_line.line_id}"]
    assert income["ledger_anchor"]["details"][0]["source_type"] == "decision_anchored_journal"
    assert income["ledger_anchor"]["details"][0]["review_state"] == "unproven"
    assert "unproven_package_input" in income["blocker_codes"]


async def test_AC19_10_1_traceability_dedupes_contribution_details():
    """AC-reporting.package-document.7: duplicate display inputs cannot change the proof set."""
    journal_line = JournalLineContribution(
        line_id=uuid4(),
        account_id=uuid4(),
        account_type=AccountType.ASSET,
        direction=Direction.DEBIT,
        amount=Decimal("11.00"),
        currency="SGD",
    )
    journal = ResolvedJournalContribution(
        entry_id=uuid4(),
        entry_date=date(2026, 5, 31),
        lines=(journal_line,),
        state="unproven",
        reason_code="missing_current_decision_anchor",
        decision_id=None,
    )
    contribution = PackageSectionContribution(
        contribution_type="ledger_command",
        section_ids=("balance_sheet", "traceability_appendix"),
        payload=journal,
        state=journal.state,
        decision_id=journal.decision_id,
        input_refs=journal.input_refs,
        reason_code=journal.reason_code,
    )

    payload = await build_personal_report_package_traceability_payload(
        contributions=(contribution, contribution),
    )
    assets = {line["line_id"]: line for line in payload["lines"]}["balance_sheet.total_assets"]
    assert assets["ledger_anchor"]["identifiers"] == [f"journal_line:{journal_line.line_id}"]
    assert len(assets["ledger_anchor"]["details"]) == 1
    assert "unproven_package_input" in assets["blocker_codes"]


async def test_AC18_8_4_AC18_8_7_package_traceability_preserves_the_ledger_decision_boundary(
    db: AsyncSession,
    test_user: User,
):
    """AC-audit.global-invariant.4 AC-extraction.1808.4 AC-extraction.1808.7: display does not bypass the decision-owned lineage.

    The ledger decision retains its audit parents.  Reporting may display the
    ledger contribution, but must not query the evidence graph or relabel an
    opaque source id as an extraction fact.
    """
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
    amount = Decimal("120.00")
    direction = TransactionDirection.IN
    description = "Evidence graph income"
    reference = "EG-INC"
    txn = ExtractedTransactionRow(
        user_id=test_user.id,
        txn_date=report_date,
        description=description,
        amount=amount,
        direction=direction.value,
        currency="SGD",
        reference=reference,
        currency_unresolved=False,
        balance_after=None,
        occurrence_index=0,
        dedup_hash=DeduplicationService.calculate_transaction_hash(
            test_user.id,
            report_date,
            amount,
            direction,
            description,
            reference,
        ),
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
    decision, counter_account, source_decision, trace_emitter = await anchored_reviewed_posting_inputs(
        db,
        user_id=test_user.id,
        transaction=atomic_txn,
        intent=EconomicIntent.INCOME,
    )
    entry = await create_entry_from_txn(
        db,
        atomic_txn,
        user_id=test_user.id,
        auto_post=True,
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        preloaded_statement=statement,
        preloaded_bank_account=bank,
        disposition=decision,
        counter_account=counter_account,
        source_decision=source_decision,
        trace_emitter=trace_emitter,
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

    traceability = PersonalReportPackageTraceabilityResponse.model_validate(
        await _traceability_payload(
            db,
            user_id=test_user.id,
            start_date=date(2026, 5, 1),
            end_date=report_date,
            as_of_date=report_date,
        )
    )
    lines = {line["line_id"]: line for line in traceability.model_dump(mode="json")["lines"]}
    total_income = lines["income_statement.total_income"]

    assert f"uploaded_document:{uploaded_doc.id}" not in total_income["source_anchor"]["identifiers"]
    assert f"atomic_transaction:{atomic_txn.id}" not in total_income["source_anchor"]["identifiers"]
    assert any(detail["journal_entry_id"] == str(entry.id) for detail in total_income["ledger_anchor"]["details"])


async def test_AC19_10_1_unknown_journal_source_ids_are_not_reported_as_statement_transactions(
    db: AsyncSession,
    test_user: User,
):
    """AC-reporting.source-anchors.1: AC-extraction.1808.5: AC18.8.5 AC19.10.1: Unknown journal source IDs remain explicit blockers, not fake statement anchors."""
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

    traceability = PersonalReportPackageTraceabilityResponse.model_validate(
        await _traceability_payload(
            db,
            user_id=test_user.id,
            start_date=date(2026, 5, 1),
            end_date=report_date,
            as_of_date=report_date,
        )
    )
    lines = {line["line_id"]: line for line in traceability.model_dump(mode="json")["lines"]}
    total_income = lines["income_statement.total_income"]

    assert f"statement_transaction:{unknown_source_id}" not in total_income["source_anchor"]["identifiers"]
    assert total_income["source_anchor"].get("identifiers", []) == []
    assert "unproven_package_input" in total_income["blocker_codes"]
    assert any(
        detail["source_kind"] == "journal_line"
        and detail["journal_entry_id"] == str(entry.id)
        and detail["amount"] == "88.00"
        and detail["reason_code"] == "missing_current_decision_anchor"
        for detail in total_income["ledger_anchor"]["details"]
    )
