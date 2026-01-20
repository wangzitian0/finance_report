"""add users table (no-op: users table created in 0001_initial_schema)

Revision ID: 0003_add_users_table
Revises: 0002_add_chat_tables
Create Date: 2026-01-11 19:30:00.000000

"""

# revision identifiers, used by Alembic.
revision = "0003_add_users_table"
down_revision = "0002_add_chat_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
