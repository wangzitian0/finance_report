"""Journal entry models for double-entry bookkeeping."""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DECIMAL, CheckConstraint, Date, DateTime, Enum, ForeignKey, String, Text, event
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin

if TYPE_CHECKING:
    from src.models.account import Account


class JournalEntryStatus(str, enum.Enum):
    """Status of a journal entry."""

    DRAFT = "draft"
    POSTED = "posted"
    RECONCILED = "reconciled"
    VOID = "void"


class JournalEntrySourceType(str, enum.Enum):
    """Source type of a journal entry."""

    MANUAL = "manual"
    USER_CONFIRMED = "user_confirmed"
    AUTO_MATCHED = "auto_matched"
    AUTO_PARSED = "auto_parsed"
    # NOTE: the legacy ``bank_statement`` value was retired in migration 0040
    # (#896). Data was migrated to ``auto_parsed`` in 0018 and no write path
    # emits it. The raw string is still tolerated defensively by
    # ``normalize_source_type`` and the immutability trigger's text guards.
    SYSTEM = "system"
    FX_REVALUATION = "fx_revaluation"


class Direction(str, enum.Enum):
    """Debit or credit direction."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class JournalEntry(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """
    Journal entry header containing metadata for a bookkeeping transaction.

    Each entry must have at least 2 journal lines with balanced debits and credits.
    """

    __tablename__ = "journal_entries"

    entry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    memo: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[JournalEntrySourceType] = mapped_column(
        Enum(
            JournalEntrySourceType,
            name="journal_source_type_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=JournalEntrySourceType.MANUAL,
    )
    source_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[JournalEntryStatus] = mapped_column(
        Enum(
            JournalEntryStatus,
            name="journal_entry_status_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=JournalEntryStatus.DRAFT,
        index=True,
    )
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    void_reversal_entry_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "journal_entries.id",
            name="fk_journal_entries_void_reversal_entry_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    lines: Mapped[list[JournalLine]] = relationship(
        "JournalLine", back_populates="journal_entry", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<JournalEntry {self.entry_date} - {self.memo[:30]}>"

    @property
    def confidence_tier(self) -> str:
        """Derived UI confidence tier based on source type."""
        from src.services.confidence_tier import derive_confidence_tier

        return derive_confidence_tier(self.source_type)


class JournalLine(Base, UUIDMixin, TimestampMixin):
    """
    Individual debit or credit line in a journal entry.

    Amount must always be positive. Direction (DEBIT/CREDIT) determines
    the effect on the account based on account type.
    """

    __tablename__ = "journal_lines"
    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_amount"),
        CheckConstraint("fx_rate IS NULL OR fx_rate > 0", name="ck_journal_lines_fx_rate_positive"),
    )

    journal_entry_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accounts.id"), nullable=False, index=True
    )
    direction: Mapped[Direction] = mapped_column(
        Enum(
            Direction,
            name="journal_line_direction_enum",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(DECIMAL(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="SGD")
    fx_rate: Mapped[Decimal | None] = mapped_column(DECIMAL(18, 6), nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    journal_entry: Mapped[JournalEntry] = relationship("JournalEntry", back_populates="lines")
    account: Mapped[Account] = relationship("Account", back_populates="journal_lines")

    def __repr__(self) -> str:
        return f"<JournalLine {self.direction.value} {self.amount} {self.currency}>"


class JournalAuditLog(Base, UUIDMixin):
    """Audit trail entry for journal transaction changes."""

    __tablename__ = "journal_audit_log"

    entry_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    old_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


_LEDGER_INVARIANT_SQL = """
CREATE OR REPLACE FUNCTION fr_ledger_base_currency()
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE(NULLIF(current_setting('finance_report.base_currency', true), ''), 'SGD')
$$;

CREATE OR REPLACE FUNCTION fr_validate_journal_entry_invariants(p_entry_id uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_status text;
    v_base_currency text := upper(fr_ledger_base_currency());
    v_line_count integer;
    v_bad_fx_count integer;
    v_total_debit numeric;
    v_total_credit numeric;
BEGIN
    SELECT status::text
    INTO v_status
    FROM journal_entries
    WHERE id = p_entry_id;

    IF NOT FOUND OR v_status NOT IN ('posted', 'reconciled') THEN
        RETURN;
    END IF;

    SELECT
        count(*),
        count(*) FILTER (
            WHERE COALESCE(upper(currency), v_base_currency) <> v_base_currency
              AND (fx_rate IS NULL OR fx_rate <= 0)
        ),
        COALESCE(
            sum(
                CASE WHEN direction::text = 'DEBIT'
                THEN amount * CASE
                    WHEN COALESCE(upper(currency), v_base_currency) = v_base_currency THEN 1
                    ELSE fx_rate
                END
                ELSE 0 END
            ),
            0
        ),
        COALESCE(
            sum(
                CASE WHEN direction::text = 'CREDIT'
                THEN amount * CASE
                    WHEN COALESCE(upper(currency), v_base_currency) = v_base_currency THEN 1
                    ELSE fx_rate
                END
                ELSE 0 END
            ),
            0
        )
    INTO v_line_count, v_bad_fx_count, v_total_debit, v_total_credit
    FROM journal_lines
    WHERE journal_entry_id = p_entry_id;

    IF v_line_count < 2 THEN
        RAISE EXCEPTION 'posted/reconciled journal entry % must have at least two lines', p_entry_id
            USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_posted_min_lines';
    END IF;

    IF v_bad_fx_count > 0 THEN
        RAISE EXCEPTION 'posted/reconciled journal entry % has non-base lines without positive fx_rate', p_entry_id
            USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_lines_posted_fx_required';
    END IF;

    IF abs(v_total_debit - v_total_credit) > 0.01 THEN
        RAISE EXCEPTION
            'posted/reconciled journal entry % is not balanced in base currency: debit %, credit %',
            p_entry_id, v_total_debit, v_total_credit
            USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_posted_base_balance';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION fr_validate_journal_void_reversal(p_entry_id uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_status text;
    v_user_id uuid;
    v_reversal_entry_id uuid;
    v_reversal_status text;
    v_reversal_user_id uuid;
BEGIN
    SELECT status::text, user_id, void_reversal_entry_id
    INTO v_status, v_user_id, v_reversal_entry_id
    FROM journal_entries
    WHERE id = p_entry_id;

    IF NOT FOUND OR v_status <> 'void' THEN
        RETURN;
    END IF;

    IF v_reversal_entry_id IS NULL THEN
        RAISE EXCEPTION 'void journal entry % must reference a reversal entry', p_entry_id
            USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_void_reversal_required';
    END IF;

    IF v_reversal_entry_id = p_entry_id THEN
        RAISE EXCEPTION 'void journal entry % cannot reverse itself', p_entry_id
            USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_void_reversal_not_self';
    END IF;

    SELECT status::text, user_id
    INTO v_reversal_status, v_reversal_user_id
    FROM journal_entries
    WHERE id = v_reversal_entry_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'void journal entry % references missing reversal entry %', p_entry_id, v_reversal_entry_id
            USING ERRCODE = '23503', CONSTRAINT = 'fk_journal_entries_void_reversal_entry_id';
    END IF;

    IF v_reversal_user_id <> v_user_id THEN
        RAISE EXCEPTION 'void journal entry % reversal entry belongs to another user', p_entry_id
            USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_void_reversal_same_user';
    END IF;

    IF v_reversal_status NOT IN ('posted', 'reconciled') THEN
        RAISE EXCEPTION 'void journal entry % reversal entry must be posted or reconciled', p_entry_id
            USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_void_reversal_posted';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION fr_check_journal_entry_deferred()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    PERFORM fr_validate_journal_entry_invariants(NEW.id);
    PERFORM fr_validate_journal_void_reversal(NEW.id);
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION fr_check_journal_line_deferred()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_entry_id uuid;
BEGIN
    v_entry_id := COALESCE(NEW.journal_entry_id, OLD.journal_entry_id);
    PERFORM fr_validate_journal_entry_invariants(v_entry_id);
    RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION fr_guard_journal_entry_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status::text IN ('posted', 'reconciled', 'void') THEN
            RAISE EXCEPTION 'cannot delete immutable journal entry % with status %', OLD.id, OLD.status
                USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_immutable_delete';
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.status::text = 'void' THEN
        RAISE EXCEPTION 'cannot update void journal entry %', OLD.id
            USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_void_immutable';
    END IF;

    IF OLD.status::text IN ('posted', 'reconciled') THEN
        IF OLD.status::text = 'posted' AND NEW.status::text = 'reconciled' THEN
            IF NEW.user_id IS DISTINCT FROM OLD.user_id
                OR NEW.entry_date IS DISTINCT FROM OLD.entry_date
                OR NEW.memo IS DISTINCT FROM OLD.memo
                OR NEW.source_id IS DISTINCT FROM OLD.source_id
                OR NEW.void_reason IS DISTINCT FROM OLD.void_reason
                OR NEW.void_reversal_entry_id IS DISTINCT FROM OLD.void_reversal_entry_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR (
                    NEW.source_type IS DISTINCT FROM OLD.source_type
                    AND NOT (
                        NEW.source_type::text = 'user_confirmed'
                        AND OLD.source_type::text IN ('auto_parsed', 'bank_statement', 'auto_matched')
                    )
                )
            THEN
                RAISE EXCEPTION 'posted journal entry % can only move to reconciled without fact mutation', OLD.id
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_posted_reconcile_only';
            END IF;
            RETURN NEW;
        END IF;

        IF OLD.status::text = 'posted' AND NEW.status::text = 'void' THEN
            IF NEW.user_id IS DISTINCT FROM OLD.user_id
                OR NEW.entry_date IS DISTINCT FROM OLD.entry_date
                OR NEW.memo IS DISTINCT FROM OLD.memo
                OR NEW.source_type IS DISTINCT FROM OLD.source_type
                OR NEW.source_id IS DISTINCT FROM OLD.source_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'posted journal entry % can only be voided without fact mutation', OLD.id
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_posted_void_only';
            END IF;

            IF NEW.void_reversal_entry_id IS NULL OR NEW.void_reason IS NULL OR btrim(NEW.void_reason) = '' THEN
                RAISE EXCEPTION 'voiding posted journal entry % requires reason and reversal entry', OLD.id
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_void_fields_required';
            END IF;
            RETURN NEW;
        END IF;

        IF NEW.status::text = OLD.status::text
            AND NEW.user_id IS NOT DISTINCT FROM OLD.user_id
            AND NEW.entry_date IS NOT DISTINCT FROM OLD.entry_date
            AND NEW.memo IS NOT DISTINCT FROM OLD.memo
            AND NEW.source_id IS NOT DISTINCT FROM OLD.source_id
            AND NEW.void_reason IS NOT DISTINCT FROM OLD.void_reason
            AND NEW.void_reversal_entry_id IS NOT DISTINCT FROM OLD.void_reversal_entry_id
            AND NEW.created_at IS NOT DISTINCT FROM OLD.created_at
            AND NEW.source_type IS DISTINCT FROM OLD.source_type
        THEN
            IF NEW.source_type::text = 'user_confirmed'
                AND OLD.source_type::text IN ('auto_parsed', 'bank_statement', 'auto_matched')
            THEN
                RETURN NEW;
            END IF;

            RAISE EXCEPTION 'cannot change immutable journal entry % source_type from % to %',
                OLD.id, OLD.source_type, NEW.source_type
                USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_source_type_promotion_only';
        END IF;

        RAISE EXCEPTION 'cannot directly update immutable journal entry % with status %', OLD.id, OLD.status
            USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_immutable_update';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION fr_guard_journal_line_immutability()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_old_status text;
    v_new_status text;
    v_new_xmin text;
BEGIN
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT status::text INTO v_old_status FROM journal_entries WHERE id = OLD.journal_entry_id;
        IF v_old_status IN ('posted', 'reconciled', 'void') THEN
            RAISE EXCEPTION 'cannot mutate line % for immutable journal entry %', OLD.id, OLD.journal_entry_id
                USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_lines_immutable_update';
        END IF;
    END IF;

    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT status::text, xmin::text
        INTO v_new_status, v_new_xmin
        FROM journal_entries
        WHERE id = NEW.journal_entry_id;

        IF v_new_status = 'void' THEN
            RAISE EXCEPTION 'cannot attach line % to void journal entry %', NEW.id, NEW.journal_entry_id
                USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_lines_void_insert';
        END IF;

        IF v_new_status IN ('posted', 'reconciled') AND v_new_xmin <> pg_current_xact_id()::text THEN
            RAISE EXCEPTION 'cannot attach line % to immutable journal entry %', NEW.id, NEW.journal_entry_id
                USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_lines_immutable_insert';
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ck_journal_entries_ledger_invariants ON journal_entries;
CREATE CONSTRAINT TRIGGER ck_journal_entries_ledger_invariants
AFTER INSERT OR UPDATE ON journal_entries
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fr_check_journal_entry_deferred();

DROP TRIGGER IF EXISTS ck_journal_lines_ledger_invariants ON journal_lines;
CREATE CONSTRAINT TRIGGER ck_journal_lines_ledger_invariants
AFTER INSERT OR UPDATE OR DELETE ON journal_lines
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION fr_check_journal_line_deferred();

DROP TRIGGER IF EXISTS ck_journal_entries_immutable ON journal_entries;
CREATE TRIGGER ck_journal_entries_immutable
BEFORE UPDATE OR DELETE ON journal_entries
FOR EACH ROW EXECUTE FUNCTION fr_guard_journal_entry_immutability();

DROP TRIGGER IF EXISTS ck_journal_lines_immutable ON journal_lines;
CREATE TRIGGER ck_journal_lines_immutable
BEFORE INSERT OR UPDATE OR DELETE ON journal_lines
FOR EACH ROW EXECUTE FUNCTION fr_guard_journal_line_immutability();
"""


def _split_postgresql_ddl(sql: str) -> tuple[str, ...]:
    statements: list[str] = []
    start = 0
    in_dollar_quote = False
    index = 0

    while index < len(sql):
        if sql.startswith("$$", index):
            in_dollar_quote = not in_dollar_quote
            index += 2
            continue

        if sql[index] == ";" and not in_dollar_quote:
            statement = sql[start : index + 1].strip()
            if statement:
                statements.append(statement)
            start = index + 1

        index += 1

    trailing = sql[start:].strip()
    if trailing:
        statements.append(trailing)
    return tuple(statements)


def _install_ledger_invariant_ddl(target: Any, connection: Any, **_: Any) -> None:
    if connection.dialect.name != "postgresql":
        return

    # asyncpg rejects multi-command prepared statements during metadata create_all().
    for statement in _split_postgresql_ddl(_LEDGER_INVARIANT_SQL):
        connection.exec_driver_sql(statement)


event.listen(JournalLine.__table__, "after_create", _install_ledger_invariant_ddl)
