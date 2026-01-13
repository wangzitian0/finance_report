"""Journal entry models for double-entry bookkeeping."""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import (
    DECIMAL,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.database import Base

if TYPE_CHECKING:
    from src.models.account import Account


class JournalEntryStatus(str, enum.Enum):
    """Status of a journal entry."""

    DRAFT = "draft"
    POSTED = "posted"
    RECONCILED = "reconciled"
    VOID = "void"


class JournalEntrySourceType(str, enum.Enum):
    """Source type of a journal entry."""

    MANUAL = "manual"
    BANK_STATEMENT = "bank_statement"
    SYSTEM = "system"


class Direction(str, enum.Enum):
    """Debit or credit direction."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class JournalEntry(Base):
    """
    Journal entry header containing metadata for a bookkeeping transaction.

    Each entry must have at least 2 journal lines with balanced debits and credits.
    """

    __tablename__ = "journal_entries"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    memo: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[JournalEntrySourceType] = mapped_column(
        Enum(JournalEntrySourceType), nullable=False, default=JournalEntrySourceType.MANUAL
    )
    source_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[JournalEntryStatus] = mapped_column(
        Enum(JournalEntryStatus), nullable=False, default=JournalEntryStatus.DRAFT, index=True
    )
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    void_reversal_entry_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    lines: Mapped[list[JournalLine]] = relationship(
        "JournalLine", back_populates="journal_entry", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<JournalEntry {self.entry_date} - {self.memo[:30]}>"


class JournalLine(Base):
    """
    Individual debit or credit line in a journal entry.

    Amount must always be positive. Direction (DEBIT/CREDIT) determines
    the effect on the account based on account type.
    """

    __tablename__ = "journal_lines"
    __table_args__ = (CheckConstraint("amount > 0", name="positive_amount"),)

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    journal_entry_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id"), nullable=False, index=True
    )
    account_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    direction: Mapped[Direction] = mapped_column(Enum(Direction), nullable=False)
    amount: Mapped[Decimal] = mapped_column(DECIMAL(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="SGD")
    fx_rate: Mapped[Decimal | None] = mapped_column(DECIMAL(18, 6), nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    journal_entry: Mapped[JournalEntry] = relationship("JournalEntry", back_populates="lines")
    account: Mapped[Account] = relationship("Account", back_populates="journal_lines")

    def __repr__(self) -> str:
        return f"<JournalLine {self.direction.value} {self.amount} {self.currency}>"
