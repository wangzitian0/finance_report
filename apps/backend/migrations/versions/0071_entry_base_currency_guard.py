"""Use journal_entries.base_currency in trigger validation and immutability guard (#2551).

Revision ID: 0071_entry_base_currency_guard
Revises: 0070_void_reversal_index
Create Date: 2026-04-20
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0071_entry_base_currency_guard"
down_revision: str | None = "0070_void_reversal_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VALIDATE_FUNCTION = """
CREATE OR REPLACE FUNCTION fr_validate_journal_entry_invariants(p_entry_id uuid)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_status text;
    v_row_base text;
    v_base_currency text;
    v_line_count integer;
    v_bad_fx_count integer;
    v_total_debit numeric;
    v_total_credit numeric;
BEGIN
    SELECT status::text, base_currency
    INTO v_status, v_row_base
    FROM journal_entries
    WHERE id = p_entry_id;

    IF NOT FOUND OR v_status NOT IN ('posted', 'reconciled') THEN
        RETURN;
    END IF;

    v_base_currency := upper(COALESCE(v_row_base, fr_ledger_base_currency()));

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
"""

_IMMUTABILITY_FUNCTION = """
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
                OR NEW.decision_anchor_id IS DISTINCT FROM OLD.decision_anchor_id
                OR NEW.decision_authority_state IS DISTINCT FROM OLD.decision_authority_state
                OR NEW.base_currency IS DISTINCT FROM OLD.base_currency
                OR NEW.void_reason IS DISTINCT FROM OLD.void_reason
                OR NEW.void_reversal_entry_id IS DISTINCT FROM OLD.void_reversal_entry_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.source_type IS DISTINCT FROM OLD.source_type
            THEN
                RAISE EXCEPTION 'posted journal entry % can only move to reconciled without fact mutation', OLD.id
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_posted_reconcile_only';
            END IF;
            RETURN NEW;
        END IF;

        IF OLD.status::text IN ('posted', 'reconciled') AND NEW.status::text = 'void' THEN
            IF NEW.user_id IS DISTINCT FROM OLD.user_id
                OR NEW.entry_date IS DISTINCT FROM OLD.entry_date
                OR NEW.memo IS DISTINCT FROM OLD.memo
                OR NEW.source_type IS DISTINCT FROM OLD.source_type
                OR NEW.source_id IS DISTINCT FROM OLD.source_id
                OR NEW.decision_anchor_id IS DISTINCT FROM OLD.decision_anchor_id
                OR NEW.decision_authority_state IS DISTINCT FROM OLD.decision_authority_state
                OR NEW.base_currency IS DISTINCT FROM OLD.base_currency
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'posted or reconciled journal entry % can only be voided without fact mutation', OLD.id
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_posted_void_only';
            END IF;

            IF NEW.void_reversal_entry_id IS NULL OR NEW.void_reason IS NULL OR btrim(NEW.void_reason) = '' THEN
                RAISE EXCEPTION 'voiding posted or reconciled journal entry % requires reason and reversal entry', OLD.id
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
            RAISE EXCEPTION 'cannot change immutable journal entry % source_type from % to %',
                OLD.id, OLD.source_type, NEW.source_type
                USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_source_type_immutable';
        END IF;

        RAISE EXCEPTION 'cannot directly update immutable journal entry % with status %', OLD.id, OLD.status
            USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_immutable_update';
    END IF;

    RETURN NEW;
END;
$$;
"""

_VALIDATE_FUNCTION_PREV = (
    _VALIDATE_FUNCTION.replace(
        "    v_row_base text;\n    v_base_currency text;",
        "    v_base_currency text := upper(fr_ledger_base_currency());",
    )
    .replace(
        "    SELECT status::text, base_currency\n    INTO v_status, v_row_base",
        "    SELECT status::text\n    INTO v_status",
    )
    .replace("\n    v_base_currency := upper(COALESCE(v_row_base, fr_ledger_base_currency()));\n", "")
)
_IMMUTABILITY_FUNCTION_PREV = _IMMUTABILITY_FUNCTION.replace(
    "\n                OR NEW.base_currency IS DISTINCT FROM OLD.base_currency",
    "",
)


def upgrade() -> None:
    op.execute(_VALIDATE_FUNCTION)
    op.execute(_IMMUTABILITY_FUNCTION)


def downgrade() -> None:
    op.execute(_VALIDATE_FUNCTION_PREV)
    op.execute(_IMMUTABILITY_FUNCTION_PREV)
