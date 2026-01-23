"""Layer 4: Reporting - Snapshots and Cache."""

from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.layer3 import ClassificationRule


class ReportType(str, Enum):
    """Types of financial reports."""

    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW = "cash_flow"


class ReportSnapshot(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """
    Layer 4: Immutable snapshot of a financial report.

    Generated from Layer 2 (Atomic) + Layer 3 (Rules).
    Used for historical viewing and caching expensive calculations.
    """

    __tablename__ = "report_snapshots"
    __table_args__ = ()

    report_type: Mapped[ReportType] = mapped_column(
        SQLEnum(
            ReportType,
            name="report_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )

    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, comment="Report end date")
    start_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="Report start date (for ranges)"
    )

    rule_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("classification_rules.id", ondelete="CASCADE"),
        nullable=False,
    )

    report_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="Full report JSON structure"
    )

    is_latest: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Is this the most recent generation?",
    )
    ttl: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Expiration time for cache"
    )

    rule_version: Mapped["ClassificationRule"] = relationship("ClassificationRule")
