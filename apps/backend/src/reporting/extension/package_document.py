"""Assembly of the sole typed personal-report delivery document."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    SqlTraceRecordRepository,
    TraceDecisionPolicyRegistry,
    TraceDecisionRef,
    TraceEmitter,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
    current_authoritative_trace_decisions,
    shared_current_authority,
)
from src.config_app import get_effective_base_currency
from src.extraction import (
    StatementEvidenceType,
    StatementSourceType,
    coverage_bank_custody_account_ids,
    current_statement_disposition_policy_snapshot,
    list_statement_contributions,
    statement_disposition_policy_for_user,
)
from src.extraction.extension.extraction_trace import extraction_trace_policy_registry
from src.ledger import ledger_trace_policy_registry, list_journal_contributions
from src.portfolio import build_investment_performance_report_schedule
from src.pricing import (
    MarketValuationSelection,
    PriceableSubject,
    ResolutionPolicy,
    pricing_trace_policy_registry,
    resolve_manual_valuation_contributions,
    resolve_selected_market_valuation_contribution,
)
from src.reporting.base.cash_flow_types import CashFlowPreview, CashFlowResponse
from src.reporting.base.package_contribution import PackageCashInputs, PackageSectionContribution, PackageSectionId
from src.reporting.base.package_decision import (
    PACKAGE_DECISION_POLICY_VERSION,
    PackageReadinessDecisionPolicy,
    personal_report_package_target,
)
from src.reporting.base.report_package_contract import (
    PERSONAL_REPORT_PACKAGE_CONTRACT,
    PERSONAL_REPORT_PACKAGE_NOTES,
    PERSONAL_REPORT_PACKAGE_TRACEABILITY,
)
from src.reporting.base.types import PACKAGE_INCLUDE_RESTRICTED, PersonalReportingFrameworkId
from src.reporting.extension._core import _aggregate_net_income_sql, _quantize_money
from src.reporting.extension.annualized_income import generate_annualized_income_schedule
from src.reporting.extension.cash_flow import (
    CashCoverage,
    cash_coverage,
    cash_flow_line_events,
    cash_flow_preview,
    cash_flow_proof_reason_text,
    generate_cash_flow,
)
from src.reporting.extension.framework_policy import derive_user_framework_policy_result
from src.reporting.extension.framework_report import (
    assemble_framework_balance_sheet,
    assemble_framework_income_statement,
)
from src.reporting.extension.report_package import package_evidence_references
from src.reporting.extension.report_traceability import build_personal_report_package_traceability_payload
from src.schemas.portfolio import InvestmentPerformanceReportScheduleResponse
from src.schemas.reporting import (
    BalanceSheetResponse,
    ExcludedHoldingRow,
    FrameworkPolicyDecision,
    FrameworkPolicyPreview,
    FrameworkPolicyResult,
    IncomeStatementResponse,
    PersonalReportPackageContext,
    PersonalReportPackageContractResponse,
    PersonalReportPackageDocument,
    PersonalReportPackageDocumentLifecycle,
    PersonalReportPackageInputCoverage,
    PersonalReportPackageNotesResponse,
    PersonalReportPackagePreview,
    PersonalReportPackagePreviewSections,
    PersonalReportPackageReadinessBlocker,
    PersonalReportPackageReadinessResponse,
    PersonalReportPackageReadinessState,
    PersonalReportPackageSections,
    PersonalReportPackageSnapshotStatus,
    PersonalReportPackageStatementDispositionPolicy,
    PersonalReportPackageTraceabilityAnchor,
    PersonalReportPackageTraceabilityAnchorName,
    PersonalReportPackageTraceabilityAnchorSummary,
    PersonalReportPackageTraceabilityLineSummary,
    PersonalReportPackageTraceabilityResponse,
    PersonalReportPackageTraceabilitySummaryResponse,
    PersonalReportPackageTraceManifestEntry,
)

RESTRICTED_ASSET_TREATMENT_NOTE_ID = "restricted-asset-treatment"
PACKAGE_POLICY_PREVIEW_DECISIONS = 25
_COORD_KEYS = (
    "target_kind",
    "target_id",
    "target_version",
    "assertion_kind",
    "assertion_id",
    "assertion_version",
    "authority_tier",
)


def _decision_sections_dump(sections: Any) -> dict[str, Any]:
    dumped = sections.model_dump(mode="json")
    bs = getattr(sections, "balance_sheet", None)
    if (
        bs is not None
        and hasattr(bs, "model_fields_set")
        and "excluded_holdings" not in bs.model_fields_set
        and not getattr(bs, "excluded_holdings", None)
        and isinstance(dumped.get("balance_sheet"), dict)
    ):
        dumped["balance_sheet"].pop("excluded_holdings", None)
    return dumped


def personal_report_package_decision_ref(document: PersonalReportPackageDocument) -> TraceDecisionRef:
    if document.schema_version != "2":
        raise ValueError("unsupported package document schema version")
    if document.lifecycle is not PersonalReportPackageDocumentLifecycle.FROZEN:
        raise ValueError("package decision coordinates require a frozen document")
    if document.snapshot_id is None or document.package_decision_id is None:
        raise ValueError("frozen package decision coordinates require snapshot and decision ids")
    if document.statement_disposition_policy is None:
        raise ValueError("package decision coordinates require a statement disposition policy")
    return TraceDecisionRef(
        decision_id=document.package_decision_id,
        target=personal_report_package_target(
            snapshot_id=document.snapshot_id,
            context=document.context.model_dump(mode="json"),
            framework_policy=document.framework_policy.model_dump(mode="json"),
            statement_disposition_policy=document.statement_disposition_policy.model_dump(mode="json"),
            input_manifest=[item.model_dump(mode="json") for item in document.input_manifest],
            sections=_decision_sections_dump(document.sections),
        ),
        assertion=PackageReadinessDecisionPolicy().assertion,
    )


def _contract(framework_id: PersonalReportingFrameworkId) -> PersonalReportPackageContractResponse:
    return PersonalReportPackageContractResponse.model_validate(
        {**PERSONAL_REPORT_PACKAGE_CONTRACT, "selected_framework_id": framework_id.value}
    )


async def _package_statement_disposition_policy(
    db: AsyncSession, user_id: UUID
) -> PersonalReportPackageStatementDispositionPolicy:
    snapshot = current_statement_disposition_policy_snapshot(
        policy=await statement_disposition_policy_for_user(db, user_id)
    )
    return PersonalReportPackageStatementDispositionPolicy.model_validate(
        {**snapshot.semantic_payload(), "semantic_digest": snapshot.semantic_digest}
    )


def _conversion_gap_text(warning: dict[str, str]) -> str:
    pair = f"{warning['currency']} to {warning['target_currency']}"
    return (
        f"no FX rate for {pair}"
        if warning["type"] == "missing_fx_rate_excluded_holding"
        else f"FX conversion failed for {pair}"
    )


def _excluded_holding_text(row: ExcludedHoldingRow, currency: str) -> str:
    label = row.asset_class.replace("_", " ")
    if row.net_worth is None or row.total_assets is None or row.total_liabilities is None:
        gaps = ", ".join(sorted({_conversion_gap_text(w) for w in row.warnings}))
        return f"{label}: amount not available, {gaps}"
    return f"{label} {currency} {row.net_worth:,.2f} net (assets {currency} {row.total_assets:,.2f}, liabilities {currency} {row.total_liabilities:,.2f})"


def _restricted_asset_treatment_disclosure(
    base_disclosure: str, *, include_restricted: bool, excluded_holdings: list[ExcludedHoldingRow], currency: str
) -> str:
    if include_restricted:
        return f"{base_disclosure} This package includes restricted and illiquid holdings in the balance sheet."
    if not excluded_holdings:
        return (
            f"{base_disclosure} On the as-of date this package excludes no restricted or illiquid holding: "
            "no such valuation is current on that date."
        )
    rows = "; ".join(_excluded_holding_text(row, currency) for row in excluded_holdings)
    return (
        f"{base_disclosure} This package excludes these restricted and illiquid holdings, with the "
        f"liabilities of their class, from the balance sheet: {rows}."
    )


def _package_notes(
    sdp: PersonalReportPackageStatementDispositionPolicy,
    *,
    balance_sheet: BalanceSheetResponse,
    include_restricted: bool,
) -> PersonalReportPackageNotesResponse:
    any_score_note = (
        "At the time of this package the system accepts AI suggestions at any score for this user. "
        "Entries posted under that setting carry a low confidence tier, and a row that the AI could "
        "not place sits in a general account. The decision record of each entry names the policy "
        "version that ran. "
        if sdp.machine_confidence_threshold == 0
        else ""
    )
    notes = [
        (
            {
                **note,
                "disclosure": _restricted_asset_treatment_disclosure(
                    note["disclosure"],
                    include_restricted=include_restricted,
                    excluded_holdings=balance_sheet.excluded_holdings,
                    currency=balance_sheet.currency,
                ),
            }
            if note["note_id"] == RESTRICTED_ASSET_TREATMENT_NOTE_ID
            else note
        )
        for note in PERSONAL_REPORT_PACKAGE_NOTES["notes"]
    ]
    notes.append(
        {
            "note_id": "statement-disposition-policy",
            "label": "Statement Disposition Policy",
            "owner_epic": "EPIC-018",
            "basis": "immutable_statement_disposition_policy_snapshot",
            "source_state": "frozen_runtime_policy_snapshot",
            "applies_to_sections": ["balance_sheet", "income_statement", "cash_flow", "traceability_appendix"],
            "disclosure": (
                f"Statement disposition policy {sdp.policy_version} ran in {sdp.mode} mode. "
                f"Machine authority threshold is {sdp.machine_confidence_threshold}; "
                f"P&L authority threshold is {sdp.pnl_effect_confidence_threshold}. "
                f"Unknown and ambiguous intent route to review. Live LLM proposals are "
                f"{'enabled' if sdp.live_llm_proposals_enabled else 'disabled'}. "
                f"{any_score_note}Deployment commit: {sdp.deployment_git_sha}."
            ),
        }
    )
    return PersonalReportPackageNotesResponse.model_validate({**PERSONAL_REPORT_PACKAGE_NOTES, "notes": notes})


def _policy_decisions_by_source_id(policy: Any) -> dict[str, Any]:
    return {str(anchor.source_id): d for d in policy.decisions for anchor in d.evidence_anchors}


def _section_contribution(
    contribution_type: Literal["statement_source", "ledger_command", "valuation", "opening_position"],
    section_ids: tuple[PackageSectionId, ...],
    payload: Any,
    input_refs: tuple[str, ...],
) -> PackageSectionContribution[Any]:
    return PackageSectionContribution(
        contribution_type=contribution_type,
        section_ids=section_ids,
        payload=payload,
        state=payload.state,
        decision=payload.decision,
        input_refs=input_refs,
        reason_code=payload.reason_code,
    )


def _statement_section_contribution(
    c: Any, *, start_date: date, end_date: date, as_of_date: date | None = None
) -> PackageSectionContribution[Any]:
    sections: list[PackageSectionId] = ["traceability_appendix"]
    result = c.source_result
    if result is not None:
        bound = as_of_date or end_date
        current = c.effective_period_end is not None and c.effective_period_end <= bound
        if current and (result.balances or result.transactions):
            sections.append("balance_sheet")
        if current and result.positions:
            sections.extend(("balance_sheet", "investment_performance"))
        overlaps = (
            c.effective_period_start is not None
            and c.effective_period_end is not None
            and c.effective_period_start <= end_date
            and c.effective_period_end >= start_date
        )
        if overlaps and any(start_date <= f.transaction_date <= min(end_date, bound) for f in result.transactions):
            sections.extend(("cash_flow", "income_statement", "annualized_income_long_term"))
    return _section_contribution(
        "statement_source", tuple(dict.fromkeys(sections)), c, c.input_refs or (f"statement:{c.statement_id}",)
    )


def _journal_section_contribution(c: Any, *, start_date: date, end_date: date) -> PackageSectionContribution[Any]:
    sections: list[PackageSectionId] = ["balance_sheet", "traceability_appendix"]
    if start_date <= c.entry_date <= end_date:
        sections.append("cash_flow")
        if any(line.account_type.value.lower() in {"income", "expense"} for line in c.lines):
            sections.extend(("income_statement", "annualized_income_long_term"))
    return _section_contribution("ledger_command", tuple(dict.fromkeys(sections)), c, c.input_refs)


def _opening_section_contribution(p: Any) -> PackageSectionContribution[Any]:
    return _section_contribution(
        "opening_position", ("balance_sheet", "cash_flow", "traceability_appendix"), p, (f"opening_position:{p.account_id}",)
    )


def _valuation_section_contribution(c: Any) -> PackageSectionContribution[Any]:
    input_refs = c.input_refs or (f"valuation:{c.lineage_id or f'{c.subject.kind.value}:{c.subject.key}'}",)
    sections = cast(
        tuple[PackageSectionId, ...],
        ("balance_sheet", "investment_performance", "traceability_appendix")
        if c.subject.kind.value == "security"
        else ("balance_sheet", "annualized_income_long_term", "traceability_appendix"),
    )
    return _section_contribution("valuation", sections, c, input_refs)


def _is_bank_statement_contribution(c: Any) -> bool:
    if c.contribution_type != "statement_source":
        return False
    res = getattr(c.payload, "source_result", None)
    return res is not None and (
        res.source_type is StatementSourceType.BANK or res.evidence_type is StatementEvidenceType.TRANSACTION_LEDGER
    )


def _cash_inputs_from_contributions(contributions: tuple[PackageSectionContribution[Any], ...]) -> PackageCashInputs:
    account_ids: set[UUID] = set()
    input_refs: set[str] = set()
    has_unproven = False
    for c in contributions:
        if not _is_bank_statement_contribution(c):
            continue
        account_id = getattr(c.payload, "account_id", None)
        input_refs.update(c.input_refs)
        if c.is_authoritative and account_id is not None:
            account_ids.add(account_id)
        else:
            has_unproven = True
    if has_unproven:
        return PackageCashInputs(
            account_ids=frozenset(account_ids),
            input_refs=tuple(sorted(input_refs)),
            reason_code="cash_balance_input_unproven",
        )
    return (
        PackageCashInputs(account_ids=frozenset(account_ids), input_refs=tuple(sorted(input_refs)))
        if account_ids
        else PackageCashInputs.missing()
    )


def _blocker(
    code: str,
    reason: str,
    *,
    label: str = "Package section invariant failed",
    count: int = 1,
    href: str = "/reports?tab=package",
) -> PersonalReportPackageReadinessBlocker:
    return PersonalReportPackageReadinessBlocker(
        code=code, label=label, severity="blocking", count=count, reason=reason, action_href=href
    )


def _policy_blockers(policy: Any) -> list[PersonalReportPackageReadinessBlocker]:
    grouped: dict[str, int] = defaultdict(int)
    for gap in policy.gaps:
        if gap.blocker:
            grouped[gap.code] += 1
    return [
        _blocker(
            code,
            "An explicit framework policy gap must be resolved before the package is trusted.",
            label="Unsupported policy domain" if code == "unsupported_policy_domain" else "Framework policy gap",
            count=count,
        )
        for code, count in sorted(grouped.items())
    ]


def _section_invariant_blockers(
    sections: PersonalReportPackageSections,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date,
    currency: str,
    contributions: tuple[PackageSectionContribution[Any], ...],
    cash_inputs: PackageCashInputs,
    cumulative_net_income: Decimal,
    period_net_income: Decimal,
) -> list[PersonalReportPackageReadinessBlocker]:
    bs = sections.balance_sheet
    inc = sections.income_statement
    cf = sections.cash_flow
    inv = sections.investment_performance
    ann = sections.annualized_income_long_term
    cash_rollforward = cf.summary.ending_cash - cf.summary.beginning_cash
    opening_adj = cf.cash_bridge.opening_stock_adjustment if cf.cash_bridge else Decimal("0")
    proof_code = cf.proof_reasons[0] if cf.proof_reasons else "cash_flow_unproven"
    period_matches = (
        bs.as_of_date == as_of_date
        and inc.start_date == start_date
        and inc.end_date == end_date
        and cf.start_date == start_date
        and cf.end_date == end_date
        and inv.period_start == start_date
        and inv.period_end == end_date
        and inv.as_of_date == as_of_date
        and ann.as_of_date == as_of_date
    )
    section_currencies = {
        bs.currency,
        inc.currency,
        cf.currency,
        inv.currency,
        ann.income.currency,
        ann.restricted_fair_value_total_currency,
    }
    checks: tuple[tuple[bool, str, str], ...] = (
        (
            not bs.is_balanced or abs(bs.equation_delta) >= Decimal("0.01"),
            "balance_sheet_equation_failed",
            "The balance sheet does not balance.",
        ),
        (
            bs.net_income != cumulative_net_income or inc.net_income != period_net_income,
            "statement_net_income_mismatch",
            "Statement net income differs from the ledger for its cumulative or selected period.",
        ),
        (
            cash_rollforward != cf.summary.net_cash_flow + opening_adj,
            "cash_flow_rollforward_failed",
            "Beginning cash plus net cash flow and opening balance adjustment does not equal ending cash.",
        ),
        (
            bool(contributions) and cf.proof_state != "proven",
            proof_code,
            cash_flow_proof_reason_text(proof_code),
        ),
        (
            bool(contributions) and not cash_inputs.is_complete,
            cash_inputs.reason_code or "cash_balance_input_unproven",
            "Cash balances require an authoritative bank-statement custody account input.",
        ),
        (
            bool(bs.opening_balance_warnings),
            "opening_balance_missing",
            "Recorded activity is missing an opening balance required for a complete statement.",
        ),
        (
            bool(bs.portfolio_warnings),
            "portfolio_value_incomplete",
            "One or more selected positions lack a point-in-time value.",
        ),
        (
            inv.data_freshness.stale,
            "investment_market_data_stale",
            "The selected investment schedule uses stale market data.",
        ),
        (
            bool(getattr(inv, "holdings", ()))
            and not any(c.is_authoritative and "investment_performance" in c.section_ids for c in contributions),
            "investment_contribution_missing",
            "Investment holdings have no current authoritative source contribution.",
        ),
        (not period_matches, "section_period_mismatch", "A section does not match the document period."),
        (
            section_currencies != {currency},
            "section_currency_mismatch",
            "Every package section must use the document currency.",
        ),
        (
            bool(ann.restricted_fair_value_total_excludes),
            "restricted_holding_fx_unavailable",
            "A restricted holding has no FX rate to the document currency, so the restricted fair-value total leaves it out.",
        ),
    )
    return [_blocker(code, reason) for failed, code, reason in checks if failed]


@dataclass(frozen=True)
class _PackageEvaluation:
    policy: Any
    contributions: tuple[PackageSectionContribution[Any], ...]
    sections: PersonalReportPackageSections
    input_manifest: list[PersonalReportPackageTraceManifestEntry]
    readiness: PersonalReportPackageReadinessResponse


class PackageAssembler:
    async def assemble(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        framework_id: PersonalReportingFrameworkId,
        start_date: date,
        end_date: date,
        as_of_date: date,
        currency: str,
        include_restricted: bool = PACKAGE_INCLUDE_RESTRICTED,
        lifecycle: PersonalReportPackageDocumentLifecycle = PersonalReportPackageDocumentLifecycle.PREVIEW,
        snapshot_id: UUID | None = None,
        frozen_at: datetime | None = None,
    ) -> PersonalReportPackageDocument:
        ev = await self._evaluate(
            db,
            user_id=user_id,
            framework_id=framework_id,
            start_date=start_date,
            end_date=end_date,
            as_of_date=as_of_date,
            currency=currency,
            include_restricted=include_restricted,
        )
        contract = _contract(framework_id)
        sdp = await _package_statement_disposition_policy(db, user_id)
        sections = ev.sections
        sections.traceability_appendix = await _traceability_appendix(ev.contributions)
        sections.notes = _package_notes(
            sdp, balance_sheet=sections.balance_sheet, include_restricted=include_restricted
        )
        context = PersonalReportPackageContext(
            framework_id=framework_id,
            start_date=start_date,
            end_date=end_date,
            as_of_date=as_of_date,
            currency=currency,
            include_restricted=include_restricted,
        )
        package_decision_id = None
        if (
            lifecycle is PersonalReportPackageDocumentLifecycle.FROZEN
            and ev.readiness.state is PersonalReportPackageReadinessState.READY
        ):
            if snapshot_id is None or frozen_at is None:
                raise ValueError("frozen package assembly requires snapshot_id and frozen_at")
            package_decision_id = await self._emit_package_decision(
                db,
                user_id=user_id,
                snapshot_id=snapshot_id,
                occurred_at=frozen_at,
                context=context.model_dump(mode="json"),
                framework_policy=ev.policy.model_dump(mode="json"),
                statement_disposition_policy=sdp.model_dump(mode="json"),
                input_manifest=ev.input_manifest,
                sections=sections,
            )
        return PersonalReportPackageDocument(
            schema_version="2",
            lifecycle=lifecycle,
            snapshot_id=snapshot_id,
            package_decision_id=package_decision_id,
            generated_at=datetime.now(UTC),
            frozen_at=frozen_at,
            package_id=contract.package_id,
            status=(
                PersonalReportPackageSnapshotStatus.TRUSTED
                if package_decision_id is not None
                else PersonalReportPackageSnapshotStatus.DRAFT
            ),
            context=context,
            contract=contract,
            readiness=ev.readiness,
            framework_policy=ev.policy,
            statement_disposition_policy=sdp,
            input_manifest=ev.input_manifest,
            sections=sections,
        )

    async def evaluate_readiness(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        framework_id: PersonalReportingFrameworkId,
        start_date: date,
        end_date: date,
        as_of_date: date,
        currency: str,
        include_restricted: bool = PACKAGE_INCLUDE_RESTRICTED,
    ) -> PersonalReportPackageReadinessResponse:
        ev = await self._evaluate(
            db,
            user_id=user_id,
            framework_id=framework_id,
            start_date=start_date,
            end_date=end_date,
            as_of_date=as_of_date,
            currency=currency,
            include_restricted=include_restricted,
        )
        return ev.readiness

    async def _evaluate(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        framework_id: PersonalReportingFrameworkId,
        start_date: date,
        end_date: date,
        as_of_date: date,
        currency: str,
        include_restricted: bool,
    ) -> _PackageEvaluation:
        async with shared_current_authority(db, TraceScope.tenant(user_id)):
            policy = await derive_user_framework_policy_result(
                db,
                user_id,
                framework_id=framework_id,
                report_period_start=start_date,
                report_period_end=end_date,
                as_of_date=as_of_date,
            )
            base_contributions = await self._contributions(
                db, user_id=user_id, start_date=start_date, end_date=end_date, as_of_date=as_of_date
            )
            cash_inputs = _cash_inputs_from_contributions(base_contributions)
            sections = await self._sections(
                db,
                user_id=user_id,
                framework_id=framework_id,
                start_date=start_date,
                end_date=end_date,
                as_of_date=as_of_date,
                currency=currency,
                include_restricted=include_restricted,
                decisions_by_source_id=_policy_decisions_by_source_id(policy),
                contributions=base_contributions,
                cash_inputs=cash_inputs,
            )
            contributions = await self._with_market_contributions(
                db,
                user_id=user_id,
                base_contributions=base_contributions,
                investment_performance=sections.investment_performance,
            )
            input_manifest, unproven_refs = await self._input_manifest(db, user_id=user_id, contributions=contributions)
            coverage = PersonalReportPackageInputCoverage(
                manifest_decision_count=len(input_manifest),
                authoritative_input_count=sum(len(item.input_refs) for item in input_manifest),
                unproven_input_count=len(unproven_refs),
            )
            cum_raw, _ = await _aggregate_net_income_sql(db, user_id, currency, as_of_date)
            per_raw, _ = await _aggregate_net_income_sql(db, user_id, currency, end_date, start_date=start_date)
            readiness = self._readiness(
                policy=policy,
                coverage=coverage,
                section_blockers=_section_invariant_blockers(
                    sections,
                    start_date=start_date,
                    end_date=end_date,
                    as_of_date=as_of_date,
                    currency=currency,
                    contributions=contributions,
                    cash_inputs=cash_inputs,
                    cumulative_net_income=_quantize_money(cum_raw),
                    period_net_income=_quantize_money(per_raw),
                ),
            )
            return _PackageEvaluation(
                policy=policy,
                contributions=contributions,
                sections=sections,
                input_manifest=input_manifest,
                readiness=readiness,
            )

    async def _emit_package_decision(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        snapshot_id: UUID,
        occurred_at: datetime,
        context: dict[str, Any],
        framework_policy: dict[str, Any],
        statement_disposition_policy: dict[str, Any],
        input_manifest: list[PersonalReportPackageTraceManifestEntry],
        sections: PersonalReportPackageSections,
    ) -> UUID:
        package_policy = PackageReadinessDecisionPolicy()
        policies = (
            *extraction_trace_policy_registry().policies,
            *ledger_trace_policy_registry().policies,
            *pricing_trace_policy_registry().policies,
            package_policy,
        )
        repository = SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry(policies))
        scope = TraceScope.tenant(user_id)
        parents = []
        for item in input_manifest:
            parent = await repository.get(scope, item.decision_id)
            if parent is None or parent.result is not TraceResult.AUTHORITATIVE:
                raise ValueError("package input decision is missing or non-authoritative")
            parents.append(parent)
        if not parents:
            raise ValueError("trusted package requires at least one authoritative input decision")
        target = personal_report_package_target(
            snapshot_id=snapshot_id,
            context=context,
            framework_policy=framework_policy,
            statement_disposition_policy=statement_disposition_policy,
            input_manifest=[item.model_dump(mode="json") for item in input_manifest],
            sections=sections.model_dump(mode="json"),
        )
        execution_id = f"report-package:{snapshot_id}"
        obs = TraceRecord.observation(
            scope=scope,
            target=target,
            target_class=TraceTargetClass.FINANCIAL,
            assertion=VersionedTraceRef(
                "package_invariant", "typed-sections-and-accounting", PACKAGE_DECISION_POLICY_VERSION
            ),
            authority=package_policy.authority,
            result=TraceResult.PASS,
            execution_id=execution_id,
            evidence_manifest_digest=target.version,
            occurred_at=occurred_at,
            score=None,
            reason_code="package_sections_valid",
        )
        decision = TraceRecord.decision(
            scope=scope,
            target=target,
            policy=package_policy,
            execution_id=execution_id,
            occurred_at=occurred_at,
            parents=(obs, *parents),
        )
        return (await TraceEmitter(repository).emit_many((obs, decision)))[-1].record_id

    @staticmethod
    def _readiness(
        *,
        policy: Any,
        coverage: PersonalReportPackageInputCoverage,
        section_blockers: list[PersonalReportPackageReadinessBlocker] | None = None,
    ) -> PersonalReportPackageReadinessResponse:
        blockers = [*_policy_blockers(policy), *(section_blockers or [])]
        if coverage.unproven_input_count:
            blockers.append(
                _blocker(
                    "unproven_package_input",
                    "One or more report-contributing inputs do not have a current authoritative decision. Generate only a draft until each input is re-established.",
                    label="Unproven package input",
                    count=coverage.unproven_input_count,
                    href="/audit",
                )
            )
        if blockers:
            state, label, href = PersonalReportPackageReadinessState.BLOCKED, "Blocked", blockers[0].action_href
        elif coverage.authoritative_input_count + coverage.unproven_input_count:
            state, label, href = PersonalReportPackageReadinessState.READY, "Ready", "/reports?tab=package"
        else:
            state, label, href = PersonalReportPackageReadinessState.DRAFT, "Draft", "/upload"
        return PersonalReportPackageReadinessResponse(
            package_id=PERSONAL_REPORT_PACKAGE_CONTRACT["package_id"],
            state=state,
            label=label,
            action_href=href,
            blocking_count=sum(b.count for b in blockers),
            blockers=blockers,
            input_coverage=coverage,
        )

    async def _sections(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        framework_id: PersonalReportingFrameworkId,
        start_date: date,
        end_date: date,
        as_of_date: date,
        currency: str,
        include_restricted: bool,
        decisions_by_source_id: dict[str, Any],
        contributions: tuple[PackageSectionContribution[Any], ...],
        cash_inputs: PackageCashInputs,
    ) -> PersonalReportPackageSections:
        del contributions
        bs = await assemble_framework_balance_sheet(
            db,
            user_id,
            framework_id=framework_id,
            as_of_date=as_of_date,
            currency=currency,
            include_restricted=include_restricted,
            decisions_by_source_id=decisions_by_source_id,
        )
        inc = await assemble_framework_income_statement(
            db,
            user_id,
            framework_id=framework_id,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
            decisions_by_source_id=decisions_by_source_id,
            ending_unrealized_fx_gain_loss=bs.get("unrealized_fx_gain_loss") if end_date == as_of_date else None,
        )
        cf = await generate_cash_flow(
            db,
            user_id,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
            cash_account_ids=cash_inputs.account_ids,
        )
        inv = await self._investment_performance(
            db, user_id=user_id, start_date=start_date, end_date=end_date, as_of_date=as_of_date, currency=currency
        )
        ann = await generate_annualized_income_schedule(db, user_id, as_of_date=as_of_date, currency=currency)
        return PersonalReportPackageSections(
            balance_sheet=BalanceSheetResponse.model_validate(bs),
            income_statement=IncomeStatementResponse.model_validate(inc),
            cash_flow=CashFlowResponse.model_validate(cf),
            investment_performance=inv,
            annualized_income_long_term=ann,
            notes=PersonalReportPackageNotesResponse.model_validate(PERSONAL_REPORT_PACKAGE_NOTES),
            traceability_appendix=PersonalReportPackageTraceabilityResponse.model_validate(
                PERSONAL_REPORT_PACKAGE_TRACEABILITY
            ),
        )

    async def _contributions(
        self, db: AsyncSession, *, user_id: UUID, start_date: date, end_date: date, as_of_date: date
    ) -> tuple[PackageSectionContribution[Any], ...]:
        from src.ledger import list_opening_positions

        openings = await list_opening_positions(db, user_id=user_id, as_of=as_of_date)
        stmts = await self._statement_contributions(
            db, user_id=user_id, start_date=start_date, end_date=end_date, as_of_date=as_of_date
        )
        journals = await list_journal_contributions(db, user_id=user_id, start_date=date.min, end_date=as_of_date)
        vals = await resolve_manual_valuation_contributions(
            db, user_id=user_id, as_of=as_of_date, policy=ResolutionPolicy()
        )
        return (
            *stmts,
            *(_journal_section_contribution(j, start_date=start_date, end_date=end_date) for j in journals),
            *(_valuation_section_contribution(v) for v in vals),
            *(_opening_section_contribution(p) for p in sorted(openings, key=lambda pos: str(pos.account_id))),
        )

    @staticmethod
    async def _statement_contributions(
        db: AsyncSession, *, user_id: UUID, start_date: date, end_date: date, as_of_date: date
    ) -> tuple[PackageSectionContribution[Any], ...]:
        results = await list_statement_contributions(db, user_id=user_id, as_of=date.max)
        return tuple(
            item
            for item in (
                _statement_section_contribution(r, start_date=start_date, end_date=end_date, as_of_date=as_of_date)
                for r in results
            )
            if (item.payload.effective_period_end is not None and item.payload.effective_period_end <= as_of_date)
            or "income_statement" in item.section_ids
        )

    @staticmethod
    async def _investment_performance(
        db: AsyncSession, *, user_id: UUID, start_date: date, end_date: date, as_of_date: date, currency: str
    ) -> InvestmentPerformanceReportScheduleResponse:
        return InvestmentPerformanceReportScheduleResponse.model_validate(
            await build_investment_performance_report_schedule(
                db, user_id, period_start=start_date, period_end=end_date, as_of_date=as_of_date, currency=currency
            )
        )

    async def _with_market_contributions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        base_contributions: tuple[PackageSectionContribution[Any], ...],
        investment_performance: InvestmentPerformanceReportScheduleResponse,
    ) -> tuple[PackageSectionContribution[Any], ...]:
        market = await self._selected_market_contributions(
            db, user_id=user_id, selections=investment_performance.market_valuation_selections
        )
        return (*base_contributions, *market)

    async def _evidence_contributions(
        self, db: AsyncSession, *, user_id: UUID, start_date: date, end_date: date, as_of_date: date, currency: str
    ) -> tuple[PackageSectionContribution[Any], ...]:
        base = await self._contributions(
            db, user_id=user_id, start_date=start_date, end_date=end_date, as_of_date=as_of_date
        )
        inv = await self._investment_performance(
            db, user_id=user_id, start_date=start_date, end_date=end_date, as_of_date=as_of_date, currency=currency
        )
        return await self._with_market_contributions(
            db, user_id=user_id, base_contributions=base, investment_performance=inv
        )

    async def line_details(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        start_date: date,
        end_date: date,
        as_of_date: date,
        currency: str,
        line_id: str,
        anchor: PersonalReportPackageTraceabilityAnchorName,
    ) -> list[dict[str, str | Decimal | None]] | None:
        if line_id not in {line["line_id"] for line in PERSONAL_REPORT_PACKAGE_TRACEABILITY["lines"]}:
            return None
        appendix = await _traceability_appendix(
            await self._evidence_contributions(
                db, user_id=user_id, start_date=start_date, end_date=end_date, as_of_date=as_of_date, currency=currency
            )
        )
        line = next(line for line in appendix.lines if line.line_id == line_id)
        return getattr(line, anchor.value).details

    async def manifest_entries(
        self, db: AsyncSession, *, user_id: UUID, start_date: date, end_date: date, as_of_date: date, currency: str
    ) -> list[PersonalReportPackageTraceManifestEntry]:
        async with shared_current_authority(db, TraceScope.tenant(user_id)):
            manifest, _ = await self._input_manifest(
                db,
                user_id=user_id,
                contributions=await self._evidence_contributions(
                    db,
                    user_id=user_id,
                    start_date=start_date,
                    end_date=end_date,
                    as_of_date=as_of_date,
                    currency=currency,
                ),
            )
        return manifest

    async def policy_decisions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        framework_id: PersonalReportingFrameworkId,
        start_date: date,
        end_date: date,
        as_of_date: date,
    ) -> list[FrameworkPolicyDecision]:
        return (
            await derive_user_framework_policy_result(
                db,
                user_id,
                framework_id=framework_id,
                report_period_start=start_date,
                report_period_end=end_date,
                as_of_date=as_of_date,
            )
        ).decisions

    async def cash_flow_events(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        start_date: date,
        end_date: date,
        as_of_date: date,
        currency: str,
        line_id: str,
    ) -> list[dict[str, object]] | None:
        stmts = await self._statement_contributions(
            db, user_id=user_id, start_date=start_date, end_date=end_date, as_of_date=as_of_date
        )
        return await cash_flow_line_events(
            db,
            user_id,
            line_id=line_id,
            start_date=start_date,
            end_date=end_date,
            currency=currency,
            cash_account_ids=_cash_inputs_from_contributions(stmts).account_ids,
        )

    async def _selected_market_contributions(
        self, db: AsyncSession, *, user_id: UUID, selections: list[Any]
    ) -> tuple[PackageSectionContribution[Any], ...]:
        policy = ResolutionPolicy(max_age_days=0)
        return tuple(
            [
                _valuation_section_contribution(
                    await resolve_selected_market_valuation_contribution(
                        db,
                        user_id=user_id,
                        selection=MarketValuationSelection(
                            subject=PriceableSubject.security(s.asset_identifier),
                            observation_id=s.observation_id,
                            requested_as_of=s.requested_as_of,
                        ),
                        policy=policy,
                    )
                )
                for s in selections
            ]
        )

    async def _input_manifest(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        contributions: tuple[PackageSectionContribution[Any], ...],
    ) -> tuple[list[PersonalReportPackageTraceManifestEntry], list[str]]:
        by_decision: dict[UUID, list[PackageSectionContribution[Any]]] = defaultdict(list)
        unproven: set[str] = set()
        for contribution in contributions:
            if contribution.is_authoritative and contribution.decision is not None:
                by_decision[contribution.decision.decision_id].append(contribution)
            else:
                unproven.update(contribution.input_refs)
        if not by_decision:
            return [], sorted(unproven)
        current_decisions = {
            did: dict(row._mapping)
            for did, row in (
                await current_authoritative_trace_decisions(db, TraceScope.tenant(user_id), by_decision)
            ).items()
        }
        accepted: dict[UUID, set[str]] = defaultdict(set)
        for did, items in by_decision.items():
            cur = current_decisions.get(did)
            for c in items:
                if c.decision is None or cur is None or not self._decision_coordinates_match(cur, c.decision):
                    unproven.update(c.input_refs)
                else:
                    accepted[did].update(c.input_refs)
        manifest = [
            PersonalReportPackageTraceManifestEntry(
                decision_id=did,
                input_refs=sorted(accepted[did]),
                **{k: current_decisions[did][k] for k in _COORD_KEYS},
            )
            for did in sorted(accepted, key=str)
        ]
        return manifest, sorted(unproven)

    @staticmethod
    def _decision_coordinates_match(current: dict[str, Any], expected: TraceDecisionRef) -> bool:
        return (
            current["decision_id"] == expected.decision_id
            and current["target_kind"] == expected.target.kind
            and current["target_id"] == expected.target.id
            and current["target_version"] == expected.target.version
            and current["assertion_kind"] == expected.assertion.kind
            and current["assertion_id"] == expected.assertion.id
            and current["assertion_version"] == expected.assertion.version
        )


async def _traceability_appendix(
    contributions: tuple[PackageSectionContribution[Any], ...],
) -> PersonalReportPackageTraceabilityResponse:
    return PersonalReportPackageTraceabilityResponse.model_validate(
        await build_personal_report_package_traceability_payload(contributions=contributions)
    )


def _anchor_summary(anchor: PersonalReportPackageTraceabilityAnchor) -> PersonalReportPackageTraceabilityAnchorSummary:
    return PersonalReportPackageTraceabilityAnchorSummary(
        state=anchor.state,
        source_types=anchor.source_types,
        entry_statuses=anchor.entry_statuses,
        identifier_fields=anchor.identifier_fields,
        unavailable_reason=anchor.unavailable_reason,
        detail_count=len(anchor.details),
    )


def traceability_summary(
    appendix: PersonalReportPackageTraceabilityResponse,
) -> PersonalReportPackageTraceabilitySummaryResponse:
    return PersonalReportPackageTraceabilitySummaryResponse(
        section_id=appendix.section_id,
        label=appendix.label,
        status=appendix.status,
        lines=[
            PersonalReportPackageTraceabilityLineSummary(
                **line.model_dump(exclude={"source_anchor", "ledger_anchor"}),
                source_anchor=_anchor_summary(line.source_anchor),
                ledger_anchor=_anchor_summary(line.ledger_anchor),
            )
            for line in appendix.lines
        ],
        completeness_warnings=appendix.completeness_warnings,
    )


def framework_policy_preview(policy: FrameworkPolicyResult) -> FrameworkPolicyPreview:
    return FrameworkPolicyPreview(
        **{
            **dict(policy),
            "decisions": policy.decisions[:PACKAGE_POLICY_PREVIEW_DECISIONS],
            "decision_count": len(policy.decisions),
            "evidence_reference_count": len(package_evidence_references(policy)),
        }
    )


def package_preview(document: PersonalReportPackageDocument) -> PersonalReportPackagePreview:
    if document.lifecycle is not PersonalReportPackageDocumentLifecycle.PREVIEW:
        raise ValueError("only a preview document has a preview payload")
    if document.status is not PersonalReportPackageSnapshotStatus.DRAFT:
        raise ValueError("a preview document has no package decision, so its status is draft")
    s = document.sections
    return PersonalReportPackagePreview(
        schema_version=document.schema_version,
        lifecycle=document.lifecycle,
        generated_at=document.generated_at,
        package_id=document.package_id,
        status=PersonalReportPackageSnapshotStatus.DRAFT,
        context=document.context,
        contract=document.contract,
        readiness=document.readiness,
        framework_policy=framework_policy_preview(document.framework_policy),
        statement_disposition_policy=document.statement_disposition_policy,
        sections=PersonalReportPackagePreviewSections(
            balance_sheet=s.balance_sheet,
            income_statement=s.income_statement,
            cash_flow=CashFlowPreview.model_validate(cash_flow_preview(s.cash_flow.model_dump())),
            investment_performance=s.investment_performance,
            annualized_income_long_term=s.annualized_income_long_term,
            notes=s.notes,
            traceability_appendix=traceability_summary(s.traceability_appendix),
        ),
    )


async def report_coverage(db: AsyncSession, *, user_id: UUID, as_of: date) -> CashCoverage:
    latest_end: list[date | None] = []
    custody_ids = await coverage_bank_custody_account_ids(
        db, user_id=user_id, as_of=as_of, out_latest_approved_end=latest_end
    )
    return await cash_coverage(
        db,
        user_id,
        as_of=as_of,
        cash_account_id_sets=(None, custody_ids),
        latest_statement_end=latest_end[0] if latest_end else None,
    )


async def current_package_readiness(
    db: AsyncSession, *, user_id: UUID, as_of_date: date | None = None
) -> PersonalReportPackageReadinessResponse:
    report_end = as_of_date or date.today()
    report_start = report_end - timedelta(days=365)
    coverage_start = (await report_coverage(db, user_id=user_id, as_of=report_end)).start
    if coverage_start is not None and report_start < coverage_start <= report_end:
        report_start = coverage_start
    return await PackageAssembler().evaluate_readiness(
        db,
        user_id=user_id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=report_start,
        end_date=report_end,
        as_of_date=report_end,
        currency=await get_effective_base_currency(db, user_id=user_id),
    )
