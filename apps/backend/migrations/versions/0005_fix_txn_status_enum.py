"""Normalize bank statement transaction status enum name.

Revision ID: 0005_fix_txn_status_enum
Revises: 0004_add_name_to_users
Create Date: 2026-01-20 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_fix_txn_status_enum"
down_revision = "0004_add_name_to_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'bankstatementtransactionstatus'
            ) THEN
                IF EXISTS (
                    SELECT 1 FROM pg_type WHERE typname = 'bank_statement_transaction_status_enum'
                ) THEN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'bank_statement_transactions'
                          AND column_name = 'status'
                          AND udt_name = 'bankstatementtransactionstatus'
                    ) THEN
                        ALTER TABLE bank_statement_transactions
                            ALTER COLUMN status TYPE bank_statement_transaction_status_enum
                            USING status::text::bank_statement_transaction_status_enum;
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE udt_name = 'bankstatementtransactionstatus'
                    ) THEN
                        DROP TYPE bankstatementtransactionstatus;
                    END IF;
                ELSE
                    ALTER TYPE bankstatementtransactionstatus 
                    RENAME TO bank_statement_transaction_status_enum;
                END IF;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'bank_statement_transaction_status_enum'
            ) AND NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'bankstatementtransactionstatus'
            ) THEN
                ALTER TYPE bank_statement_transaction_status_enum 
                RENAME TO bankstatementtransactionstatus;
            END IF;
        END $$;
        """
    )
