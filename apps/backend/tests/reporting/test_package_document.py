from __future__ import annotations

import ast
import copy
import json
import typing
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

import src.reporting.extension.framework_report as framework_report_mod
import src.reporting.extension.income_statement as income_statement_mod
import src.reporting.extension.package_document as package_document_mod
from src.audit import (
    Money,
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
from src.config import settings
from src.extraction import StatementSourceType
from src.ledger import AccountType, Entry, post_entry
from src.reporting import personal_report_package_decision_ref, personal_report_package_target
from src.reporting.base.cash_flow_types import CashFlowBridge
from src.reporting.base.package_contribution import PackageCashInputs, PackageSectionContribution
from src.reporting.base.package_decision import PackageReadinessDecisionPolicy
from src.reporting.extension.balance_sheet import generate_balance_sheet as real_generate_balance_sheet
from src.reporting.extension.package_document import (
    PackageAssembler,
    _cash_inputs_from_contributions,
    _package_notes,
    _package_statement_disposition_policy,
    _policy_blockers,
    _section_invariant_blockers,
    _valuation_section_contribution,
    current_package_readiness,
)
from src.reporting.extension.report_traceability import (
    build_personal_report_package_traceability_payload as real_build_traceability,
)
from src.schemas.reporting import (
    BalanceSheetResponse,
    PersonalReportPackageDocument,
    PersonalReportPackageDocumentLifecycle,
    PersonalReportPackageInputCoverage,
    PersonalReportPackageReadinessState,
)
from tests.reporting._report_fixtures import seed_accounts

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


def _obs(*, scope, target, reason_code: str = "fixture_input"):
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


def test_AC_reporting_package_document_1_2_6_7_contract_and_closure() -> None:
    schema = PersonalReportPackageDocument.model_json_schema()
    assert {
        "schema_version",
        "lifecycle",
        "status",
        "contract",
        "readiness",
        "framework_policy",
        "input_manifest",
        "sections",
    } <= set(schema["required"])
    sec_schema = schema["$defs"]["PersonalReportPackageSections"]
    assert {
        "balance_sheet",
        "income_statement",
        "cash_flow",
        "investment_performance",
        "annualized_income_long_term",
        "notes",
        "traceability_appendix",
    } <= set(sec_schema["required"]) and sec_schema["additionalProperties"] is False

    ready = PackageAssembler._readiness(
        policy=SimpleNamespace(gaps=[]),
        coverage=PersonalReportPackageInputCoverage(manifest_decision_count=1, authoritative_input_count=1),
    )
    draft = PackageAssembler._readiness(
        policy=SimpleNamespace(gaps=[]),
        coverage=PersonalReportPackageInputCoverage(
            manifest_decision_count=1, authoritative_input_count=1, unproven_input_count=3
        ),
    )
    assert (
        ready.state is PersonalReportPackageReadinessState.READY
        and draft.state is PersonalReportPackageReadinessState.BLOCKED
    )
    assert {b.code for b in draft.blockers} == {"unproven_package_input"}

    router_src = (REPOSITORY_ROOT / "apps/backend/src/routers/reports.py").read_text()
    asm_src = (REPOSITORY_ROOT / "apps/backend/src/reporting/extension/package_document.py").read_text()
    trace_src = (REPOSITORY_ROOT / "apps/backend/src/reporting/extension/report_traceability.py").read_text()
    assert "PackageAssembler," in router_src and all(
        s not in router_src
        for s in (
            "async def _personal_report_package_section_payloads",
            "async def _build_personal_report_package_snapshot_data",
            "elif report_type == ExportReportType.PACKAGE",
        )
    )
    assert (
        '"get_personal_report_package_readiness"'
        not in (REPOSITORY_ROOT / "apps/backend/src/reporting/__init__.py").read_text()
    )
    assert all(raw not in asm_src for raw in ("AtomicPosition", "ManualValuationSnapshot", "DividendIncome"))
    assert (
        "class PackageSectionContribution"
        in (REPOSITORY_ROOT / "apps/backend/src/reporting/base/package_contribution.py").read_text()
    )
    assert all(
        b in asm_src
        for b in (
            "list_statement_contributions",
            "list_journal_contributions",
            "resolve_manual_valuation_contributions",
            "resolve_selected_market_valuation_contribution",
        )
    )
    sig = asm_src.split("async def _input_manifest", 1)[1].split(") ->", 1)[0]
    assert (
        "contributions:" in sig
        and "traceability:" not in sig
        and "contributions: tuple[PackageSectionContribution" in trace_src
    )
    assert all(
        raw not in trace_src
        for raw in (
            "AtomicPosition",
            "ManualValuationSnapshot",
            "DividendIncome",
            "MarketDataOverride",
            "JournalEntry",
            "StatementSummary",
        )
    )

    prod = REPOSITORY_ROOT / "apps/backend/src"
    assert [
        p.relative_to(REPOSITORY_ROOT).as_posix()
        for p in prod.rglob("*.py")
        if any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "PersonalReportPackageDocument"
            for n in ast.walk(ast.parse(p.read_text()))
        )
    ] == ["apps/backend/src/reporting/extension/package_document.py"]
    assert all(
        not (REPOSITORY_ROOT / r).exists()
        for r in (
            "apps/backend/src/reporting/extension/report_readiness.py",
            "apps/backend/src/reporting/extension/confidence_metric.py",
        )
    )
    assert all("get_personal_report_package_readiness" not in p.read_text() for p in prod.rglob("*.py"))
    assert all(
        "/api/reports/package/readiness" not in p.read_text()
        for p in (REPOSITORY_ROOT / "apps/frontend/src").rglob("*.ts*")
    )
    retired = (
        "/api/reports/package/contract",
        "/api/reports/package/readiness",
        "/api/reports/package/framework-policy",
        "/api/reports/package/annualized-income-schedule",
        "/api/reports/package/notes",
        "/api/reports/package/traceability",
    )
    assert all(
        r not in (REPOSITORY_ROOT / rel).read_text()
        for rel in (
            "common/reporting/readme.md",
            "common/reporting/framework-reporting.md",
            "common/workflow/workflow-events.md",
            "common/pricing/readme.md",
            "docs/user-guide/reports.md",
        )
        for r in retired
    )
    journey = (REPOSITORY_ROOT / "tests/e2e/test_personal_financial_report_package.py").read_text()
    assert all(r.removeprefix("/api") not in journey for r in retired)
    assert (
        "confidence_metric_snapshots"
        not in (REPOSITORY_ROOT / "apps/backend/src/runtime/extension/snapshot_anonymizer.py").read_text()
    )


def test_AC_reporting_package_document_3_trust_is_one_trace_decision_fold() -> None:
    scope, input_t, pkg_t = (
        TraceScope.tenant(uuid4()),
        VersionedTraceRef("journal_command", "entry-1", "1"),
        VersionedTraceRef("personal_report_package", "snapshot-1", "c" * 64),
    )
    in_obs = _obs(scope=scope, target=input_t)
    in_dec = TraceRecord.decision(
        scope=scope,
        target=input_t,
        policy=_InputPolicy(),
        execution_id=in_obs.execution_id,
        occurred_at=in_obs.occurred_at,
        parents=(in_obs,),
    )
    sec_obs = _obs(scope=scope, target=pkg_t, reason_code="package_sections_valid")
    dec = TraceRecord.decision(
        scope=scope,
        target=pkg_t,
        policy=PackageReadinessDecisionPolicy(),
        execution_id="package-fixture",
        occurred_at=sec_obs.occurred_at,
        parents=(sec_obs, in_dec),
    )
    assert dec.result is TraceResult.AUTHORITATIVE and dec.parent_ids == tuple(
        sorted((sec_obs.record_id, in_dec.record_id), key=str)
    )

    p_start, p_end = date(2025, 1, 1), date(2025, 12, 31)
    sections = SimpleNamespace(
        balance_sheet=SimpleNamespace(
            is_balanced=False,
            equation_delta=Decimal("1.00"),
            net_income=Decimal("25.00"),
            as_of_date=p_end,
            currency="SGD",
            opening_balance_warnings=[],
            portfolio_warnings=[],
        ),
        income_statement=SimpleNamespace(
            net_income=Decimal("24.00"), start_date=p_start, end_date=p_end, currency="SGD"
        ),
        cash_flow=SimpleNamespace(
            start_date=p_start,
            end_date=p_end,
            currency="SGD",
            proof_state="proven",
            proof_reasons=[],
            cash_bridge=CashFlowBridge(
                classified_activity=Decimal("5.00"),
                unclassified_cash=Decimal("0.00"),
                fx_effect=Decimal("0.00"),
                cash_delta=Decimal("4.00"),
                reconciles=False,
            ),
            summary=SimpleNamespace(
                beginning_cash=Decimal("10.00"), net_cash_flow=Decimal("5.00"), ending_cash=Decimal("14.00")
            ),
        ),
        investment_performance=SimpleNamespace(
            period_start=p_start,
            period_end=p_end,
            as_of_date=p_end,
            currency="SGD",
            holdings=[SimpleNamespace()],
            data_freshness=SimpleNamespace(stale=False),
        ),
        annualized_income_long_term=SimpleNamespace(
            as_of_date=p_end,
            income=SimpleNamespace(currency="USD"),
            restricted_fair_value_total_currency="USD",
            restricted_fair_value_total_excludes=["Employer RSU (HKD 1,000.00)"],
        ),
    )
    blockers = lambda c=(): _section_invariant_blockers(
        sections,
        cumulative_net_income=Decimal("25.00"),
        period_net_income=Decimal("25.00"),
        start_date=p_start,
        end_date=p_end,
        as_of_date=p_end,
        currency="SGD",
        contributions=c,
        cash_inputs=PackageCashInputs.missing(),
    )
    b_auth = blockers((SimpleNamespace(is_authoritative=True, section_ids=("balance_sheet",)),))
    assert (
        PackageAssembler._readiness(
            policy=SimpleNamespace(gaps=[]),
            coverage=PersonalReportPackageInputCoverage(manifest_decision_count=1, authoritative_input_count=1),
            section_blockers=b_auth,
        ).state
        is PersonalReportPackageReadinessState.BLOCKED
    )
    assert {b.code for b in b_auth} == {
        "balance_sheet_equation_failed",
        "cash_flow_rollforward_failed",
        "investment_contribution_missing",
        "section_currency_mismatch",
        "statement_net_income_mismatch",
        "cash_balance_input_missing",
        "restricted_holding_fx_unavailable",
    }
    assert "cash_balance_input_missing" not in {b.code for b in blockers()}

    sections.balance_sheet.opening_balance_warnings, sections.balance_sheet.portfolio_warnings = [{}], [{}]
    sections.investment_performance.data_freshness.stale, sections.investment_performance.as_of_date = True, p_start
    assert {
        "investment_market_data_stale",
        "opening_balance_missing",
        "portfolio_value_incomplete",
        "section_period_mismatch",
    } <= {b.code for b in blockers()}
    sections.cash_flow.proof_state, sections.cash_flow.proof_reasons = (
        "unproven",
        ["cash_event_classification_ambiguous"],
    )
    assert "cash_event_classification_ambiguous" not in {b.code for b in blockers()}
    assert "cash_event_classification_ambiguous" in {
        b.code for b in blockers((SimpleNamespace(is_authoritative=False, section_ids=("cash_flow",)),))
    }
    sections.cash_flow.proof_reasons = ["opening_coverage_starts_after_period"]
    assert next(
        b
        for b in blockers((SimpleNamespace(is_authoritative=True, section_ids=("cash_flow",)),))
        if b.code == "opening_coverage_starts_after_period"
    ).reason.startswith("Your statements start after the first day of this period.")


def test_AC_reporting_2466_1_proof_reasons_cash_inputs_and_contributions() -> None:
    from src.reporting.extension import cash_flow as cash_flow_module
    from src.reporting.extension.cash_flow import (
        CASH_FLOW_PROOF_REASON_TEXT,
        CASH_FLOW_UNPROVEN_FALLBACK_TEXT,
        cash_flow_proof_reason_text,
    )

    emitted = {
        n.args[0].value
        for n in ast.walk(ast.parse(Path(cash_flow_module.__file__).read_text(encoding="utf-8")))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "add"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "proof_reasons"
        and n.args
        and isinstance(n.args[0], ast.Constant)
    }
    assert len(emitted) >= 6 and emitted == set(CASH_FLOW_PROOF_REASON_TEXT)
    texts = [cash_flow_proof_reason_text(c) for c in sorted(emitted)]
    assert (
        CASH_FLOW_UNPROVEN_FALLBACK_TEXT not in texts
        and len(set(texts)) == len(texts)
        and cash_flow_proof_reason_text("unknown_reason") == CASH_FLOW_UNPROVEN_FALLBACK_TEXT
    )

    missing = PackageCashInputs.missing()
    assert (
        not missing.is_complete
        and missing.account_ids == frozenset()
        and missing.reason_code == "cash_balance_input_missing"
    )
    for kw, m in (
        ({"account_ids": frozenset({uuid4()}), "input_refs": ("statement_result:fixture",)}, "exact input ref"),
        ({"account_ids": frozenset(), "input_refs": ()}, "at least one account"),
        (
            {"account_ids": frozenset(), "input_refs": ("",), "reason_code": "cash_balance_input_missing"},
            "cannot be blank",
        ),
    ):
        with pytest.raises(ValueError, match=m):
            PackageCashInputs(**kw)

    dec = TraceDecisionRef(
        decision_id=uuid4(),
        target=VersionedTraceRef("journal_command", "entry-1", "1"),
        assertion=VersionedTraceRef("ledger_authority", "posted", "1"),
    )
    for st in (
        {"section_ids": (), "state": "unproven", "decision": None, "reason_code": "m"},
        {
            "section_ids": ("balance_sheet",),
            "state": "unproven",
            "decision": None,
            "reason_code": "m",
            "input_refs": (),
        },
        {"section_ids": ("balance_sheet",), "state": "authoritative", "decision": None, "reason_code": None},
        {"section_ids": ("balance_sheet",), "state": "unproven", "decision": None, "reason_code": None},
        {"section_ids": ("balance_sheet",), "state": "unproven", "decision": dec, "reason_code": "m"},
    ):
        with pytest.raises(ValueError):
            PackageSectionContribution(
                contribution_type="ledger_command",
                payload=object(),
                input_refs=st.pop("input_refs", ("journal_entry:entry-1",)),
                **st,
            )

    assert _valuation_section_contribution(
        SimpleNamespace(
            input_refs=(),
            lineage_id=None,
            subject=SimpleNamespace(kind=SimpleNamespace(value="security"), key="ACME"),
            state="unproven",
            decision=None,
            reason_code="missing",
        )
    ).input_refs == ("valuation:security:ACME",)
    ci = _cash_inputs_from_contributions(
        (
            PackageSectionContribution(
                contribution_type="statement_source",
                section_ids=("balance_sheet",),
                payload=SimpleNamespace(
                    source_result=SimpleNamespace(source_type=StatementSourceType.BANK), account_id=None
                ),
                state="unproven",
                decision=None,
                input_refs=("statement:bank-1",),
                reason_code="missing",
            ),
        )
    )
    assert (ci.reason_code, ci.input_refs) == ("cash_balance_input_unproven", ("statement:bank-1",))
    assert [
        (b.code, b.count)
        for b in _policy_blockers(
            SimpleNamespace(
                gaps=[
                    SimpleNamespace(blocker=True, code="unsupported_policy_domain"),
                    SimpleNamespace(blocker=False, code="non_blocking_gap"),
                ]
            )
        )
    ] == [("unsupported_policy_domain", 1)]


async def test_AC_reporting_package_document_9_requires_exact_decision_coordinates() -> None:
    t_ok, a_ok = (
        VersionedTraceRef("journal_command", "expected", "v1"),
        VersionedTraceRef("ledger_authority", "expected", "v1"),
    )
    t_bad, a_bad = (
        VersionedTraceRef("journal_command", "other", "v1"),
        VersionedTraceRef("ledger_authority", "other", "v1"),
    )
    for kw, m in (
        ({"decision_id": "bad", "target": t_ok, "assertion": a_ok}, "UUID"),
        ({"decision_id": uuid4(), "target": "bad", "assertion": a_ok}, "VersionedTraceRef"),
        ({"decision_id": uuid4(), "target": t_ok, "assertion": "bad"}, "VersionedTraceRef"),
    ):
        with pytest.raises(TraceRecordValidationError, match=m):
            TraceDecisionRef(**kw)
    exact_id, t_id, a_id, cross_id = uuid4(), uuid4(), uuid4(), uuid4()
    rows = [
        SimpleNamespace(
            _mapping={
                "decision_id": did,
                "target_kind": t.kind,
                "target_id": t.id,
                "target_version": t.version,
                "assertion_kind": a.kind,
                "assertion_id": a.id,
                "assertion_version": a.version,
                "authority_tier": "CODE-ONLY",
            },
            decision_id=did,
            target_kind=t.kind,
            target_id=t.id,
            target_version=t.version,
            assertion_kind=a.kind,
            assertion_id=a.id,
            assertion_version=a.version,
            authority_tier="CODE-ONLY",
        )
        for did, t, a in ((exact_id, t_ok, a_ok), (t_id, t_bad, a_ok), (a_id, t_ok, a_bad))
    ]
    contribs = tuple(
        PackageSectionContribution(
            contribution_type="ledger_command",
            section_ids=("balance_sheet",),
            payload=object(),
            state="authoritative",
            decision=TraceDecisionRef(decision_id=did, target=t_ok, assertion=a_ok),
            input_refs=(ref,),
            reason_code=None,
        )
        for did, ref in (
            (exact_id, "journal_entry:exact"),
            (t_id, "journal_entry:wrong-target"),
            (a_id, "journal_entry:wrong-assertion"),
            (cross_id, "journal_entry:cross-scope"),
        )
    )
    manifest, unproven = await PackageAssembler()._input_manifest(
        SimpleNamespace(info={}, execute=lambda _q: _async_val(rows)), user_id=uuid4(), contributions=contribs
    )
    assert [m.decision_id for m in manifest] == [exact_id] and unproven == [
        "journal_entry:cross-scope",
        "journal_entry:wrong-assertion",
        "journal_entry:wrong-target",
    ]


async def _async_val(v):
    return v


def test_AC_reporting_package_document_10_and_2667_1_coordinates_and_bound_defaults() -> None:
    sid, did = UUID("10000000-0000-0000-0000-000000000001"), UUID("20000000-0000-0000-0000-000000000002")
    sem = {
        "context": {
            "framework_id": "personal_financial_reporting",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "as_of_date": "2026-12-31",
            "currency": "SGD",
        },
        "framework_policy": {"result_id": "policy-1", "gaps": []},
        "statement_disposition_policy": {"policy_version": "2026-07-19"},
        "input_manifest": [{"decision_id": str(did), "input_refs": ["statement:1"]}],
        "sections": {"balance_sheet": {"total_assets": "125.00"}},
    }
    jv = lambda v: SimpleNamespace(model_dump=lambda *, mode: copy.deepcopy(v))
    target = personal_report_package_target(snapshot_id=sid, **sem)
    assert target == VersionedTraceRef(
        kind="personal_report_package",
        id=str(sid),
        version="9d136a722c6fee121996a72b47f70e46633ea8828c57d96899a96f56f56ec5ae",
    )
    doc = SimpleNamespace(
        schema_version="2",
        lifecycle=PersonalReportPackageDocumentLifecycle.FROZEN,
        snapshot_id=sid,
        package_decision_id=did,
        context=jv(sem["context"]),
        framework_policy=jv(sem["framework_policy"]),
        statement_disposition_policy=jv(sem["statement_disposition_policy"]),
        input_manifest=[jv(i) for i in sem["input_manifest"]],
        sections=jv(sem["sections"]),
    )
    assert personal_report_package_decision_ref(doc) == TraceDecisionRef(
        decision_id=did, target=target, assertion=PackageReadinessDecisionPolicy().assertion
    )
    for upd, m in (
        ({"schema_version": "1"}, "schema version"),
        ({"lifecycle": PersonalReportPackageDocumentLifecycle.PREVIEW}, "frozen document"),
        ({"package_decision_id": None}, "snapshot and decision ids"),
        ({"statement_disposition_policy": None}, "statement disposition policy"),
    ):
        with pytest.raises(ValueError, match=m):
            personal_report_package_decision_ref(SimpleNamespace(**vars(doc) | upd))
    for field in sem:
        ch = copy.deepcopy(sem)
        ch[field].append({"decision_id": str(uuid4()), "input_refs": ["statement:c"]}) if isinstance(
            ch[field], list
        ) else ch[field].__setitem__("counterfactual", field)
        assert personal_report_package_target(snapshot_id=sid, **ch) != target
    assert personal_report_package_target(snapshot_id=uuid4(), **sem) != target
    asm_src = (REPOSITORY_ROOT / "apps/backend/src/reporting/extension/package_document.py").read_text()
    assert "personal_report_package_target(" in asm_src and "semantic_payload =" not in asm_src

    post_stored = json.loads(
        (REPOSITORY_ROOT / "apps/backend/tests/fixtures/package_document_main_shape.json").read_text()
    )
    pre_stored = copy.deepcopy(post_stored)
    pre_stored["sections"]["balance_sheet"].pop("excluded_holdings")
    pre_doc, post_doc = (
        PersonalReportPackageDocument.model_validate(pre_stored),
        PersonalReportPackageDocument.model_validate(post_stored),
    )
    assert (
        "excluded_holdings" not in pre_doc.sections.balance_sheet.model_fields_set
        and "excluded_holdings" in post_doc.sections.balance_sheet.model_fields_set
    )
    assert pre_doc.model_dump(mode="json") == pre_stored and post_doc.model_dump(mode="json") == post_stored
    assert personal_report_package_decision_ref(pre_doc).target == personal_report_package_target(
        snapshot_id=UUID(pre_stored["snapshot_id"]),
        context=pre_stored["context"],
        framework_policy=pre_stored["framework_policy"],
        statement_disposition_policy=pre_stored["statement_disposition_policy"],
        input_manifest=pre_stored["input_manifest"],
        sections=pre_stored["sections"],
    )
    assert (
        personal_report_package_decision_ref(post_doc).target.version
        == "aacc713256b0f0411ce8c416598a2b75ddbb8a0634fe0e4036f773f2094da538"
    )
    assert (
        personal_report_package_decision_ref(pre_doc).target.version
        != personal_report_package_decision_ref(post_doc).target.version
    )

    visited, defaults = set(), set()

    def walk(tp: object) -> None:
        if typing.get_origin(tp) is not None:
            [walk(a) for a in typing.get_args(tp)]
        elif isinstance(tp, type) and issubclass(tp, BaseModel) and tp not in visited:
            visited.add(tp)
            for fn, fi in tp.model_fields.items():
                if not fi.is_required():
                    defaults.add((tp.__name__, fn))
                walk(fi.annotation)

    [
        walk(PersonalReportPackageDocument.model_fields[r].annotation)
        for r in ("context", "framework_policy", "statement_disposition_policy", "input_manifest", "sections")
    ]
    assert defaults == {
        ("AnnualizedIncomeScheduleHolding", "unlock_date"),
        ("AnnualizedIncomeScheduleHolding", "vesting_schedule"),
        ("AnnualizedIncomeScheduleResponse", "restricted_fair_value_total_excludes"),
        ("BalanceSheetResponse", "cta_adjustment"),
        ("BalanceSheetResponse", "excluded_holdings"),
        ("BalanceSheetResponse", "fx_warnings"),
        ("BalanceSheetResponse", "net_income"),
        ("BalanceSheetResponse", "net_worth_adjustment_gain_loss"),
        ("BalanceSheetResponse", "opening_balance_warnings"),
        ("BalanceSheetResponse", "portfolio_warnings"),
        ("BalanceSheetResponse", "unrealized_fx_gain_loss"),
        ("CashFlowBridge", "discrepancy"),
        ("CashFlowBridge", "opening_stock_adjustment"),
        ("CashFlowEventLineage", "decision_anchor_id"),
        ("CashFlowEventLineage", "event_types"),
        ("CashFlowEventLineage", "reason_code"),
        ("CashFlowEventLineage", "source_id"),
        ("CashFlowItem", "account_id"),
        ("CashFlowItem", "description"),
        ("CashFlowResponse", "cash_bridge"),
        ("CashFlowResponse", "event_lineage"),
        ("CashFlowResponse", "fx_warnings"),
        ("ExcludedHoldingRow", "warnings"),
        ("FrameworkPolicyDecision", "accepted_value"),
        ("FrameworkPolicyDecision", "classification"),
        ("FrameworkPolicyDecision", "disclosure"),
        ("FrameworkPolicyDecision", "evidence_anchors"),
        ("FrameworkPolicyDecision", "measurement"),
        ("FrameworkPolicyDecision", "policy_field_name"),
        ("FrameworkPolicyDecision", "presentation"),
        ("FrameworkPolicyDecision", "provenance"),
        ("FrameworkPolicyDecision", "recognition"),
        ("FrameworkPolicyDecision", "review_state"),
        ("FrameworkPolicyEvidenceAnchor", "description"),
        ("FrameworkPolicyGap", "evidence_anchors"),
        ("FrameworkPolicyResult", "gaps"),
        ("IncomeStatementResponse", "fx_warnings"),
        ("InvestmentPerformanceDataFreshness", "manual_override_basis"),
        ("InvestmentPerformanceDataFreshness", "stale_holdings"),
        ("InvestmentPerformanceReportScheduleResponse", "market_valuation_selections"),
        ("PersonalReportPackageCompletenessWarning", "remediation"),
        ("PersonalReportPackageContext", "include_restricted"),
        ("PersonalReportPackageTraceabilityAnchor", "details"),
        ("PersonalReportPackageTraceabilityAnchor", "entry_statuses"),
        ("PersonalReportPackageTraceabilityAnchor", "identifier_fields"),
        ("PersonalReportPackageTraceabilityAnchor", "identifiers"),
        ("PersonalReportPackageTraceabilityAnchor", "source_types"),
        ("PersonalReportPackageTraceabilityAnchor", "unavailable_reason"),
        ("PersonalReportPackageTraceabilityLine", "amount_field"),
        ("PersonalReportPackageTraceabilityLine", "anchor_count"),
        ("PersonalReportPackageTraceabilityLine", "blocker_codes"),
        ("PersonalReportPackageTraceabilityLine", "currency_field"),
        ("ReportLine", "allocation_source_type"),
        ("ReportLine", "line_id"),
        ("ReportLine", "native_amount"),
        ("ReportLine", "parent_id"),
        ("ReportLine", "provenance"),
        ("ReportLine", "source_currency"),
    }


async def test_AC_extraction_auto_accept_8_and_package_doc_13_and_2623_1(db, test_user, monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", True)
    auto = await _package_statement_disposition_policy(db, test_user.id)
    test_user.ai_settings = {"auto_accept_ai_suggestions": False}
    await db.flush()
    manual = await _package_statement_disposition_policy(db, test_user.id)
    assert (str(auto.machine_confidence_threshold), str(manual.machine_confidence_threshold)) == (
        "0",
        "0.85",
    ) and auto.semantic_digest != manual.semantic_digest
    bs = BalanceSheetResponse.model_validate(
        {
            "as_of_date": "2026-07-31",
            "currency": "SGD",
            "assets": [],
            "liabilities": [],
            "equity": [],
            "total_assets": "0.00",
            "total_liabilities": "0.00",
            "total_equity": "0.00",
            "equation_delta": "0.00",
            "is_balanced": True,
        }
    )
    note = lambda p: next(
        i["disclosure"]
        for i in _package_notes(p, balance_sheet=bs, include_restricted=False).model_dump()["notes"]
        if i["note_id"] == "statement-disposition-policy"
    )
    assert "accepts AI suggestions at any score" in note(auto) and "accepts AI suggestions at any score" not in note(
        manual
    )

    trace_calls = bs_calls = 0

    async def count_trace(**kw):
        nonlocal trace_calls
        trace_calls += 1
        return await real_build_traceability(**kw)

    async def count_bs(*a, **kw):
        nonlocal bs_calls
        bs_calls += 1
        return await real_generate_balance_sheet(*a, **kw)

    monkeypatch.setattr(package_document_mod, "build_personal_report_package_traceability_payload", count_trace)
    monkeypatch.setattr(framework_report_mod, "generate_balance_sheet", count_bs)
    if hasattr(income_statement_mod, "generate_balance_sheet"):
        monkeypatch.setattr(income_statement_mod, "generate_balance_sheet", count_bs)

    _bank, sys_round, sys_liab = await seed_accounts(
        db,
        test_user.id,
        ("DBS", AccountType.ASSET),
        ("Rounding", AccountType.EXPENSE, "SGD", {"code": "SYS-ROUND", "is_system": True}),
        ("Sys Liab", AccountType.LIABILITY, "SGD", {"code": "SYS-LIAB", "is_system": True}),
    )
    await post_entry(
        db,
        user_id=test_user.id,
        entry_date=date(2026, 7, 15),
        memo="Rounding",
        entry=Entry.transfer(debit=sys_round.id, credit=sys_liab.id, money=Money(Decimal("0.05"), "SGD")),
        base_currency="SGD",
    )
    await db.flush()
    assert (
        await current_package_readiness(db, user_id=test_user.id, as_of_date=date(2026, 7, 31), base_currency="SGD")
    ).package_id == "personal-financial-report-package"
    doc = await PackageAssembler().assemble(
        db,
        user_id=test_user.id,
        framework_id=package_document_mod.PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        as_of_date=date(2026, 7, 31),
        currency="SGD",
    )
    assert doc.sections.traceability_appendix is not None and trace_calls == 1 and bs_calls == 1
