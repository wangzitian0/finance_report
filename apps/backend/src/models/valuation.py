"""Valuation snapshot models for net worth components."""

from datetime import date
from decimal import Decimal
from enum import Enum

from sqlalchemy import Boolean, Date, Enum as SQLEnum, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin


class ValuationComponentType(str, Enum):
    """Supported net worth component categories."""

    BANK_CASH = "bank_cash"
    BROKERAGE_POSITION = "brokerage_position"
    PROPERTY = "property"
    MORTGAGE = "mortgage"
    TAX_PAYABLE_OR_REFUND = "tax_payable_or_refund"
    SALARY_BONUS_RECEIVABLE = "salary_bonus_receivable"
    ESOP_RSU_OPTION = "esop_rsu_option"
    CPF_OR_LONG_TERM_SAVINGS = "cpf_or_long_term_savings"
    INSURANCE_CASH_VALUE = "insurance_cash_value"
    OTHER_ASSET = "other_asset"
    OTHER_LIABILITY = "other_liability"


class ValuationSide(str, Enum):
    """Whether a component increases or decreases net worth."""

    ASSET = "asset"
    LIABILITY = "liability"


class ValuationSource(str, Enum):
    """Source of a valuation snapshot."""

    MANUAL = "manual"
    IMPORTED = "imported"
    SYSTEM = "system"


class ValuationConfidence(str, Enum):
    """Confidence tier for a valuation snapshot."""

    TRUSTED = "trusted"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    ESTIMATED = "estimated"


class ValuationSnapshot(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """Point-in-time valuation for a net worth component.

    Snapshots are append-only from a product perspective. New values are stored
    as new rows so the net worth calculation can explain value, source, and
    freshness at any as-of date.
    """

    __tablename__ = "valuation_snapshots"

    component_type: Mapped[ValuationComponentType] = mapped_column(
        SQLEnum(
            ValuationComponentType,
            name="valuation_component_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    component_name: Mapped[str] = mapped_column(String(120), nullable=False)
    side: Mapped[ValuationSide] = mapped_column(
        SQLEnum(
            ValuationSide,
            name="valuation_side_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        index=True,
    )
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    source: Mapped[ValuationSource] = mapped_column(
        SQLEnum(
            ValuationSource,
            name="valuation_source_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=ValuationSource.MANUAL,
    )
    confidence: Mapped[ValuationConfidence] = mapped_column(
        SQLEnum(
            ValuationConfidence,
            name="valuation_confidence_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=ValuationConfidence.TRUSTED,
    )
    stale_after_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    include_in_total_net_worth: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    include_in_liquid_net_worth: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    restricted_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<ValuationSnapshot {self.component_type.value} {self.component_name} "
            f"{self.value} {self.currency} as_of={self.as_of_date}>"
        )
