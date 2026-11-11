"""Canonical L1 reporting-line registry mapping standard report lines to frameworks."""

from __future__ import annotations

from dataclasses import dataclass

from src.reporting.base.types import PersonalReportingFrameworkId, ReportLineId


@dataclass(frozen=True)
class RegisteredReportLine:
    """A registered L1 reporting line with metadata for statement rendering and frameworks."""

    line_id: ReportLineId
    frameworks: set[PersonalReportingFrameworkId]
    statement: str
    section: str
    order_us: int
    order_hk: int
    label: str


_NOT_APPLICABLE_ORDER: int = 999
_US = PersonalReportingFrameworkId.US_GAAP_LIKE
_HK = PersonalReportingFrameworkId.HKFRS_LIKE
_FW_MAP: dict[str, set[PersonalReportingFrameworkId]] = {
    "both": {_US, _HK},
    "us": {_US},
    "hk": {_HK},
}

_L1_SPECS: tuple[tuple[ReportLineId, str, str, int, int, str, str], ...] = (
    (ReportLineId.CASH_IN_TRANSIT, "balance_sheet", "assets", 15, 15, "Cash in transit", "both"),
    (ReportLineId.SALARY, "income_statement", "income", 50, 50, "Salary and employment income", "both"),
    (ReportLineId.INVESTMENT_INCOME, "income_statement", "income", 52, 52, "Investment income", "both"),
    (ReportLineId.REFUNDS, "income_statement", "income", 53, 53, "Refund income", "both"),
    (ReportLineId.OTHER_INCOME, "income_statement", "income", 54, 54, "Other income", "both"),
    (ReportLineId.DINING_EXPENSES, "income_statement", "expenses", 50, 50, "Dining", "both"),
    (ReportLineId.GROCERIES_EXPENSES, "income_statement", "expenses", 51, 51, "Groceries", "both"),
    (ReportLineId.TRANSPORT_EXPENSES, "income_statement", "expenses", 52, 52, "Transport", "both"),
    (ReportLineId.HOUSING_EXPENSES, "income_statement", "expenses", 53, 53, "Housing", "both"),
    (ReportLineId.UTILITIES_EXPENSES, "income_statement", "expenses", 54, 54, "Utilities", "both"),
    (ReportLineId.SHOPPING_EXPENSES, "income_statement", "expenses", 55, 55, "Shopping", "both"),
    (ReportLineId.HEALTHCARE_EXPENSES, "income_statement", "expenses", 56, 56, "Healthcare", "both"),
    (ReportLineId.ENTERTAINMENT_EXPENSES, "income_statement", "expenses", 57, 57, "Entertainment", "both"),
    (ReportLineId.TRAVEL_EXPENSES, "income_statement", "expenses", 58, 58, "Travel", "both"),
    (ReportLineId.EDUCATION_EXPENSES, "income_statement", "expenses", 59, 59, "Education", "both"),
    (ReportLineId.INSURANCE_EXPENSES, "income_statement", "expenses", 60, 60, "Insurance", "both"),
    (ReportLineId.FEES_EXPENSES, "income_statement", "expenses", 61, 61, "Fees and charges", "both"),
    (ReportLineId.OTHER_EXPENSES, "income_statement", "expenses", 62, 62, "Other expenses", "both"),
    (
        ReportLineId.CASH_AND_CASH_EQUIVALENTS,
        "balance_sheet",
        "assets",
        10,
        10,
        "Cash and cash equivalents",
        "both",
    ),
    (
        ReportLineId.MARKETABLE_SECURITIES,
        "balance_sheet",
        "assets",
        20,
        _NOT_APPLICABLE_ORDER,
        "Marketable securities",
        "us",
    ),
    (
        ReportLineId.FINANCIAL_ASSETS_AT_FAIR_VALUE,
        "balance_sheet",
        "assets",
        _NOT_APPLICABLE_ORDER,
        20,
        "Financial assets at fair value",
        "hk",
    ),
    (ReportLineId.INVESTMENTS_FUNDS, "balance_sheet", "assets", 30, 30, "Investments in funds", "both"),
    (ReportLineId.RESTRICTED_COMPENSATION, "balance_sheet", "assets", 40, 40, "Restricted compensation", "both"),
    (
        ReportLineId.INVESTMENT_PROPERTY,
        "balance_sheet",
        "assets",
        _NOT_APPLICABLE_ORDER,
        50,
        "Investment property",
        "hk",
    ),
    (
        ReportLineId.BIOLOGICAL_ASSETS,
        "balance_sheet",
        "assets",
        _NOT_APPLICABLE_ORDER,
        60,
        "Biological assets",
        "hk",
    ),
    (ReportLineId.MANUAL_PRIVATE_ASSETS, "balance_sheet", "assets", 70, 70, "Manual private assets", "both"),
    (ReportLineId.FINANCIAL_LIABILITIES, "balance_sheet", "liabilities", 10, 10, "Financial liabilities", "both"),
    (ReportLineId.FX_TRANSLATION, "balance_sheet", "equity", 10, 10, "FX translation adjustment", "both"),
    (
        ReportLineId.DIVIDENDS_AND_INTEREST,
        "income_statement",
        "income",
        10,
        10,
        "Dividends and interest income",
        "both",
    ),
    (
        ReportLineId.UNREALIZED_INVESTMENT_GAIN_LOSS,
        "income_statement",
        "income",
        20,
        _NOT_APPLICABLE_ORDER,
        "Unrealized investment gain/loss",
        "us",
    ),
    (
        ReportLineId.FAIR_VALUE_CHANGE_IN_FINANCIAL_ASSETS,
        "income_statement",
        "income",
        _NOT_APPLICABLE_ORDER,
        20,
        "Fair value change in financial assets",
        "hk",
    ),
    (ReportLineId.FX_GAIN_LOSS, "income_statement", "income", 30, 30, "FX gain/loss", "both"),
    (
        ReportLineId.INVESTMENT_FEES,
        "income_statement",
        "expenses",
        10,
        10,
        "Investment fees and commissions",
        "both",
    ),
    (ReportLineId.ENDING_CASH, "cash_flow", "cash", 10, 10, "Ending cash balance", "both"),
    (ReportLineId.INVESTING_FEES, "cash_flow", "investing", 10, 10, "Investment fees and commissions paid", "both"),
    (ReportLineId.INTERNAL_TRANSFERS, "cash_flow", "cash", 20, 20, "Internal transfers", "both"),
    (ReportLineId.FUND_LIQUIDITY, "notes", "notes", 10, 10, "Fund Liquidity Note", "both"),
    (ReportLineId.TAX_HOOKS, "notes", "notes", 20, 20, "Tax Hooks Note", "both"),
    (ReportLineId.RESTRICTED_ASSET_TREATMENT, "notes", "notes", 30, 30, "Restricted Asset Treatment Note", "both"),
    (ReportLineId.MANUAL_VALUATION_BASIS, "notes", "notes", 40, 40, "Manual Valuation Basis Note", "both"),
    (ReportLineId.LIABILITY_COVERAGE, "notes", "notes", 50, 50, "Liability Coverage Note", "both"),
    (ReportLineId.TRANSFER_MATCHING, "notes", "notes", 60, 60, "Transfer Matching Note", "both"),
    (ReportLineId.TAX_RELEVANT_ITEMS, "notes", "notes", 70, 70, "Tax Relevant Items Note", "both"),
    (
        ReportLineId.US_LIKE_MARKET_PRICE_BASIS,
        "notes",
        "notes",
        80,
        _NOT_APPLICABLE_ORDER,
        "US-like Market Price Basis Note",
        "us",
    ),
    (
        ReportLineId.HK_LIKE_FAIR_VALUE_BASIS,
        "notes",
        "notes",
        _NOT_APPLICABLE_ORDER,
        80,
        "HK-like Fair Value Basis Note",
        "hk",
    ),
)

L1_REGISTRY: dict[ReportLineId, RegisteredReportLine] = {
    line_id: RegisteredReportLine(
        line_id=line_id,
        frameworks=set(_FW_MAP[fw]),
        statement=statement,
        section=section,
        order_us=order_us,
        order_hk=order_hk,
        label=label,
    )
    for line_id, statement, section, order_us, order_hk, label, fw in _L1_SPECS
}


def get_registered_line(line_id: str | ReportLineId) -> RegisteredReportLine | None:
    """Look up a registered line by its string ID or enum value."""
    try:
        enum_val = ReportLineId(line_id) if isinstance(line_id, str) else line_id
        return L1_REGISTRY.get(enum_val)
    except ValueError:
        return None


def is_valid_line_for_framework(line_id: str | ReportLineId, framework_id: PersonalReportingFrameworkId) -> bool:
    """Return whether a line is registered and valid under a given framework."""
    reg = get_registered_line(line_id)
    return reg is not None and framework_id in reg.frameworks


def get_framework_ordered_lines(
    framework_id: PersonalReportingFrameworkId,
    statement: str | None = None,
) -> list[RegisteredReportLine]:
    """Return registry lines sorted by framework-specific presentation order."""
    lines = [line for line in L1_REGISTRY.values() if statement is None or line.statement == statement]
    is_us = framework_id == _US
    return sorted(lines, key=lambda line: (line.order_us if is_us else line.order_hk, line.line_id.value))


INCOME_CATEGORY_LINES: dict[str, ReportLineId] = {
    "SALARY": ReportLineId.SALARY,
    "INTEREST": ReportLineId.DIVIDENDS_AND_INTEREST,
    "INVESTMENT_INCOME": ReportLineId.INVESTMENT_INCOME,
    "REFUND": ReportLineId.REFUNDS,
    "OTHER_INCOME": ReportLineId.OTHER_INCOME,
}
EXPENSE_CATEGORY_LINES: dict[str, ReportLineId] = {
    "DINING": ReportLineId.DINING_EXPENSES,
    "GROCERIES": ReportLineId.GROCERIES_EXPENSES,
    "TRANSPORT": ReportLineId.TRANSPORT_EXPENSES,
    "HOUSING": ReportLineId.HOUSING_EXPENSES,
    "UTILITIES": ReportLineId.UTILITIES_EXPENSES,
    "SHOPPING": ReportLineId.SHOPPING_EXPENSES,
    "HEALTHCARE": ReportLineId.HEALTHCARE_EXPENSES,
    "ENTERTAINMENT": ReportLineId.ENTERTAINMENT_EXPENSES,
    "TRAVEL": ReportLineId.TRAVEL_EXPENSES,
    "EDUCATION": ReportLineId.EDUCATION_EXPENSES,
    "INSURANCE": ReportLineId.INSURANCE_EXPENSES,
    "FEES": ReportLineId.FEES_EXPENSES,
    "OTHER_EXPENSE": ReportLineId.OTHER_EXPENSES,
}


def economic_category_line(category: str | None, account_type: str) -> ReportLineId:
    """Map exact accepted category values; incomplete history stays honestly generic."""
    if account_type == "INCOME":
        return INCOME_CATEGORY_LINES.get(category or "", ReportLineId.OTHER_INCOME)
    if account_type == "EXPENSE":
        return EXPENSE_CATEGORY_LINES.get(category or "", ReportLineId.OTHER_EXPENSES)
    raise ValueError("Economic category mapping requires an income or expense account")
