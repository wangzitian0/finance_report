"""add normalized email unique index

Revision ID: 0026_user_email_norm_idx
Revises: 0025_add_evidence_lineage
Create Date: 2026-06-06 00:00:00.000000

"""

from alembic import op

revision = "0026_user_email_norm_idx"
down_revision = "0025_add_evidence_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX uq_users_email_normalized ON users (lower(email))")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_users_email_normalized")
