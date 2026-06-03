"""Pydantic schemas for financial reporting endpoints."""

from datetime import date
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from src.models import AccountType


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
