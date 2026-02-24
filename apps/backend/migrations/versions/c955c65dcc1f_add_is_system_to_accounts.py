"""add_is_system_to_accounts"""

from alembic import op
import sqlalchemy as sa



revision = 'c955c65dcc1f'
down_revision = '0011_add_txn_currency_balance'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_system column to accounts table
    op.add_column('accounts', sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    # Remove is_system column from accounts table
    op.drop_column('accounts', 'is_system')
