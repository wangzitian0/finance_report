"""Canonical L1 reporting-line registry mapping standard report lines to frameworks."""

from __future__ import annotations

from dataclasses import dataclass

from src.schemas.reporting import PersonalReportingFrameworkId, ReportLineId


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


# Sentinel order value: line does not belong to this framework's presentation.
_NOT_APPLICABLE_ORDER: int = 999


L1_REGISTRY: dict[ReportLineId, RegisteredReportLine] = {
    ReportLineId.CASH_AND_CASH_EQUIVALENTS: RegisteredReportLine(
        line_id=ReportLineId.CASH_AND_CASH_EQUIVALENTS,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="balance_sheet",
        section="assets",
        order_us=10,
        order_hk=10,
        label="Cash and cash equivalents",
    ),
    ReportLineId.MARKETABLE_SECURITIES: RegisteredReportLine(
        line_id=ReportLineId.MARKETABLE_SECURITIES,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE},
        statement="balance_sheet",
        section="assets",
        order_us=20,
        order_hk=_NOT_APPLICABLE_ORDER,
        label="Marketable securities",
    ),
    ReportLineId.FINANCIAL_ASSETS_AT_FAIR_VALUE: RegisteredReportLine(
        line_id=ReportLineId.FINANCIAL_ASSETS_AT_FAIR_VALUE,
        frameworks={PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="balance_sheet",
        section="assets",
        order_us=_NOT_APPLICABLE_ORDER,
        order_hk=20,
        label="Financial assets at fair value",
    ),
    ReportLineId.INVESTMENTS_FUNDS: RegisteredReportLine(
        line_id=ReportLineId.INVESTMENTS_FUNDS,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="balance_sheet",
        section="assets",
        order_us=30,
        order_hk=30,
        label="Investments in funds",
    ),
    ReportLineId.RESTRICTED_COMPENSATION: RegisteredReportLine(
        line_id=ReportLineId.RESTRICTED_COMPENSATION,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="balance_sheet",
        section="assets",
        order_us=40,
        order_hk=40,
        label="Restricted compensation",
    ),
    ReportLineId.INVESTMENT_PROPERTY: RegisteredReportLine(
        line_id=ReportLineId.INVESTMENT_PROPERTY,
        frameworks={PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="balance_sheet",
        section="assets",
        order_us=_NOT_APPLICABLE_ORDER,
        order_hk=50,
        label="Investment property",
    ),
    ReportLineId.BIOLOGICAL_ASSETS: RegisteredReportLine(
        line_id=ReportLineId.BIOLOGICAL_ASSETS,
        frameworks={PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="balance_sheet",
        section="assets",
        order_us=_NOT_APPLICABLE_ORDER,
        order_hk=60,
        label="Biological assets",
    ),
    ReportLineId.MANUAL_PRIVATE_ASSETS: RegisteredReportLine(
        line_id=ReportLineId.MANUAL_PRIVATE_ASSETS,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="balance_sheet",
        section="assets",
        order_us=70,
        order_hk=70,
        label="Manual private assets",
    ),
    ReportLineId.FINANCIAL_LIABILITIES: RegisteredReportLine(
        line_id=ReportLineId.FINANCIAL_LIABILITIES,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="balance_sheet",
        section="liabilities",
        order_us=10,
        order_hk=10,
        label="Financial liabilities",
    ),
    ReportLineId.FX_TRANSLATION: RegisteredReportLine(
        line_id=ReportLineId.FX_TRANSLATION,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="balance_sheet",
        section="equity",
        order_us=10,
        order_hk=10,
        label="FX translation adjustment",
    ),
    ReportLineId.DIVIDENDS_AND_INTEREST: RegisteredReportLine(
        line_id=ReportLineId.DIVIDENDS_AND_INTEREST,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="income_statement",
        section="income",
        order_us=10,
        order_hk=10,
        label="Dividends and interest income",
    ),
    ReportLineId.UNREALIZED_INVESTMENT_GAIN_LOSS: RegisteredReportLine(
        line_id=ReportLineId.UNREALIZED_INVESTMENT_GAIN_LOSS,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE},
        statement="income_statement",
        section="income",
        order_us=20,
        order_hk=_NOT_APPLICABLE_ORDER,
        label="Unrealized investment gain/loss",
    ),
    ReportLineId.FAIR_VALUE_CHANGE_IN_FINANCIAL_ASSETS: RegisteredReportLine(
        line_id=ReportLineId.FAIR_VALUE_CHANGE_IN_FINANCIAL_ASSETS,
        frameworks={PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="income_statement",
        section="income",
        order_us=_NOT_APPLICABLE_ORDER,
        order_hk=20,
        label="Fair value change in financial assets",
    ),
    ReportLineId.FX_GAIN_LOSS: RegisteredReportLine(
        line_id=ReportLineId.FX_GAIN_LOSS,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="income_statement",
        section="income",
        order_us=30,
        order_hk=30,
        label="FX gain/loss",
    ),
    ReportLineId.INVESTMENT_FEES: RegisteredReportLine(
        line_id=ReportLineId.INVESTMENT_FEES,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="income_statement",
        section="expenses",
        order_us=10,
        order_hk=10,
        label="Investment fees and commissions",
    ),
    ReportLineId.ENDING_CASH: RegisteredReportLine(
        line_id=ReportLineId.ENDING_CASH,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="cash_flow",
        section="cash",
        order_us=10,
        order_hk=10,
        label="Ending cash balance",
    ),
    ReportLineId.INVESTING_FEES: RegisteredReportLine(
        line_id=ReportLineId.INVESTING_FEES,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="cash_flow",
        section="investing",
        order_us=10,
        order_hk=10,
        label="Investment fees and commissions paid",
    ),
    ReportLineId.INTERNAL_TRANSFERS: RegisteredReportLine(
        line_id=ReportLineId.INTERNAL_TRANSFERS,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="cash_flow",
        section="cash",
        order_us=20,
        order_hk=20,
        label="Internal transfers",
    ),
    ReportLineId.FUND_LIQUIDITY: RegisteredReportLine(
        line_id=ReportLineId.FUND_LIQUIDITY,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="notes",
        section="notes",
        order_us=10,
        order_hk=10,
        label="Fund Liquidity Note",
    ),
    ReportLineId.TAX_HOOKS: RegisteredReportLine(
        line_id=ReportLineId.TAX_HOOKS,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="notes",
        section="notes",
        order_us=20,
        order_hk=20,
        label="Tax Hooks Note",
    ),
    ReportLineId.RESTRICTED_ASSET_TREATMENT: RegisteredReportLine(
        line_id=ReportLineId.RESTRICTED_ASSET_TREATMENT,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="notes",
        section="notes",
        order_us=30,
        order_hk=30,
        label="Restricted Asset Treatment Note",
    ),
    ReportLineId.MANUAL_VALUATION_BASIS: RegisteredReportLine(
        line_id=ReportLineId.MANUAL_VALUATION_BASIS,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="notes",
        section="notes",
        order_us=40,
        order_hk=40,
        label="Manual Valuation Basis Note",
    ),
    ReportLineId.LIABILITY_COVERAGE: RegisteredReportLine(
        line_id=ReportLineId.LIABILITY_COVERAGE,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="notes",
        section="notes",
        order_us=50,
        order_hk=50,
        label="Liability Coverage Note",
    ),
    ReportLineId.TRANSFER_MATCHING: RegisteredReportLine(
        line_id=ReportLineId.TRANSFER_MATCHING,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="notes",
        section="notes",
        order_us=60,
        order_hk=60,
        label="Transfer Matching Note",
    ),
    ReportLineId.TAX_RELEVANT_ITEMS: RegisteredReportLine(
        line_id=ReportLineId.TAX_RELEVANT_ITEMS,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE, PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="notes",
        section="notes",
        order_us=70,
        order_hk=70,
        label="Tax Relevant Items Note",
    ),
    ReportLineId.US_LIKE_MARKET_PRICE_BASIS: RegisteredReportLine(
        line_id=ReportLineId.US_LIKE_MARKET_PRICE_BASIS,
        frameworks={PersonalReportingFrameworkId.US_GAAP_LIKE},
        statement="notes",
        section="notes",
        order_us=80,
        order_hk=_NOT_APPLICABLE_ORDER,
        label="US-like Market Price Basis Note",
    ),
    ReportLineId.HK_LIKE_FAIR_VALUE_BASIS: RegisteredReportLine(
        line_id=ReportLineId.HK_LIKE_FAIR_VALUE_BASIS,
        frameworks={PersonalReportingFrameworkId.HKFRS_LIKE},
        statement="notes",
        section="notes",
        order_us=_NOT_APPLICABLE_ORDER,
        order_hk=80,
        label="HK-like Fair Value Basis Note",
    ),
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
    if reg is None:
        return False
    return framework_id in reg.frameworks


def get_framework_ordered_lines(
    framework_id: PersonalReportingFrameworkId,
    statement: str | None = None,
) -> list[RegisteredReportLine]:
    """Return registry lines applicable to a framework, sorted by framework-specific presentation order.

    Includes US-union / HK-union elements: for any framework, we return all lines that are
    either valid in that framework or belong to the statements. HK-only lines are included
    but marked/configured so that they are empty under US.
    """
    lines = list(L1_REGISTRY.values())
    if statement is not None:
        lines = [line for line in lines if line.statement == statement]

    if framework_id == PersonalReportingFrameworkId.US_GAAP_LIKE:
        # For US, sort by order_us. Any HK-only lines will have order_us = 999
        lines.sort(key=lambda line: (line.order_us, line.line_id.value))
    else:
        # For HK, sort by order_hk. Any US-only lines will have order_hk = 999
        lines.sort(key=lambda line: (line.order_hk, line.line_id.value))

    return lines
