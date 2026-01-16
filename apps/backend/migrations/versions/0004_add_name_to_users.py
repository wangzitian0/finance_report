"""add name column to users table

Revision ID: 0004_add_name_to_users
Revises: 0003_add_users_table
Create Date: 2026-01-15 14:25:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '0004_add_name_to_users'
down_revision = '0003_add_users_table'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('name', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'name')
