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

from src.audit.money import CurrencyBalances
from src.database import Base
from src.extraction.orm.statement_enums import BankStatementStatus, Stage1Status
from src.platform.orm.base import TimestampMixin, UserOwnedMixin, UUIDMixin


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
    # #1123 AC1: per-currency opening/closing balances for multi-currency
    # statements (Wise / IBKR / Futu), shape ``[{currency, opening, closing}]``.
    # Additive to the scalar columns above, which stay populated for the
    # single-currency degenerate case and backward compatibility. Reconciliation
    # runs per currency (open + ΣIN − ΣOUT ≈ close), never summing across them.
    currency_balances: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)

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
    # #962: set when the reviewer explicitly resolves the Stage-1 duplicate /
    # transfer-pair candidates (confirming they are distinct or a real transfer).
    # The approval guard honors this so a legitimately-conflicting statement is
    # no longer permanently stuck in ``parsed``. Cleared on reject/reparse since
    # a fresh transaction set must be re-reviewed.
    stage1_conflicts_resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the reviewer resolved Stage-1 duplicate/transfer-pair candidates (#962)",
    )
    extraction_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True, default=None)

    def typed_currency_balances(self) -> CurrencyBalances:
        """Per-currency balances as a typed :class:`CurrencyBalances` (#1167 / #1171; AC-audit.22.1).

        Parses the ``currency_balances`` JSONB (``[{currency, opening, closing}]``,
        amounts persisted as strings) into the typed container, so a multi-currency
        statement is read as one balance *per currency* and is structurally
        incapable of collapsing onto a single scalar. Returns an empty container
        when ``currency_balances`` is NULL/empty (the single-currency degenerate
        case still lives in the scalar ``opening_balance``/``closing_balance``).
        """
        return CurrencyBalances.from_jsonb(self.currency_balances)
