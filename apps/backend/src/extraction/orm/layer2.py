"""Layer 2: Atomic Records - Immutable, deduplicated transaction and position records."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false as sa_false,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.platform.orm.base import TimestampMixin, UserOwnedMixin, UUIDMixin


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

    Deduplication: SHA256(user_id|date|amount|direction|description|reference|disambiguator)
    where disambiguator is the running ``balance_after`` when present, else ``#occurrence_index``
    (see ``DeduplicationService.calculate_transaction_hash``). ``balance_after`` is persisted so
    the Stage-1 conflict guard can tell two real-but-identical transactions apart.
    Upsert Behavior:
    - If dedup_hash exists → Append to source_documents array
    - If dedup_hash new → Insert new record
    """

    __tablename__ = "atomic_transactions"
    __table_args__ = (
        UniqueConstraint("user_id", "dedup_hash", name="uq_atomic_transactions_user_dedup_hash"),
        CheckConstraint("amount > 0", name="ck_atomic_transactions_amount_positive"),
    )

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
    currency_unresolved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=sa_false(),
        default=False,
        comment=(
            "EPIC-012 AC12.40: True when the ingest boundary could NOT determine the "
            "transaction currency (no statement/account metadata). The currency column then "
            "holds a non-authoritative placeholder and the row MUST NOT be promoted to a "
            "JournalLine until a reviewer specifies the currency. Never silent-default."
        ),
    )
    currency_resolved_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        comment="EPIC-012 AC12.40.3: user_id of the reviewer who specified the currency (audit: who).",
    )
    currency_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="EPIC-012 AC12.40.3: timestamp the currency was specified by a reviewer (audit: when).",
    )
    balance_after: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
        comment="Statement running balance after this transaction; disambiguates real-but-identical rows",
    )

    dedup_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA256(user_id|date|amount|dir|desc|ref|disambiguator); disambiguator=balance_after or #occurrence",
    )

    source_documents: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment='[{"doc_id": "uuid", "doc_type": "bank_statement"}]',
    )

    def __repr__(self) -> str:
        return f"<AtomicTransaction {self.txn_date} {self.direction.value} {self.amount} {self.currency}>"


class AtomicTransactionSourceDocument(Base, TimestampMixin):
    """Trusted normalized source-document anchor for an atomic transaction."""

    __tablename__ = "atomic_transaction_source_documents"
    __table_args__ = (Index("idx_atomic_txn_source_docs_document", "uploaded_document_id"),)

    atomic_txn_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("atomic_transactions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    uploaded_document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("uploaded_documents.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    atomic_transaction: Mapped[AtomicTransaction] = relationship("AtomicTransaction")
    uploaded_document = relationship("UploadedDocument")


class AtomicPosition(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """
    Layer 2: Deduplicated position snapshots.

    Write-once position snapshots from brokerage statements. Each snapshot
    represents holdings at a specific date for a specific asset at a broker.

    Deduplication: SHA256(user_id|snapshot_date|asset_identifier|broker)
    """

    __tablename__ = "atomic_positions"
    # No market_value sign constraint: short positions (a margin short or a sold
    # option) are signed — negative quantity AND negative market value — and are
    # first-class (#1448). ``quantity`` is likewise unconstrained.
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


class AtomicPositionSourceDocument(Base, TimestampMixin):
    """Trusted normalized source-document anchor for an atomic position snapshot."""

    __tablename__ = "atomic_position_source_documents"
    __table_args__ = (Index("idx_atomic_position_source_docs_document", "uploaded_document_id"),)

    atomic_position_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("atomic_positions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    uploaded_document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("uploaded_documents.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    atomic_position: Mapped[AtomicPosition] = relationship("AtomicPosition")
    uploaded_document = relationship("UploadedDocument")
