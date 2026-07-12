"""Portfolio management models — investment accounting.

Moved from ``src/models/portfolio.py`` (#1675 D5). Cross-domain references
(``managed_positions`` — extraction-bound layer3 — and ledger's
``journal_entries``) are bare ForeignKey **columns** only: the former
``position`` / ``journal_entry`` ``relationship()`` navigations were unused
and are removed per the 2026-07-11 ruling (object-graph navigation across
domains is the coupling; the FK column is DB-level integrity). The
``MarketDataOverride`` price-observation store moved to ``pricing`` (its
domain owner), not here.
"""

from datetime import date
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, Enum as SQLEnum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.extraction.orm.layer3 import CostBasisMethod
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin



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
