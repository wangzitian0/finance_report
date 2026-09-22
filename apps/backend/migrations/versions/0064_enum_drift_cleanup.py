"""Clean up enum label drift surfaced by infra2's pre-deploy schema gate (#698).

``0063_enum_case_compat`` added BOTH the current lowercase labels AND the legacy
uppercase labels to five enum types "for casing compatibility" -- but that legalized
the drift rather than resolving it. infra2's ``tools/pre_deploy_schema_check.py``
(wired into the deploy path in infra2 PR #783) compares the live Postgres enum label
set against the code side 1:1: an orphan label the code no longer declares is *itself*
the failure it flags (``missing_in_code``), independent of whether any row still
writes it. Live-verified 2026-09-22 by an independent run of the same comparison
against both real databases (direct psql, read-only): prod has 6 discrepant enum
types, staging has 4 -- matching PR #783's own live-probe numbers exactly. Also
verified: zero rows in either environment hold any orphan label below
(``SELECT ... WHERE col::text IN (...)`` returns 0 rows for every column/label pair
in both staging and prod), so none of these are live drift -- all are dead labels
left over from historical renames.

Two independent drift shapes:

1. Legacy-uppercase orphans (0063's mistake), present in BOTH staging and prod:
   ``chat_session_status_enum``, ``chat_message_role_enum``,
   ``journal_entry_status_enum``.
2. Legacy-lowercase orphans, pre-dating 0007's enum-name normalization, PROD ONLY
   (staging never carried them -- a fresher database):
   ``account_type_enum``, ``journal_line_direction_enum``.

Postgres has no ``DROP VALUE`` for an enum label, so each is rebuilt
rename-create-rebind-drop (0040's pattern): a defensive, idempotent ``UPDATE``
first collapses any residual orphan-cased row to its canonical form (a no-op today,
per the live-verification above -- it only guards a stray future write racing this
migration), then the type is rebuilt without the orphan labels. Each rebuild is
guarded on the orphan label actually being present, so this migration is a safe
no-op wherever a given drift was never present (e.g. running it against staging is a
no-op for the two prod-only cases) and is safe to re-run.

A third, unrelated drift shape was also found and is explicitly NOT an orphan label
to drop: ``LLMProtocolFamily.GOOGLE_GEMINI = "google-gemini"``
(``src/llm/base/types.py``) was added to the code side with no migration ever adding
the label to ``llm_protocol_family_enum`` -- present in BOTH environments. This is
the same *forward* drift shape as the #698 incident itself (code ahead of DB), not a
legacy leftover, so the fix is a plain additive ``ADD VALUE IF NOT EXISTS`` (Postgres
can grow an enum without a rebuild) -- there is no orphan label to argue about; the
code is already right and the DB needs to catch up.

Revision ID: 0064_enum_drift_cleanup
Revises: 0063_enum_case_compat
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic (must be <= 32 chars).
revision: str = "0064_enum_drift_cleanup"
down_revision: str | None = "0063_enum_case_compat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (enum_type, table, column, canonical_values, orphan_values)
_LABEL_DROPS: tuple[tuple[str, str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "chat_session_status_enum",
        "chat_sessions",
        "status",
        ("active", "deleted"),
        ("ACTIVE", "DELETED"),
    ),
    (
        "chat_message_role_enum",
        "chat_messages",
        "role",
        ("user", "assistant", "system"),
        ("USER", "ASSISTANT", "SYSTEM"),
    ),
    (
        "journal_entry_status_enum",
        "journal_entries",
        "status",
        ("draft", "posted", "reconciled", "void"),
        ("DRAFT", "POSTED", "RECONCILED", "VOID"),
    ),
    (
        "account_type_enum",
        "accounts",
        "type",
        ("ASSET", "LIABILITY", "EQUITY", "INCOME", "EXPENSE"),
        ("asset", "liability", "equity", "income", "expense"),
    ),
    (
        "journal_line_direction_enum",
        "journal_lines",
        "direction",
        ("DEBIT", "CREDIT"),
        ("debit", "credit"),
    ),
)

# Added to LLMProtocolFamily (src/llm/base/types.py) with no migration ever adding
# the DB label -- the DB needs a label added, not a label dropped.
_LLM_PROTOCOL_FAMILY_ENUM = "llm_protocol_family_enum"
_LLM_PROTOCOL_FAMILY_ADD = "google-gemini"


def upgrade() -> None:
    for enum_name, table, column, canonical, orphans in _LABEL_DROPS:
        # 1. Defensive, idempotent: collapse any residual orphan-cased rows to the
        #    canonical casing before the type is rebuilt (0040's pattern). Text-cast
        #    comparison tolerates either enum state; the WHERE clause means this only
        #    ever touches rows actually holding an orphan label.
        #
        #    Committed in its own transaction (autocommit_block): journal_entries and
        #    journal_lines each carry an `AFTER INSERT OR UPDATE ... DEFERRABLE
        #    INITIALLY DEFERRED` constraint trigger (0032_ledger_invariants) that
        #    queues a pending trigger event on any row this UPDATE actually touches.
        #    Postgres refuses `ALTER TABLE ... ALTER COLUMN ... TYPE` in step 2 while
        #    a trigger event from the SAME transaction is still pending ("cannot ALTER
        #    TABLE because it has pending trigger events") -- committing here flushes
        #    it (running the deferred invariant check) before the rebuild. Verified by
        #    seeding an orphan-cased row on a live schema copy and observing this exact
        #    failure without the commit boundary. Harmless when 0 rows match (today, on
        #    both real environments): a same-transaction UPDATE would have been a no-op
        #    to split out too.
        canonical_by_lower = {value.lower(): value for value in canonical}
        case_map = "\n".join(
            f"                    WHEN '{orphan}' THEN '{canonical_by_lower[orphan.lower()]}'" for orphan in orphans
        )
        orphan_list = ", ".join(f"'{o}'" for o in orphans)
        canonical_list = ", ".join(f"'{c}'" for c in canonical)
        with op.get_context().autocommit_block():
            op.execute(
                f"""
                UPDATE {table}
                SET {column} = (
                    CASE {column}::text
{case_map}
                        ELSE {column}::text
                    END
                )::{enum_name}
                WHERE {column}::text IN ({orphan_list})
                """
            )

        # 2. Rebuild the enum without the orphan labels. Guarded so this is a no-op
        #    on a database where none of the orphan labels are present (e.g. staging
        #    for account_type_enum / journal_line_direction_enum -- see module
        #    docstring).
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM pg_enum e
                    JOIN pg_type t ON t.oid = e.enumtypid
                    WHERE t.typname = '{enum_name}'
                      AND e.enumlabel IN ({orphan_list})
                ) THEN
                    ALTER TYPE {enum_name} RENAME TO {enum_name}_old;
                    CREATE TYPE {enum_name} AS ENUM ({canonical_list});
                    ALTER TABLE {table}
                        ALTER COLUMN {column} DROP DEFAULT,
                        ALTER COLUMN {column} TYPE {enum_name}
                            USING {column}::text::{enum_name};
                    DROP TYPE {enum_name}_old;
                END IF;
            END $$;
            """
        )

    # 3. Additive: the code side already declares 'google-gemini'
    #    (LLMProtocolFamily.GOOGLE_GEMINI); the DB enum never got the label. Growing
    #    an enum needs no rebuild, but ADD VALUE cannot run inside this migration's
    #    transaction block.
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE {_LLM_PROTOCOL_FAMILY_ENUM} ADD VALUE IF NOT EXISTS '{_LLM_PROTOCOL_FAMILY_ADD}'")


def downgrade() -> None:
    # Label drops: re-add the orphan labels so the migration is reversible (mirrors
    # 0040's downgrade). Idempotent and tolerant of an already-present label.
    with op.get_context().autocommit_block():
        for enum_name, _table, _column, _canonical, orphans in _LABEL_DROPS:
            for orphan in orphans:
                op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{orphan}'")

    # The additive 'google-gemini' label cannot be safely removed (Postgres has no
    # DROP VALUE); downgrade leaves it in place, same as every other ADD VALUE
    # downgrade in this repo's migration history (e.g. 0040's, 0063's).
