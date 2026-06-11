"""harden ledger invariants"""

from alembic import op

revision = "0032_ledger_invariants"
down_revision = "0031_drop_orphan_stage1_enum"
branch_labels = None
depends_on = None


LEDGER_INVARIANT_DDL = """
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


DROP_LEDGER_INVARIANT_DDL = """
DROP TRIGGER IF EXISTS ck_journal_lines_immutable ON journal_lines;
DROP TRIGGER IF EXISTS ck_journal_entries_immutable ON journal_entries;
DROP TRIGGER IF EXISTS ck_journal_lines_ledger_invariants ON journal_lines;
DROP TRIGGER IF EXISTS ck_journal_entries_ledger_invariants ON journal_entries;
DROP FUNCTION IF EXISTS fr_guard_journal_line_immutability();
DROP FUNCTION IF EXISTS fr_guard_journal_entry_immutability();
DROP FUNCTION IF EXISTS fr_check_journal_line_deferred();
DROP FUNCTION IF EXISTS fr_check_journal_entry_deferred();
DROP FUNCTION IF EXISTS fr_validate_journal_void_reversal(uuid);
DROP FUNCTION IF EXISTS fr_validate_journal_entry_invariants(uuid);
DROP FUNCTION IF EXISTS fr_ledger_base_currency();
"""


def upgrade() -> None:
    op.execute(
        """
CREATE OR REPLACE FUNCTION fr_ledger_base_currency()
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE(NULLIF(current_setting('finance_report.base_currency', true), ''), 'SGD')
$$
"""
    )
    op.execute(
        """
DO $$
DECLARE
    v_base_currency text := upper(fr_ledger_base_currency());
BEGIN
    IF EXISTS (
        SELECT 1
        FROM journal_lines
        WHERE fx_rate <= 0
    ) THEN
        RAISE EXCEPTION 'preflight failed: journal_lines contains non-positive fx_rate values';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM journal_entries entry
        LEFT JOIN journal_lines line ON line.journal_entry_id = entry.id
        WHERE entry.status::text IN ('posted', 'reconciled')
        GROUP BY entry.id
        HAVING count(line.id) < 2
    ) THEN
        RAISE EXCEPTION 'preflight failed: posted/reconciled journal_entries with fewer than two lines exist';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM journal_entries entry
        JOIN journal_lines line ON line.journal_entry_id = entry.id
        WHERE entry.status::text IN ('posted', 'reconciled')
          AND COALESCE(upper(line.currency), v_base_currency) <> v_base_currency
          AND (line.fx_rate IS NULL OR line.fx_rate <= 0)
    ) THEN
        RAISE EXCEPTION 'preflight failed: posted/reconciled non-base journal lines lack positive fx_rate';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM (
            SELECT
                entry.id,
                COALESCE(
                    sum(
                        CASE WHEN line.direction::text = 'DEBIT'
                        THEN line.amount * CASE
                            WHEN COALESCE(upper(line.currency), v_base_currency) = v_base_currency THEN 1
                            ELSE line.fx_rate
                        END
                        ELSE 0 END
                    ),
                    0
                ) AS total_debit,
                COALESCE(
                    sum(
                        CASE WHEN line.direction::text = 'CREDIT'
                        THEN line.amount * CASE
                            WHEN COALESCE(upper(line.currency), v_base_currency) = v_base_currency THEN 1
                            ELSE line.fx_rate
                        END
                        ELSE 0 END
                    ),
                    0
                ) AS total_credit
            FROM journal_entries entry
            JOIN journal_lines line ON line.journal_entry_id = entry.id
            WHERE entry.status::text IN ('posted', 'reconciled')
            GROUP BY entry.id
        ) totals
        WHERE abs(total_debit - total_credit) > 0.01
    ) THEN
        RAISE EXCEPTION 'preflight failed: unbalanced posted/reconciled journal_entries exist';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM journal_entries voided
        LEFT JOIN journal_entries reversal ON reversal.id = voided.void_reversal_entry_id
        WHERE voided.status::text = 'void'
          AND (
            voided.void_reversal_entry_id IS NULL
            OR reversal.id IS NULL
            OR reversal.user_id <> voided.user_id
            OR reversal.status::text NOT IN ('posted', 'reconciled')
          )
    ) THEN
        RAISE EXCEPTION 'preflight failed: void journal_entries have invalid reversal relationships';
    END IF;
END
$$
"""
    )
    op.create_check_constraint(
        "ck_journal_lines_fx_rate_positive",
        "journal_lines",
        "fx_rate IS NULL OR fx_rate > 0",
    )
    op.create_foreign_key(
        "fk_journal_entries_void_reversal_entry_id",
        "journal_entries",
        "journal_entries",
        ["void_reversal_entry_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(LEDGER_INVARIANT_DDL)


def downgrade() -> None:
    op.execute(DROP_LEDGER_INVARIANT_DDL)
    op.drop_constraint("fk_journal_entries_void_reversal_entry_id", "journal_entries", type_="foreignkey")
    op.drop_constraint("ck_journal_lines_fx_rate_positive", "journal_lines", type_="check")
