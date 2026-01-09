"""Statement and AccountEvent models for document extraction."""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    pass


class StatementStatus(str, Enum):
    """Statement processing status."""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    APPROVED = "approved"
    REJECTED = "rejected"


class ConfidenceLevel(str, Enum):
    """Confidence level for parsed data."""

    HIGH = "high"  # ≥85: Auto-accept
    MEDIUM = "medium"  # 60-84: Review queue
    LOW = "low"  # <60: Manual entry required


class Statement(Base):
    """Uploaded financial statement."""

    __tablename__ = "statements"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    # user_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("users.id"))

    # File metadata
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=True)  # SHA256 for dedup
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)

    # Statement details
    institution: Mapped[str] = mapped_column(String(100), nullable=False)
    account_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="SGD")
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    # Processing
    status: Mapped[StatementStatus] = mapped_column(
        SQLEnum(StatementStatus),
        default=StatementStatus.UPLOADED,
    )
    confidence_score: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    balance_validated: Mapped[bool] = mapped_column(default=False)
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Audit
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    events: Mapped[list["AccountEvent"]] = relationship(
        "AccountEvent",
        back_populates="statement",
        cascade="all, delete-orphan",
    )


class AccountEvent(Base):
    """Individual transaction extracted from a statement."""

    __tablename__ = "account_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    statement_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("statements.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Transaction details
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)  # IN, OUT
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Confidence tracking
    confidence: Mapped[ConfidenceLevel] = mapped_column(
        SQLEnum(ConfidenceLevel),
        default=ConfidenceLevel.HIGH,
    )
    confidence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # Original OCR

    # Audit
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    # Relationships
    statement: Mapped["Statement"] = relationship(
        "Statement",
        back_populates="events",
    )
