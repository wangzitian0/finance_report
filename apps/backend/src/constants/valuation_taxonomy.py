"""Stable valuation taxonomy contract (#1221, EPIC-011 AC11.21).

Single source of truth for the small, durable set of valuation classes that
report generation, net worth, allocation, and framework-policy logic depend on.

Design rule (the whole point of this contract): jurisdiction-, scheme-, and
vendor-specific names (CPF, 401k, MPF, SRS, IRA, social-security personal
accounts, specific insurers/brokers) are NEVER stable taxonomy codes. Those
details are extracted as metadata and *mapped onto* these classes. Durable
economic meaning lives in the three report-stable dimensions
(``EconomicSide``, ``ValuationRole``, ``LiquidityClass``) plus a small L1/L2
class tree — never in product names.

This module is pure contract: no database tables, no LLM prompts, no report
behavior. Storage (#1222), the legacy adapter (#1223), LLM classification
(#1224), and report consumption (#1225) all validate against it.
"""

from __future__ import annotations

from enum import Enum

# ---------------------------------------------------------------------------
# Report-stable dimensions — the durable economic meaning reports consume.
# ---------------------------------------------------------------------------


class EconomicSide(str, Enum):
    """Which side of net worth a valuation contributes to.

    ``NON_ASSET`` is the explicit exclusion class: e.g. an insurance *coverage*
    amount is a protection figure, not owned value, so it never enters net
    worth even though it is a number on a statement.
    """

    ASSET = "asset"
    LIABILITY = "liability"
    NON_ASSET = "non_asset"


class ValuationRole(str, Enum):
    """How the valuation participates in reports."""

    NET_WORTH_COMPONENT = "net_worth_component"
    COVERAGE_AMOUNT = "coverage_amount"
    INFORMATIONAL = "informational"


class LiquidityClass(str, Enum):
    """Liquidity presentation dimension (stable)."""

    LIQUID = "liquid"
    RESTRICTED = "restricted"
    ILLIQUID = "illiquid"
    LIABILITY = "liability"


# ---------------------------------------------------------------------------
# Stable L1 / L2 class tree — small and durable by design.
# ---------------------------------------------------------------------------


class ValuationL1(str, Enum):
    """Top-level stable valuation class."""

    CASH = "cash"
    MARKETABLE_INVESTMENT = "marketable_investment"
    RETIREMENT_AND_BENEFIT = "retirement_and_benefit"
    RESTRICTED_COMPENSATION = "restricted_compensation"
    REAL_ESTATE = "real_estate"
    LIABILITY = "liability"
    OTHER_ASSET = "other_asset"
    NON_ASSET = "non_asset"


class ValuationL2(str, Enum):
    """Second-level stable subdivisions. Limited and jurisdiction-agnostic."""

    # cash
    CASH_DEPOSIT = "cash_deposit"
    # marketable_investment
    PUBLIC_EQUITY = "public_equity"
    FUND = "fund"
    BOND = "bond"
    # retirement_and_benefit
    MANDATORY_RETIREMENT = "mandatory_retirement"
    VOLUNTARY_RETIREMENT = "voluntary_retirement"
    LONG_TERM_BENEFIT = "long_term_benefit"
    # restricted_compensation
    EQUITY_AWARD = "equity_award"
    # real_estate
    PROPERTY = "property"
    # liability
    SECURED_LIABILITY = "secured_liability"
    UNSECURED_LIABILITY = "unsecured_liability"
    TAX_LIABILITY = "tax_liability"
    # non_asset / fallback
    PROTECTION_COVERAGE = "protection_coverage"
    UNCLASSIFIED = "unclassified"


# ---------------------------------------------------------------------------
# L2 -> (L1 parent, default economic side). Every L2 code has exactly one row.
# ---------------------------------------------------------------------------

L2_PARENT: dict[ValuationL2, ValuationL1] = {
    ValuationL2.CASH_DEPOSIT: ValuationL1.CASH,
    ValuationL2.PUBLIC_EQUITY: ValuationL1.MARKETABLE_INVESTMENT,
    ValuationL2.FUND: ValuationL1.MARKETABLE_INVESTMENT,
    ValuationL2.BOND: ValuationL1.MARKETABLE_INVESTMENT,
    ValuationL2.MANDATORY_RETIREMENT: ValuationL1.RETIREMENT_AND_BENEFIT,
    ValuationL2.VOLUNTARY_RETIREMENT: ValuationL1.RETIREMENT_AND_BENEFIT,
    ValuationL2.LONG_TERM_BENEFIT: ValuationL1.RETIREMENT_AND_BENEFIT,
    ValuationL2.EQUITY_AWARD: ValuationL1.RESTRICTED_COMPENSATION,
    ValuationL2.PROPERTY: ValuationL1.REAL_ESTATE,
    ValuationL2.SECURED_LIABILITY: ValuationL1.LIABILITY,
    ValuationL2.UNSECURED_LIABILITY: ValuationL1.LIABILITY,
    ValuationL2.TAX_LIABILITY: ValuationL1.LIABILITY,
    ValuationL2.PROTECTION_COVERAGE: ValuationL1.NON_ASSET,
    ValuationL2.UNCLASSIFIED: ValuationL1.OTHER_ASSET,
}

L1_DEFAULT_SIDE: dict[ValuationL1, EconomicSide] = {
    ValuationL1.CASH: EconomicSide.ASSET,
    ValuationL1.MARKETABLE_INVESTMENT: EconomicSide.ASSET,
    ValuationL1.RETIREMENT_AND_BENEFIT: EconomicSide.ASSET,
    ValuationL1.RESTRICTED_COMPENSATION: EconomicSide.ASSET,
    ValuationL1.REAL_ESTATE: EconomicSide.ASSET,
    ValuationL1.LIABILITY: EconomicSide.LIABILITY,
    ValuationL1.OTHER_ASSET: EconomicSide.ASSET,
    ValuationL1.NON_ASSET: EconomicSide.NON_ASSET,
}

# Tokens that must never appear in a stable taxonomy code. Jurisdiction names,
# statutory-scheme names, and vendor/issuer names belong in extracted metadata,
# not in the durable contract.
FORBIDDEN_CODE_TOKENS: tuple[str, ...] = (
    "cpf",
    "mpf",
    "srs",
    "ira",
    "401k",
    "403b",
    "roth",
    "social_security",
    "socialsecurity",
    "provident",
    "esop",
    "rsu",
    "singapore",
    "china",
    "usa",
    "fidelity",
    "vanguard",
    "schwab",
    "prudential",
    "manulife",
    "insurer",
)


def default_side_for_l1(l1: ValuationL1) -> EconomicSide:
    """Return the report-stable economic side a given L1 class defaults to."""

    return L1_DEFAULT_SIDE[l1]


def parent_l1(l2: ValuationL2) -> ValuationL1:
    """Return the single L1 parent a given L2 code rolls up to."""

    return L2_PARENT[l2]


def all_stable_codes() -> list[str]:
    """Every stable taxonomy code string (L1 + L2) for guard checks."""

    return [c.value for c in ValuationL1] + [c.value for c in ValuationL2]
