"""Reconciliation match models.

Moved from ``src/models/reconciliation.py`` (#1675 D5). Both ``AtomicTransaction``
(extraction) and ``journal_entries`` (ledger) are referenced by bare ForeignKey
**column** only, never ``relationship()`` — cross-domain object-graph
navigation is the coupling; the FK column is DB-level integrity (2026-07-11
ruling). Consumers resolve ``atomic_txn_id`` via an explicit query (#1675 D4,
now that ``AtomicTransaction`` has moved into ``extraction/orm/layer2.py``).
"""

from enum import Enum
from uuid import UUID

from sqlalchemy import Enum as SQLEnum, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.platform.orm.base import TimestampMixin, UUIDMixin


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

    atomic_txn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("atomic_transactions.id", ondelete="CASCADE"),
        nullable=False,
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
    # No relationship() to extraction's AtomicTransaction: resolve
    # atomic_txn_id by an explicit query (#1675 D4 ruling).


class ReconciliationMatchJournalEntry(Base, TimestampMixin):
    """Trusted normalized journal-entry anchor for a reconciliation match."""

    __tablename__ = "reconciliation_match_journal_entries"
    __table_args__ = (Index("idx_reconciliation_match_journal_entries_entry", "journal_entry_id"),)

    match_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("reconciliation_matches.id", ondelete="CASCADE"),
        primary_key=True,
    )
    journal_entry_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="RESTRICT"),
        primary_key=True,
    )

    reconciliation_match: Mapped[ReconciliationMatch] = relationship("ReconciliationMatch")
    # No relationship() to ledger's JournalEntry: resolve by id (#1675 ruling).
