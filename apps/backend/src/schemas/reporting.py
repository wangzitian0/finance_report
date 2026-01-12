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
    trends: list[IncomeStatementTrend]


class TrendPeriod(str, Enum):
    """Supported period grouping for trends."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


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
