"""Reporting-owned framework and canonical-line vocabulary."""

from enum import Enum


class PersonalReportingFrameworkId(str, Enum):
    """Supported personal reporting framework targets."""

    US_GAAP_LIKE = "personal_us_gaap_like"
    HKFRS_LIKE = "personal_hkfrs_like"


class ReportLineId(str, Enum):
    """Enumerated canonical L1 reporting lines for personal report packages."""

    CASH_AND_CASH_EQUIVALENTS = "assets.cash_and_cash_equivalents"
    MARKETABLE_SECURITIES = "assets.marketable_securities"
    FINANCIAL_ASSETS_AT_FAIR_VALUE = "assets.financial_assets_at_fair_value"
    INVESTMENTS_FUNDS = "assets.investments.funds"
    RESTRICTED_COMPENSATION = "assets.restricted_compensation"
    INVESTMENT_PROPERTY = "assets.investment_property"
    BIOLOGICAL_ASSETS = "assets.biological_assets"
    MANUAL_PRIVATE_ASSETS = "assets.manual_private_assets"
    FINANCIAL_LIABILITIES = "liabilities.financial_liabilities"
    FX_TRANSLATION = "equity.fx_translation"
    DIVIDENDS_AND_INTEREST = "income.dividends_and_interest"
    UNREALIZED_INVESTMENT_GAIN_LOSS = "income.unrealized_investment_gain_loss"
    FAIR_VALUE_CHANGE_IN_FINANCIAL_ASSETS = "income.fair_value_change_in_financial_assets"
    FX_GAIN_LOSS = "income.fx_gain_loss"
    INVESTMENT_FEES = "expenses.investment_fees"
    ENDING_CASH = "cash.ending_cash"
    INVESTING_FEES = "investing.fees"
    INTERNAL_TRANSFERS = "cash.internal_transfers"
    FUND_LIQUIDITY = "notes.fund_liquidity"
    TAX_HOOKS = "notes.tax_hooks"
    RESTRICTED_ASSET_TREATMENT = "notes.restricted_asset_treatment"
    MANUAL_VALUATION_BASIS = "notes.manual_valuation_basis"
    LIABILITY_COVERAGE = "notes.liability_coverage"
    TRANSFER_MATCHING = "notes.transfer_matching"
    TAX_RELEVANT_ITEMS = "notes.tax_relevant_items"
    US_LIKE_MARKET_PRICE_BASIS = "notes.us_like_market_price_basis"
    HK_LIKE_FAIR_VALUE_BASIS = "notes.hk_like_fair_value_basis"


class PolicyDimension(str, Enum):
    """Required decision dimensions for every framework policy conclusion."""

    RECOGNITION = "recognition"
    MEASUREMENT = "measurement"
    CLASSIFICATION = "classification"
    PRESENTATION = "presentation"
    DISCLOSURE = "disclosure"


__all__ = [
    "PersonalReportingFrameworkId",
    "PolicyDimension",
    "ReportLineId",
]
