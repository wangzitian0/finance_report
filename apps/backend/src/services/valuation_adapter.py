"""Legacy manual valuation -> stable taxonomy adapter (#1223, EPIC-011 AC11.23).

Read-only compatibility bridge. It maps each legacy
``ManualValuationComponentType`` deterministically onto the stable taxonomy
contract (``src.constants.valuation_taxonomy``) and projects a
``ManualValuationSnapshot`` onto the same stable classification read-model shape
that new valuation facts (#1222) will use.

The legacy enum becomes an input *hint*; it is not retired and no PostgreSQL
enum value is removed. This module adds no persistence, no LLM, and does not
change the existing snapshot read path — reports keep their current behaviour
until #1225 switches consumption over.

The mapping is the single deterministic source for legacy classification: the
``liquidity_class`` it produces matches the legacy
``assets._DEFAULT_LIQUIDITY_CLASS`` table exactly, and the L1 class matches the
legacy reporting allocation classes, so switching reports to read stable codes
(#1225) is provably total-preserving.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.constants.valuation_taxonomy import (
    EconomicSide,
    LiquidityClass,
    ValuationL1,
    ValuationL2,
    ValuationRole,
    default_side_for_l1,
)
from src.models.layer3 import ManualValuationComponentType as Legacy, ManualValuationSnapshot

# Deterministic legacy mappings are fully trusted (no model inference involved).
_LEGACY_CONFIDENCE = Decimal("1.0")


@dataclass(frozen=True)
class StableValuationCodes:
    """The stable taxonomy codes a valuation resolves to."""

    l1: ValuationL1
    l2: ValuationL2
    economic_side: EconomicSide
    valuation_role: ValuationRole
    liquidity_class: LiquidityClass


def _codes(
    l1: ValuationL1,
    l2: ValuationL2,
    liquidity: LiquidityClass,
    *,
    role: ValuationRole = ValuationRole.NET_WORTH_COMPONENT,
) -> StableValuationCodes:
    # economic_side is always the L1 default for legacy data, keeping the
    # adapter consistent with the contract's L1 -> side derivation.
    return StableValuationCodes(l1, l2, default_side_for_l1(l1), role, liquidity)


# Total mapping: every ManualValuationComponentType has exactly one row.
_LEGACY_TO_STABLE: dict[Legacy, StableValuationCodes] = {
    Legacy.PROPERTY_VALUE: _codes(ValuationL1.REAL_ESTATE, ValuationL2.PROPERTY, LiquidityClass.ILLIQUID),
    Legacy.MORTGAGE_BALANCE: _codes(ValuationL1.LIABILITY, ValuationL2.SECURED_LIABILITY, LiquidityClass.LIABILITY),
    Legacy.CPF_BALANCE: _codes(
        ValuationL1.RETIREMENT_AND_BENEFIT,
        ValuationL2.MANDATORY_RETIREMENT,
        LiquidityClass.RESTRICTED,
    ),
    Legacy.RETIREMENT_ACCOUNT: _codes(
        ValuationL1.RETIREMENT_AND_BENEFIT,
        ValuationL2.VOLUNTARY_RETIREMENT,
        LiquidityClass.RESTRICTED,
    ),
    Legacy.SOCIAL_SECURITY_PERSONAL_ACCOUNT: _codes(
        ValuationL1.RETIREMENT_AND_BENEFIT,
        ValuationL2.MANDATORY_RETIREMENT,
        LiquidityClass.RESTRICTED,
    ),
    Legacy.LONG_TERM_BENEFIT_ASSET: _codes(
        ValuationL1.RETIREMENT_AND_BENEFIT,
        ValuationL2.LONG_TERM_BENEFIT,
        LiquidityClass.RESTRICTED,
    ),
    Legacy.LONG_TERM_SAVINGS: _codes(
        ValuationL1.RETIREMENT_AND_BENEFIT,
        ValuationL2.LONG_TERM_BENEFIT,
        LiquidityClass.RESTRICTED,
    ),
    Legacy.TAX_PAYABLE: _codes(ValuationL1.LIABILITY, ValuationL2.TAX_LIABILITY, LiquidityClass.LIABILITY),
    Legacy.TAX_REFUND: _codes(ValuationL1.CASH, ValuationL2.CASH_DEPOSIT, LiquidityClass.LIQUID),
    # Insurance is represented only by its attributable cash/surrender value,
    # which is an asset (never a coverage amount). Coverage figures are handled
    # by #1224 as non_asset/coverage_amount.
    Legacy.INSURANCE_CASH_VALUE: _codes(
        ValuationL1.RETIREMENT_AND_BENEFIT,
        ValuationL2.LONG_TERM_BENEFIT,
        LiquidityClass.RESTRICTED,
    ),
    Legacy.ESOP: _codes(
        ValuationL1.RESTRICTED_COMPENSATION,
        ValuationL2.EQUITY_AWARD,
        LiquidityClass.RESTRICTED,
    ),
    Legacy.RSU: _codes(
        ValuationL1.RESTRICTED_COMPENSATION,
        ValuationL2.EQUITY_AWARD,
        LiquidityClass.RESTRICTED,
    ),
    Legacy.STOCK_OPTIONS: _codes(
        ValuationL1.RESTRICTED_COMPENSATION,
        ValuationL2.EQUITY_AWARD,
        LiquidityClass.RESTRICTED,
    ),
    Legacy.OTHER_ASSET: _codes(ValuationL1.OTHER_ASSET, ValuationL2.UNCLASSIFIED, LiquidityClass.LIQUID),
    Legacy.OTHER_LIABILITY: _codes(ValuationL1.LIABILITY, ValuationL2.UNSECURED_LIABILITY, LiquidityClass.LIABILITY),
}


@dataclass(frozen=True)
class StableValuationView:
    """A legacy snapshot projected onto the stable classification read-model.

    The same shape future code will build from new ``ValuationClassification``
    rows, so report logic (#1225) can consume one read-model regardless of the
    source. ``component_type`` is the legacy input hint and is ``None`` for
    natively-classified facts.
    """

    codes: StableValuationCodes
    as_of_date: date
    value: Decimal
    currency: str
    source: str
    valuation_basis: str | None
    confidence: Decimal
    component_type: str | None
    rationale: str


def classify_legacy_component(component_type: Legacy) -> StableValuationCodes:
    """Map a legacy component type to its stable taxonomy codes (total)."""

    return _LEGACY_TO_STABLE[component_type]


def adapt_snapshot(snapshot: ManualValuationSnapshot) -> StableValuationView:
    """Project a legacy manual valuation snapshot onto the stable read-model.

    Preserves the snapshot's source, as-of date, currency, value, and valuation
    basis so traceability survives the bridge.
    """

    codes = classify_legacy_component(snapshot.component_type)
    return StableValuationView(
        codes=codes,
        as_of_date=snapshot.as_of_date,
        value=snapshot.value,
        currency=snapshot.currency,
        source=snapshot.source,
        valuation_basis=(snapshot.valuation_basis.value if snapshot.valuation_basis else None),
        confidence=_LEGACY_CONFIDENCE,
        component_type=snapshot.component_type.value,
        rationale=f"Deterministic legacy mapping from {snapshot.component_type.value}.",
    )
