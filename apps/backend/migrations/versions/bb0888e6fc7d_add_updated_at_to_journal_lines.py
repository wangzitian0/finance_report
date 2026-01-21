"""add updated_at to journal_lines

Revision ID: bb0888e6fc7d
Revises: ba0777d5eb6c
Create Date: 2026-01-21 12:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "bb0888e6fc7d"
down_revision = "ba0777d5eb6c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "journal_lines",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("journal_lines", "updated_at")
