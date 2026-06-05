"""add normalized email unique index

Revision ID: 0026_user_email_norm_idx
Revises: 0025_add_evidence_lineage
Create Date: 2026-06-06 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "0026_user_email_norm_idx"
down_revision = "0025_add_evidence_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_users_email_normalized",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_users_email_normalized", table_name="users")
