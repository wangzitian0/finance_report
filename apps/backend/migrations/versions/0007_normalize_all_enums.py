"""Normalize all enum names.

Revision ID: 0007_normalize_all_enums
Revises: 0006_parse_nullable_fields
Create Date: 2026-01-20 10:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0007_normalize_all_enums"
down_revision = "0006_parse_nullable_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # List of (old_name, new_name, table, column)
    enums_to_fix = [
        ("accounttype", "account_type_enum", "accounts", "type"),
        ("bankstatementstatus", "bank_statement_status_enum", "bank_statements", "status"),
        ("confidencelevel", "confidence_level_enum", "bank_statement_transactions", "confidence"),
        ("journalentrystatus", "journal_entry_status_enum", "journal_entries", "status"),
        ("journalentrysourcetype", "journal_source_type_enum", "journal_entries", "source_type"),
        ("direction", "journal_line_direction_enum", "journal_lines", "direction"),
        ("reconciliationstatus", "reconciliation_status_enum", "reconciliation_matches", "status"),
        ("chatsessionstatus", "chat_session_status_enum", "chat_sessions", "status"),
        ("chatmessagerole", "chat_message_role_enum", "chat_messages", "role"),
    ]

    for old_name, new_name, table, column in enums_to_fix:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_type WHERE typname = '{old_name}') THEN
                    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = '{new_name}') THEN
                        -- If both exist, move column to the new one if it's still using the old one
                        IF EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE table_name = '{table}'
                              AND column_name = '{column}'
                              AND udt_name = '{old_name}'
                        ) THEN
                            ALTER TABLE {table}
                                ALTER COLUMN {column} TYPE {new_name}
                                USING {column}::text::{new_name};
                        END IF;
                        
                        -- Drop old type if no longer used
                        IF NOT EXISTS (
                            SELECT 1
                            FROM information_schema.columns
                            WHERE udt_name = '{old_name}'
                        ) THEN
                            DROP TYPE {old_name};
                        END IF;
                    ELSE
                        -- If only old one exists, rename it
                        ALTER TYPE {old_name} RENAME TO {new_name};
                    END IF;
                END IF;
            END $$;
            """
        )


def downgrade() -> None:
    # Downgrade is optional for this kind of normalization but we can provide it
    # Mapping back to the most likely default names
    enums_to_revert = [
        ("account_type_enum", "accounttype"),
        ("bank_statement_status_enum", "bankstatementstatus"),
        ("confidence_level_enum", "confidencelevel"),
        ("journal_entry_status_enum", "journalentrystatus"),
        ("journal_source_type_enum", "journalentrysourcetype"),
        ("journal_line_direction_enum", "direction"),
        ("reconciliation_status_enum", "reconciliationstatus"),
        ("chat_session_status_enum", "chatsessionstatus"),
        ("chat_message_role_enum", "chatmessagerole"),
    ]
    
    for current_name, old_name in enums_to_revert:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_type WHERE typname = '{current_name}') 
                   AND NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{old_name}') THEN
                    ALTER TYPE {current_name} RENAME TO {old_name};
                END IF;
            END $$;
            """
        )
