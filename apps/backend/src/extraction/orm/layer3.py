"""Layer 3: Business Logic - Classification rules and results."""

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.extraction.base.source_vocabulary import ClassificationStatus, RuleType
from src.platform.orm.base import TimestampMixin, UserOwnedMixin, UUIDMixin

if TYPE_CHECKING:
    from src.extraction.orm.layer2 import AtomicTransaction


class ClassificationRule(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """
    Layer 3: Versioned business logic for classifying transactions.

    Rules map transactions to accounts/tags based on criteria.
    Rules are versioned to allow historical replay and audit trails.
    """

    __tablename__ = "classification_rules"
    __table_args__ = (
        UniqueConstraint("user_id", "rule_name", "version_number", name="uq_classification_rules_version"),
    )

    version_number: Mapped[int] = mapped_column(Integer, nullable=False, comment="Monotonic version")
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, comment="Rule applies from date")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rule_name: Mapped[str] = mapped_column(String(100), nullable=False)

    rule_type: Mapped[RuleType] = mapped_column(
        SQLEnum(
            RuleType,
            name="rule_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )

    rule_config: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="Matching criteria")
    tag_mappings: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="Tags to apply")

    default_account_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Cross-domain references are bare FK id columns only (#1675 D4): ledger's
    # Account (default_account_id above) and identity's User (created_by) are
    # resolved via explicit queries, never relationship() navigation.
    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )


class TransactionClassification(Base, UUIDMixin, TimestampMixin):
    """
    Layer 3: The result of applying classification rules to atomic transactions.

    Links an AtomicTransaction to an Account (and tags) via a specific Rule Version.
    """

    __tablename__ = "transaction_classification"
    # One live answer for each row and rule version. A superseded answer stays as history (#2994, re-ask).
    __table_args__ = (
        Index(
            "uq_txn_classification_version",
            "atomic_txn_id",
            "rule_version_id",
            unique=True,
            postgresql_where=text("status IN ('draft', 'applied')"),
        ),
        # The partial index cannot serve a query with a bound status: this one keeps the lookups by row indexed.
        Index("ix_txn_classification_txn_rule", "atomic_txn_id", "rule_version_id"),
    )

    atomic_txn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("atomic_transactions.id", ondelete="CASCADE"),
        nullable=False,
    )

    rule_version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("classification_rules.id", ondelete="CASCADE"),
        nullable=False,
    )

    account_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )

    tags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[ClassificationStatus] = mapped_column(
        SQLEnum(
            ClassificationStatus,
            name="classification_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=ClassificationStatus.APPLIED,
    )

    superseded_by_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("transaction_classification.id"),
        nullable=True,
    )

    # Intra-family navigation stays; the ledger Account is id-only (#1675 D4).
    atomic_transaction: Mapped["AtomicTransaction"] = relationship("AtomicTransaction")
    rule_version: Mapped["ClassificationRule"] = relationship("ClassificationRule")
