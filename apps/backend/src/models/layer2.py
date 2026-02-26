"""Layer 2: Atomic Records - Immutable, deduplicated transaction and position records."""

from datetime import date
from decimal import Decimal
from enum import Enum

from sqlalchemy import Date, Enum as SQLEnum, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin


class TransactionDirection(str, Enum):
    """Transaction flow direction."""

    IN = "IN"
    OUT = "OUT"


class AssetType(str, Enum):
    """Type of financial asset."""

    STOCK = "stock"
    BOND = "bond"
    ETF = "etf"
    MUTUAL_FUND = "mutual_fund"
    PROPERTY = "property"
    CASH = "cash"
    OTHER = "other"


class AtomicTransaction(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """
    Layer 2: Deduplicated transaction records.

    Write-once records with hash-based deduplication. Once created, only
    source_documents can be appended (never modified). This ensures data
    integrity and simplifies debugging.

    Deduplication: SHA256(user_id|date|amount|direction|description|reference)
    Upsert Behavior:
    - If dedup_hash exists → Append to source_documents array
    - If dedup_hash new → Insert new record
    """

    __tablename__ = "atomic_transactions"
    __table_args__ = (UniqueConstraint("user_id", "dedup_hash", name="uq_atomic_transactions_user_dedup_hash"),)

    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, comment="Absolute value")
    direction: Mapped[TransactionDirection] = mapped_column(
        SQLEnum(
            TransactionDirection,
            name="transaction_direction_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, comment="ISO currency code")

    dedup_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA256(user_id|date|amount|dir|desc|ref)",
    )

    source_documents: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment='[{"doc_id": "uuid", "doc_type": "bank_statement"}]',
    )

    def __repr__(self) -> str:
        return f"<AtomicTransaction {self.txn_date} {self.direction.value} {self.amount} {self.currency}>"


class AtomicPosition(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """
    Layer 2: Deduplicated position snapshots.

    Write-once position snapshots from brokerage statements. Each snapshot
    represents holdings at a specific date for a specific asset at a broker.

    Deduplication: SHA256(user_id|snapshot_date|asset_identifier|broker)
    """

    __tablename__ = "atomic_positions"
    __table_args__ = (UniqueConstraint("user_id", "dedup_hash", name="uq_atomic_positions_user_dedup_hash"),)

    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    asset_identifier: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="Ticker (AAPL), ISIN, property address"
    )
    broker: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="Moomoo, Ping An Securities, etc.")
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, comment="Shares, units")
    market_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, comment="Fair value in asset's currency"
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, comment="Asset currency")

    # Portfolio management fields (EPIC-017)
    asset_type: Mapped[AssetType | None] = mapped_column(
        SQLEnum(
            AssetType,
            name="asset_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=True,
        comment="Asset classification",
    )
    sector: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="Sector for allocation")
    geography: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="Country/region")

    dedup_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA256(user_id|date|asset|broker)",
    )

    source_documents: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment='[{"doc_id": "uuid", "doc_type": "brokerage_statement"}]',
    )

    def __repr__(self) -> str:
        return (
            f"<AtomicPosition {self.snapshot_date} {self.asset_identifier} "
            f"{self.quantity} @ {self.market_value} {self.currency}>"
        )
