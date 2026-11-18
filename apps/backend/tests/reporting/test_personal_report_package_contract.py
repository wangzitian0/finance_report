from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, TraceDecisionRef, TraceEmitter, VersionedTraceRef
from src.audit.orm.trace_record import TraceRecordRow
from src.config import settings
from src.deps import PaginationParams
from src.extraction import (
    BankStatementStatus,
    DocumentType,
    EconomicIntent,
    ExtractedTransactionRow,
    Stage1Status,
    StatementSourceType,
    TransactionDirection,
    UploadedDocument,
)
from src.extraction.extension.deduplication import DeduplicationService, dual_write_layer2
from src.extraction.extension.evidence_graph_integration import EvidenceGraphIntegrationService
from src.extraction.extension.review_queue import create_entry_from_txn
from src.extraction.orm.layer2 import AssetType, AtomicPosition, AtomicTransaction
from src.portfolio.orm.portfolio import CostBasisMethod, ManagedPosition, PositionStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import (
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    JournalLineContribution,
    ResolvedJournalContribution,
)
from src.ledger.extension.anchored_posting import submit_system_journal_entry
from src.platform import DomainError
from src.portfolio import DividendIncome
from src.pricing import (
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
    MarketDataOverride,
    PriceSource,
)
from src.pricing.orm.manual_valuation import ManualValuationSnapshot
from src.reporting import (
    PERSONAL_REPORT_PACKAGE_CONTRACT,
    PERSONAL_REPORT_PACKAGE_NOTES,
    PackageAssembler,
    PackageDocumentVersionError,
    PackageSectionContribution,
    ReportSnapshot,
    ReportType,
    build_personal_report_package_traceability_payload,
    package_preview,
    package_snapshot_document,
    package_snapshot_summary,
)
from src.request_context import RequestContext
from src.routers.reports import (
    PackageSnapshotExportFormat,
    export_personal_report_package_snapshot,
    generate_personal_report_package_snapshot,
    get_personal_report_package_snapshot,
    list_personal_report_package_snapshots,
    preview_personal_report_package,
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
from tests.factories import AccountFactory, AtomicTransactionFactory, UserFactory
from tests.statement_ingestion import anchored_reviewed_posting_inputs

_PKG_REQ = PersonalReportPackageGenerateRequest(
    framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
    start_date=date(2025, 1, 1),
    end_date=date(2025, 12, 31),
    as_of_date=date(2025, 12, 31),
    currency="SGD",
)


@pytest.fixture(autouse=True)
def patch_database_connection():
    yield


def _package_contract_fixture(
    framework_id: PersonalReportingFrameworkId | None = None,
) -> PersonalReportPackageContractResponse:
    return PersonalReportPackageContractResponse.model_validate(
        {**PERSONAL_REPORT_PACKAGE_CONTRACT, "selected_framework_id": framework_id.value if framework_id else None}
    )


def _package_notes_fixture() -> PersonalReportPackageNotesResponse:
    return PersonalReportPackageNotesResponse.model_validate(PERSONAL_REPORT_PACKAGE_NOTES)


async def _traceability_payload(
    db: AsyncSession, *, user_id, start_date: date, end_date: date, as_of_date: date
) -> dict:
    return await build_personal_report_package_traceability_payload(
        contributions=await PackageAssembler()._contributions(
            db, user_id=user_id, start_date=start_date, end_date=end_date, as_of_date=as_of_date
        )
    )


def _make_pair_entry(
    user_id,
    entry_date: date,
    debit_id,
    credit_id,
    *,
    amount: Decimal = Decimal("100.00"),
    memo: str = "Income",
    source_id=None,
) -> JournalEntry:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        source_id=source_id,
        status=JournalEntryStatus.POSTED,
    )
    entry.lines = [
        JournalLine(account_id=debit_id, direction=Direction.DEBIT, amount=amount, currency="SGD"),
        JournalLine(account_id=credit_id, direction=Direction.CREDIT, amount=amount, currency="SGD"),
    ]
    return entry


def _package_document(
    *,
    readiness_state: str,
    blocking_count: int,
    section_label: str,
    lifecycle: PersonalReportPackageDocumentLifecycle,
    snapshot_id,
    frozen_at,
) -> PersonalReportPackageDocument:
    return PersonalReportPackageDocument.model_validate(
        {
            "schema_version": "2",
            "lifecycle": lifecycle,
            "snapshot_id": snapshot_id,
            "generated_at": datetime(2025, 12, 31, tzinfo=UTC),
            "frozen_at": frozen_at,
            "package_id": "personal-financial-report-package",
            "status": "draft",
            "context": {
                "framework_id": "personal_us_gaap_like",
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "as_of_date": "2025-12-31",
                "currency": "SGD",
            },
            "contract": _package_contract_fixture(PersonalReportingFrameworkId.US_GAAP_LIKE),
            "readiness": {
                "package_id": "personal-financial-report-package",
                "state": readiness_state,
                "label": readiness_state.title(),
                "action_href": "/reports?tab=package",
                "blocking_count": blocking_count,
                "blockers": [],
                "input_coverage": {
                    "manifest_decision_count": 1,
                    "authoritative_input_count": 1,
                    "unproven_input_count": 0,
                },
            },
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
                    "proof_state": "proven",
                    "proof_reasons": [],
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
                "traceability_appendix": {
                    "section_id": "traceability_appendix",
                    "label": "Traceability Appendix",
                    "status": "ready",
                    "lines": [
                        {
                            "line_id": "balance_sheet.total_assets",
                            "section_id": "balance_sheet",
                            "label": section_label,
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
                            "ledger_anchor": {"state": "not_applicable", "entry_statuses": [], "identifiers": []},
                            "anchor_count": 1,
                            "blocker_codes": [],
                        },
                    ],
                    "completeness_warnings": [],
                },
            },
        }
    )


def test_AC5_9_AC5_11_AC5_12_package_contract_and_notes():
    payload = _package_contract_fixture().model_dump(mode="json")
    sections = {s["section_id"]: s for s in payload["sections"]}
    assert (payload["package_id"], payload["version"]) == ("personal-financial-report-package", "1.0") and list(
        sections
    ) == [
        "balance_sheet",
        "income_statement",
        "cash_flow",
        "investment_performance",
        "annualized_income_long_term",
        "notes",
        "traceability_appendix",
    ]
    assert (
        sections["balance_sheet"]["label"],
        sections["balance_sheet"]["period_type"],
        sections["income_statement"]["period_type"],
        sections["cash_flow"]["period_type"],
        sections["investment_performance"]["owner_epic"],
        sections["balance_sheet"]["decimal_total_fields"],
    ) == (
        "Balance Sheet",
        "as_of",
        "period",
        "period",
        "EPIC-017",
        ["total_assets", "total_liabilities", "total_equity", "equation_delta"],
    )
    assert "annualized_total" in sections["annualized_income_long_term"]["decimal_total_fields"] and all(
        (sections[s]["status"], sections[s]["blocking_issue"]) == ("ready", None)
        for s in ("annualized_income_long_term", "notes", "traceability_appendix")
    )
    assert payload["period_semantics"] == {
        "start_date": "required for period sections",
        "end_date": "required for period sections",
        "as_of_date": "required for point-in-time sections",
        "currency": "ISO-4217 code; defaults to base currency when omitted",
        "framework_id": "selected supported personal reporting framework",
        "decimal_serialization": "string",
    }
    assert (payload["export_contract"]["formats"], payload["export_contract"]["csv_columns"]) == (
        ["json", "csv"],
        [
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
        ],
    )

    notes_payload = _package_notes_fixture().model_dump(mode="json")
    notes = {n["note_id"]: n for n in notes_payload["notes"]}
    assert (notes_payload["section_id"], notes_payload["status"]) == ("notes", "ready") and list(notes) == [
        "basis-of-preparation",
        "reporting-period-and-currency",
        "valuation-basis",
        "investment-market-data",
        "source-confidence-review",
        "restricted-asset-treatment",
    ]
    assert all(
        p in notes_payload["non_compliance_statement"]
        for p in ("not a regulated filing", "not legal advice", "not tax advice")
    ) and all(p not in notes_payload["non_compliance_statement"] for p in ("US GAAP compliant", "HKEX filing"))
    assert (
        notes["basis-of-preparation"]["owner_epic"],
        notes["valuation-basis"]["owner_epic"],
        notes["investment-market-data"]["owner_epic"],
        notes["source-confidence-review"]["owner_epic"],
        notes["basis-of-preparation"]["source_state"],
        notes["valuation-basis"]["source_state"],
    ) == ("EPIC-005", "EPIC-011", "EPIC-017", "EPIC-018", "package_contract", "manual_valuation_snapshots")


@pytest.mark.parametrize(
    ("lifecycle", "match_msg"),
    [
        (PersonalReportPackageDocumentLifecycle.PREVIEW, "not a frozen document"),
        (PersonalReportPackageDocumentLifecycle.FROZEN, "identity does not match"),
    ],
)
def test_AC5_12_2_package_snapshot_document_version_guards(lifecycle, match_msg):
    created_at = datetime(2026, 7, 19, tzinfo=UTC)
    legacy = ReportSnapshot(
        id=uuid4(),
        user_id=uuid4(),
        report_type=ReportType.PACKAGE,
        as_of_date=date(2025, 12, 31),
        start_date=date(2025, 1, 1),
        report_data={"framework_id": "personal_us_gaap_like", "currency": "sgd"},
        is_latest=True,
        created_at=created_at,
    )
    assert (package_snapshot_summary(legacy).status.value, package_snapshot_summary(legacy).currency) == (
        "legacy_unproven",
        "SGD",
    )
    frozen = lifecycle is PersonalReportPackageDocumentLifecycle.FROZEN
    legacy.report_data = _package_document(
        readiness_state="ready" if frozen else "blocked",
        blocking_count=0,
        section_label="Doc",
        lifecycle=lifecycle,
        snapshot_id=(uuid4() if frozen else None),
        frozen_at=(created_at if frozen else None),
    ).model_dump(mode="json")
    with pytest.raises(PackageDocumentVersionError, match=match_msg):
        package_snapshot_document(legacy)


@pytest.mark.parametrize(
    ("overrides", "match_msg"),
    [
        (
            {"status": "trusted", "lifecycle": "preview", "package_decision_id": str(uuid4())},
            "only a frozen package document",
        ),
        (
            {"status": "trusted", "snapshot_id": None, "package_decision_id": None},
            "requires snapshot and TraceRecord decision ids",
        ),
        (
            {"status": "draft", "lifecycle": "preview", "package_decision_id": str(uuid4())},
            "preview package cannot persist",
        ),
    ],
)
def test_AC5_12_2_package_document_lifecycle_validation(overrides, match_msg):
    frozen = _package_document(
        readiness_state="ready",
        blocking_count=0,
        section_label="Frozen",
        lifecycle=PersonalReportPackageDocumentLifecycle.FROZEN,
        snapshot_id=uuid4(),
        frozen_at=datetime(2026, 7, 19, tzinfo=UTC),
    ).model_dump(mode="json")
    with pytest.raises(ValueError, match=match_msg):
        PersonalReportPackageDocument.model_validate({**frozen, **overrides})


async def test_package_preview_routes_through_the_single_assembler_and_legacy_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _package_document(
        readiness_state="ready",
        blocking_count=0,
        section_label="Total Assets",
        lifecycle=PersonalReportPackageDocumentLifecycle.PREVIEW,
        snapshot_id=None,
        frozen_at=None,
    )
    calls: list[str] = []

    class FakeSession:
        committed = False

        async def commit(self) -> None:
            self.committed = True

        scalar = AsyncMock(
            return_value=ReportSnapshot(
                id=uuid4(),
                user_id=uuid4(),
                report_type=ReportType.PACKAGE,
                as_of_date=date(2025, 12, 31),
                start_date=date(2025, 1, 1),
                report_data={"framework_id": "personal_us_gaap_like"},
                is_latest=True,
            )
        )

    class FakeAssembler:
        async def assemble(self, *_args, **kwargs):
            assert (kwargs["currency"], kwargs["as_of_date"]) == ("SGD", date(2025, 12, 31))
            return (calls.append("assemble"), document)[1]

    session = FakeSession()
    monkeypatch.setattr("src.routers.reports.PackageAssembler", FakeAssembler)
    resp = await preview_personal_report_package(
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        as_of_date=date(2025, 12, 31),
        currency="sgd",
        include_restricted=False,
        ctx=RequestContext(session, uuid4()),
    )
    assert (
        calls,
        session.committed,
        resp,
        resp.readiness,
        [line.line_id for line in resp.sections.traceability_appendix.lines],
    ) == (
        ["assemble"],
        False,
        package_preview(document),
        document.readiness,
        [line.line_id for line in document.sections.traceability_appendix.lines],
    ) and not hasattr(resp, "input_manifest")
    with pytest.raises(ValueError, match="only a preview document"):
        package_preview(document.model_copy(update={"lifecycle": PersonalReportPackageDocumentLifecycle.FROZEN}))
    with pytest.raises(DomainError) as exc_info:
        await get_personal_report_package_snapshot(snapshot_id=uuid4(), ctx=RequestContext(session, uuid4()))
    assert exc_info.value.status_code == 400


async def _patch_package_snapshot_inputs(
    monkeypatch: pytest.MonkeyPatch, *, readiness_state: str, blocking_count: int, section_label: str = "Total Assets"
) -> None:
    class FakePackageAssembler:
        assemble = AsyncMock(
            side_effect=lambda *_a, **kw: _package_document(
                readiness_state=readiness_state,
                blocking_count=blocking_count,
                section_label=section_label,
                lifecycle=kw["lifecycle"],
                snapshot_id=kw["snapshot_id"],
                frozen_at=kw["frozen_at"],
            )
        )

    monkeypatch.setattr("src.routers.reports.PackageAssembler", FakePackageAssembler)


async def _install_trace_anchored_package_fixture(
    db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch, *, fault_after_trace_flush: bool = False
) -> UUID:
    asset, income = (
        await AccountFactory.create_async(db, user_id=test_user.id, name="Anchored cash", type=AccountType.ASSET),
        await AccountFactory.create_async(db, user_id=test_user.id, name="Anchored income", type=AccountType.INCOME),
    )
    entry = await submit_system_journal_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2025, 6, 30),
        memo="Package authority",
        lines_data=[
            {"account_id": asset.id, "direction": Direction.DEBIT, "amount": Decimal("100.00"), "currency": "SGD"},
            {"account_id": income.id, "direction": Direction.CREDIT, "amount": Decimal("100.00"), "currency": "SGD"},
        ],
        base_currency="SGD",
        operation=f"pkg-{uuid4().hex[:8]}",
    )
    await db.commit()
    disp_txn = await AtomicTransactionFactory.create_async(
        db,
        user_id=test_user.id,
        txn_date=date(2025, 6, 30),
        description="Package trace",
        amount=Decimal("1.00"),
        direction=TransactionDirection.IN,
        source_documents=[],
    )
    await anchored_reviewed_posting_inputs(db, user_id=test_user.id, transaction=disp_txn, intent=EconomicIntent.INCOME)
    fixture = _package_document(
        readiness_state="blocked",
        blocking_count=1,
        section_label="Anchored",
        lifecycle=PersonalReportPackageDocumentLifecycle.PREVIEW,
        snapshot_id=None,
        frozen_at=None,
    )
    (
        fixture.sections.balance_sheet.net_income,
        fixture.sections.balance_sheet.total_equity,
        fixture.sections.income_statement.total_income,
        fixture.sections.income_statement.total_expenses,
        fixture.sections.income_statement.net_income,
    ) = Decimal("100.00"), Decimal("0.00"), Decimal("100.00"), Decimal("0.00"), Decimal("100.00")
    ed = await db.get(TraceRecordRow, entry.decision_anchor_id)
    (
        fixture.sections.traceability_appendix.lines[0].ledger_anchor.identifiers,
        fixture.sections.traceability_appendix.lines[0].ledger_anchor.details,
    ) = (
        [f"journal_entry:{entry.id}"],
        [
            {
                "identifier": f"journal_entry:{entry.id}",
                "review_state": "current_authoritative_decision",
                "decision_id": str(entry.decision_anchor_id),
            }
        ],
    )
    orig_contrib = PackageAssembler._contributions

    class FaultEmitter(TraceEmitter):
        async def emit_many(self, records):
            await super().emit_many(records)
            raise RuntimeError("fault_after_package_trace_flush")

    monkeypatch.setattr("src.routers.reports.PackageAssembler", PackageAssembler)
    monkeypatch.setattr(
        "src.reporting.extension.package_document.derive_user_framework_policy_result",
        AsyncMock(return_value=fixture.framework_policy),
    )
    monkeypatch.setattr(PackageAssembler, "_sections", AsyncMock(return_value=fixture.sections))

    async def fixture_contributions(assembler, *args, **kwargs):
        return (
            *(await orig_contrib(assembler, *args, **kwargs)),
            PackageSectionContribution(
                contribution_type="statement_source",
                section_ids=("balance_sheet", "cash_flow", "traceability_appendix"),
                payload=SimpleNamespace(
                    statement_id=uuid4(),
                    source_result=SimpleNamespace(source_type=StatementSourceType.BANK, statement_currency="SGD"),
                    account_id=asset.id,
                ),
                state="authoritative",
                decision=TraceDecisionRef(
                    decision_id=entry.decision_anchor_id,
                    target=VersionedTraceRef(ed.target_kind, ed.target_id, ed.target_version),
                    assertion=VersionedTraceRef(ed.assertion_kind, ed.assertion_id, ed.assertion_version),
                ),
                input_refs=(f"account:{asset.id}", f"journal_entry:{entry.id}"),
                reason_code=None,
            ),
        )

    monkeypatch.setattr(PackageAssembler, "_contributions", fixture_contributions)
    monkeypatch.setattr(
        "src.reporting.extension.package_document.TraceEmitter", FaultEmitter
    ) if fault_after_trace_flush else None
    return disp_txn.id


async def test_AC5_19_1_package_generate_creates_draft_or_trusted_snapshot(
    db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
):
    await _patch_package_snapshot_inputs(monkeypatch, readiness_state="blocked", blocking_count=1)
    draft = await generate_personal_report_package_snapshot(RequestContext(db, test_user.id), request=_PKG_REQ)
    assert (
        draft.status,
        draft.framework_id,
        draft.currency,
        draft.readiness_state,
        draft.document.lifecycle,
        draft.document.readiness.state,
        draft.document.readiness.input_coverage.manifest_decision_count,
        draft.document.sections.traceability_appendix.section_id,
        draft.document.sections.balance_sheet.total_assets,
    ) == (
        "draft",
        PersonalReportingFrameworkId.US_GAAP_LIKE,
        "SGD",
        "blocked",
        PersonalReportPackageDocumentLifecycle.FROZEN,
        "blocked",
        1,
        "traceability_appendix",
        Decimal("100.00"),
    )
    await _install_trace_anchored_package_fixture(db, test_user, monkeypatch)
    trusted = await generate_personal_report_package_snapshot(RequestContext(db, test_user.id), request=_PKG_REQ)
    latest = (
        (
            await db.execute(
                select(ReportSnapshot).where(
                    ReportSnapshot.user_id == test_user.id,
                    ReportSnapshot.report_type == ReportType.PACKAGE,
                    ReportSnapshot.is_latest.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    assert (trusted.status, trusted.readiness_state, len(trusted.document.input_manifest), [r.id for r in latest]) == (
        "trusted",
        "ready",
        1,
        [trusted.id],
    ) and trusted.document.package_decision_id is not None


async def test_AC_extraction_disposition_7_frozen_package_persists_trace_bound_policy_snapshot(
    db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    monkeypatch.setattr(settings, "git_commit_sha", "a" * 40)
    disp_txn_id = await _install_trace_anchored_package_fixture(db, test_user, monkeypatch)
    snapshot = await generate_personal_report_package_snapshot(RequestContext(db, test_user.id), request=_PKG_REQ)
    policy = snapshot.document.statement_disposition_policy
    trace = (
        await db.execute(
            select(TraceRecordRow).where(
                TraceRecordRow.assertion_kind == "economic_intent", TraceRecordRow.target_id == str(disp_txn_id)
            )
        )
    ).scalar_one()
    note = next(n for n in snapshot.document.sections.notes.notes if n.note_id == "statement-disposition-policy")
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
    assert (
        trace.assertion_version
        == f"v{policy.schema_version}|{policy.policy_version}|{policy.mode}|machine:{policy.machine_confidence_threshold}|pnl:{policy.pnl_effect_confidence_threshold}|unknown:{policy.unknown_intent_outcome}|ambiguous:{policy.ambiguous_intent_outcome}|llm:{int(policy.live_llm_proposals_enabled)}|git:{policy.deployment_git_sha}"
    )
    assert note.source_state == "frozen_runtime_policy_snapshot" and all(
        s in note.disclosure
        for s in ("disposition-v1", "Machine authority threshold is 0.85", "P&L authority threshold is 0.85", "a" * 40)
    )
    monkeypatch.setattr(settings, "git_commit_sha", "b" * 40)
    reopened = await get_personal_report_package_snapshot(snapshot_id=snapshot.id, ctx=RequestContext(db, test_user.id))
    assert (
        reopened.document.statement_disposition_policy == policy
        and next(
            n for n in reopened.document.sections.notes.notes if n.note_id == "statement-disposition-policy"
        ).disclosure
        == note.disclosure
    )


async def test_AC_reporting_package_document_5_trace_and_snapshot_rollback_together(
    db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
):
    await _install_trace_anchored_package_fixture(db, test_user, monkeypatch, fault_after_trace_flush=True)
    user_id = test_user.id
    with pytest.raises(RuntimeError, match="fault_after_package_trace_flush"):
        await generate_personal_report_package_snapshot(RequestContext(db, user_id), request=_PKG_REQ)
    q = select(func.count(TraceRecordRow.id)).where(
        TraceRecordRow.scope_id == str(user_id), TraceRecordRow.target_kind == "personal_report_package"
    )
    assert await db.scalar(q) > 0
    await db.rollback()
    assert (
        await db.scalar(q) == 0
        and await db.scalar(
            select(func.count(ReportSnapshot.id)).where(
                ReportSnapshot.user_id == user_id, ReportSnapshot.report_type == ReportType.PACKAGE
            )
        )
        == 0
    )


async def test_AC5_19_2_and_export_snapshot_user_scoped_and_immutable(
    db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
):
    await _patch_package_snapshot_inputs(
        monkeypatch, readiness_state="ready", blocking_count=0, section_label="Frozen CSV"
    )
    snapshot = await generate_personal_report_package_snapshot(RequestContext(db, test_user.id), request=_PKG_REQ)
    other_id = (await UserFactory.create_async(db)).id
    db.add(
        ReportSnapshot(
            user_id=other_id,
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
    listed = await list_personal_report_package_snapshots(
        RequestContext(db, test_user.id), pagination=PaginationParams()
    )
    reopened = await get_personal_report_package_snapshot(snapshot_id=snapshot.id, ctx=RequestContext(db, test_user.id))
    assert [i.id for i in listed] == [snapshot.id] and reopened.document.sections.traceability_appendix.lines[
        0
    ].label == "Frozen CSV"
    with pytest.raises(DomainError) as exc_info:
        await get_personal_report_package_snapshot(snapshot_id=snapshot.id, ctx=RequestContext(db, other_id))
    assert (exc_info.value.status_code, exc_info.value.detail) == (404, "Package snapshot not found")

    json_resp, csv_resp = (
        await export_personal_report_package_snapshot(
            snapshot_id=snapshot.id, format=PackageSnapshotExportFormat.JSON, ctx=RequestContext(db, test_user.id)
        ),
        await export_personal_report_package_snapshot(
            snapshot_id=snapshot.id, format=PackageSnapshotExportFormat.CSV, ctx=RequestContext(db, test_user.id)
        ),
    )
    json_body, csv_body = (
        "".join([c async for c in json_resp.body_iterator]),
        "".join([c async for c in csv_resp.body_iterator]),
    )
    row = next(r for r in csv.DictReader(StringIO(csv_body)) if r["line_id"] == "notes.non_compliance_statement")
    assert (
        "Frozen CSV" in json_body
        and "Live Changed" not in json_body
        and '"schema_version": "2"' in json_body
        and '"document"' in json_body
        and "personal-report-package" in json_resp.headers["content-disposition"]
    )
    assert (
        csv_body.splitlines()[0].startswith("package_id,section_id,line_id,label")
        and "Frozen CSV" in csv_body
        and "source_document:stmt-1" in csv_body
        and "Live Changed" not in csv_body
        and (row["amount"], row["currency"]) == ("", "")
    )


async def test_AC5_13_1_AC5_13_2_package_traceability_endpoints(db: AsyncSession, test_user: User):
    today = date.today()
    payload = PersonalReportPackageTraceabilityResponse.model_validate(
        await _traceability_payload(db, user_id=test_user.id, start_date=today, end_date=today, as_of_date=today)
    ).model_dump(mode="json")
    lines = {line["line_id"]: line for line in payload["lines"]}
    ta = lines["balance_sheet.total_assets"]
    assert (
        payload["section_id"],
        payload["status"],
        ta["section_id"],
        ta["source_state"],
        ta["ledger_anchor"]["entry_statuses"],
        ta["anchor_count"],
        lines["notes.non_compliance_statement"]["source_state"],
        lines["notes.non_compliance_statement"]["ledger_anchor"]["state"],
    ) == (
        "traceability_appendix",
        "ready",
        "balance_sheet",
        "posted_reconciled_journal_lines_and_manual_valuations",
        ["posted", "reconciled"],
        0,
        "package_contract",
        "not_applicable",
    )
    assert {
        "balance_sheet.total_assets",
        "income_statement.total_income",
        "cash_flow.net_cash_flow",
        "investment_performance.market_value",
        "annualized_income_long_term.restricted_fair_value_total",
    } <= set(lines) and "manual_valuation_snapshot_ids" in ta["source_anchor"]["identifier_fields"]
    assert {
        "missing_source_anchor",
        "manual_only_source",
        "stale_market_data",
        "duplicate_source_coverage",
        "overlapping_statement_period",
    } <= {w["code"] for w in payload["completeness_warnings"]}
    assert all(
        line["source_anchor"]["state"] in {"available", "not_applicable", "unavailable"}
        and line["ledger_anchor"]["state"] in {"available", "not_applicable", "unavailable"}
        and isinstance(line["blocker_codes"], list)
        for line in payload["lines"]
    )


async def test_AC5_13_5_package_traceability_returns_dynamic_current_user_identifiers(
    db: AsyncSession, test_user: User
):
    rdate, stmt_txn_id, other = date(2026, 5, 31), uuid4(), await UserFactory.create_async(db)
    bank, income, inv = [
        await AccountFactory.create_async(db, user_id=test_user.id, name=n, type=t)
        for n, t in [
            ("Trace Bank", AccountType.ASSET),
            ("Trace Salary", AccountType.INCOME),
            ("Trace Brokerage", AccountType.ASSET),
        ]
    ]
    ob, oi = [
        await AccountFactory.create_async(db, user_id=other.id, name=n, type=t)
        for n, t in [("Other Bank", AccountType.ASSET), ("Other Income", AccountType.INCOME)]
    ]
    doc = UploadedDocument(
        user_id=test_user.id,
        file_path="s3://trace/statement.csv",
        file_hash=f"trace-{uuid4().hex}",
        original_filename="trace-statement.csv",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(doc)
    await db.flush()
    db.add_all(
        [
            StatementSummary(
                user_id=test_user.id,
                account_id=bank.id,
                uploaded_document_id=doc.id,
                file_hash=doc.file_hash,
                institution="Trace Bank",
                currency="SGD",
                period_start=date(2026, 5, 1),
                period_end=rdate,
                opening_balance=Decimal("0.00"),
                closing_balance=Decimal("100.00"),
                status=BankStatementStatus.APPROVED,
                balance_validated=True,
                stage1_status=Stage1Status.APPROVED,
            ),
            AtomicTransaction(
                id=stmt_txn_id,
                user_id=test_user.id,
                txn_date=rdate,
                description="Traceable income",
                amount=Decimal("100.00"),
                direction=TransactionDirection.IN,
                currency="SGD",
                dedup_hash=uuid4().hex + uuid4().hex,
                source_documents=[{"doc_id": str(doc.id), "doc_type": DocumentType.BANK_STATEMENT.value}],
            ),
            entry := _make_pair_entry(
                test_user.id, rdate, bank.id, income.id, source_id=stmt_txn_id, memo="Traceable income"
            ),
            other_entry := _make_pair_entry(other.id, rdate, ob.id, oi.id, source_id=uuid4(), memo="Other income"),
            pos := ManagedPosition(
                user_id=test_user.id,
                account_id=inv.id,
                asset_identifier="TRACE",
                quantity=Decimal("10"),
                cost_basis=Decimal("100.00"),
                currency="SGD",
                acquisition_date=date(2026, 1, 1),
                status=PositionStatus.ACTIVE,
                cost_basis_method=CostBasisMethod.FIFO,
            ),
        ]
    )
    await db.flush()
    atomic = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=rdate,
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
        as_of_date=rdate,
        value=Decimal("500000.00"),
        currency="SGD",
        source="Trace Property",
    )
    dividend = DividendIncome(
        user_id=test_user.id, position_id=pos.id, payment_date=rdate, amount=Decimal("8.25"), currency="SGD"
    )
    price = MarketDataOverride(
        user_id=test_user.id,
        asset_identifier="TRACE",
        price_date=rdate,
        price=Decimal("12.50"),
        currency="SGD",
        source=PriceSource.MANUAL,
    )
    db.add_all([atomic, manual, dividend, price])
    await db.commit()
    lines = {
        line["line_id"]: line
        for line in PersonalReportPackageTraceabilityResponse.model_validate(
            await _traceability_payload(
                db, user_id=test_user.id, start_date=date(2026, 5, 1), end_date=rdate, as_of_date=rdate
            )
        ).model_dump(mode="json")["lines"]
    }
    ta, inv_line = lines["balance_sheet.total_assets"], lines["investment_performance.market_value"]
    assert (
        f"pricing_observation:{manual.id}" in ta["source_anchor"]["identifiers"]
        and f"atomic_transaction:{stmt_txn_id}" not in ta["source_anchor"]["identifiers"]
    )
    assert any(
        d["source_kind"] == "pricing_valuation_observation"
        and d["source_id"] == str(manual.id)
        and d["amount"] == "500000.00"
        and d["currency"] == "SGD"
        and d["review_state"] == "unproven"
        and d["reason_code"] == "missing_observation_decision"
        for d in ta["source_anchor"]["details"]
    )
    assert any(
        d["journal_entry_id"] == str(entry.id)
        and d["source_kind"] == "journal_line"
        and d["review_state"] == "unproven"
        for d in ta["ledger_anchor"]["details"]
    )
    assert inv_line["source_anchor"]["identifiers"] == [] and all(
        f"{p}:{oid}" not in inv_line["source_anchor"]["identifiers"]
        for p, oid in (("atomic_position", atomic.id), ("dividend_income", dividend.id), ("market_price", price.id))
    )
    assert not any(
        str(other_entry.id) in ident
        for line in lines.values()
        for k in ("source_anchor", "ledger_anchor")
        for ident in line[k]["identifiers"]
    )


async def test_AC11_9_10_package_traceability_surfaces_manual_valuation_basis(db: AsyncSession, test_user: User):
    rdate = date(2026, 5, 31)
    with_b = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of_date=rdate,
        value=Decimal("500000.00"),
        currency="SGD",
        source="Appraised Property",
        valuation_basis=ManualValuationBasis.MARKET_APPRAISAL,
    )
    without_b = ManualValuationSnapshot(
        user_id=test_user.id,
        component_type=ManualValuationComponentType.LONG_TERM_SAVINGS,
        liquidity_class=ManualValuationLiquidityClass.ILLIQUID,
        as_of_date=rdate,
        value=Decimal("12000.00"),
        currency="SGD",
        source="Legacy Savings",
        valuation_basis=None,
    )
    db.add_all([with_b, without_b])
    await db.commit()
    lines = {
        line["line_id"]: line
        for line in PersonalReportPackageTraceabilityResponse.model_validate(
            await _traceability_payload(
                db, user_id=test_user.id, start_date=date(2026, 5, 1), end_date=rdate, as_of_date=rdate
            )
        ).model_dump(mode="json")["lines"]
    }
    details = {
        d["source_id"]: d
        for d in lines["balance_sheet.total_assets"]["source_anchor"]["details"]
        if d["source_kind"] == "pricing_valuation_observation"
    }
    assert (details[str(with_b.id)]["valuation_basis"], details[str(without_b.id)]["valuation_basis"]) == (
        "market_appraisal",
        "unspecified",
    )


@pytest.mark.parametrize(
    ("account_type", "direction", "line_id", "dedup"),
    [
        (AccountType.INCOME, Direction.CREDIT, "income_statement.total_income", False),
        (AccountType.ASSET, Direction.DEBIT, "balance_sheet.total_assets", True),
    ],
)
async def test_AC19_10_1_traceability_renders_only_ledger_owned_source_membership(
    account_type, direction, line_id, dedup
):
    jl = JournalLineContribution(
        line_id=uuid4(),
        account_id=uuid4(),
        account_type=account_type,
        direction=direction,
        amount=Decimal("42.00"),
        currency="SGD",
    )
    j = ResolvedJournalContribution(
        entry_id=uuid4(),
        entry_date=date(2026, 5, 31),
        lines=(jl,),
        state="unproven",
        reason_code="missing_current_decision_anchor",
        decision=None,
    )
    contrib = PackageSectionContribution(
        contribution_type="ledger_command",
        section_ids=("balance_sheet", "income_statement", "traceability_appendix"),
        payload=j,
        state=j.state,
        decision=j.decision,
        input_refs=j.input_refs,
        reason_code=j.reason_code,
    )
    target = {
        line["line_id"]: line
        for line in (
            await build_personal_report_package_traceability_payload(
                contributions=(contrib, contrib) if dedup else (contrib,)
            )
        )["lines"]
    }[line_id]
    assert (
        target["source_anchor"].get("identifiers", []) == []
        and target["ledger_anchor"]["identifiers"] == [f"journal_line:{jl.line_id}"]
        and len(target["ledger_anchor"]["details"]) == 1
        and "unproven_package_input" in target["blocker_codes"]
    )
    assert (
        target["ledger_anchor"]["details"][0]["source_type"],
        target["ledger_anchor"]["details"][0]["review_state"],
    ) == ("decision_anchored_journal", "unproven")


async def test_AC18_8_4_AC18_8_7_and_AC19_10_1_ledger_decision_boundary(db: AsyncSession, test_user: User):
    rdate, unk_id = date(2026, 5, 31), uuid4()
    bank, income = (
        await AccountFactory.create_async(db, user_id=test_user.id, name="Evidence Trace Bank", type=AccountType.ASSET),
        await AccountFactory.create_async(db, user_id=test_user.id, name="Unknown Income", type=AccountType.INCOME),
    )
    stmt = StatementSummary(
        user_id=test_user.id,
        account_id=bank.id,
        file_hash=f"evidence-trace-{uuid4().hex}",
        institution="Trace Bank",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=rdate,
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("120.00"),
        status=BankStatementStatus.APPROVED,
        balance_validated=True,
        stage1_status=Stage1Status.APPROVED,
    )
    txn = ExtractedTransactionRow(
        user_id=test_user.id,
        txn_date=rdate,
        description="Evidence graph income",
        amount=Decimal("120.00"),
        direction="IN",
        currency="SGD",
        reference="EG-INC",
        currency_unresolved=False,
        balance_after=None,
        occurrence_index=0,
        dedup_hash=DeduplicationService.calculate_transaction_hash(
            test_user.id, rdate, Decimal("120.00"), TransactionDirection.IN, "Evidence graph income", "EG-INC"
        ),
    )
    await dual_write_layer2(
        db=db,
        user_id=test_user.id,
        statement=stmt,
        transactions=[txn],
        original_filename="evidence-statement.csv",
        document_type=DocumentType.BANK_STATEMENT,
    )
    await db.flush()
    atomic_txn = (
        await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id))
    ).scalar_one()
    decision, counter, source_dec, emitter = await anchored_reviewed_posting_inputs(
        db, user_id=test_user.id, transaction=atomic_txn, intent=EconomicIntent.INCOME
    )
    entry = await create_entry_from_txn(
        db,
        atomic_txn,
        user_id=test_user.id,
        auto_post=True,
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        preloaded_statement=stmt,
        preloaded_bank_account=bank,
        disposition=decision,
        counter_account=counter,
        source_decision=source_dec,
        trace_emitter=emitter,
        base_currency="SGD",
    )
    unk_entry = _make_pair_entry(
        test_user.id, rdate, bank.id, income.id, amount=Decimal("88.00"), source_id=unk_id, memo="Unsupported source"
    )
    db.add(unk_entry)
    await db.flush()
    await db.refresh(entry, ["lines"])
    await EvidenceGraphIntegrationService().record_journal_posting(
        db, user_id=test_user.id, atomic_transaction=atomic_txn, journal_entry=entry
    )
    await db.commit()
    doc = (await db.execute(select(UploadedDocument).where(UploadedDocument.user_id == test_user.id))).scalar_one()
    ti = {
        line["line_id"]: line
        for line in PersonalReportPackageTraceabilityResponse.model_validate(
            await _traceability_payload(
                db, user_id=test_user.id, start_date=date(2026, 5, 1), end_date=rdate, as_of_date=rdate
            )
        ).model_dump(mode="json")["lines"]
    }["income_statement.total_income"]
    assert (
        all(
            p not in ti["source_anchor"]["identifiers"]
            for p in (
                f"uploaded_document:{doc.id}",
                f"atomic_transaction:{atomic_txn.id}",
                f"statement_transaction:{unk_id}",
            )
        )
        and ti["source_anchor"].get("identifiers", []) == []
        and "unproven_package_input" in ti["blocker_codes"]
    )
    assert any(d["journal_entry_id"] == str(entry.id) for d in ti["ledger_anchor"]["details"]) and any(
        d["source_kind"] == "journal_line"
        and d["journal_entry_id"] == str(unk_entry.id)
        and d["amount"] == "88.00"
        and d["reason_code"] == "missing_current_decision_anchor"
        for d in ti["ledger_anchor"]["details"]
    )
