"""Layer 3: Business Logic - Classification rules and results."""

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
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

from src.audit.money import Currency, Money
from src.audit.quantity import Quantity, Unit
from src.database import Base
from src.platform.orm.base import TimestampMixin, UserOwnedMixin, UUIDMixin

# A managed position's quantity has no stored unit column; shares/units are the
# implicit unit (matches PORTFOLIO_QUANTITY_UNIT / INVESTMENT_QUANTITY_UNIT in the
# services, kept here as a literal so the model never imports a service).
POSITION_QUANTITY_UNIT = "units"

if TYPE_CHECKING:
    from src.extraction.orm.layer2 import AtomicTransaction


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

    # Intra-family navigation stays; the ledger Account is id-only (#1675 D4).
    atomic_transaction: Mapped["AtomicTransaction"] = relationship("AtomicTransaction")
    rule_version: Mapped["ClassificationRule"] = relationship("ClassificationRule")


class PositionStatus(str, Enum):
    """Status of a managed position."""

    ACTIVE = "active"
    DISPOSED = "disposed"


class CostBasisMethod(str, Enum):
    """Cost basis calculation method for realized P&L."""

    FIFO = "FIFO"  # First In First Out
    LIFO = "LIFO"  # Last In First Out
    AVGCOST = "AvgCost"  # Average Cost


class ManagedPosition(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """
    Layer 3: Calculated position derived from AtomicPositions.

    Tracks the lifecycle of an asset (cost basis, acquisition date).
    Aggregates multiple atomic snapshots into a coherent asset view.
    """

    __tablename__ = "managed_positions"
    # No cost_basis sign constraint: a short position (margin short or sold option)
    # carries negative quantity AND negative cost_basis/market value, reducing
    # portfolio value rather than being rejected (#1448).
    __table_args__ = (
        UniqueConstraint("user_id", "account_id", "asset_identifier", name="uq_managed_positions_user_account_asset"),
        CheckConstraint(
            "disposal_date IS NULL OR disposal_date >= acquisition_date",
            name="ck_managed_positions_disposal_after_acquisition",
        ),
    )

    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="CASCADE"),
        nullable=False,
    )

    asset_identifier: Mapped[str] = mapped_column(String(100), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    cost_basis: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, comment="Total cost basis")

    # Portfolio management fields (EPIC-017)
    cost_basis_method: Mapped[CostBasisMethod | None] = mapped_column(
        SQLEnum(
            CostBasisMethod,
            name="cost_basis_method_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
        default=CostBasisMethod.FIFO,
        comment="Method for calculating realized P&L",
    )
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
        comment="Unrealized gain/loss (market_value - cost_basis)",
    )
    realized_pnl: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
        comment="Realized gain/loss from disposals",
    )

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

    # No relationship() to ledger's Account (#1675 D4): consumers resolve
    # account_id via an explicit query (see portfolio/extension/holdings.py).

    # ── typed read accessors (the ORM→business boundary, #3) ────────────────
    # Business code reads these and stays in value types; the raw Decimal columns
    # remain the storage/write boundary. Nullable PnL columns coalesce to zero
    # (matching the existing ``or Decimal("0.00")`` call-site convention).
    @property
    def cost_basis_money(self) -> Money:
        return Money(self.cost_basis, Currency.of(self.currency))

    @property
    def unrealized_pnl_money(self) -> Money:
        return Money(self.unrealized_pnl or Decimal("0.00"), Currency.of(self.currency))

    @property
    def realized_pnl_money(self) -> Money:
        return Money(self.realized_pnl or Decimal("0.00"), Currency.of(self.currency))

    @property
    def quantity_qty(self) -> Quantity:
        return Quantity(self.quantity, Unit.of(POSITION_QUANTITY_UNIT))
