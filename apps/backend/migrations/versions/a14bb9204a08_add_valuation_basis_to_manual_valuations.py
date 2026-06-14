"""add valuation_basis to manual valuations"""

from alembic import op
import sqlalchemy as sa



revision = 'a14bb9204a08'
down_revision = '0038_atomic_txn_balance_after'
branch_labels = None
depends_on = None


def upgrade() -> None:
    basis_enum = sa.Enum(
        'market_appraisal',
        'broker_statement',
        'employer_grant_document',
        'bank_statement',
        'government_statement',
        'insurer_statement',
        'self_estimate',
        name='manual_valuation_basis_enum',
    )
    basis_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'manual_valuation_snapshots',
        sa.Column('valuation_basis', basis_enum, nullable=True),
    )


def downgrade() -> None:
    op.drop_column('manual_valuation_snapshots', 'valuation_basis')
    sa.Enum(name='manual_valuation_basis_enum').drop(op.get_bind(), checkfirst=True)
