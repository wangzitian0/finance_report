"""Reconciliation match models."""

from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    from src.models.statement import BankStatementTransaction


class ReconciliationStatus(str, Enum):
    """Match status for reconciliation results."""

    AUTO_ACCEPTED = "auto_accepted"
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ReconciliationMatch(Base):
    """Match record between bank transaction and journal entries."""

    __tablename__ = "reconciliation_matches"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    bank_txn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("bank_statement_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )
    journal_entry_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    match_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Scores are non-monetary; floats are acceptable for display/analysis.
    score_breakdown: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    status: Mapped[ReconciliationStatus] = mapped_column(
        SQLEnum(ReconciliationStatus),
        default=ReconciliationStatus.PENDING_REVIEW,
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("reconciliation_matches.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    transaction: Mapped["BankStatementTransaction"] = relationship(
        "BankStatementTransaction",
        back_populates="matches",
    )
