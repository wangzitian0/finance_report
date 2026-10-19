"""Let the immutability guard void a reconciled journal entry (#2528).

#2472 changed `fr_guard_journal_entry_immutability` in the ORM DDL and added no migration. A database built
by Alembic kept the function of revision 0056: it allows `posted -> void` but not `reconciled -> void`. The
correction of the category of a reconciled entry then ended in `ck_journal_entries_immutable_update`
and the API answered 500. This revision installs the function that the ORM DDL holds. It adds the void
branch for reconciled entries and a specific error for a change of `source_type` alone.
The downgrade restores the function of revision 0056.
"""

from alembic import op

revision = "0066_reconciled_void_guard"
down_revision = "0065_user_soft_delete"
branch_labels = None
depends_on = None

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

_PREVIOUS_IMMUTABILITY_FUNCTION = """
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
                OR NEW.source_type IS DISTINCT FROM OLD.source_type
                OR NEW.source_id IS DISTINCT FROM OLD.source_id
                OR NEW.decision_anchor_id IS DISTINCT FROM OLD.decision_anchor_id
                OR NEW.decision_authority_state IS DISTINCT FROM OLD.decision_authority_state
                OR NEW.void_reason IS DISTINCT FROM OLD.void_reason
                OR NEW.void_reversal_entry_id IS DISTINCT FROM OLD.void_reversal_entry_id
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
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
                OR NEW.decision_anchor_id IS DISTINCT FROM OLD.decision_anchor_id
                OR NEW.decision_authority_state IS DISTINCT FROM OLD.decision_authority_state
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
        RAISE EXCEPTION 'cannot directly update immutable journal entry % with status %', OLD.id, OLD.status
            USING ERRCODE = '23514', CONSTRAINT = 'ck_journal_entries_immutable_update';
    END IF;
    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.execute(_IMMUTABILITY_FUNCTION)


def downgrade() -> None:
    op.execute(_PREVIOUS_IMMUTABILITY_FUNCTION)
