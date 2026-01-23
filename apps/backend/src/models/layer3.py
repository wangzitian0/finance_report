"""Layer 3: Business Logic - Classification rules and results."""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    Enum as SQLEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.account import Account
    from src.models.layer2 import AtomicTransaction
    from src.models.user import User


class RuleType(str, Enum):
    """Type of classification rule."""

    KEYWORD_MATCH = "keyword_match"
    REGEX_MATCH = "regex_match"
    ML_MODEL = "ml_model"


class ClassificationStatus(str, Enum):
    """Status of transaction classification."""

    DRAFT = "draft"
    APPLIED = "applied"
    SUPERSEDED = "superseded"


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

    created_by: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    default_account: Mapped["Account"] = relationship("Account")
    author: Mapped["User"] = relationship("User", foreign_keys=[created_by])


class TransactionClassification(Base, UUIDMixin, TimestampMixin):
    """
    Layer 3: The result of applying classification rules to atomic transactions.

    Links an AtomicTransaction to an Account (and tags) via a specific Rule Version.
    """

    __tablename__ = "transaction_classification"
    __table_args__ = (UniqueConstraint("atomic_txn_id", "rule_version_id", name="uq_txn_classification_version"),)

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

    atomic_transaction: Mapped["AtomicTransaction"] = relationship("AtomicTransaction")
    rule_version: Mapped["ClassificationRule"] = relationship("ClassificationRule")
    account: Mapped["Account"] = relationship("Account")


class PositionStatus(str, Enum):
    """Status of a managed position."""

    ACTIVE = "active"
    DISPOSED = "disposed"


class ManagedPosition(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """
    Layer 3: Calculated position derived from AtomicPositions.

    Tracks the lifecycle of an asset (cost basis, acquisition date).
    Aggregates multiple atomic snapshots into a coherent asset view.
    """

    __tablename__ = "managed_positions"

    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )

    asset_identifier: Mapped[str] = mapped_column(String(100), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, comment="Total cost basis")

    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    disposal_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    status: Mapped[PositionStatus] = mapped_column(
        SQLEnum(
            PositionStatus,
            name="position_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=PositionStatus.ACTIVE,
    )

    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    position_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    account: Mapped["Account"] = relationship("Account")
