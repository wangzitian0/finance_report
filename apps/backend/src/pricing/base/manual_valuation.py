"""Pricing-owned vocabulary for the legacy manual-valuation store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID


class ManualValuationComponentType(str, Enum):
    """Manual net-worth component classification owned by pricing."""

    PROPERTY_VALUE = "property_value"
    MORTGAGE_BALANCE = "mortgage_balance"
    CPF_BALANCE = "cpf_balance"
    RETIREMENT_ACCOUNT = "retirement_account"
    SOCIAL_SECURITY_PERSONAL_ACCOUNT = "social_security_personal_account"
    LONG_TERM_BENEFIT_ASSET = "long_term_benefit_asset"
    LONG_TERM_SAVINGS = "long_term_savings"
    TAX_PAYABLE = "tax_payable"
    TAX_REFUND = "tax_refund"
    INSURANCE_CASH_VALUE = "insurance_cash_value"
    ESOP = "esop"
    RSU = "rsu"
    STOCK_OPTIONS = "stock_options"
    OTHER_ASSET = "other_asset"
    OTHER_LIABILITY = "other_liability"


class ManualValuationLiquidityClass(str, Enum):
    """Presentation liquidity of a pricing-owned valuation fact."""

    LIQUID = "liquid"
    RESTRICTED = "restricted"
    ILLIQUID = "illiquid"
    LIABILITY = "liability"


class ManualValuationBasis(str, Enum):
    """Evidence basis attached to a human-entered valuation."""

    MARKET_APPRAISAL = "market_appraisal"
    BROKER_STATEMENT = "broker_statement"
    EMPLOYER_GRANT_DOCUMENT = "employer_grant_document"
    BANK_STATEMENT = "bank_statement"
    GOVERNMENT_STATEMENT = "government_statement"
    INSURER_STATEMENT = "insurer_statement"
    SELF_ESTIMATE = "self_estimate"


@dataclass(frozen=True, slots=True)
class ManualValuationFact:
    """Persistence-neutral read model consumed outside pricing."""

    id: UUID
    component_type: ManualValuationComponentType
    liquidity_class: ManualValuationLiquidityClass
    as_of_date: date
    value: Decimal
    currency: str
    source: str
    valuation_basis: ManualValuationBasis | None
    notes: str | None
    reminder_date: date | None
    created_at: datetime
