"""Pydantic schemas for financial reporting endpoints."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, Field, model_serializer, model_validator

from src.ledger import AccountType, Direction
from src.platform import validate_internal_action_href
from src.reporting import (
    CashFlowPreview,
    CashFlowResponse,
    InvariantStatus as InvariantStatus,
    MonthContinuityBucket as MonthContinuityBucket,
    PersonalDataQualityHealthResponse as PersonalDataQualityHealthResponse,
    PersonalReportingFrameworkId,
    PolicyDimension,
    QualityActionItem as QualityActionItem,
    QualityGrade as QualityGrade,
    ReportLineId,
    ReportType,
)
from src.schemas.base import BaseResponse, CurrencyCode, default_list, default_obj
from src.schemas.portfolio import InvestmentPerformanceReportScheduleResponse
from src.schemas.provenance import DataProvenance

ActionHref = Annotated[str, AfterValidator(validate_internal_action_href)]
CurrencyStr = Annotated[str, Field(min_length=3, max_length=3)]
NonNegInt = Annotated[int, Field(ge=0)]
PosInt = Annotated[int, Field(ge=1)]
_TARGETS = frozenset({"balance_sheet", "income_statement", "cash_flow", "notes"})
_omit_none = lambda v: v is None  # noqa: E731


def _check_line_mappings(mappings: dict[str, str], framework_id: PersonalReportingFrameworkId, prefix: str) -> None:
    from src.reporting import is_valid_line_for_framework

    for target, line_id in mappings.items():
        if target not in _TARGETS:
            allowed = ", ".join(sorted(_TARGETS))
            raise ValueError(f"{prefix} unknown statement target '{target}'; allowed: {allowed}")
        if not is_valid_line_for_framework(line_id, framework_id):
            raise ValueError(
                f"{prefix} '{line_id}' which is not a registered L1 line valid in framework '{framework_id.value}'"
                if prefix.startswith("Rule")
                else f"Line mapping '{line_id}' is not a registered L1 line valid in framework '{framework_id.value}'"
            )


class ReportLine(BaseModel):
    line_id: ReportLineId | None = Field(default=None, exclude_if=_omit_none, description="Framework line id.")
    account_id: UUID
    name: str
    type: AccountType
    parent_id: UUID | None = None
    amount: Decimal
    provenance: DataProvenance | None = None
    source_currency: CurrencyStr | None = Field(default=None, exclude_if=_omit_none, description="Native currency.")
    native_amount: Decimal | None = Field(default=None, exclude_if=_omit_none, description="Signed native balance.")
    allocation_source_type: (
        Literal[
            "ledger_account",
            "manual_valuation",
            "portfolio_market_adjustment",
            "portfolio_cost_basis",
            "internal_transfer_fee",
        ]
        | None
    ) = Field(default=None, exclude_if=_omit_none, description="Report line origin.")


class AccountLineageLine(BaseModel):
    journal_line_id: UUID
    journal_entry_id: UUID
    entry_date: date
    memo: str
    direction: Direction
    original_amount: Decimal
    original_currency: CurrencyStr
    amount: Decimal


class AccountLineageResponse(BaseModel):
    account_id: UUID
    account_name: str
    account_type: AccountType
    currency: CurrencyStr
    as_of_date: date
    start_date: date | None = None
    total: Decimal
    lines: list[AccountLineageLine]


class ExcludedHoldingRow(BaseModel):
    asset_class: str
    total_assets: Decimal | None
    total_liabilities: Decimal | None
    net_worth: Decimal | None
    warnings: list[dict[str, str]] = default_list()


class BalanceSheetResponse(BaseModel):
    as_of_date: date
    currency: CurrencyStr
    assets: list[ReportLine]
    liabilities: list[ReportLine]
    equity: list[ReportLine]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    net_income: Decimal = Decimal("0.00")
    unrealized_fx_gain_loss: Decimal = Decimal("0.00")
    net_worth_adjustment_gain_loss: Decimal = Decimal("0.00")
    cta_adjustment: Decimal = Decimal("0.00")
    fx_warnings: list[dict[str, str]] = default_list()
    portfolio_warnings: list[dict[str, str]] = default_list()
    opening_balance_warnings: list[dict[str, str]] = default_list()
    excluded_holdings: list[ExcludedHoldingRow] = default_list()
    equation_delta: Decimal
    is_balanced: bool


class IncomeStatementTrend(BaseModel):
    period_start: date
    period_end: date
    total_income: Decimal
    total_expenses: Decimal
    net_income: Decimal


class IncomeStatementResponse(BaseModel):
    start_date: date
    end_date: date
    currency: CurrencyStr
    income: list[ReportLine]
    expenses: list[ReportLine]
    total_income: Decimal
    total_expenses: Decimal
    net_income: Decimal
    fx_warnings: list[dict[str, str]] = default_list()
    trends: list[IncomeStatementTrend]


class TrendPeriod(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class NetWorthGranularity(str, Enum):
    DAILY = "daily"
    MONTHLY = "monthly"


class NetWorthTimeSeriesPoint(BaseModel):
    date: date
    total_assets: Decimal
    total_liabilities: Decimal
    net_worth: Decimal
    currency: CurrencyStr


class NetWorthTimeSeriesResponse(BaseModel):
    currency: CurrencyStr
    granularity: NetWorthGranularity
    points: list[NetWorthTimeSeriesPoint]


class NetWorthAllocationSourceLine(BaseModel):
    source_type: str
    source_id: UUID | None = None
    label: str
    value: Decimal


class NetWorthAllocationRow(BaseModel):
    asset_class: str
    liquidity_class: str
    source_currency: CurrencyStr
    value: Decimal
    percentage_of_net_worth: Decimal | None = None
    source_line_count: NonNegInt
    source_lines: list[NetWorthAllocationSourceLine]


class NetWorthAllocationResponse(BaseModel):
    as_of_date: date
    currency: CurrencyStr
    include_restricted: bool
    total_assets: Decimal
    total_liabilities: Decimal
    net_worth: Decimal
    rows: list[NetWorthAllocationRow]
    opening_balance_warnings: list[dict[str, str]] = default_list()
    portfolio_warnings: list[dict[str, str]] = default_list()
    excluded_holdings: list[ExcludedHoldingRow] = default_list()


class AccountTrendPoint(BaseModel):
    period_start: date
    period_end: date
    amount: Decimal


class AccountTrendResponse(BaseModel):
    account_id: UUID
    currency: CurrencyStr
    period: TrendPeriod
    points: list[AccountTrendPoint]


class BreakdownPeriod(str, Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class BreakdownType(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"


class CategoryBreakdownItem(BaseModel):
    category_id: UUID
    category_name: str
    total: Decimal


class CategoryBreakdownResponse(BaseModel):
    type: AccountType
    currency: CurrencyStr
    period_start: date
    period_end: date
    items: list[CategoryBreakdownItem]


class PersonalReportPackageSectionContract(BaseModel):
    section_id: str
    label: str
    owner_epic: str
    period_type: str
    status: str
    required: bool = True
    blocking_issue: str | None = None
    decimal_total_fields: list[str] = default_list()


class PersonalReportPackageExportContract(BaseModel):
    formats: list[str]
    csv_columns: list[str]


class PersonalReportPackageContractResponse(BaseModel):
    package_id: str
    version: str
    period_semantics: dict[str, str]
    supported_frameworks: list[str] = default_list()
    selected_framework_id: str | None = None
    sections: list[PersonalReportPackageSectionContract]
    export_contract: PersonalReportPackageExportContract


class PolicyFactDomain(str, Enum):
    CASH = "cash"
    LISTED_SECURITY = "listed_security"
    FUND = "fund"
    PERSONAL_INCOME = "personal_income"
    PERSONAL_EXPENSE = "personal_expense"
    DIVIDEND_INTEREST = "dividend_interest"
    BROKERAGE_FEE = "brokerage_fee"
    FX = "fx"
    RESTRICTED_COMPENSATION = "restricted_compensation"
    PROPERTY_MORTGAGE_PRIVATE = "property_mortgage_private"
    LIABILITY = "liability"
    TRANSFER = "transfer"
    TAX_NOTE = "tax_note"
    UNSUPPORTED = "unsupported"


class PolicyProvenance(str, Enum):
    DETERMINISTIC_MATRIX = "deterministic_matrix"
    REVIEWED_AI_SUGGESTION = "reviewed_ai_suggestion"
    EXPLICIT_MANUAL_INPUT = "explicit_manual_input"


class PolicyReviewState(str, Enum):
    ACCEPTED = "accepted"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    NOT_REQUIRED = "not_required"


class FrameworkPolicyEvidenceAnchor(BaseModel):
    anchor_id: str
    anchor_type: str
    source_system: str
    source_id: str
    description: str | None = None


class FrameworkPolicyFact(BaseModel):
    fact_id: str
    domain: PolicyFactDomain
    instrument_type: str
    amount: Decimal | None = None
    currency: CurrencyStr | None = None
    event_date: date | None = None
    anchors: list[FrameworkPolicyEvidenceAnchor] = default_list()
    holding_intent: str | None = None
    horizon: str | None = None


class FrameworkPolicyDecision(BaseModel):
    domain: PolicyFactDomain
    recognition: str | None = None
    measurement: str | None = None
    classification: str | None = None
    presentation: str | None = None
    disclosure: str | None = None
    line_mappings: dict[str, str]
    evidence_anchors: list[FrameworkPolicyEvidenceAnchor] = default_list()
    provenance: PolicyProvenance = PolicyProvenance.DETERMINISTIC_MATRIX
    review_state: PolicyReviewState = PolicyReviewState.ACCEPTED
    policy_field_name: str = "framework_policy_decision"
    accepted_value: str | None = None

    @model_validator(mode="after")
    def validate_required_dimensions(self) -> "FrameworkPolicyDecision":
        missing = [f"{self.domain.value}.{d.value}" for d in PolicyDimension if not getattr(self, d.value)]
        if missing:
            raise ValueError(f"missing required policy dimensions: {', '.join(missing)}")
        return self


class FrameworkPolicyGap(BaseModel):
    code: str
    fact_id: str
    domain: PolicyFactDomain
    instrument_type: str
    blocker: bool
    reason: str
    remediation: str
    evidence_anchors: list[FrameworkPolicyEvidenceAnchor] = default_list()


class FrameworkPolicyMatrixRule(BaseModel):
    domain: PolicyFactDomain
    supported_instrument_types: list[str]
    policy_by_dimension: dict[PolicyDimension, str]
    line_mappings: dict[str, str]
    required_evidence: list[str]
    disclosure_requirements: list[str]
    blocker_conditions: list[str]

    @model_validator(mode="after")
    def validate_matrix_dimensions(self) -> "FrameworkPolicyMatrixRule":
        missing = [d.value for d in PolicyDimension if d not in self.policy_by_dimension]
        if missing:
            raise ValueError(f"missing matrix policy dimensions: {', '.join(missing)}")
        return self


class FrameworkPolicyMatrix(BaseModel):
    framework_id: PersonalReportingFrameworkId
    version: str
    rules: list[FrameworkPolicyMatrixRule]

    @model_validator(mode="after")
    def validate_rules_line_mappings(self) -> "FrameworkPolicyMatrix":
        for rule in self.rules:
            _check_line_mappings(
                rule.line_mappings, self.framework_id, f"Rule for domain {rule.domain.value} maps to"
            )
        return self


class FrameworkPolicyResult(BaseModel):
    result_id: str
    framework_id: PersonalReportingFrameworkId
    matrix_version: str
    report_period_start: date
    report_period_end: date
    generated_at: date
    required_statements: list[str]
    decisions: list[FrameworkPolicyDecision]
    gaps: list[FrameworkPolicyGap] = default_list()

    @model_validator(mode="after")
    def validate_decision_dimensions(self) -> "FrameworkPolicyResult":
        incomplete = [
            f"{d.domain.value}.{dim.value}"
            for d in self.decisions
            for dim in PolicyDimension
            if not getattr(d, dim.value)
        ]
        if incomplete:
            raise ValueError(f"missing required policy dimensions: {', '.join(sorted(set(incomplete)))}")
        for decision in self.decisions:
            _check_line_mappings(decision.line_mappings, self.framework_id, "Decision line mapping uses")
        return self


class FrameworkPolicyPreview(FrameworkPolicyResult):
    decision_count: NonNegInt
    evidence_reference_count: NonNegInt


class PersonalReportPackageReadinessBlocker(BaseModel):
    code: str
    label: str
    severity: str
    count: int
    reason: str
    action_href: ActionHref


class PersonalReportPackageReadinessState(str, Enum):
    DRAFT = "draft"
    BLOCKED = "blocked"
    READY = "ready"


class PersonalReportPackageSnapshotStatus(str, Enum):
    DRAFT = "draft"
    TRUSTED = "trusted"
    LEGACY_UNPROVEN = "legacy_unproven"


class PersonalReportPackageDocumentLifecycle(str, Enum):
    PREVIEW = "preview"
    FROZEN = "frozen"


class PersonalReportPackageInputCoverage(BaseModel):
    manifest_decision_count: NonNegInt = 0
    authoritative_input_count: NonNegInt = 0
    unproven_input_count: NonNegInt = 0


class ReportCoverageResponse(BaseModel):
    as_of_date: date
    coverage_start: date | None = None
    limiting_accounts: list[str] = default_list()
    latest_statement_end: date | None = None


class PersonalReportPackageReadinessResponse(BaseModel):
    package_id: str
    state: PersonalReportPackageReadinessState
    label: str
    action_href: ActionHref
    blocking_count: int
    blockers: list[PersonalReportPackageReadinessBlocker] = default_list()
    input_coverage: PersonalReportPackageInputCoverage = default_obj(PersonalReportPackageInputCoverage)


class PersonalReportPackageSnapshotSummary(BaseModel):
    id: UUID
    package_id: str
    status: PersonalReportPackageSnapshotStatus
    framework_id: PersonalReportingFrameworkId
    start_date: date
    end_date: date
    as_of_date: date
    currency: CurrencyStr
    readiness_state: str
    is_latest: bool
    created_at: datetime | None = None


class ReportSnapshotSummary(BaseResponse):
    id: UUID
    report_type: ReportType
    as_of_date: date | None = None
    start_date: date | None = None
    rule_version_id: UUID | None = None
    is_latest: bool
    created_at: datetime | None = None


class PersonalReportPackageGenerateRequest(BaseModel):
    framework_id: PersonalReportingFrameworkId = PersonalReportingFrameworkId.US_GAAP_LIKE
    start_date: date | None = None
    end_date: date | None = None
    as_of_date: date | None = None
    currency: CurrencyCode | None = None
    include_restricted: bool | None = None


class PersonalReportPackageNote(BaseModel):
    note_id: str
    label: str
    owner_epic: str
    basis: str
    source_state: str
    applies_to_sections: list[str]
    disclosure: str


class PersonalReportPackageNotesResponse(BaseModel):
    section_id: str
    label: str
    status: str
    notes: list[PersonalReportPackageNote]
    non_compliance_statement: str


class PersonalReportPackageTraceabilityAnchor(BaseModel):
    state: str
    source_types: list[str] = default_list()
    entry_statuses: list[str] = default_list()
    identifier_fields: list[str] = default_list()
    identifiers: list[str] = default_list()
    unavailable_reason: str | None = None
    details: list[dict[str, str | Decimal | None]] = default_list()


class PersonalReportPackageTraceabilityLine(BaseModel):
    line_id: str
    section_id: str
    label: str
    amount_field: str | None = None
    currency_field: str | None = None
    source_state: str
    source_anchor: PersonalReportPackageTraceabilityAnchor
    ledger_anchor: PersonalReportPackageTraceabilityAnchor
    anchor_count: int = 0
    blocker_codes: list[str] = default_list()


class PersonalReportPackageCompletenessWarning(BaseModel):
    code: str
    label: str
    applies_to_sections: list[str]
    state: str
    remediation: str | None = None


class PersonalReportPackageTraceabilityResponse(BaseModel):
    section_id: str
    label: str
    status: str
    lines: list[PersonalReportPackageTraceabilityLine]
    completeness_warnings: list[PersonalReportPackageCompletenessWarning]


class PersonalReportPackageTraceabilityAnchorName(str, Enum):
    SOURCE = "source_anchor"
    LEDGER = "ledger_anchor"


class PersonalReportPackageTraceabilityAnchorSummary(BaseModel):
    state: str
    source_types: list[str] = default_list()
    entry_statuses: list[str] = default_list()
    identifier_fields: list[str] = default_list()
    unavailable_reason: str | None = None
    detail_count: NonNegInt


class PersonalReportPackageTraceabilityLineSummary(BaseModel):
    line_id: str
    section_id: str
    label: str
    amount_field: str | None = None
    currency_field: str | None = None
    source_state: str
    source_anchor: PersonalReportPackageTraceabilityAnchorSummary
    ledger_anchor: PersonalReportPackageTraceabilityAnchorSummary
    anchor_count: int = 0
    blocker_codes: list[str] = default_list()


class PersonalReportPackageTraceabilitySummaryResponse(BaseModel):
    section_id: str
    label: str
    status: str
    lines: list[PersonalReportPackageTraceabilityLineSummary]
    completeness_warnings: list[PersonalReportPackageCompletenessWarning]


class PersonalReportPackageLineDetailsPage(BaseModel):
    line_id: str
    anchor: PersonalReportPackageTraceabilityAnchorName
    total: NonNegInt
    limit: PosInt
    offset: NonNegInt
    details: list[dict[str, str | Decimal | None]] = default_list()


class AnnualizedIncomeScheduleIncome(BaseModel):
    annualized_salary: Decimal
    annualized_bonus: Decimal
    annualized_dividend: Decimal
    annualized_total: Decimal
    currency: CurrencyStr
    calculation_basis: str


class AnnualizedIncomeScheduleHolding(BaseModel):
    ticker: str
    compensation_type: str
    fair_value: Decimal
    currency: CurrencyStr
    valuation_basis: str
    vesting_schedule: str | None = None
    unlock_date: date | None = None
    liquidity_class: str
    net_worth_treatment: str


class AnnualizedIncomeScheduleNetWorthTreatment(BaseModel):
    liquid_net_worth_default: str
    restricted_wealth_basis: str
    include_restricted_query: str
    exclude_restricted_query: str


class AnnualizedIncomeScheduleResponse(BaseModel):
    section_id: str
    label: str
    as_of_date: date
    trailing_period_start: date
    trailing_period_end: date
    trailing_period_days: int
    income: AnnualizedIncomeScheduleIncome
    restricted_holdings: list[AnnualizedIncomeScheduleHolding]
    restricted_fair_value_total: Decimal
    restricted_fair_value_total_currency: CurrencyStr
    restricted_fair_value_total_excludes: list[dict[str, str]] = Field(
        default_factory=list, exclude_if=lambda v: not v, description="Unconverted restricted holdings."
    )
    net_worth_treatment: AnnualizedIncomeScheduleNetWorthTreatment
    notes: list[str]


class PersonalReportPackageContext(BaseModel):
    framework_id: PersonalReportingFrameworkId
    start_date: date
    end_date: date
    as_of_date: date
    currency: CurrencyCode
    include_restricted: bool | None = Field(default=None, exclude_if=_omit_none, description="Restricted scope.")


class PersonalReportPackageStatementDispositionPolicy(BaseModel):
    schema_version: Literal["1"]
    policy_version: str
    mode: Literal["off", "observe", "enforce"]
    machine_confidence_threshold: Decimal
    pnl_effect_confidence_threshold: Decimal
    unknown_intent_outcome: Literal["review"]
    ambiguous_intent_outcome: Literal["review"]
    live_llm_proposals_enabled: bool
    deployment_git_sha: str
    semantic_digest: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PersonalReportPackageTraceManifestEntry(BaseModel):
    decision_id: UUID
    input_refs: Annotated[list[str], Field(min_length=1)]
    target_kind: str
    target_id: str
    target_version: str
    assertion_kind: str
    assertion_id: str
    assertion_version: str
    authority_tier: str


class PersonalReportPackageSections(BaseModel):
    model_config = {"extra": "forbid"}

    balance_sheet: BalanceSheetResponse
    income_statement: IncomeStatementResponse
    cash_flow: CashFlowResponse
    investment_performance: InvestmentPerformanceReportScheduleResponse
    annualized_income_long_term: AnnualizedIncomeScheduleResponse
    notes: PersonalReportPackageNotesResponse
    traceability_appendix: PersonalReportPackageTraceabilityResponse

    @model_serializer(mode="wrap")
    def _serialize_sections(self, handler):
        data = handler(self)
        if (
            "excluded_holdings" not in self.balance_sheet.model_fields_set
            and not self.balance_sheet.excluded_holdings
            and isinstance(data.get("balance_sheet"), dict)
        ):
            data["balance_sheet"].pop("excluded_holdings", None)
        return data


class PersonalReportPackageDocument(BaseModel):
    model_config = {"extra": "forbid"}

    schema_version: Literal["2"]
    lifecycle: PersonalReportPackageDocumentLifecycle
    snapshot_id: UUID | None = None
    package_decision_id: UUID | None = None
    generated_at: datetime
    frozen_at: datetime | None = None
    package_id: str
    status: PersonalReportPackageSnapshotStatus
    context: PersonalReportPackageContext
    contract: PersonalReportPackageContractResponse
    readiness: PersonalReportPackageReadinessResponse
    framework_policy: FrameworkPolicyResult
    statement_disposition_policy: PersonalReportPackageStatementDispositionPolicy | None = None
    input_manifest: list[PersonalReportPackageTraceManifestEntry]
    sections: PersonalReportPackageSections

    @model_validator(mode="after")
    def validate_frozen_trust_anchor(self) -> "PersonalReportPackageDocument":
        if self.status is PersonalReportPackageSnapshotStatus.TRUSTED:
            if self.lifecycle is not PersonalReportPackageDocumentLifecycle.FROZEN:
                raise ValueError("only a frozen package document can be trusted")
            if self.snapshot_id is None or self.package_decision_id is None:
                raise ValueError("trusted package requires snapshot and TraceRecord decision ids")
        if self.package_decision_id is not None and self.lifecycle is not PersonalReportPackageDocumentLifecycle.FROZEN:
            raise ValueError("preview package cannot persist an authority decision")
        return self


class PersonalReportPackagePreviewSections(BaseModel):
    model_config = {"extra": "forbid"}

    balance_sheet: BalanceSheetResponse
    income_statement: IncomeStatementResponse
    cash_flow: CashFlowPreview
    investment_performance: InvestmentPerformanceReportScheduleResponse
    annualized_income_long_term: AnnualizedIncomeScheduleResponse
    notes: PersonalReportPackageNotesResponse
    traceability_appendix: PersonalReportPackageTraceabilitySummaryResponse


class PersonalReportPackagePreview(BaseModel):
    model_config = {"extra": "forbid"}

    schema_version: Literal["2"]
    lifecycle: Literal[PersonalReportPackageDocumentLifecycle.PREVIEW]
    generated_at: datetime
    package_id: str
    status: Literal[PersonalReportPackageSnapshotStatus.DRAFT]
    context: PersonalReportPackageContext
    contract: PersonalReportPackageContractResponse
    readiness: PersonalReportPackageReadinessResponse
    framework_policy: FrameworkPolicyPreview
    statement_disposition_policy: PersonalReportPackageStatementDispositionPolicy | None = None
    sections: PersonalReportPackagePreviewSections


class PersonalReportPackageManifestEntriesPage(BaseModel):
    total: NonNegInt
    limit: PosInt
    offset: NonNegInt
    entries: list[PersonalReportPackageTraceManifestEntry] = default_list()


class PersonalReportPackagePolicyDecisionsPage(BaseModel):
    total: NonNegInt
    limit: PosInt
    offset: NonNegInt
    decisions: list[FrameworkPolicyDecision] = default_list()


class PersonalReportPackageSnapshotResponse(PersonalReportPackageSnapshotSummary):
    document: PersonalReportPackageDocument
