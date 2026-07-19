"""Structural contract tests for the sole personal-report package document."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.audit import (
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.reporting.base.package_contribution import PackageCashInputs
from src.reporting.base.package_decision import PackageReadinessDecisionPolicy
from src.reporting.extension.package_document import PackageAssembler, _section_invariant_blockers
from src.schemas.reporting import (
    PersonalReportPackageDocument,
    PersonalReportPackageInputCoverage,
    PersonalReportPackageReadinessState,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


class _InputPolicy:
    assertion = VersionedTraceRef("ledger_authority", "fixture", "1")
    authority = TraceAuthorityProfile(
        package="ledger",
        tier="CODE-ONLY",
        proof_kind="exact",
        provenance="deterministic",
        execution_stage="product.runtime",
        assertion_owner_digest="a" * 64,
        producer_version="1",
    )
    causality = TraceCausality.DIRECT
    target_class = TraceTargetClass.FINANCIAL

    def fold(self, parents):
        return TraceDecisionOutcome(TraceResult.AUTHORITATIVE, "fixture_authorized")


def _observation(*, scope, target, reason_code="fixture_input"):
    return TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=VersionedTraceRef("invariant", reason_code, "1"),
        authority=_InputPolicy.authority,
        result=TraceResult.PASS,
        execution_id="package-fixture",
        evidence_manifest_digest="b" * 64,
        occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
        score=None,
        reason_code=reason_code,
    )


def test_AC_reporting_package_document_1_requires_typed_delivery_sections() -> None:
    """AC-reporting.package-document.1: the package cannot degrade to an untyped payload map."""

    schema = PersonalReportPackageDocument.model_json_schema()
    required = set(schema["required"])
    assert {
        "schema_version",
        "lifecycle",
        "status",
        "contract",
        "readiness",
        "framework_policy",
        "input_manifest",
        "sections",
    } <= required

    section_schema = schema["$defs"]["PersonalReportPackageSections"]
    assert {
        "balance_sheet",
        "income_statement",
        "cash_flow",
        "investment_performance",
        "annualized_income_long_term",
        "notes",
        "traceability_appendix",
    } <= set(section_schema["required"])
    assert section_schema["additionalProperties"] is False


def test_AC_reporting_package_document_2_has_one_assembler_and_no_live_package_export() -> None:
    """AC-reporting.package-document.2: report delivery cannot fork at the HTTP layer."""

    router_source = (REPOSITORY_ROOT / "apps/backend/src/routers/reports.py").read_text()
    assert "PackageAssembler," in router_source
    assert "async def _personal_report_package_section_payloads" not in router_source
    assert "async def _build_personal_report_package_snapshot_data" not in router_source
    assert "elif report_type == ExportReportType.PACKAGE" not in router_source
    package_init = REPOSITORY_ROOT / "apps/backend/src/reporting/__init__.py"
    assert '"get_personal_report_package_readiness"' not in package_init.read_text()
    assert not (REPOSITORY_ROOT / "apps/backend/src/reporting/extension/report_readiness.py").exists()
    assembler_source = (REPOSITORY_ROOT / "apps/backend/src/reporting/extension/package_document.py").read_text()
    for forbidden_raw_input in ("AtomicPosition", "ManualValuationSnapshot", "DividendIncome"):
        assert forbidden_raw_input not in assembler_source


def test_AC_reporting_package_document_2_fails_closed_on_unproven_inputs() -> None:
    """Direct decision coverage, not source labels, is the only trust predicate."""

    ready = PackageAssembler._readiness(
        policy=SimpleNamespace(gaps=[]),
        coverage=PersonalReportPackageInputCoverage(
            manifest_decision_count=1,
            authoritative_input_count=1,
        ),
    )
    assert ready.state is PersonalReportPackageReadinessState.READY

    draft = PackageAssembler._readiness(
        policy=SimpleNamespace(gaps=[]),
        coverage=PersonalReportPackageInputCoverage(
            manifest_decision_count=1,
            authoritative_input_count=1,
            unproven_input_count=3,
        ),
    )
    assert draft.state is PersonalReportPackageReadinessState.BLOCKED
    assert {blocker.code for blocker in draft.blockers} == {
        "unproven_package_input",
    }


def test_AC_reporting_package_document_3_trust_is_one_trace_decision_fold() -> None:
    """AC-reporting.package-document.3: package trust is a TraceRecord decision."""
    scope = TraceScope.tenant(uuid4())
    input_target = VersionedTraceRef("journal_command", "entry-1", "1")
    input_observation = _observation(scope=scope, target=input_target)
    input_decision = TraceRecord.decision(
        scope=scope,
        target=input_target,
        policy=_InputPolicy(),
        execution_id=input_observation.execution_id,
        occurred_at=input_observation.occurred_at,
        parents=(input_observation,),
    )
    package_target = VersionedTraceRef("personal_report_package", "snapshot-1", "c" * 64)
    section_observation = _observation(
        scope=scope,
        target=package_target,
        reason_code="package_sections_valid",
    )
    decision = TraceRecord.decision(
        scope=scope,
        target=package_target,
        policy=PackageReadinessDecisionPolicy(),
        execution_id="package-fixture",
        occurred_at=section_observation.occurred_at,
        parents=(section_observation, input_decision),
    )
    assert decision.result is TraceResult.AUTHORITATIVE
    assert decision.parent_ids == tuple(sorted((section_observation.record_id, input_decision.record_id), key=str))


def test_AC_reporting_package_document_3_blocks_failed_section_observations() -> None:
    """The package decision cannot label unverified accounting sections PASS."""
    period_start = datetime(2025, 1, 1).date()
    period_end = datetime(2025, 12, 31).date()
    sections = SimpleNamespace(
        balance_sheet=SimpleNamespace(
            is_balanced=False,
            equation_delta=Decimal("1.00"),
            net_income=Decimal("25.00"),
            as_of_date=period_end,
            currency="SGD",
            opening_balance_warnings=[],
            portfolio_warnings=[],
        ),
        income_statement=SimpleNamespace(
            net_income=Decimal("24.00"),
            start_date=period_start,
            end_date=period_end,
            currency="SGD",
        ),
        cash_flow=SimpleNamespace(
            start_date=period_start,
            end_date=period_end,
            currency="SGD",
            summary=SimpleNamespace(
                beginning_cash=Decimal("10.00"),
                net_cash_flow=Decimal("5.00"),
                ending_cash=Decimal("14.00"),
            ),
        ),
        investment_performance=SimpleNamespace(
            period_start=period_start,
            period_end=period_end,
            as_of_date=period_end,
            currency="SGD",
            holdings=[SimpleNamespace()],
            data_freshness=SimpleNamespace(stale=False),
        ),
        annualized_income_long_term=SimpleNamespace(
            as_of_date=period_end,
            income=SimpleNamespace(currency="USD"),
            restricted_fair_value_total_currency="USD",
        ),
    )
    blockers = _section_invariant_blockers(
        sections,
        start_date=period_start,
        end_date=period_end,
        as_of_date=period_end,
        currency="SGD",
        contributions=(SimpleNamespace(is_authoritative=True, section_ids=("balance_sheet",)),),
        cash_inputs=PackageCashInputs.missing(),
    )
    readiness = PackageAssembler._readiness(
        policy=SimpleNamespace(gaps=[]),
        coverage=PersonalReportPackageInputCoverage(
            manifest_decision_count=1,
            authoritative_input_count=1,
        ),
        section_blockers=blockers,
    )
    assert readiness.state is PersonalReportPackageReadinessState.BLOCKED
    assert {blocker.code for blocker in readiness.blockers} == {
        "balance_sheet_equation_failed",
        "cash_flow_rollforward_failed",
        "investment_contribution_missing",
        "section_currency_mismatch",
        "statement_net_income_mismatch",
        "cash_balance_input_missing",
    }
    empty_input_blockers = _section_invariant_blockers(
        sections,
        start_date=period_start,
        end_date=period_end,
        as_of_date=period_end,
        currency="SGD",
        contributions=(),
        cash_inputs=PackageCashInputs.missing(),
    )
    assert "cash_balance_input_missing" not in {blocker.code for blocker in empty_input_blockers}


def test_AC_reporting_package_document_8_missing_cash_inputs_block_trust() -> None:
    """AC-reporting.package-document.8: absence is explicit, never a lexical fallback."""
    cash_inputs = PackageCashInputs.missing()

    assert not cash_inputs.is_complete
    assert cash_inputs.account_ids == frozenset()
    assert cash_inputs.reason_code == "cash_balance_input_missing"

    with pytest.raises(ValueError, match="exact input ref"):
        PackageCashInputs(
            account_ids=frozenset({uuid4()}),
            input_refs=("statement_result:fixture",),
        )


def test_AC_reporting_package_document_5_trace_and_snapshot_rollback_together() -> None:
    """AC-reporting.package-document.5: persistence test fault-injects after trace flush."""
    source = (REPOSITORY_ROOT / "apps/backend/tests/api/test_personal_report_package_contract.py").read_text()
    assert "AC-reporting.package-document.5" in source
    assert "fault_after_package_trace_flush" in source


def test_AC_reporting_package_document_6_producer_and_consumer_closure() -> None:
    """AC-reporting.package-document.6: no shadow package producer/readiness authority."""
    production = REPOSITORY_ROOT / "apps/backend/src"
    constructors = []
    for path in production.rglob("*.py"):
        tree = ast.parse(path.read_text())
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "PersonalReportPackageDocument"
            for node in ast.walk(tree)
        ):
            constructors.append(path.relative_to(REPOSITORY_ROOT).as_posix())
    assert constructors == ["apps/backend/src/reporting/extension/package_document.py"]

    for retired in (
        "apps/backend/src/reporting/extension/report_readiness.py",
        "apps/backend/src/reporting/extension/confidence_metric.py",
    ):
        assert not (REPOSITORY_ROOT / retired).exists()

    for path in production.rglob("*.py"):
        assert "get_personal_report_package_readiness" not in path.read_text(), path
    for path in (REPOSITORY_ROOT / "apps/frontend/src").rglob("*.ts*"):
        assert "/api/reports/package/readiness" not in path.read_text(), path


def test_AC_reporting_package_document_7_manifest_folds_only_typed_contributions() -> None:
    """AC-reporting.package-document.7: document proof and display share typed inputs."""
    contribution_source = (REPOSITORY_ROOT / "apps/backend/src/reporting/base/package_contribution.py").read_text()
    assert "class PackageSectionContribution" in contribution_source

    assembler_source = (REPOSITORY_ROOT / "apps/backend/src/reporting/extension/package_document.py").read_text()
    for public_boundary in (
        "list_statement_contributions",
        "list_journal_contributions",
        "resolve_manual_valuation_contributions",
        "resolve_selected_market_valuation_contribution",
    ):
        assert public_boundary in assembler_source
    input_manifest_source = assembler_source.split("async def _input_manifest", 1)[1]
    assert "contributions:" in input_manifest_source.split(") ->", 1)[0]
    assert "traceability:" not in input_manifest_source.split(") ->", 1)[0]
    assert "for contribution in contributions" in input_manifest_source

    traceability_source = (REPOSITORY_ROOT / "apps/backend/src/reporting/extension/report_traceability.py").read_text()
    assert "contributions: tuple[PackageSectionContribution" in traceability_source
    for forbidden_raw_input in (
        "AtomicPosition",
        "ManualValuationSnapshot",
        "DividendIncome",
        "MarketDataOverride",
        "JournalEntry",
        "StatementSummary",
    ):
        assert forbidden_raw_input not in traceability_source
