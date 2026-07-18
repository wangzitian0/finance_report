"""Require explicit authority state for journal-entry provenance (#1909)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0056_decision_anchored_journal"
down_revision = "0055_reviewed_stmt_envelope"
branch_labels = None
depends_on = None

authority_state = postgresql.ENUM(
    "anchored",
    "legacy_unproven",
    name="journal_entry_authority_state_enum",
    create_type=False,
)


def upgrade() -> None:
    authority_state.create(op.get_bind(), checkfirst=True)
    op.add_column("journal_entries", sa.Column("decision_anchor_id", postgresql.UUID(as_uuid=True), nullable=True))
    # Existing posted/reconciled entries are immutable before this revision. A
    # PostgreSQL fast default expresses their explicit legacy state without an
    # UPDATE that would fire the immutability trigger. Drop it immediately so
    # future writers must choose authority state through the anchored boundary.
    op.add_column(
        "journal_entries",
        sa.Column(
            "decision_authority_state",
            authority_state,
            nullable=False,
            server_default=sa.text("'legacy_unproven'::journal_entry_authority_state_enum"),
        ),
    )
    op.alter_column("journal_entries", "decision_authority_state", server_default=None)
    op.create_foreign_key(
        "fk_journal_entries_decision_anchor",
        "journal_entries",
        "trace_records",
        ["decision_anchor_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint("uq_journal_entries_decision_anchor", "journal_entries", ["decision_anchor_id"])
    op.create_check_constraint(
        "ck_journal_entries_decision_anchor_complete",
        "journal_entries",
        "(decision_authority_state = 'anchored' "
        "AND decision_anchor_id IS NOT NULL) "
        "OR (decision_authority_state = 'legacy_unproven' "
        "AND decision_anchor_id IS NULL)",
    )
    op.execute(_IMMUTABILITY_FUNCTION)


def downgrade() -> None:
    # The live trigger mentions anchor columns. Restore the preceding function
    # before dropping them so a downgrade leaves a valid write path.
    op.execute(_LEGACY_IMMUTABILITY_FUNCTION)
    op.drop_constraint("ck_journal_entries_decision_anchor_complete", "journal_entries", type_="check")
    op.drop_constraint("uq_journal_entries_decision_anchor", "journal_entries", type_="unique")
    op.drop_constraint("fk_journal_entries_decision_anchor", "journal_entries", type_="foreignkey")
    for column in (
        "decision_authority_state",
        "decision_anchor_id",
    ):
        op.drop_column("journal_entries", column)
    authority_state.drop(op.get_bind(), checkfirst=True)


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


_LEGACY_IMMUTABILITY_FUNCTION = """
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
"""
