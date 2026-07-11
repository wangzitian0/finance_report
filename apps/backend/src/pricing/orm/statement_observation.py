"""``StatementPriceObservation`` — pricing's store for ingested statement prices (#1642).

The event-fed, id-referenced copy of a statement-extracted unit price
(boundary ruling 4, #1610): the authoritative document-fact stays in
``extraction``; pricing keeps its own denormalized row so ``resolve()`` can
treat statement prices as first-class candidates without ever joining into
extraction's write model. The table follows the wide-table projection
contract (``common/meta/migration-standard.md``):

- **event-fed** — only the ``PriceObserved`` ingest subscriber
  (``extension/ingest.py``) writes it; rebuildable by replaying events.
- **idempotent** — ``source_observation_id`` (the extraction fact id, the
  event's natural dedup key) is UNIQUE, so at-least-once redelivery cannot
  duplicate a row.
- **zero FK** — ``user_id``/``source_observation_id`` are plain ids carried
  as provenance (Decision B, #1416): no shared transaction, no FK into
  another domain's tables.
- **bitemporal** — ``as_of`` (which day the price belongs to) vs
  ``observed_at`` (when extraction learned it); a late backfill is a new row,
  never a rewrite (Axiom A: append-only, no updates or deletes).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import DECIMAL, CheckConstraint, Date, DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base


class StatementPriceObservation(Base):
    """One ingested copy of a statement-extracted unit price (append-only)."""

    __tablename__ = "statement_price_observations"
    __table_args__ = (
        UniqueConstraint(
            "source_observation_id",
            name="uq_statement_price_observations_source_id",
        ),
        CheckConstraint("value > 0", name="ck_statement_price_observations_value_positive"),
        Index("idx_statement_price_observations_lookup", "subject_kind", "subject_key", "as_of"),
    )

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    #: The owning user (statement facts are inherently user-owned). A plain id,
    #: deliberately not a FK (zero-FK projection contract).
    user_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    subject_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[Decimal] = mapped_column(DECIMAL(18, 6), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    #: When extraction learned the fact (the event's ``occurred_at``).
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Provenance + dedup key: the extraction-side fact id the event announced.
    source_observation_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    #: When pricing ingested the copy (relay dispatch time, not fact time).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    def __repr__(self) -> str:
        return (
            f"<StatementPriceObservation {self.subject_kind}:{self.subject_key} "
            f"{self.value} {self.currency} {self.as_of}>"
        )
