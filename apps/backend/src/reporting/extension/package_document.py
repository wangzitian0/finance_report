"""Assembly of the sole typed personal-report delivery document."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
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
from src.config import settings
from src.extraction import (
    StatementSourceType,
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
from src.reporting.base.cash_flow_types import CashFlowResponse
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
from src.reporting.extension.cash_flow import cash_flow_proof_reason_text, generate_cash_flow
from src.reporting.extension.framework_policy import derive_user_framework_policy_result
from src.reporting.extension.framework_report import (
    assemble_framework_balance_sheet,
    assemble_framework_income_statement,
)
from src.reporting.extension.report_traceability import build_personal_report_package_traceability_payload
from src.schemas.portfolio import InvestmentPerformanceReportScheduleResponse
from src.schemas.reporting import (
    BalanceSheetResponse,
    ExcludedHoldingRow,
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


def personal_report_package_decision_ref(document: PersonalReportPackageDocument) -> TraceDecisionRef:
    """Reconstruct exact audit coordinates from one selected frozen document."""
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
            sections=document.sections.model_dump(mode="json"),
        ),
        assertion=PackageReadinessDecisionPolicy().assertion,
    )


def _contract(framework_id: PersonalReportingFrameworkId) -> PersonalReportPackageContractResponse:
    payload = dict(PERSONAL_REPORT_PACKAGE_CONTRACT)
    payload["selected_framework_id"] = framework_id.value
    return PersonalReportPackageContractResponse.model_validate(payload)


async def _package_statement_disposition_policy(
    db: AsyncSession, user_id: UUID
) -> PersonalReportPackageStatementDispositionPolicy:
    """Adapt extraction's published snapshot without reconstructing policy semantics here.

    The score gate depends on the setting ``auto_accept_ai_suggestions`` of the user (#2405). The package
    discloses the gate that is in force when the package is generated. An entry that was posted under another
    setting keeps its own policy version in its decision record.
    """
    snapshot = current_statement_disposition_policy_snapshot(
        policy=await statement_disposition_policy_for_user(db, user_id)
    )
    return PersonalReportPackageStatementDispositionPolicy.model_validate(
        {
            **snapshot.semantic_payload(),
            "semantic_digest": snapshot.semantic_digest,
        }
    )


RESTRICTED_ASSET_TREATMENT_NOTE_ID = "restricted-asset-treatment"


def _excluded_holding_text(row: ExcludedHoldingRow, currency: str) -> str:
    label = row.asset_class.replace("_", " ")
    if row.net_worth is None or row.total_assets is None or row.total_liabilities is None:
        pairs = ", ".join(sorted({f"{w['currency']} to {w['target_currency']}" for w in row.warnings}))
        return f"{label}: amount not available, no FX rate for {pairs}"
    return (
        f"{label} {currency} {row.net_worth:,.2f} net "
        f"(assets {currency} {row.total_assets:,.2f}, liabilities {currency} {row.total_liabilities:,.2f})"
    )


def _restricted_asset_treatment_disclosure(
    base_disclosure: str,
    *,
    include_restricted: bool,
    excluded_holdings: list[ExcludedHoldingRow],
    currency: str,
) -> str:
    """Name the scope of this package and each excluded class with its amount (#2645).

    The liquid scope excludes restricted and illiquid valuations and the liabilities of
    their class, for example a mortgage with its property. The package states each
    excluded class, so the reader can reconcile the total to the full net worth.
    """
    if include_restricted:
        return f"{base_disclosure} This package includes restricted and illiquid holdings in the balance sheet."
    if not excluded_holdings:
        return f"{base_disclosure} This package excludes no restricted or illiquid holding: none is recorded."
    rows = "; ".join(_excluded_holding_text(row, currency) for row in excluded_holdings)
    return (
        f"{base_disclosure} This package excludes these restricted and illiquid holdings, with the "
        f"liabilities of their class, from the balance sheet: {rows}."
    )


def _package_notes(
    statement_disposition_policy: PersonalReportPackageStatementDispositionPolicy,
    *,
    balance_sheet: BalanceSheetResponse,
    include_restricted: bool,
) -> PersonalReportPackageNotesResponse:
    payload = dict(PERSONAL_REPORT_PACKAGE_NOTES)
    payload["notes"] = [
        *(
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
            for note in PERSONAL_REPORT_PACKAGE_NOTES["notes"]
        ),
        {
            "note_id": "statement-disposition-policy",
            "label": "Statement Disposition Policy",
            "owner_epic": "EPIC-018",
            "basis": "immutable_statement_disposition_policy_snapshot",
            "source_state": "frozen_runtime_policy_snapshot",
            "applies_to_sections": ["balance_sheet", "income_statement", "cash_flow", "traceability_appendix"],
            "disclosure": (
                f"Statement disposition policy {statement_disposition_policy.policy_version} ran in "
                f"{statement_disposition_policy.mode} mode. Machine authority threshold is "
                f"{statement_disposition_policy.machine_confidence_threshold}; P&L authority threshold is "
                f"{statement_disposition_policy.pnl_effect_confidence_threshold}. Unknown and ambiguous intent "
                f"route to review. Live LLM proposals are "
                f"{'enabled' if statement_disposition_policy.live_llm_proposals_enabled else 'disabled'}. "
                + (
                    "At the time of this package the system accepts AI suggestions at any score for this user. "
                    "Entries posted under that setting carry a low confidence tier, and a row that the AI could "
                    "not place sits in a general account. The decision record of each entry names the policy "
                    "version that ran. "
                    if statement_disposition_policy.machine_confidence_threshold == 0
                    else ""
                )
                + f"Deployment commit: {statement_disposition_policy.deployment_git_sha}."
            ),
        },
    ]
    return PersonalReportPackageNotesResponse.model_validate(payload)


def _policy_decisions_by_source_id(policy: Any) -> dict[str, Any]:
    decisions_by_source_id: dict[str, Any] = {}
    for decision in policy.decisions:
        for anchor in decision.evidence_anchors:
            decisions_by_source_id[str(anchor.source_id)] = decision
    return decisions_by_source_id


def _statement_section_contribution(
    contribution: Any,
    *,
    start_date: date,
    end_date: date,
    as_of_date: date | None = None,
) -> PackageSectionContribution[Any]:
    """Map immutable source facts to only the package sections they can support."""
    sections: list[PackageSectionId] = ["traceability_appendix"]
    result = contribution.source_result
    if result is not None:
        stock_is_current = contribution.effective_period_end is not None and contribution.effective_period_end <= (
            as_of_date or end_date
        )
        if stock_is_current and (result.balances or result.transactions):
            sections.append("balance_sheet")
        if stock_is_current and result.positions:
            sections.extend(("balance_sheet", "investment_performance"))
        overlaps_period = (
            contribution.effective_period_start is not None
            and contribution.effective_period_end is not None
            and contribution.effective_period_start <= end_date
            and contribution.effective_period_end >= start_date
        )
        has_period_movement = any(
            start_date <= fact.transaction_date <= min(end_date, as_of_date or end_date) for fact in result.transactions
        )
        if has_period_movement and overlaps_period:
            sections.extend(("cash_flow", "income_statement", "annualized_income_long_term"))
    input_refs = contribution.input_refs or (f"statement:{contribution.statement_id}",)
    return PackageSectionContribution(
        contribution_type="statement_source",
        section_ids=tuple(dict.fromkeys(sections)),
        payload=contribution,
        state=contribution.state,
        decision=contribution.decision,
        input_refs=input_refs,
        reason_code=contribution.reason_code,
    )


def _journal_section_contribution(
    contribution: Any,
    *,
    start_date: date,
    end_date: date,
) -> PackageSectionContribution[Any]:
    """Include historical journal facts for position sections, period facts for flows."""
    sections: list[PackageSectionId] = ["balance_sheet", "traceability_appendix"]
    if start_date <= contribution.entry_date <= end_date:
        sections.append("cash_flow")
        if any(line.account_type.value.lower() in {"income", "expense"} for line in contribution.lines):
            sections.extend(("income_statement", "annualized_income_long_term"))
    return PackageSectionContribution(
        contribution_type="ledger_command",
        section_ids=tuple(dict.fromkeys(sections)),
        payload=contribution,
        state=contribution.state,
        decision=contribution.decision,
        input_refs=contribution.input_refs,
        reason_code=contribution.reason_code,
    )


def _opening_section_contribution(position: Any) -> PackageSectionContribution[Any]:
    """Keep even a zero, journal-free initialization in the package authority manifest."""
    return PackageSectionContribution(
        contribution_type="opening_position",
        section_ids=("balance_sheet", "cash_flow", "traceability_appendix"),
        payload=position,
        state=position.state,
        decision=position.decision,
        input_refs=(f"opening_position:{position.account_id}",),
        reason_code=position.reason_code,
    )


def _valuation_section_contribution(contribution: Any) -> PackageSectionContribution[Any]:
    input_refs = contribution.input_refs
    if not input_refs:
        identity = contribution.lineage_id or f"{contribution.subject.kind.value}:{contribution.subject.key}"
        input_refs = (f"valuation:{identity}",)
    if contribution.subject.kind.value == "security":
        sections = cast(
            tuple[PackageSectionId, ...],
            ("balance_sheet", "investment_performance", "traceability_appendix"),
        )
    else:
        sections = cast(
            tuple[PackageSectionId, ...],
            ("balance_sheet", "annualized_income_long_term", "traceability_appendix"),
        )
    return PackageSectionContribution(
        contribution_type="valuation",
        section_ids=sections,
        payload=contribution,
        state=contribution.state,
        decision=contribution.decision,
        input_refs=input_refs,
        reason_code=contribution.reason_code,
    )


def _cash_inputs_from_contributions(
    contributions: tuple[PackageSectionContribution[Any], ...],
) -> PackageCashInputs:
    """Select exact bank custody accounts without interpreting names as facts."""
    account_ids: set[UUID] = set()
    input_refs: set[str] = set()
    has_unproven_bank_input = False
    for contribution in contributions:
        if contribution.contribution_type != "statement_source":
            continue
        payload = contribution.payload
        result = getattr(payload, "source_result", None)
        if result is None or result.source_type is not StatementSourceType.BANK:
            continue
        account_id = getattr(payload, "account_id", None)
        if contribution.is_authoritative and account_id is not None:
            account_ids.add(account_id)
            input_refs.update(contribution.input_refs)
        else:
            has_unproven_bank_input = True
            input_refs.update(contribution.input_refs)
    if has_unproven_bank_input:
        return PackageCashInputs(
            account_ids=frozenset(account_ids),
            input_refs=tuple(sorted(input_refs)),
            reason_code="cash_balance_input_unproven",
        )
    if not account_ids:
        return PackageCashInputs.missing()
    return PackageCashInputs(
        account_ids=frozenset(account_ids),
        input_refs=tuple(sorted(input_refs)),
    )


def _unproven_input_blocker(count: int) -> PersonalReportPackageReadinessBlocker:
    return PersonalReportPackageReadinessBlocker(
        code="unproven_package_input",
        label="Unproven package input",
        severity="blocking",
        count=count,
        reason=(
            "One or more report-contributing inputs do not have a current authoritative "
            "decision. Generate only a draft until each input is re-established."
        ),
        action_href="/review",
    )


def _policy_blockers(policy: Any) -> list[PersonalReportPackageReadinessBlocker]:
    """Use explicit framework policy gaps; never infer authority from source labels."""
    grouped: dict[str, int] = defaultdict(int)
    for gap in policy.gaps:
        if gap.blocker:
            grouped[gap.code] += 1
    return [
        PersonalReportPackageReadinessBlocker(
            code=code,
            label="Unsupported policy domain" if code == "unsupported_policy_domain" else "Framework policy gap",
            severity="blocking",
            count=count,
            reason="An explicit framework policy gap must be resolved before the package is trusted.",
            action_href="/reports/package",
        )
        for code, count in sorted(grouped.items())
    ]


def _section_blocker(code: str, reason: str) -> PersonalReportPackageReadinessBlocker:
    return PersonalReportPackageReadinessBlocker(
        code=code,
        label="Package section invariant failed",
        severity="blocking",
        count=1,
        reason=reason,
        action_href="/reports/package",
    )


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
    """Prove cross-section accounting and context before authority emission."""
    blockers: list[PersonalReportPackageReadinessBlocker] = []
    balance_sheet = sections.balance_sheet
    income_statement = sections.income_statement
    cash_flow = sections.cash_flow
    investment = sections.investment_performance
    annualized = sections.annualized_income_long_term
    if not balance_sheet.is_balanced or abs(balance_sheet.equation_delta) >= Decimal("0.01"):
        blockers.append(_section_blocker("balance_sheet_equation_failed", "The balance sheet does not balance."))
    if balance_sheet.net_income != cumulative_net_income or income_statement.net_income != period_net_income:
        blockers.append(
            _section_blocker(
                "statement_net_income_mismatch",
                "Statement net income differs from the ledger for its cumulative or selected period.",
            )
        )
    cash_rollforward = cash_flow.summary.ending_cash - cash_flow.summary.beginning_cash
    opening_adjustment = cash_flow.cash_bridge.opening_stock_adjustment if cash_flow.cash_bridge else Decimal("0")
    if cash_rollforward != cash_flow.summary.net_cash_flow + opening_adjustment:
        blockers.append(
            _section_blocker(
                "cash_flow_rollforward_failed",
                "Beginning cash plus net cash flow and opening balance adjustment does not equal ending cash.",
            )
        )
    # An empty package asserts no financial facts. Enforce cash-event proof
    # once at least one authoritative or unproven package input is projected.
    if contributions and cash_flow.proof_state != "proven":
        reason_code = cash_flow.proof_reasons[0] if cash_flow.proof_reasons else "cash_flow_unproven"
        blockers.append(
            _section_blocker(
                reason_code,
                cash_flow_proof_reason_text(reason_code),
            )
        )
    # Once any package input exists, a zero cash balance also requires exact
    # source evidence.
    if contributions and not cash_inputs.is_complete:
        blockers.append(
            _section_blocker(
                cash_inputs.reason_code or "cash_balance_input_unproven",
                "Cash balances require an authoritative bank-statement custody account input.",
            )
        )
    if balance_sheet.opening_balance_warnings:
        blockers.append(
            _section_blocker(
                "opening_balance_missing",
                "Recorded activity is missing an opening balance required for a complete statement.",
            )
        )
    if balance_sheet.portfolio_warnings:
        blockers.append(
            _section_blocker(
                "portfolio_value_incomplete",
                "One or more selected positions lack a point-in-time value.",
            )
        )
    if investment.data_freshness.stale:
        blockers.append(
            _section_blocker(
                "investment_market_data_stale",
                "The selected investment schedule uses stale market data.",
            )
        )
    if getattr(investment, "holdings", ()) and not any(
        contribution.is_authoritative and "investment_performance" in contribution.section_ids
        for contribution in contributions
    ):
        blockers.append(
            _section_blocker(
                "investment_contribution_missing",
                "Investment holdings have no current authoritative source contribution.",
            )
        )
    period_matches = (
        balance_sheet.as_of_date == as_of_date
        and income_statement.start_date == start_date
        and income_statement.end_date == end_date
        and cash_flow.start_date == start_date
        and cash_flow.end_date == end_date
        and investment.period_start == start_date
        and investment.period_end == end_date
        and investment.as_of_date == as_of_date
        and annualized.as_of_date == as_of_date
    )
    if not period_matches:
        blockers.append(_section_blocker("section_period_mismatch", "A section does not match the document period."))
    section_currencies = {
        balance_sheet.currency,
        income_statement.currency,
        cash_flow.currency,
        investment.currency,
        annualized.income.currency,
        annualized.restricted_fair_value_total_currency,
    }
    if section_currencies != {currency}:
        blockers.append(
            _section_blocker("section_currency_mismatch", "Every package section must use the document currency.")
        )
    return blockers


@dataclass(frozen=True)
class _PackageEvaluation:
    """Readiness and the inputs that ``assemble`` reuses for display sections and the decision."""

    policy: Any
    contributions: tuple[PackageSectionContribution[Any], ...]
    sections: PersonalReportPackageSections
    input_manifest: list[PersonalReportPackageTraceManifestEntry]
    readiness: PersonalReportPackageReadinessResponse


class PackageAssembler:
    """Build one preview/frozen document without router-local section aggregation."""

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
        """Assemble the document and fail closed on unanchored contributing inputs."""
        evaluation = await self._evaluate(
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
        statement_disposition_policy = await _package_statement_disposition_policy(db, user_id)
        policy = evaluation.policy
        sections = evaluation.sections
        input_manifest = evaluation.input_manifest
        readiness = evaluation.readiness
        sections.traceability_appendix = await _traceability_appendix(evaluation.contributions)
        sections.notes = _package_notes(
            statement_disposition_policy,
            balance_sheet=sections.balance_sheet,
            include_restricted=include_restricted,
        )
        now = datetime.now(UTC)
        package_decision_id = None
        if (
            lifecycle is PersonalReportPackageDocumentLifecycle.FROZEN
            and readiness.state is PersonalReportPackageReadinessState.READY
        ):
            if snapshot_id is None or frozen_at is None:
                raise ValueError("frozen package assembly requires snapshot_id and frozen_at")
            package_decision_id = await self._emit_package_decision(
                db,
                user_id=user_id,
                snapshot_id=snapshot_id,
                occurred_at=frozen_at,
                context={
                    "framework_id": framework_id.value,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "as_of_date": as_of_date.isoformat(),
                    "currency": currency,
                },
                framework_policy=policy.model_dump(mode="json"),
                statement_disposition_policy=statement_disposition_policy.model_dump(mode="json"),
                input_manifest=input_manifest,
                sections=sections,
            )
        trusted = package_decision_id is not None
        return PersonalReportPackageDocument(
            schema_version="2",
            lifecycle=lifecycle,
            snapshot_id=snapshot_id,
            package_decision_id=package_decision_id,
            generated_at=now,
            frozen_at=frozen_at,
            package_id=contract.package_id,
            status=(
                PersonalReportPackageSnapshotStatus.TRUSTED if trusted else PersonalReportPackageSnapshotStatus.DRAFT
            ),
            context=PersonalReportPackageContext(
                framework_id=framework_id,
                start_date=start_date,
                end_date=end_date,
                as_of_date=as_of_date,
                currency=currency,
            ),
            contract=contract,
            readiness=readiness,
            framework_policy=policy,
            statement_disposition_policy=statement_disposition_policy,
            input_manifest=input_manifest,
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
        """Return the readiness that ``assemble`` returns for the same arguments.

        This path does not build the traceability appendix, the notes, or a package decision.
        Readiness does not read these sections (#2583).
        """
        evaluation = await self._evaluate(
            db,
            user_id=user_id,
            framework_id=framework_id,
            start_date=start_date,
            end_date=end_date,
            as_of_date=as_of_date,
            currency=currency,
            include_restricted=include_restricted,
        )
        return evaluation.readiness

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
        """Compute every readiness input and the readiness. This is the one readiness path.

        Every current-authority read of the evaluation uses one read of the projection (#2602).
        """
        async with shared_current_authority(db, TraceScope.tenant(user_id)):
            policy = await derive_user_framework_policy_result(
                db,
                user_id,
                framework_id=framework_id,
                report_period_start=start_date,
                report_period_end=end_date,
                as_of_date=as_of_date,
            )
            decisions_by_source_id = _policy_decisions_by_source_id(policy)
            base_contributions = await self._contributions(
                db,
                user_id=user_id,
                start_date=start_date,
                end_date=end_date,
                as_of_date=as_of_date,
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
                decisions_by_source_id=decisions_by_source_id,
                contributions=base_contributions,
                cash_inputs=cash_inputs,
            )
            contributions = await self._with_market_contributions(
                db,
                user_id=user_id,
                base_contributions=base_contributions,
                investment_performance=sections.investment_performance,
            )
            input_manifest, unproven_input_refs = await self._input_manifest(
                db,
                user_id=user_id,
                contributions=contributions,
            )
            coverage = PersonalReportPackageInputCoverage(
                manifest_decision_count=len(input_manifest),
                authoritative_input_count=sum(len(item.input_refs) for item in input_manifest),
                unproven_input_count=len(unproven_input_refs),
            )
            # Position and flow sections have different periods and FX averaging
            # windows. Compare each against its matching ledger projection rather
            # than comparing lifetime income with the selected month's income.
            cumulative_net_income = _quantize_money(await _aggregate_net_income_sql(db, user_id, currency, as_of_date))
            period_net_income = _quantize_money(
                await _aggregate_net_income_sql(db, user_id, currency, end_date, start_date=start_date)
            )
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
                    cumulative_net_income=cumulative_net_income,
                    period_net_income=period_net_income,
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
        context: dict[str, str],
        framework_policy: dict[str, Any],
        statement_disposition_policy: dict[str, Any],
        input_manifest: list[PersonalReportPackageTraceManifestEntry],
        sections: PersonalReportPackageSections,
    ) -> UUID:
        """Flush the package decision without committing the caller-owned transaction."""
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
        target_version = target.version
        execution_id = f"report-package:{snapshot_id}"
        section_observation = TraceRecord.observation(
            scope=scope,
            target=target,
            target_class=TraceTargetClass.FINANCIAL,
            assertion=VersionedTraceRef(
                "package_invariant",
                "typed-sections-and-accounting",
                PACKAGE_DECISION_POLICY_VERSION,
            ),
            authority=package_policy.authority,
            result=TraceResult.PASS,
            execution_id=execution_id,
            evidence_manifest_digest=target_version,
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
            parents=(section_observation, *parents),
        )
        emitted = await TraceEmitter(repository).emit_many((section_observation, decision))
        await self._after_trace_flush()
        return emitted[-1].record_id

    async def _after_trace_flush(self) -> None:
        """Fault-injection seam; production intentionally does nothing."""

    @staticmethod
    def _readiness(
        *,
        policy: Any,
        coverage: PersonalReportPackageInputCoverage,
        section_blockers: list[PersonalReportPackageReadinessBlocker] | None = None,
    ) -> PersonalReportPackageReadinessResponse:
        blockers = [*_policy_blockers(policy), *(section_blockers or [])]
        if coverage.unproven_input_count:
            blockers.append(_unproven_input_blocker(coverage.unproven_input_count))
        input_count = coverage.authoritative_input_count + coverage.unproven_input_count
        if blockers:
            state = PersonalReportPackageReadinessState.BLOCKED
            label = "Blocked"
            action_href = blockers[0].action_href
        elif input_count:
            state = PersonalReportPackageReadinessState.READY
            label = "Ready"
            action_href = "/reports/package"
        else:
            state = PersonalReportPackageReadinessState.DRAFT
            label = "Draft"
            action_href = "/statements/upload"
        return PersonalReportPackageReadinessResponse(
            package_id=PERSONAL_REPORT_PACKAGE_CONTRACT["package_id"],
            state=state,
            label=label,
            action_href=action_href,
            blocking_count=sum(blocker.count for blocker in blockers),
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
        balance_sheet = await assemble_framework_balance_sheet(
            db,
            user_id,
            framework_id=framework_id,
            as_of_date=as_of_date,
            currency=currency,
            include_restricted=include_restricted,
            decisions_by_source_id=decisions_by_source_id,
        )
        income_statement, cash_flow, investment_performance, annualized_income = (
            await assemble_framework_income_statement(
                db,
                user_id,
                framework_id=framework_id,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
                decisions_by_source_id=decisions_by_source_id,
                ending_unrealized_fx_gain_loss=(
                    balance_sheet.get("unrealized_fx_gain_loss") if end_date == as_of_date else None
                ),
            ),
            await generate_cash_flow(
                db,
                user_id,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
                cash_account_ids=cash_inputs.account_ids,
            ),
            await self._investment_performance(
                db,
                user_id=user_id,
                start_date=start_date,
                end_date=end_date,
                as_of_date=as_of_date,
                currency=currency,
            ),
            await generate_annualized_income_schedule(db, user_id, as_of_date=as_of_date, currency=currency),
        )
        return PersonalReportPackageSections(
            balance_sheet=BalanceSheetResponse.model_validate(balance_sheet),
            income_statement=IncomeStatementResponse.model_validate(income_statement),
            cash_flow=CashFlowResponse.model_validate(cash_flow),
            investment_performance=investment_performance,
            annualized_income_long_term=annualized_income,
            notes=PersonalReportPackageNotesResponse.model_validate(PERSONAL_REPORT_PACKAGE_NOTES),
            traceability_appendix=PersonalReportPackageTraceabilityResponse.model_validate(
                PERSONAL_REPORT_PACKAGE_TRACEABILITY
            ),
        )

    async def _contributions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        start_date: date,
        end_date: date,
        as_of_date: date,
    ) -> tuple[PackageSectionContribution[Any], ...]:
        """Adapt package-owned DTOs; never reconstruct their authority locally."""
        from src.ledger import list_opening_positions

        opening_results = await list_opening_positions(db, user_id=user_id, as_of=as_of_date)
        # Extraction's as_of filter selects closing stock. Movement evidence can
        # belong to a statement that closes later, so select its sections here.
        statement_results = await list_statement_contributions(db, user_id=user_id, as_of=date.max)
        statement_contributions = tuple(
            _statement_section_contribution(item, start_date=start_date, end_date=end_date, as_of_date=as_of_date)
            for item in statement_results
        )
        journal_results = await list_journal_contributions(
            db,
            user_id=user_id,
            start_date=date.min,
            end_date=as_of_date,
        )
        valuation_results = await resolve_manual_valuation_contributions(
            db,
            user_id=user_id,
            as_of=as_of_date,
            policy=ResolutionPolicy(),
        )
        return (
            *(
                item
                for item in statement_contributions
                if (item.payload.effective_period_end is not None and item.payload.effective_period_end <= as_of_date)
                or "income_statement" in item.section_ids
            ),
            *(
                _journal_section_contribution(item, start_date=start_date, end_date=end_date)
                for item in journal_results
            ),
            *(_valuation_section_contribution(item) for item in valuation_results),
            # The ledger read leaves accounts of equal version in database order. Each evidence page
            # is a new request, so the package fixes one order: one position per account (#2583 S8).
            *(
                _opening_section_contribution(item)
                for item in sorted(opening_results, key=lambda position: str(position.account_id))
            ),
        )

    @staticmethod
    async def _investment_performance(
        db: AsyncSession,
        *,
        user_id: UUID,
        start_date: date,
        end_date: date,
        as_of_date: date,
        currency: str,
    ) -> InvestmentPerformanceReportScheduleResponse:
        """Return the investment schedule. Its market selections are package contributions."""
        return InvestmentPerformanceReportScheduleResponse.model_validate(
            await build_investment_performance_report_schedule(
                db,
                user_id,
                period_start=start_date,
                period_end=end_date,
                as_of_date=as_of_date,
                currency=currency,
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
        """Add the market prices that the investment schedule shows. The result is the package contribution set."""
        market_contributions = await self._selected_market_contributions(
            db,
            user_id=user_id,
            selections=investment_performance.market_valuation_selections,
        )
        return (*base_contributions, *market_contributions)

    async def _evidence_contributions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        start_date: date,
        end_date: date,
        as_of_date: date,
        currency: str,
    ) -> tuple[PackageSectionContribution[Any], ...]:
        """Return the contribution set that ``_evaluate`` computes for the same arguments.

        The appendix and the input manifest read only this set. This path therefore does not
        build the balance sheet, the income statement, the cash flow or the readiness.
        """
        base_contributions = await self._contributions(
            db,
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            as_of_date=as_of_date,
        )
        investment_performance = await self._investment_performance(
            db,
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            as_of_date=as_of_date,
            currency=currency,
        )
        return await self._with_market_contributions(
            db,
            user_id=user_id,
            base_contributions=base_contributions,
            investment_performance=investment_performance,
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
        """Return all details of one appendix anchor, as ``assemble`` writes them. Return None for an unknown line."""
        if line_id not in {line["line_id"] for line in PERSONAL_REPORT_PACKAGE_TRACEABILITY["lines"]}:
            return None
        # Two filtered authority reads (opening positions, journal entries) read fewer rows
        # than one shared read of every current decision, so this path opens no shared block.
        appendix = await _traceability_appendix(
            await self._evidence_contributions(
                db,
                user_id=user_id,
                start_date=start_date,
                end_date=end_date,
                as_of_date=as_of_date,
                currency=currency,
            )
        )
        # The builder writes every contract line, so the line exists.
        line = next(line for line in appendix.lines if line.line_id == line_id)
        return getattr(line, anchor.value).details

    async def manifest_entries(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        start_date: date,
        end_date: date,
        as_of_date: date,
        currency: str,
    ) -> list[PersonalReportPackageTraceManifestEntry]:
        """Return the input manifest that ``assemble`` writes for the same arguments.

        The contributions and the manifest use one read of the current-authority projection (#2602).
        """
        async with shared_current_authority(db, TraceScope.tenant(user_id)):
            manifest, _unproven_input_refs = await self._input_manifest(
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

    async def _selected_market_contributions(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        selections: list[Any],
    ) -> tuple[PackageSectionContribution[Any], ...]:
        """Freeze only the exact external prices rendered by the investment schedule."""
        contributions = []
        policy = ResolutionPolicy(max_age_days=0)
        for selection in selections:
            contribution = await resolve_selected_market_valuation_contribution(
                db,
                user_id=user_id,
                selection=MarketValuationSelection(
                    subject=PriceableSubject.security(selection.asset_identifier),
                    observation_id=selection.observation_id,
                    requested_as_of=selection.requested_as_of,
                ),
                policy=policy,
            )
            contributions.append(_valuation_section_contribution(contribution))
        return tuple(contributions)

    async def _input_manifest(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        contributions: tuple[PackageSectionContribution[Any], ...],
    ) -> tuple[list[PersonalReportPackageTraceManifestEntry], list[str]]:
        """Fold exact contribution refs; display traceability never grants authority."""
        contributions_by_decision: dict[UUID, list[PackageSectionContribution[Any]]] = defaultdict(list)
        unproven_refs: set[str] = set()
        for contribution in contributions:
            if contribution.is_authoritative and contribution.decision is not None:
                contributions_by_decision[contribution.decision.decision_id].append(contribution)
            else:
                unproven_refs.update(contribution.input_refs)

        if not contributions_by_decision:
            return [], sorted(unproven_refs)
        current_decisions: dict[UUID, dict[str, Any]] = {
            decision_id: dict(row._mapping)
            for decision_id, row in (
                await current_authoritative_trace_decisions(db, TraceScope.tenant(user_id), contributions_by_decision)
            ).items()
        }
        accepted_refs_by_decision: dict[UUID, set[str]] = defaultdict(set)
        for decision_id, decision_contributions in contributions_by_decision.items():
            current = current_decisions.get(decision_id)
            for contribution in decision_contributions:
                expected = contribution.decision
                if expected is None or current is None or not self._decision_coordinates_match(current, expected):
                    unproven_refs.update(contribution.input_refs)
                    continue
                accepted_refs_by_decision[decision_id].update(contribution.input_refs)
        manifest = [
            PersonalReportPackageTraceManifestEntry(
                decision_id=decision_id,
                input_refs=sorted(accepted_refs_by_decision[decision_id]),
                **{
                    key: current_decisions[decision_id][key]
                    for key in (
                        "target_kind",
                        "target_id",
                        "target_version",
                        "assertion_kind",
                        "assertion_id",
                        "assertion_version",
                        "authority_tier",
                    )
                },
            )
            for decision_id in sorted(accepted_refs_by_decision, key=str)
        ]
        return manifest, sorted(unproven_refs)

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
    """Build the typed appendix. ``assemble`` and ``line_details`` use this one builder."""
    return PersonalReportPackageTraceabilityResponse.model_validate(
        await build_personal_report_package_traceability_payload(contributions=contributions)
    )


def _anchor_summary(
    anchor: PersonalReportPackageTraceabilityAnchor,
) -> PersonalReportPackageTraceabilityAnchorSummary:
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
    """Replace the identifiers and the details of each anchor with their count."""
    return PersonalReportPackageTraceabilitySummaryResponse(
        section_id=appendix.section_id,
        label=appendix.label,
        status=appendix.status,
        lines=[
            PersonalReportPackageTraceabilityLineSummary(
                line_id=line.line_id,
                section_id=line.section_id,
                label=line.label,
                amount_field=line.amount_field,
                currency_field=line.currency_field,
                source_state=line.source_state,
                source_anchor=_anchor_summary(line.source_anchor),
                ledger_anchor=_anchor_summary(line.ledger_anchor),
                anchor_count=line.anchor_count,
                blocker_codes=line.blocker_codes,
            )
            for line in appendix.lines
        ],
        completeness_warnings=appendix.completeness_warnings,
    )


def package_preview(document: PersonalReportPackageDocument) -> PersonalReportPackagePreview:
    """Project a preview document to the bounded preview payload (#2583).

    The appendix keeps one summary for each line. The input manifest entries are not in the
    payload: ``readiness.input_coverage`` gives their counts. A frozen document has no preview.
    """
    if document.lifecycle is not PersonalReportPackageDocumentLifecycle.PREVIEW:
        raise ValueError("only a preview document has a preview payload")
    if document.status is not PersonalReportPackageSnapshotStatus.DRAFT:
        raise ValueError("a preview document has no package decision, so its status is draft")
    sections = document.sections
    return PersonalReportPackagePreview(
        schema_version=document.schema_version,
        lifecycle=document.lifecycle,
        generated_at=document.generated_at,
        package_id=document.package_id,
        status=PersonalReportPackageSnapshotStatus.DRAFT,
        context=document.context,
        contract=document.contract,
        readiness=document.readiness,
        framework_policy=document.framework_policy,
        statement_disposition_policy=document.statement_disposition_policy,
        sections=PersonalReportPackagePreviewSections(
            balance_sheet=sections.balance_sheet,
            income_statement=sections.income_statement,
            cash_flow=sections.cash_flow,
            investment_performance=sections.investment_performance,
            annualized_income_long_term=sections.annualized_income_long_term,
            notes=sections.notes,
            traceability_appendix=traceability_summary(sections.traceability_appendix),
        ),
    )


async def current_package_readiness(
    db: AsyncSession,
    *,
    user_id: UUID,
    as_of_date: date | None = None,
) -> PersonalReportPackageReadinessResponse:
    """Evaluate readiness of the current default-framework candidate through the sole assembler."""
    report_end = as_of_date or date.today()
    return await PackageAssembler().evaluate_readiness(
        db,
        user_id=user_id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=report_end - timedelta(days=365),
        end_date=report_end,
        as_of_date=report_end,
        currency=settings.base_currency,
    )
