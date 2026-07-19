"""Assembly of the sole typed personal-report delivery document."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    SqlTraceRecordRepository,
    TraceDecisionPolicyRegistry,
    TraceEmitter,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
    current_authoritative_trace_decision_projection,
)
from src.config import settings
from src.extraction import (
    StatementSourceType,
    current_statement_disposition_policy_snapshot,
    list_statement_contributions,
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
from src.reporting.base.package_contribution import PackageCashInputs, PackageSectionContribution, PackageSectionId
from src.reporting.base.package_decision import (
    PACKAGE_DECISION_POLICY_VERSION,
    PackageReadinessDecisionPolicy,
)
from src.reporting.base.report_package_contract import (
    PERSONAL_REPORT_PACKAGE_CONTRACT,
    PERSONAL_REPORT_PACKAGE_NOTES,
)
from src.reporting.base.types import PersonalReportingFrameworkId
from src.reporting.extension.annualized_income import generate_annualized_income_schedule
from src.reporting.extension.cash_flow import generate_cash_flow
from src.reporting.extension.framework_policy import derive_user_framework_policy_result
from src.reporting.extension.framework_report import (
    assemble_framework_balance_sheet,
    assemble_framework_income_statement,
)
from src.reporting.extension.report_traceability import build_personal_report_package_traceability_payload
from src.schemas.portfolio import InvestmentPerformanceReportScheduleResponse
from src.schemas.reporting import (
    BalanceSheetResponse,
    CashFlowResponse,
    IncomeStatementResponse,
    PersonalReportPackageContext,
    PersonalReportPackageContractResponse,
    PersonalReportPackageDocument,
    PersonalReportPackageDocumentLifecycle,
    PersonalReportPackageDocumentSummary,
    PersonalReportPackageInputCoverage,
    PersonalReportPackageNotesResponse,
    PersonalReportPackageReadinessBlocker,
    PersonalReportPackageReadinessResponse,
    PersonalReportPackageReadinessState,
    PersonalReportPackageSections,
    PersonalReportPackageSnapshotStatus,
    PersonalReportPackageStatementDispositionPolicy,
    PersonalReportPackageTraceabilityResponse,
    PersonalReportPackageTraceManifestEntry,
)


def _package_document_summary(document: PersonalReportPackageDocument) -> PersonalReportPackageDocumentSummary:
    """Project one typed document without recomputing authority in the consumer."""
    if document.lifecycle is PersonalReportPackageDocumentLifecycle.FROZEN:
        if document.snapshot_id is None or document.frozen_at is None:
            raise ValueError("Frozen package document is missing durable identity metadata")
    return PersonalReportPackageDocumentSummary(
        snapshot_id=document.snapshot_id,
        package_id=document.package_id,
        lifecycle=document.lifecycle,
        status=document.status,
        context=document.context,
        readiness=document.readiness,
        generated_at=document.generated_at,
        frozen_at=document.frozen_at,
    )


def _contract(framework_id: PersonalReportingFrameworkId) -> PersonalReportPackageContractResponse:
    payload = dict(PERSONAL_REPORT_PACKAGE_CONTRACT)
    payload["selected_framework_id"] = framework_id.value
    return PersonalReportPackageContractResponse.model_validate(payload)


def _package_statement_disposition_policy() -> PersonalReportPackageStatementDispositionPolicy:
    """Adapt extraction's published snapshot without reconstructing policy semantics here."""
    snapshot = current_statement_disposition_policy_snapshot()
    return PersonalReportPackageStatementDispositionPolicy.model_validate(
        {
            **snapshot.semantic_payload(),
            "semantic_digest": snapshot.semantic_digest,
        }
    )


def _package_notes(
    statement_disposition_policy: PersonalReportPackageStatementDispositionPolicy,
) -> PersonalReportPackageNotesResponse:
    payload = dict(PERSONAL_REPORT_PACKAGE_NOTES)
    payload["notes"] = [
        *PERSONAL_REPORT_PACKAGE_NOTES["notes"],
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
                f"Deployment commit: {statement_disposition_policy.deployment_git_sha}."
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
) -> PackageSectionContribution[Any]:
    """Map immutable source facts to only the package sections they can support."""
    sections: list[PackageSectionId] = ["traceability_appendix"]
    result = contribution.source_result
    if result is not None:
        if result.balances or result.transactions:
            sections.append("balance_sheet")
        if result.positions:
            sections.extend(("balance_sheet", "investment_performance"))
        overlaps_period = (
            contribution.effective_period_start is not None
            and contribution.effective_period_end is not None
            and contribution.effective_period_start <= end_date
            and contribution.effective_period_end >= start_date
        )
        if result.transactions and overlaps_period:
            sections.extend(("cash_flow", "income_statement", "annualized_income_long_term"))
    input_refs = contribution.input_refs or (f"statement:{contribution.statement_id}",)
    return PackageSectionContribution(
        contribution_type="statement_source",
        section_ids=tuple(dict.fromkeys(sections)),
        payload=contribution,
        state=contribution.state,
        decision_id=contribution.decision_id,
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
        decision_id=contribution.decision_id,
        input_refs=contribution.input_refs,
        reason_code=contribution.reason_code,
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
        decision_id=contribution.decision_id,
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
    if balance_sheet.net_income != income_statement.net_income:
        blockers.append(
            _section_blocker("statement_net_income_mismatch", "Balance-sheet and income-statement net income differ.")
        )
    cash_rollforward = cash_flow.summary.ending_cash - cash_flow.summary.beginning_cash
    if cash_rollforward != cash_flow.summary.net_cash_flow:
        blockers.append(
            _section_blocker(
                "cash_flow_rollforward_failed", "Beginning cash plus net cash flow does not equal ending cash."
            )
        )
    if not cash_inputs.is_complete:
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
        include_restricted: bool = False,
        lifecycle: PersonalReportPackageDocumentLifecycle = PersonalReportPackageDocumentLifecycle.PREVIEW,
        snapshot_id: UUID | None = None,
        frozen_at: datetime | None = None,
    ) -> PersonalReportPackageDocument:
        """Assemble the document and fail closed on unanchored contributing inputs."""
        contract = _contract(framework_id)
        statement_disposition_policy = _package_statement_disposition_policy()
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
        market_contributions = await self._selected_market_contributions(
            db,
            user_id=user_id,
            selections=sections.investment_performance.market_valuation_selections,
        )
        contributions = (*base_contributions, *market_contributions)
        sections.traceability_appendix = PersonalReportPackageTraceabilityResponse.model_validate(
            await build_personal_report_package_traceability_payload(contributions=contributions)
        )
        sections.notes = _package_notes(statement_disposition_policy)
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
            ),
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

        semantic_payload = {
            "schema_version": "2",
            "snapshot_id": str(snapshot_id),
            "context": context,
            "framework_policy": framework_policy,
            "statement_disposition_policy": statement_disposition_policy,
            "input_manifest": [item.model_dump(mode="json") for item in input_manifest],
            "sections": sections.model_dump(mode="json"),
        }
        target_version = hashlib.sha256(
            json.dumps(semantic_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        target = VersionedTraceRef("personal_report_package", str(snapshot_id), target_version)
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
        balance_sheet, income_statement, cash_flow, investment_performance, annualized_income, traceability = (
            await assemble_framework_balance_sheet(
                db,
                user_id,
                framework_id=framework_id,
                as_of_date=as_of_date,
                currency=currency,
                include_restricted=include_restricted,
                decisions_by_source_id=decisions_by_source_id,
            ),
            await assemble_framework_income_statement(
                db,
                user_id,
                framework_id=framework_id,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
                decisions_by_source_id=decisions_by_source_id,
            ),
            await generate_cash_flow(
                db,
                user_id,
                start_date=start_date,
                end_date=end_date,
                currency=currency,
                cash_account_ids=cash_inputs.account_ids,
            ),
            await build_investment_performance_report_schedule(
                db,
                user_id,
                period_start=start_date,
                period_end=end_date,
                as_of_date=as_of_date,
                currency=currency,
            ),
            await generate_annualized_income_schedule(db, user_id, as_of_date=as_of_date, currency=currency),
            await build_personal_report_package_traceability_payload(
                contributions=contributions,
            ),
        )
        return PersonalReportPackageSections(
            balance_sheet=BalanceSheetResponse.model_validate(balance_sheet),
            income_statement=IncomeStatementResponse.model_validate(income_statement),
            cash_flow=CashFlowResponse.model_validate(cash_flow),
            investment_performance=InvestmentPerformanceReportScheduleResponse.model_validate(investment_performance),
            annualized_income_long_term=annualized_income,
            notes=PersonalReportPackageNotesResponse.model_validate(PERSONAL_REPORT_PACKAGE_NOTES),
            traceability_appendix=PersonalReportPackageTraceabilityResponse.model_validate(traceability),
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
        statement_results = await list_statement_contributions(db, user_id=user_id, as_of=as_of_date)
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
                _statement_section_contribution(item, start_date=start_date, end_date=end_date)
                for item in statement_results
            ),
            *(
                _journal_section_contribution(item, start_date=start_date, end_date=end_date)
                for item in journal_results
            ),
            *(_valuation_section_contribution(item) for item in valuation_results),
        )

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
        refs_by_decision: dict[UUID, set[str]] = defaultdict(set)
        unproven_refs: set[str] = set()
        for contribution in contributions:
            if contribution.is_authoritative and contribution.decision_id is not None:
                refs_by_decision[contribution.decision_id].update(contribution.input_refs)
            else:
                unproven_refs.update(contribution.input_refs)

        if not refs_by_decision:
            return [], sorted(unproven_refs)
        projection = current_authoritative_trace_decision_projection(TraceScope.tenant(user_id)).subquery(
            "package_authority_decisions"
        )
        trusted_result = await db.execute(
            select(
                projection.c.decision_id,
                projection.c.target_kind,
                projection.c.target_id,
                projection.c.target_version,
                projection.c.assertion_kind,
                projection.c.assertion_id,
                projection.c.assertion_version,
                projection.c.authority_tier,
            ).where(projection.c.decision_id.in_(refs_by_decision))
        )
        current_decisions: dict[UUID, dict[str, Any]] = {}
        for row in trusted_result.mappings():
            current_decisions[row["decision_id"]] = dict(row)
        for decision_id, refs in refs_by_decision.items():
            if decision_id not in current_decisions:
                unproven_refs.update(refs)
        manifest = [
            PersonalReportPackageTraceManifestEntry(
                decision_id=decision_id,
                input_refs=sorted(refs_by_decision[decision_id]),
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
            for decision_id in sorted(current_decisions, key=str)
        ]
        return manifest, sorted(unproven_refs)


async def current_package_document_summary(
    db: AsyncSession,
    *,
    user_id: UUID,
    as_of_date: date | None = None,
) -> PersonalReportPackageDocumentSummary:
    """Build the current default-framework candidate through the sole assembler."""
    report_end = as_of_date or date.today()
    document = await PackageAssembler().assemble(
        db,
        user_id=user_id,
        framework_id=PersonalReportingFrameworkId.US_GAAP_LIKE,
        start_date=report_end - timedelta(days=365),
        end_date=report_end,
        as_of_date=report_end,
        currency=settings.base_currency,
    )
    return _package_document_summary(document)
