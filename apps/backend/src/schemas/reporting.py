"""Pydantic schemas for financial reporting endpoints."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from src.models import AccountType


def _validate_internal_action_href(value: str) -> str:
    if not value.startswith("/") or value.startswith("//") or "://" in value:
        raise ValueError("action_href must be an internal relative path")
    return value


class ReportLine(BaseModel):
    """Generic report line for account totals."""

    account_id: UUID
    name: str
    type: AccountType
    parent_id: UUID | None = None
    amount: Decimal


class BalanceSheetResponse(BaseModel):
    """Balance sheet response schema."""

    as_of_date: date
    currency: str = Field(min_length=3, max_length=3)
    assets: list[ReportLine]
    liabilities: list[ReportLine]
    equity: list[ReportLine]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    net_income: Decimal = Decimal("0.00")
    unrealized_fx_gain_loss: Decimal = Decimal("0.00")
    net_worth_adjustment_gain_loss: Decimal = Decimal("0.00")
    fx_warnings: list[dict[str, str]] = Field(default_factory=list)
    equation_delta: Decimal
    is_balanced: bool


class IncomeStatementTrend(BaseModel):
    """Income statement trend bucket."""

    period_start: date
    period_end: date
    total_income: Decimal
    total_expenses: Decimal
    net_income: Decimal


class IncomeStatementResponse(BaseModel):
    """Income statement response schema."""

    start_date: date
    end_date: date
    currency: str = Field(min_length=3, max_length=3)
    income: list[ReportLine]
    expenses: list[ReportLine]
    total_income: Decimal
    total_expenses: Decimal
    net_income: Decimal
    fx_warnings: list[dict[str, str]] = Field(default_factory=list)
    trends: list[IncomeStatementTrend]


class TrendPeriod(str, Enum):
    """Supported period grouping for trends."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class NetWorthGranularity(str, Enum):
    """Supported net worth time-series granularity."""

    DAILY = "daily"
    MONTHLY = "monthly"


class NetWorthTimeSeriesPoint(BaseModel):
    """Net worth point-in-time value."""

    date: date
    total_assets: Decimal
    total_liabilities: Decimal
    net_worth: Decimal
    currency: str = Field(min_length=3, max_length=3)


class NetWorthTimeSeriesResponse(BaseModel):
    """Net worth time-series response."""

    currency: str = Field(min_length=3, max_length=3)
    granularity: NetWorthGranularity
    points: list[NetWorthTimeSeriesPoint]


class AccountTrendPoint(BaseModel):
    """Trend data point for an account."""

    period_start: date
    period_end: date
    amount: Decimal


class AccountTrendResponse(BaseModel):
    """Account trend response schema."""

    account_id: UUID
    currency: str = Field(min_length=3, max_length=3)
    period: TrendPeriod
    points: list[AccountTrendPoint]


class BreakdownPeriod(str, Enum):
    """Supported breakdown periods."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class BreakdownType(str, Enum):
    """Breakdown for income or expense categories."""

    INCOME = "income"
    EXPENSE = "expense"


class CategoryBreakdownItem(BaseModel):
    """Category breakdown item."""

    category_id: UUID
    category_name: str
    total: Decimal


class CategoryBreakdownResponse(BaseModel):
    """Category breakdown response schema."""

    type: AccountType
    currency: str = Field(min_length=3, max_length=3)
    period_start: date
    period_end: date
    items: list[CategoryBreakdownItem]


class CashFlowItem(BaseModel):
    """Cash flow item for operating, investing, financing activities."""

    category: str
    subcategory: str
    amount: Decimal
    description: str | None = None


class CashFlowSummary(BaseModel):
    """Cash flow summary totals."""

    operating_activities: Decimal
    investing_activities: Decimal
    financing_activities: Decimal
    net_cash_flow: Decimal
    beginning_cash: Decimal
    ending_cash: Decimal


class CashFlowResponse(BaseModel):
    """Cash flow statement response schema."""

    start_date: date
    end_date: date
    currency: str = Field(min_length=3, max_length=3)
    operating: list[CashFlowItem]
    investing: list[CashFlowItem]
    financing: list[CashFlowItem]
    summary: CashFlowSummary


class PersonalReportPackageSectionContract(BaseModel):
    """Stable section contract for the personal financial-report package."""

    section_id: str
    label: str
    owner_epic: str
    period_type: str
    source_endpoint: str
    status: str
    required: bool = True
    blocking_issue: str | None = None
    decimal_total_fields: list[str] = Field(default_factory=list)


class PersonalReportPackageExportContract(BaseModel):
    """Stable export contract for personal package consumers."""

    formats: list[str]
    csv_columns: list[str]


class PersonalReportPackageContractResponse(BaseModel):
    """Package-level API/export contract for the north-star report package."""

    package_id: str
    version: str
    period_semantics: dict[str, str]
    sections: list[PersonalReportPackageSectionContract]
    export_contract: PersonalReportPackageExportContract


class PersonalReportingFrameworkId(str, Enum):
    """Supported personal reporting framework targets."""

    US_GAAP_LIKE = "personal_us_gaap_like"
    HKFRS_LIKE = "personal_hkfrs_like"


class PolicyDimension(str, Enum):
    """Required decision dimensions for every framework policy conclusion."""

    RECOGNITION = "recognition"
    MEASUREMENT = "measurement"
    CLASSIFICATION = "classification"
    PRESENTATION = "presentation"
    DISCLOSURE = "disclosure"


class PolicyFactDomain(str, Enum):
    """Personal finance domains covered by the v1 policy matrix."""

    CASH = "cash"
    LISTED_SECURITY = "listed_security"
    FUND = "fund"
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
    """How a framework policy decision became trusted."""

    DETERMINISTIC_MATRIX = "deterministic_matrix"
    REVIEWED_AI_SUGGESTION = "reviewed_ai_suggestion"
    EXPLICIT_MANUAL_INPUT = "explicit_manual_input"


class PolicyReviewState(str, Enum):
    """Review state for framework policy fields."""

    ACCEPTED = "accepted"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    NOT_REQUIRED = "not_required"


class FrameworkPolicyEvidenceAnchor(BaseModel):
    """Source, ledger, portfolio, valuation, or review anchor for a policy field."""

    anchor_id: str
    anchor_type: str
    source_system: str
    source_id: str
    description: str | None = None


class FrameworkPolicyFact(BaseModel):
    """Framework-neutral fact consumed by the target-backward policy layer."""

    fact_id: str
    domain: PolicyFactDomain
    instrument_type: str
    amount: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    event_date: date | None = None
    anchors: list[FrameworkPolicyEvidenceAnchor] = Field(default_factory=list)


class FrameworkPolicyDecision(BaseModel):
    """One deterministic framework policy conclusion for a personal finance domain."""

    domain: PolicyFactDomain
    recognition: str | None = None
    measurement: str | None = None
    classification: str | None = None
    presentation: str | None = None
    disclosure: str | None = None
    line_mappings: dict[str, str]
    evidence_anchors: list[FrameworkPolicyEvidenceAnchor] = Field(default_factory=list)
    provenance: PolicyProvenance = PolicyProvenance.DETERMINISTIC_MATRIX
    confidence_tier: str = "TRUSTED"
    review_state: PolicyReviewState = PolicyReviewState.ACCEPTED
    policy_field_name: str = "framework_policy_decision"
    accepted_value: str | None = None

    @model_validator(mode="after")
    def validate_required_dimensions(self) -> "FrameworkPolicyDecision":
        missing = [dimension.value for dimension in PolicyDimension if not getattr(self, dimension.value)]
        if missing:
            raise ValueError(f"missing required policy dimensions: {', '.join(missing)}")
        return self


class FrameworkPolicyGap(BaseModel):
    """Explicit policy gap that blocks trusted framework output."""

    code: str
    fact_id: str
    domain: PolicyFactDomain
    instrument_type: str
    blocker: bool
    reason: str
    remediation: str
    evidence_anchors: list[FrameworkPolicyEvidenceAnchor] = Field(default_factory=list)


class FrameworkPolicyMatrixRule(BaseModel):
    """Framework-specific rule for one supported personal finance domain."""

    domain: PolicyFactDomain
    supported_instrument_types: list[str]
    policy_by_dimension: dict[PolicyDimension, str]
    line_mappings: dict[str, str]
    required_evidence: list[str]
    disclosure_requirements: list[str]
    blocker_conditions: list[str]

    @model_validator(mode="after")
    def validate_matrix_dimensions(self) -> "FrameworkPolicyMatrixRule":
        missing = [dimension.value for dimension in PolicyDimension if dimension not in self.policy_by_dimension]
        if missing:
            raise ValueError(f"missing matrix policy dimensions: {', '.join(missing)}")
        return self


class FrameworkPolicyMatrix(BaseModel):
    """Deterministic v1 framework policy matrix."""

    framework_id: PersonalReportingFrameworkId
    version: str
    rules: list[FrameworkPolicyMatrixRule]


class FrameworkPolicyResult(BaseModel):
    """Read-only target-backward policy result consumed by readiness and reporting."""

    framework_id: PersonalReportingFrameworkId
    report_period_start: date
    report_period_end: date
    generated_at: date
    required_statements: list[str]
    decisions: list[FrameworkPolicyDecision]
    gaps: list[FrameworkPolicyGap] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_decision_dimensions(self) -> "FrameworkPolicyResult":
        incomplete = [
            decision.domain.value
            for decision in self.decisions
            for dimension in PolicyDimension
            if not getattr(decision, dimension.value)
        ]
        if incomplete:
            raise ValueError(f"missing required policy dimensions: {', '.join(sorted(set(incomplete)))}")
        return self


class PersonalReportPackageReadinessBlocker(BaseModel):
    """Actionable blocker that prevents a report package from being ready."""

    code: str
    label: str
    severity: str
    count: int
    reason: str
    action_href: str

    @field_validator("action_href")
    @classmethod
    def validate_action_href(cls, value: str) -> str:
        return _validate_internal_action_href(value)


class PersonalReportPackageReadinessState(str, Enum):
    """Allowed states for the personal report package readiness contract."""

    DRAFT = "draft"
    PROCESSING = "processing"
    BLOCKED = "blocked"
    READY = "ready"
    GENERATED = "generated"
    STALE = "stale"


class PersonalReportPackageReadinessResponse(BaseModel):
    """Deterministic readiness state for the personal report package."""

    package_id: str
    state: PersonalReportPackageReadinessState
    label: str
    action_href: str
    blocking_count: int
    blockers: list[PersonalReportPackageReadinessBlocker] = Field(default_factory=list)
    source_summary: dict[str, int] = Field(default_factory=dict)
    generated_at: datetime | None = None
    stale_since: datetime | None = None

    @field_validator("action_href")
    @classmethod
    def validate_action_href(cls, value: str) -> str:
        return _validate_internal_action_href(value)


class PersonalReportPackageNote(BaseModel):
    """Disclosure note included in the personal financial-report package."""

    note_id: str
    label: str
    owner_epic: str
    basis: str
    source_state: str
    applies_to_sections: list[str]
    disclosure: str


class PersonalReportPackageNotesResponse(BaseModel):
    """Package-level notes and disclosures for report consumers."""

    section_id: str
    label: str
    status: str
    notes: list[PersonalReportPackageNote]
    non_compliance_statement: str


class PersonalReportPackageTraceabilityAnchor(BaseModel):
    """Source or ledger anchor metadata for one package report line."""

    state: str
    source_types: list[str] = Field(default_factory=list)
    entry_statuses: list[str] = Field(default_factory=list)
    identifier_fields: list[str] = Field(default_factory=list)
    identifiers: list[str] = Field(default_factory=list)
    unavailable_reason: str | None = None


class PersonalReportPackageTraceabilityLine(BaseModel):
    """Traceability metadata for one personal report package line."""

    line_id: str
    section_id: str
    label: str
    amount_field: str | None = None
    currency_field: str | None = None
    source_state: str
    source_anchor: PersonalReportPackageTraceabilityAnchor
    ledger_anchor: PersonalReportPackageTraceabilityAnchor
    review_state: str
    confidence_tier: str


class PersonalReportPackageCompletenessWarning(BaseModel):
    """Potential completeness risk disclosed by the traceability appendix."""

    code: str
    label: str
    applies_to_sections: list[str]
    state: str
    remediation: str | None = None


class PersonalReportPackageTraceabilityResponse(BaseModel):
    """Package-level source-ledger-report traceability appendix."""

    section_id: str
    label: str
    status: str
    lines: list[PersonalReportPackageTraceabilityLine]
    completeness_warnings: list[PersonalReportPackageCompletenessWarning]


class AnnualizedIncomeScheduleIncome(BaseModel):
    """Trailing income totals for the personal report package."""

    annualized_salary: Decimal
    annualized_bonus: Decimal
    annualized_dividend: Decimal
    annualized_total: Decimal
    currency: str = Field(min_length=3, max_length=3)
    calculation_basis: str


class AnnualizedIncomeScheduleHolding(BaseModel):
    """Restricted long-term compensation holding for the personal report package."""

    ticker: str
    compensation_type: str
    fair_value: Decimal
    currency: str = Field(min_length=3, max_length=3)
    valuation_basis: str
    vesting_schedule: str | None = None
    unlock_date: date | None = None
    liquidity_class: str
    net_worth_treatment: str


class AnnualizedIncomeScheduleNetWorthTreatment(BaseModel):
    """Net-worth presentation semantics for restricted compensation."""

    liquid_net_worth_default: str
    restricted_wealth_basis: str
    include_restricted_query: str
    exclude_restricted_query: str


class AnnualizedIncomeScheduleResponse(BaseModel):
    """Report-ready annualized income and long-term compensation schedule."""

    section_id: str
    label: str
    as_of_date: date
    trailing_period_start: date
    trailing_period_end: date
    trailing_period_days: int
    income: AnnualizedIncomeScheduleIncome
    restricted_holdings: list[AnnualizedIncomeScheduleHolding]
    restricted_fair_value_total: Decimal
    restricted_fair_value_total_currency: str = Field(min_length=3, max_length=3)
    net_worth_treatment: AnnualizedIncomeScheduleNetWorthTreatment
    notes: list[str]
