"""Bank statement models for document extraction."""

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base

if TYPE_CHECKING:
    from src.models.reconciliation import ReconciliationMatch


class BankStatementStatus(str, Enum):
    """Statement processing status."""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    APPROVED = "approved"
    REJECTED = "rejected"


class BankStatementTransactionStatus(str, Enum):
    """Transaction reconciliation status."""

    PENDING = "pending"
    MATCHED = "matched"
    UNMATCHED = "unmatched"


class ConfidenceLevel(str, Enum):
    """Confidence level for parsed data."""

    HIGH = "high"  # >=85: Auto-accept
    MEDIUM = "medium"  # 60-84: Review queue
    LOW = "low"  # <60: Manual entry required


class BankStatement(Base):
    """Uploaded financial statement."""

    __tablename__ = "bank_statements"
    __table_args__ = (
        UniqueConstraint("user_id", "file_hash", name="uq_bank_statements_user_file_hash"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    account_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id"), nullable=True
    )

    # File metadata
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
    status: Mapped[BankStatementStatus] = mapped_column(
        SQLEnum(BankStatementStatus, name="bank_statement_status_enum"),
        default=BankStatementStatus.UPLOADED,
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
    transactions: Mapped[list["BankStatementTransaction"]] = relationship(
        "BankStatementTransaction",
        back_populates="statement",
        cascade="all, delete-orphan",
    )


class BankStatementTransaction(Base):
    """Individual transaction extracted from a statement."""

    __tablename__ = "bank_statement_transactions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    statement_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("bank_statements.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Transaction details
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)  # IN, OUT
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[BankStatementTransactionStatus] = mapped_column(
        SQLEnum(BankStatementTransactionStatus, name="bank_statement_transaction_status_enum"),
        default=BankStatementTransactionStatus.PENDING,
    )

    # Confidence tracking
    confidence: Mapped[ConfidenceLevel] = mapped_column(
        SQLEnum(ConfidenceLevel, name="confidence_level_enum"),
        default=ConfidenceLevel.HIGH,
    )
    confidence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # Original OCR

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
    statement: Mapped["BankStatement"] = relationship(
        "BankStatement",
        back_populates="transactions",
    )
    matches: Mapped[list["ReconciliationMatch"]] = relationship(
        "ReconciliationMatch",
        back_populates="transaction",
        cascade="all, delete-orphan",
    )
