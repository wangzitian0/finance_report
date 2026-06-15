"""Retire the legacy ``bank_statement`` journal source_type value (#896).

The historical data migration already happened in
``0018_source_type_priority`` (``UPDATE journal_entries SET source_type =
'auto_parsed' WHERE source_type::text = 'bank_statement'``). New code never
writes the value: every write path runs ``normalize_source_type`` first, which
maps ``bank_statement`` -> ``auto_parsed``. The value is therefore dead in both
data and code, and this revision drops it from the enum type.

Drift tolerance (AC13.10.4): this migration does NOT assume a particular enum
state. It re-runs the defensive ``UPDATE`` first so the type rebuild can never
fail on a stray row, and it only rebuilds the type when the ``bank_statement``
label is actually present. Postgres has no ``DROP VALUE``, so we rename-create-
rebind-drop. The raw string ``'bank_statement'`` is still tolerated at the
application layer (``normalize_source_type`` and the immutability trigger keep a
text-level guard) so historical raw values remain harmless.
"""

from alembic import op

revision = "0040_retire_bank_stmt_source"
down_revision = "0039_stmt_conflicts_resolved"
branch_labels = None
depends_on = None


_REMAINING_VALUES = (
    "manual",
    "user_confirmed",
    "auto_matched",
    "auto_parsed",
    "system",
    "fx_revaluation",
)


def upgrade() -> None:
    # 1. Defensive, idempotent: collapse any residual legacy rows before the
    #    type is rebuilt. Text-cast comparison tolerates either enum state.
    op.execute(
        "UPDATE journal_entries SET source_type = 'auto_parsed' "
        "WHERE source_type::text = 'bank_statement'"
    )

    # 2. Rebuild the enum without 'bank_statement'. Guarded so the migration is
    #    a no-op on databases where the label was never present.
    new_values = ", ".join(f"'{value}'" for value in _REMAINING_VALUES)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_enum e
                JOIN pg_type t ON t.oid = e.enumtypid
                WHERE t.typname = 'journal_source_type_enum'
                  AND e.enumlabel = 'bank_statement'
            ) THEN
                ALTER TYPE journal_source_type_enum RENAME TO journal_source_type_enum_old;
                CREATE TYPE journal_source_type_enum AS ENUM ({new_values});
                ALTER TABLE journal_entries
                    ALTER COLUMN source_type DROP DEFAULT,
                    ALTER COLUMN source_type TYPE journal_source_type_enum
                        USING source_type::text::journal_source_type_enum;
                DROP TYPE journal_source_type_enum_old;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Re-add the label so the migration is reversible. Idempotent and tolerant
    # of an already-present label (mirrors 0018's defensive ADD VALUE).
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE journal_source_type_enum ADD VALUE IF NOT EXISTS 'bank_statement'"
        )
