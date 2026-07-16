"""Pydantic schemas for financial reporting endpoints."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from src.ledger import AccountType, Direction
from src.reporting import ReportType
from src.reporting.base.types import (
    PersonalReportingFrameworkId,
    PolicyDimension,
    ReportLineId as ReportLineId,
)
from src.schemas.base import CurrencyCode
from src.schemas.provenance import DataProvenance

_FRAMEWORK_POLICY_LINE_MAPPING_TARGETS = frozenset({"balance_sheet", "income_statement", "cash_flow", "notes"})


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
    # Worst-input confidence tier of the line's contributing facts (Axiom B).
    # None when the line has no rated contributing fact.
    confidence_tier: str | None = None
    provenance: DataProvenance | None = None


class AccountLineageLine(BaseModel):
    """One posted journal line contributing to an account's report balance.

    Carries a ``journal_line`` evidence anchor so the UI can drill into the full
    lineage graph (journal line -> statement transaction -> atomic fact ->
    source document).
    """

    journal_line_id: UUID = Field(description="Evidence anchor for /api/evidence/lineage drill-down")
    journal_entry_id: UUID = Field(description="Parent journal entry id")
    entry_date: date = Field(description="Journal entry date")
    memo: str = Field(description="Journal entry memo")
    direction: Direction = Field(description="Line direction: DEBIT or CREDIT")
    original_amount: Decimal = Field(description="Line amount in its original currency")
    original_currency: str = Field(min_length=3, max_length=3, description="Original line currency")
    amount: Decimal = Field(description="Signed amount converted into the report currency")


class AccountLineageResponse(BaseModel):
    """Contributing journal lines behind a single account's report balance."""

    account_id: UUID = Field(description="Account whose balance is being explained")
    account_name: str = Field(description="Account display name")
    account_type: AccountType = Field(description="Account type (ASSET/LIABILITY/EQUITY/INCOME/EXPENSE)")
    currency: str = Field(min_length=3, max_length=3, description="Report presentation currency")
    as_of_date: date = Field(description="Report end date filter")
    start_date: date | None = Field(default=None, description="Optional period start filter")
    total: Decimal = Field(description="Signed total of contributing lines in the report currency")
    lines: list[AccountLineageLine] = Field(description="Posted/reconciled lines contributing to the balance")


class BalanceSheetResponse(BaseModel):
    """Balance sheet response schema."""

    as_of_date: date
    currency: str = Field(min_length=3, max_length=3)
    assets: list[ReportLine]
    liabilities: list[ReportLine]
    equity: list[ReportLine]
    # Net Worth aggregate confidence: the worst-input tier across rated lines
    # (defined rollup, not an invented number). None when nothing is rated.
    confidence_tier: str | None = None
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    net_income: Decimal = Decimal("0.00")
    unrealized_fx_gain_loss: Decimal = Decimal("0.00")
    net_worth_adjustment_gain_loss: Decimal = Decimal("0.00")
    fx_warnings: list[dict[str, str]] = Field(default_factory=list)
    # Point-in-time gap (#1791 follow-up): non-empty when a portfolio position
    # was excluded from total_assets because no price snapshot exists on or
    # before as_of_date -- the total is still accurate, just possibly
    # incomplete for a position with a data gap at this historical date.
    portfolio_warnings: list[dict[str, str]] = Field(default_factory=list)
    # Opening-balance gate (AC2.16.4 / #1481): non-empty when activity exists with
    # no recorded opening balance; the total then reflects only period movement and
    # confidence_tier is degraded to LOW.
    opening_balance_warnings: list[dict[str, str]] = Field(default_factory=list)
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


class NetWorthAllocationSourceLine(BaseModel):
    """Source line retained behind one net-worth allocation row."""

    source_type: str = Field(description="Contributor source class for drill-through.")
    source_id: UUID | None = Field(default=None, description="Source record id when the contributor has one.")
    label: str = Field(description="Human-readable contributor label.")
    value: Decimal = Field(description="Signed contributor value in the report currency.")
    href: str | None = Field(default=None, description="Internal drill-through href for the contributor.")

    @field_validator("href")
    @classmethod
    def validate_href(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_internal_action_href(value)


class NetWorthAllocationRow(BaseModel):
    """Signed allocation row grouped by asset class, liquidity, and source currency."""

    asset_class: str = Field(description="Allocation asset class bucket.")
    liquidity_class: str = Field(description="Allocation liquidity bucket.")
    source_currency: str = Field(min_length=3, max_length=3, description="Original source currency bucket.")
    value: Decimal = Field(description="Signed row value in the report currency.")
    percentage_of_net_worth: Decimal | None = Field(
        default=None,
        description="Signed row value divided by net worth, as a percentage.",
    )
    source_line_count: int = Field(ge=0, description="Number of source lines included in this row.")
    source_lines: list[NetWorthAllocationSourceLine] = Field(description="Contributor lines behind this row.")


class NetWorthAllocationResponse(BaseModel):
    """Net-worth allocation schedule response."""

    as_of_date: date = Field(description="Valuation date for the schedule.")
    currency: str = Field(min_length=3, max_length=3, description="Report presentation currency.")
    include_restricted: bool = Field(description="Whether restricted and illiquid valuation snapshots are included.")
    total_assets: Decimal = Field(description="Balance-sheet total assets in the report currency.")
    total_liabilities: Decimal = Field(description="Balance-sheet total liabilities in the report currency.")
    net_worth: Decimal = Field(description="Total assets minus total liabilities.")
    rows: list[NetWorthAllocationRow] = Field(description="Signed allocation rows that sum to net worth.")
    # Same opening-balance gate as the balance sheet (AC2.16.4 / #1481).
    confidence_tier: str | None = Field(
        default=None, description="Aggregate confidence tier; LOW when an opening balance is missing."
    )
    opening_balance_warnings: list[dict[str, str]] = Field(
        default_factory=list, description="Non-empty when activity exists without a recorded opening balance."
    )
    portfolio_warnings: list[dict[str, str]] = Field(
        default_factory=list,
        description="Same portfolio point-in-time gaps as the balance sheet (#1791 follow-up).",
    )


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
    # EPIC-022 #887: the account whose movement this line represents, so the
    # frontend can drill the amount down to its contributing journal lines via
    # /api/reports/account-lineage (each cash-flow line maps to exactly one
    # account). None for any future aggregate line with no single anchor.
    account_id: UUID | None = Field(
        default=None,
        description="Account this line's movement belongs to, for report drill-down.",
    )


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
    fx_warnings: list[dict[str, str]] = Field(default_factory=list)


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
    supported_frameworks: list[str] = Field(default_factory=list)
    selected_framework_id: str | None = None
    framework_policy_endpoint: str | None = None
    sections: list[PersonalReportPackageSectionContract]
    export_contract: PersonalReportPackageExportContract


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
    holding_intent: str | None = None
    horizon: str | None = None


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
        missing = [
            f"{self.domain.value}.{dimension.value}"
            for dimension in PolicyDimension
            if not getattr(self, dimension.value)
        ]
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

    @model_validator(mode="after")
    def validate_rules_line_mappings(self) -> "FrameworkPolicyMatrix":
        from src.reporting import is_valid_line_for_framework

        for rule in self.rules:
            for target, line_id in rule.line_mappings.items():
                if target not in _FRAMEWORK_POLICY_LINE_MAPPING_TARGETS:
                    raise ValueError(
                        f"Rule for domain {rule.domain.value} maps to unknown statement target '{target}'; "
                        f"allowed: {', '.join(sorted(_FRAMEWORK_POLICY_LINE_MAPPING_TARGETS))}"
                    )
                if not is_valid_line_for_framework(line_id, self.framework_id):
                    raise ValueError(
                        f"Rule for domain {rule.domain.value} maps to '{line_id}' which is not a registered L1 line valid in framework '{self.framework_id.value}'"
                    )
        return self


class FrameworkPolicyResult(BaseModel):
    """Read-only target-backward policy result consumed by readiness and reporting."""

    result_id: str
    framework_id: PersonalReportingFrameworkId
    matrix_version: str
    report_period_start: date
    report_period_end: date
    generated_at: date
    required_statements: list[str]
    decisions: list[FrameworkPolicyDecision]
    gaps: list[FrameworkPolicyGap] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_decision_dimensions(self) -> "FrameworkPolicyResult":
        incomplete = [
            f"{decision.domain.value}.{dimension.value}"
            for decision in self.decisions
            for dimension in PolicyDimension
            if not getattr(decision, dimension.value)
        ]
        if incomplete:
            raise ValueError(f"missing required policy dimensions: {', '.join(sorted(set(incomplete)))}")

        from src.reporting import is_valid_line_for_framework

        for decision in self.decisions:
            for target, line_id in decision.line_mappings.items():
                if target not in _FRAMEWORK_POLICY_LINE_MAPPING_TARGETS:
                    raise ValueError(
                        f"Decision line mapping uses unknown statement target '{target}'; "
                        f"allowed: {', '.join(sorted(_FRAMEWORK_POLICY_LINE_MAPPING_TARGETS))}"
                    )
                if not is_valid_line_for_framework(line_id, self.framework_id):
                    raise ValueError(
                        f"Line mapping '{line_id}' is not a registered L1 line valid in framework '{self.framework_id.value}'"
                    )
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


class PersonalReportPackageSourceTrustSummary(BaseModel):
    """Source-class trust summary for package readiness consumers."""

    source_classes: list[str] = Field(default_factory=list)
    deterministic_pr_source_classes: list[str] = Field(default_factory=list)
    post_merge_llm_ocr_source_classes: list[str] = Field(default_factory=list)
    manual_trusted_source_classes: list[str] = Field(default_factory=list)
    gap_source_classes: list[str] = Field(default_factory=list)
    blocker_codes: list[str] = Field(default_factory=list)


class PersonalReportPackageReadinessState(str, Enum):
    """Allowed states for the personal report package readiness contract."""

    DRAFT = "draft"
    PROCESSING = "processing"
    BLOCKED = "blocked"
    READY = "ready"
    GENERATED = "generated"
    STALE = "stale"


class PersonalReportPackageSnapshotStatus(str, Enum):
    """Durability/trust state of a generated package snapshot."""

    DRAFT = "draft"
    TRUSTED = "trusted"


class PersonalReportPackageReadinessResponse(BaseModel):
    """Deterministic readiness state for the personal report package."""

    package_id: str
    state: PersonalReportPackageReadinessState
    label: str
    action_href: str
    blocking_count: int
    blockers: list[PersonalReportPackageReadinessBlocker] = Field(default_factory=list)
    source_summary: dict[str, int | str] = Field(default_factory=dict)
    source_trust_summary: PersonalReportPackageSourceTrustSummary = Field(
        default_factory=PersonalReportPackageSourceTrustSummary
    )
    generated_at: datetime | None = None
    stale_since: datetime | None = None

    @field_validator("action_href")
    @classmethod
    def validate_action_href(cls, value: str) -> str:
        return _validate_internal_action_href(value)


class PersonalReportPackageSnapshotSummary(BaseModel):
    """Saved personal report package snapshot metadata."""

    id: UUID = Field(description="Report snapshot identifier")
    package_id: str = Field(description="Personal report package contract identifier")
    status: PersonalReportPackageSnapshotStatus = Field(description="Snapshot trust state")
    framework_id: PersonalReportingFrameworkId = Field(description="Framework selected for the frozen package")
    start_date: date = Field(description="Package reporting period start date")
    end_date: date = Field(description="Package reporting period end date")
    as_of_date: date = Field(description="Package balance-sheet and point-in-time report date")
    currency: str = Field(description="Snapshot presentation currency", min_length=3, max_length=3)
    readiness_state: str = Field(description="Readiness state captured when the snapshot was generated")
    is_latest: bool = Field(description="Whether this is the latest snapshot for the same package period")
    created_at: datetime | None = Field(default=None, description="Snapshot creation timestamp")


class ReportSnapshotSummary(BaseModel):
    """Typed metadata for a Layer-4 ``ReportSnapshot`` (#1008, AC18.4.2).

    Replaces the model-less ``list[dict]`` returned by
    ``GET /reports/{report_type}/snapshots`` so the contract is declared in
    OpenAPI and built from the ORM via ``from_attributes`` instead of a
    hand-rolled dict.
    """

    model_config = {"from_attributes": True}

    id: UUID = Field(description="Report snapshot identifier")
    report_type: ReportType = Field(description="Report type this snapshot was generated for")
    as_of_date: date | None = Field(default=None, description="Point-in-time report date")
    start_date: date | None = Field(default=None, description="Period start date (None for point-in-time reports)")
    rule_version_id: UUID | None = Field(
        default=None,
        description="Rule version used to generate the snapshot (None for package snapshots)",
    )
    is_latest: bool = Field(description="Whether this is the latest snapshot for the same type/period")
    created_at: datetime | None = Field(default=None, description="Snapshot creation timestamp")


class PersonalReportPackageGenerateRequest(BaseModel):
    """Request body for creating a saved package snapshot."""

    framework_id: PersonalReportingFrameworkId = Field(
        default=PersonalReportingFrameworkId.US_GAAP_LIKE,
        description="Framework to use when generating the package snapshot",
    )
    start_date: date | None = Field(default=None, description="Requested reporting period start date")
    end_date: date | None = Field(default=None, description="Requested reporting period end date")
    as_of_date: date | None = Field(default=None, description="Requested point-in-time report date")
    currency: CurrencyCode | None = Field(
        default=None,
        description="Requested presentation currency",
        min_length=3,
        max_length=3,
    )
    include_restricted: bool = Field(
        default=False,
        description="Whether restricted manual valuations are included in generated section payloads",
    )


class PersonalReportPackageSnapshotResponse(PersonalReportPackageSnapshotSummary):
    """Saved personal report package snapshot plus frozen payload."""

    payload: dict[str, Any] = Field(description="Frozen package payload used for reopen and export")


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
    details: list[dict[str, str | Decimal | None]] = Field(default_factory=list)


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
    source_classes: list[str] = Field(default_factory=list)
    proof_level: str = "unclassified"
    anchor_count: int = 0
    blocker_codes: list[str] = Field(default_factory=list)


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
    # Structured evidence basis (#706): the snapshot's `valuation_basis` enum value
    # (e.g. `employer_grant_document`, `market_appraisal`), or `unspecified` when no
    # basis was captured. Surfaces how the manual-trusted value was substantiated.
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
