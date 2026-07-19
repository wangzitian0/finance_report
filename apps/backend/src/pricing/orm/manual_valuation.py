"""Schema-preserving persistence adapter for pricing manual valuations."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, Enum as SQLEnum, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.platform.orm.base import TimestampMixin, UserOwnedMixin, UUIDMixin
from src.pricing.base.manual_valuation import (
    ManualValuationBasis,
    ManualValuationComponentType,
    ManualValuationLiquidityClass,
)


class ManualValuationSnapshot(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """Append-only pricing fact stored in the unchanged legacy table."""

    __tablename__ = "manual_valuation_snapshots"
    __table_args__ = (
        CheckConstraint("value > 0", name="ck_manual_valuation_snapshots_value_positive"),
        CheckConstraint(
            "recurrence_days IS NULL OR recurrence_days > 0",
            name="ck_manual_valuation_snapshots_recurrence_days_positive",
        ),
        Index(
            "uq_manual_valuation_user_component_source_date",
            "user_id",
            "component_type",
            "source",
            "as_of_date",
            unique=True,
            postgresql_where=text("superseded_by_id IS NULL"),
        ),
        Index("ix_manual_valuation_snapshots_user_as_of", "user_id", "as_of_date"),
    )

    component_type: Mapped[ManualValuationComponentType] = mapped_column(
        SQLEnum(
            ManualValuationComponentType,
            name="manual_valuation_component_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    liquidity_class: Mapped[ManualValuationLiquidityClass] = mapped_column(
        SQLEnum(
            ManualValuationLiquidityClass,
            name="manual_valuation_liquidity_class_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    valuation_basis: Mapped[ManualValuationBasis | None] = mapped_column(
        SQLEnum(
            ManualValuationBasis, name="manual_valuation_basis_enum", values_callable=lambda obj: [e.value for e in obj]
        ),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recurrence_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reminder_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("manual_valuation_snapshots.id", ondelete="SET NULL"), nullable=True
    )
