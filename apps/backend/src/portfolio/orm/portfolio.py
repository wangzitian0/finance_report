"""Portfolio management models — investment accounting.

Moved from ``src/models/portfolio.py`` (#1675 D5), with ``ManagedPosition``,
``PositionStatus``, and ``CostBasisMethod`` relocated from ``extraction/orm/layer3.py``
(#3123). Cross-domain references (ledger's ``accounts`` and ``journal_entries``) are
bare ForeignKey **columns** only: object-graph ``relationship()`` navigation across
domains is removed per the 2026-07-11 ruling. The ``MarketDataOverride``
price-observation store moved to ``pricing`` (its domain owner), not here.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, Enum as SQLEnum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

import src.audit as audit
from src.audit.quantity import Quantity, Unit
from src.database import Base
from src.platform.orm.base import TimestampMixin, UserOwnedMixin, UUIDMixin

# A managed position's quantity has no stored unit column; shares/units are the
# implicit unit (matches PORTFOLIO_QUANTITY_UNIT / INVESTMENT_QUANTITY_UNIT in the
# services, kept here as a literal so the model never imports a service).
POSITION_QUANTITY_UNIT = "units"


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
    """Calculated position derived from AtomicPositions.

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

    @property
    def cost_basis_money(self) -> audit.Money:
        return audit.Money(self.cost_basis, audit.Currency.of(self.currency))

    @property
    def unrealized_pnl_money(self) -> audit.Money:
        return audit.Money(self.unrealized_pnl or Decimal("0.00"), audit.Currency.of(self.currency))

    @property
    def realized_pnl_money(self) -> audit.Money:
        return audit.Money(self.realized_pnl or Decimal("0.00"), audit.Currency.of(self.currency))

    @property
    def quantity_qty(self) -> Quantity:
        return Quantity(self.quantity, Unit.of(POSITION_QUANTITY_UNIT))


class InvestmentTransactionType(str, Enum):
    """Brokerage investment transaction type."""

    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"


class InvestmentTransaction(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """Auditable brokerage transaction that drives portfolio accounting."""

    __tablename__ = "investment_transactions"
    __table_args__ = (
        CheckConstraint("gross_amount > 0", name="ck_investment_transactions_gross_amount_positive"),
        CheckConstraint("fees >= 0", name="ck_investment_transactions_fees_non_negative"),
        CheckConstraint(
            "transaction_type::text NOT IN ('buy', 'sell') OR ("
            "quantity IS NOT NULL AND quantity > 0 AND "
            "unit_price IS NOT NULL AND unit_price >= 0 AND "
            "cost_basis IS NOT NULL AND cost_basis >= 0"
            ")",
            name="ck_investment_transactions_trade_values_valid",
        ),
    )

    position_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("managed_positions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    journal_entry_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("journal_entries.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)

    transaction_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    transaction_type: Mapped[InvestmentTransactionType] = mapped_column(
        SQLEnum(
            InvestmentTransactionType,
            name="investment_transaction_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    asset_identifier: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fees: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cost_basis: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    realized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cost_basis_method: Mapped[CostBasisMethod | None] = mapped_column(
        SQLEnum(
            CostBasisMethod,
            name="cost_basis_method_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
    )

    # No relationship() to ManagedPosition (extraction-bound) or JournalEntry
    # (ledger): cross-domain references resolve by id (#1675 ruling).


class InvestmentLot(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """Open tax/accounting lot for cost-basis calculations."""

    __tablename__ = "investment_lots"
    __table_args__ = (
        CheckConstraint("original_quantity > 0", name="ck_investment_lots_original_quantity_positive"),
        CheckConstraint("remaining_quantity >= 0", name="ck_investment_lots_remaining_quantity_non_negative"),
        CheckConstraint(
            "remaining_quantity <= original_quantity",
            name="ck_investment_lots_remaining_not_above_original",
        ),
        CheckConstraint("unit_cost >= 0", name="ck_investment_lots_unit_cost_non_negative"),
        CheckConstraint(
            "disposed_date IS NULL OR disposed_date >= acquisition_date",
            name="ck_investment_lots_disposed_after_acquisition",
        ),
    )

    position_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("managed_positions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    opening_transaction_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("investment_transactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_identifier: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    original_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    remaining_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    disposed_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # No relationship() to ManagedPosition (extraction-bound): resolve by id.
    opening_transaction: Mapped[InvestmentTransaction] = relationship("InvestmentTransaction")


class DividendType(str, Enum):
    """Dividend income tax classification."""

    ORDINARY = "ordinary"
    QUALIFIED = "qualified"


class DividendIncome(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """
    Dividend income tracking for portfolio holdings.

    Links dividend payments to managed positions for portfolio performance
    and tax reporting.
    """

    __tablename__ = "dividend_income"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_dividend_income_amount_positive"),)

    position_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("managed_positions.id", ondelete="CASCADE"),
        nullable=False,
    )

    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    dividend_type: Mapped[DividendType] = mapped_column(
        SQLEnum(
            DividendType,
            name="dividend_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=DividendType.ORDINARY,
    )

    # Relationship removed - position_id FK is sufficient for queries

    def __repr__(self) -> str:
        return f"<DividendIncome {self.payment_date} {self.amount} {self.currency}>"
