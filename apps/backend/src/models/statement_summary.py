"""DWD conform: the confirmed statement envelope.

A ``StatementSummary`` is the durable, mutable conform record that binds an
uploaded statement document (ODS ``UploadedDocument``) to its custody account
(DIM ``accounts``) and carries the confirmed statement envelope — period,
opening/closing balances, institution, and review state.

Together with ``UploadedDocument`` (the raw file) and ``AtomicTransaction`` (the
per-transaction DWD facts), this completes the decomposition of the legacy
``BankStatement`` into the layered model, so ``bank_statements`` can eventually
be deprecated (EPIC-011 Stage 3).

The Python ``BankStatementStatus`` / ``Stage1Status`` enums are reused, but with
distinct PostgreSQL type names so this table does not collide with the legacy
``bank_statements`` enum types.
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
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
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin
from src.models.statement_enums import BankStatementStatus, Stage1Status


class StatementSummary(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """Confirmed statement envelope (DWD conform) for an uploaded statement."""

    __tablename__ = "statement_summaries"
    __table_args__ = (
        UniqueConstraint("user_id", "file_hash", name="uq_statement_summaries_user_file_hash"),
        CheckConstraint(
            "period_start IS NULL OR period_end IS NULL OR period_start <= period_end",
            name="ck_statement_summaries_period_order",
        ),
        CheckConstraint(
            "status::text != 'approved' OR ("
            "account_id IS NOT NULL AND "
            "NULLIF(BTRIM(currency), '') IS NOT NULL AND "
            "period_start IS NOT NULL AND "
            "period_end IS NOT NULL AND "
            "opening_balance IS NOT NULL AND "
            "closing_balance IS NOT NULL"
            ")",
            name="ck_statement_summaries_approved_complete",
        ),
        Index("idx_statement_summaries_user_account", "user_id", "account_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Link to the ODS document (canonical join is (user_id, file_hash), mirrored
    # by UploadedDocument and the legacy BankStatement).
    uploaded_document_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("uploaded_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="SHA256, canonical document join key")

    # DIM conform: custody account the statement belongs to (set at confirm).
    account_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
        comment="Custody account (DIM conform); set at statement confirmation",
    )

    # Statement envelope (source facts).
    institution: Mapped[str] = mapped_column(String(100), nullable=False)
    account_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    manual_opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    # Review / confirmation state.
    status: Mapped[BankStatementStatus] = mapped_column(
        SQLEnum(
            BankStatementStatus,
            name="statement_summary_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        default=BankStatementStatus.UPLOADED,
        nullable=False,
    )
    stage1_status: Mapped[Stage1Status | None] = mapped_column(
        SQLEnum(
            Stage1Status,
            name="statement_summary_stage1_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
            validate_strings=True,
        ),
        nullable=True,
        default=None,
    )
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    balance_validated: Mapped[bool | None] = mapped_column(default=None, nullable=True)
    validation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    balance_validation_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
    stage1_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when a reviewer confirms the surfaced duplicate / transfer-pair candidates are
    # intentional, so Stage-1 approval no longer blocks on them (#962). NULL = unacknowledged.
    conflicts_acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extraction_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)
