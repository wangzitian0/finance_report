"""Atomic valuation facts and their stable classifications (#1222, EPIC-011 AC11.22).

Storage-only slice of the valuation taxonomy program. ``AtomicValuationFact``
holds a raw, point-in-time extracted valuation (the durable fact), and
``ValuationClassification`` holds a versionable stable classification that
references a fact and is bound to the stable taxonomy contract in
``src.constants.valuation_taxonomy``. No LLM, no legacy bridge, and no report or
UI change lives here — those are owned by #1223/#1224/#1225/#1226.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum as SQLEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.constants.valuation_taxonomy import (
    EconomicSide,
    LiquidityClass,
    ValuationL1,
    ValuationL2,
    ValuationRole,
)
from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin


def _enum_values(obj: type[Enum]) -> list[str]:
    """Persist enum *values* (not names) so DB labels match the contract."""

    return [e.value for e in obj]


class ValuationReviewStatus(str, Enum):
    """Review-gate state for a stable valuation classification.

    Storage-level state only; the gating *behaviour* (when low-confidence
    classifications must enter review before trusted report use) is owned by
    later issues (#1224 LLM contract, #1226 frontend).
    """

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AtomicValuationFact(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """Raw, point-in-time extracted valuation fact (pre-classification).

    Jurisdiction, issuer, and scheme/plan names are captured here as raw
    metadata; they are never promoted into the stable taxonomy contract.
    """

    __tablename__ = "atomic_valuation_facts"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_atomic_valuation_facts_amount_non_negative"),
        # Composite-FK target: lets ValuationClassification enforce same-owner
        # references at the DB level (mirrors EvidenceNode/EvidenceEdge).
        UniqueConstraint("user_id", "id", name="uq_atomic_valuation_facts_user_id_id"),
        # Idempotent ingestion: a fact's dedup hash is unique per owner.
        Index(
            "uq_atomic_valuation_facts_user_dedup_hash",
            "user_id",
            "dedup_hash",
            unique=True,
        ),
        Index("ix_atomic_valuation_facts_user_as_of", "user_id", "as_of_date"),
    )

    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    raw_label: Mapped[str] = mapped_column(Text, nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scheme_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_document_anchor: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evidence_spans: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dedup_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ValuationClassification(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """Versionable stable classification of an ``AtomicValuationFact``.

    The taxonomy columns are bound to the contract enums, so codes outside the
    stable contract are rejected at persistence. Reclassification appends a new
    version and supersedes the prior head, so prior model output is never
    destroyed.
    """

    __tablename__ = "valuation_classifications"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_valuation_classifications_confidence_unit_interval",
        ),
        CheckConstraint("version >= 1", name="ck_valuation_classifications_version_positive"),
        # Same-owner reference: a classification can only point at a fact owned by
        # the same user (composite FK mirrors EvidenceEdge). DB ON DELETE CASCADE
        # removes classifications when their fact is deleted.
        ForeignKeyConstraint(
            ["user_id", "valuation_fact_id"],
            ["atomic_valuation_facts.user_id", "atomic_valuation_facts.id"],
            name="fk_valuation_classifications_user_fact",
            ondelete="CASCADE",
        ),
        # Append-only head: at most one current (non-superseded) classification
        # per fact; superseded history rows accumulate freely.
        Index(
            "uq_valuation_classifications_current_per_fact",
            "valuation_fact_id",
            unique=True,
            postgresql_where=text("superseded_by_id IS NULL"),
        ),
    )

    valuation_fact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    l1: Mapped[ValuationL1] = mapped_column(
        SQLEnum(ValuationL1, name="valuation_l1_enum", values_callable=_enum_values),
        nullable=False,
    )
    l2: Mapped[ValuationL2 | None] = mapped_column(
        SQLEnum(ValuationL2, name="valuation_l2_enum", values_callable=_enum_values),
        nullable=True,
    )
    economic_side: Mapped[EconomicSide] = mapped_column(
        SQLEnum(EconomicSide, name="valuation_economic_side_enum", values_callable=_enum_values),
        nullable=False,
    )
    valuation_role: Mapped[ValuationRole] = mapped_column(
        SQLEnum(ValuationRole, name="valuation_role_enum", values_callable=_enum_values),
        nullable=False,
    )
    liquidity_class: Mapped[LiquidityClass] = mapped_column(
        SQLEnum(LiquidityClass, name="valuation_liquidity_class_enum", values_callable=_enum_values),
        nullable=False,
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    review_status: Mapped[ValuationReviewStatus] = mapped_column(
        SQLEnum(ValuationReviewStatus, name="valuation_review_status_enum", values_callable=_enum_values),
        nullable=False,
        default=ValuationReviewStatus.PENDING,
        server_default=ValuationReviewStatus.PENDING.value,
    )
    model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("valuation_classifications.id", ondelete="SET NULL"),
        nullable=True,
    )
