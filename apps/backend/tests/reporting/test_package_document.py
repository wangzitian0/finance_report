"""Structural contract tests for the sole personal-report package document."""

from __future__ import annotations

import ast
import copy
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.audit import (
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceDecisionRef,
    TraceRecord,
    TraceRecordValidationError,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.extraction import StatementSourceType
from src.reporting import personal_report_package_decision_ref, personal_report_package_target
from src.reporting.base.package_contribution import PackageCashInputs, PackageSectionContribution
from src.reporting.base.package_decision import PackageReadinessDecisionPolicy
from src.reporting.extension.package_document import (
    PackageAssembler,
    _cash_inputs_from_contributions,
    _package_document_summary,
    _policy_blockers,
    _section_invariant_blockers,
    _valuation_section_contribution,
)
from src.schemas.reporting import (
    PersonalReportPackageDocument,
    PersonalReportPackageDocumentLifecycle,
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

    sections.balance_sheet.opening_balance_warnings = [{}]
    sections.balance_sheet.portfolio_warnings = [{}]
    sections.investment_performance.data_freshness.stale = True
    sections.investment_performance.as_of_date = period_start
    warning_blockers = _section_invariant_blockers(
        sections,
        start_date=period_start,
        end_date=period_end,
        as_of_date=period_end,
        currency="SGD",
        contributions=(),
        cash_inputs=PackageCashInputs.missing(),
    )
    assert {
        "investment_market_data_stale",
        "opening_balance_missing",
        "portfolio_value_incomplete",
        "section_period_mismatch",
    } <= {blocker.code for blocker in warning_blockers}


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


def test_package_contribution_envelopes_reject_incomplete_authority_contracts() -> None:
    with pytest.raises(ValueError, match="at least one account"):
        PackageCashInputs(account_ids=frozenset(), input_refs=())
    with pytest.raises(ValueError, match="cannot be blank"):
        PackageCashInputs.missing().__class__(
            account_ids=frozenset(),
            input_refs=("",),
            reason_code="cash_balance_input_missing",
        )

    decision = TraceDecisionRef(
        decision_id=uuid4(),
        target=VersionedTraceRef("journal_command", "entry-1", "1"),
        assertion=VersionedTraceRef("ledger_authority", "posted", "1"),
    )
    invalid_states = (
        {"section_ids": (), "state": "unproven", "decision": None, "reason_code": "missing"},
        {
            "section_ids": ("balance_sheet",),
            "state": "unproven",
            "decision": None,
            "reason_code": "missing",
            "input_refs": (),
        },
        {"section_ids": ("balance_sheet",), "state": "authoritative", "decision": None, "reason_code": None},
        {"section_ids": ("balance_sheet",), "state": "unproven", "decision": None, "reason_code": None},
        {"section_ids": ("balance_sheet",), "state": "unproven", "decision": decision, "reason_code": "missing"},
    )
    for state in invalid_states:
        with pytest.raises(ValueError):
            PackageSectionContribution(
                contribution_type="ledger_command",
                payload=object(),
                input_refs=state.pop("input_refs", ("journal_entry:entry-1",)),
                **state,
            )


def test_package_document_helpers_fail_closed_without_reconstructing_authority() -> None:
    with pytest.raises(ValueError, match="missing durable identity metadata"):
        _package_document_summary(
            SimpleNamespace(
                lifecycle=PersonalReportPackageDocumentLifecycle.FROZEN,
                snapshot_id=None,
                frozen_at=None,
            )
        )

    valuation = _valuation_section_contribution(
        SimpleNamespace(
            input_refs=(),
            lineage_id=None,
            subject=SimpleNamespace(kind=SimpleNamespace(value="security"), key="ACME"),
            state="unproven",
            decision=None,
            reason_code="missing_current_decision_anchor",
        )
    )
    assert valuation.input_refs == ("valuation:security:ACME",)

    unproven_bank = PackageSectionContribution(
        contribution_type="statement_source",
        section_ids=("balance_sheet",),
        payload=SimpleNamespace(
            source_result=SimpleNamespace(source_type=StatementSourceType.BANK),
            account_id=None,
        ),
        state="unproven",
        decision=None,
        input_refs=("statement:bank-1",),
        reason_code="missing_current_decision_anchor",
    )
    cash_inputs = _cash_inputs_from_contributions((unproven_bank,))
    assert cash_inputs.reason_code == "cash_balance_input_unproven"
    assert cash_inputs.input_refs == ("statement:bank-1",)

    blockers = _policy_blockers(
        SimpleNamespace(
            gaps=[
                SimpleNamespace(blocker=True, code="unsupported_policy_domain"),
                SimpleNamespace(blocker=False, code="non_blocking_gap"),
            ]
        )
    )
    assert [(blocker.code, blocker.count) for blocker in blockers] == [("unsupported_policy_domain", 1)]


@pytest.mark.asyncio
async def test_AC_reporting_package_document_9_requires_exact_decision_coordinates() -> None:
    """AC-reporting.package-document.9: an opaque current id cannot authorize the wrong fact."""
    expected_target = VersionedTraceRef("journal_command", "expected", "v1")
    expected_assertion = VersionedTraceRef("ledger_authority", "expected", "v1")
    wrong_target = VersionedTraceRef("journal_command", "other", "v1")
    wrong_assertion = VersionedTraceRef("ledger_authority", "other", "v1")
    exact_id, target_mismatch_id, assertion_mismatch_id, cross_scope_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )

    with pytest.raises(TraceRecordValidationError, match="decision id must be a UUID"):
        TraceDecisionRef(decision_id="not-a-uuid", target=expected_target, assertion=expected_assertion)
    with pytest.raises(TraceRecordValidationError, match="decision target must be a VersionedTraceRef"):
        TraceDecisionRef(decision_id=uuid4(), target="not-a-ref", assertion=expected_assertion)
    with pytest.raises(TraceRecordValidationError, match="decision assertion must be a VersionedTraceRef"):
        TraceDecisionRef(decision_id=uuid4(), target=expected_target, assertion="not-a-ref")

    class _Rows:
        def mappings(self):
            return iter(
                (
                    {
                        "decision_id": exact_id,
                        "target_kind": expected_target.kind,
                        "target_id": expected_target.id,
                        "target_version": expected_target.version,
                        "assertion_kind": expected_assertion.kind,
                        "assertion_id": expected_assertion.id,
                        "assertion_version": expected_assertion.version,
                        "authority_tier": "CODE-ONLY",
                    },
                    {
                        "decision_id": target_mismatch_id,
                        "target_kind": wrong_target.kind,
                        "target_id": wrong_target.id,
                        "target_version": wrong_target.version,
                        "assertion_kind": expected_assertion.kind,
                        "assertion_id": expected_assertion.id,
                        "assertion_version": expected_assertion.version,
                        "authority_tier": "CODE-ONLY",
                    },
                    {
                        "decision_id": assertion_mismatch_id,
                        "target_kind": expected_target.kind,
                        "target_id": expected_target.id,
                        "target_version": expected_target.version,
                        "assertion_kind": wrong_assertion.kind,
                        "assertion_id": wrong_assertion.id,
                        "assertion_version": wrong_assertion.version,
                        "authority_tier": "CODE-ONLY",
                    },
                )
            )

    class _Session:
        async def execute(self, _query):
            return _Rows()

    def contribution(decision_id, input_ref):
        return PackageSectionContribution(
            contribution_type="ledger_command",
            section_ids=("balance_sheet",),
            payload=object(),
            state="authoritative",
            decision=TraceDecisionRef(
                decision_id=decision_id,
                target=expected_target,
                assertion=expected_assertion,
            ),
            input_refs=(input_ref,),
            reason_code=None,
        )

    manifest, unproven = await PackageAssembler()._input_manifest(
        _Session(),
        user_id=uuid4(),
        contributions=(
            contribution(exact_id, "journal_entry:exact"),
            contribution(target_mismatch_id, "journal_entry:wrong-target"),
            contribution(assertion_mismatch_id, "journal_entry:wrong-assertion"),
            contribution(cross_scope_id, "journal_entry:cross-scope"),
        ),
    )

    assert [item.decision_id for item in manifest] == [exact_id]
    assert unproven == [
        "journal_entry:cross-scope",
        "journal_entry:wrong-assertion",
        "journal_entry:wrong-target",
    ]


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
    current_docs = (
        "common/reporting/readme.md",
        "common/reporting/framework-reporting.md",
        "common/workflow/workflow-events.md",
        "common/pricing/readme.md",
        "docs/user-guide/reports.md",
    )
    retired_package_routes = (
        "/api/reports/package/contract",
        "/api/reports/package/readiness",
        "/api/reports/package/framework-policy",
        "/api/reports/package/annualized-income-schedule",
        "/api/reports/package/notes",
        "/api/reports/package/traceability",
    )
    for relative_path in current_docs:
        source = (REPOSITORY_ROOT / relative_path).read_text()
        for retired_route in retired_package_routes:
            assert retired_route not in source, (relative_path, retired_route)
    anonymizer = (REPOSITORY_ROOT / "apps/backend/src/runtime/extension/snapshot_anonymizer.py").read_text()
    assert "confidence_metric_snapshots" not in anonymizer


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


class _JsonValue:
    def __init__(self, value):
        self.value = value

    def model_dump(self, *, mode):
        assert mode == "json"
        return copy.deepcopy(self.value)


def test_AC_reporting_package_document_10_reconstructs_exact_decision_coordinates() -> None:
    """AC-reporting.package-document.10: one owner function binds frozen semantics."""
    snapshot_id = UUID("10000000-0000-0000-0000-000000000001")
    decision_id = UUID("20000000-0000-0000-0000-000000000002")
    semantics = {
        "context": {
            "framework_id": "personal_financial_reporting",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "as_of_date": "2026-12-31",
            "currency": "SGD",
        },
        "framework_policy": {"result_id": "policy-1", "gaps": []},
        "statement_disposition_policy": {"policy_version": "2026-07-19"},
        "input_manifest": [{"decision_id": str(decision_id), "input_refs": ["statement:1"]}],
        "sections": {"balance_sheet": {"total_assets": "125.00"}},
    }

    target = personal_report_package_target(snapshot_id=snapshot_id, **semantics)
    assert target == VersionedTraceRef(
        kind="personal_report_package",
        id=str(snapshot_id),
        version="9d136a722c6fee121996a72b47f70e46633ea8828c57d96899a96f56f56ec5ae",
    )

    document = SimpleNamespace(
        schema_version="2",
        lifecycle=PersonalReportPackageDocumentLifecycle.FROZEN,
        snapshot_id=snapshot_id,
        package_decision_id=decision_id,
        context=_JsonValue(semantics["context"]),
        framework_policy=_JsonValue(semantics["framework_policy"]),
        statement_disposition_policy=_JsonValue(semantics["statement_disposition_policy"]),
        input_manifest=[_JsonValue(item) for item in semantics["input_manifest"]],
        sections=_JsonValue(semantics["sections"]),
    )
    decision_ref = personal_report_package_decision_ref(document)
    assert decision_ref == TraceDecisionRef(
        decision_id=decision_id,
        target=target,
        assertion=PackageReadinessDecisionPolicy().assertion,
    )

    def changed_document(**updates):
        return SimpleNamespace(**(vars(document) | updates))

    with pytest.raises(ValueError, match="schema version"):
        personal_report_package_decision_ref(changed_document(schema_version="1"))
    with pytest.raises(ValueError, match="frozen document"):
        personal_report_package_decision_ref(changed_document(lifecycle=PersonalReportPackageDocumentLifecycle.PREVIEW))
    with pytest.raises(ValueError, match="snapshot and decision ids"):
        personal_report_package_decision_ref(changed_document(package_decision_id=None))

    for field in semantics:
        changed = copy.deepcopy(semantics)
        value = changed[field]
        if isinstance(value, list):
            value.append({"decision_id": str(uuid4()), "input_refs": ["statement:changed"]})
        else:
            value["counterfactual"] = field
        assert personal_report_package_target(snapshot_id=snapshot_id, **changed) != target, field
    assert personal_report_package_target(snapshot_id=uuid4(), **semantics) != target

    assembler_source = (REPOSITORY_ROOT / "apps/backend/src/reporting/extension/package_document.py").read_text()
    assert "personal_report_package_target(" in assembler_source
    assert "semantic_payload =" not in assembler_source
