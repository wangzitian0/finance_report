"""Reconciliation match models."""

from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum as SQLEnum, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.layer2 import AtomicTransaction


class ReconciliationStatus(str, Enum):
    """Match status for reconciliation results."""

    AUTO_ACCEPTED = "auto_accepted"
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ReconciliationMatch(Base, UUIDMixin, TimestampMixin):
    """Match record between bank transaction and journal entries."""

    __tablename__ = "reconciliation_matches"
    __table_args__ = (Index("idx_reconciliation_matches_run_id", "run_id"),)

    atomic_txn_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("atomic_transactions.id", ondelete="CASCADE"),
        nullable=True,
    )
    journal_entry_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    match_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    score_breakdown: Mapped[dict[str, float]] = mapped_column(JSONB, default=dict)
    status: Mapped[ReconciliationStatus] = mapped_column(
        SQLEnum(
            ReconciliationStatus,
            name="reconciliation_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=ReconciliationStatus.PENDING_REVIEW,
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("reconciliation_matches.id"),
        nullable=True,
    )

    atomic_transaction: Mapped["AtomicTransaction"] = relationship(
        "AtomicTransaction",
        foreign_keys=[atomic_txn_id],
    )
