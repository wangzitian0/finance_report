"""Add is_deleted flag to users table for soft deletion (#1848).

Revision ID: 0065_user_soft_delete
Revises: 0064_enum_drift_cleanup
Create Date: 2026-09-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0065_user_soft_delete"
down_revision: str | None = "0064_enum_drift_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index("ix_users_is_deleted", "users", ["is_deleted"])


def downgrade() -> None:
    op.drop_index("ix_users_is_deleted", table_name="users")
    op.drop_column("users", "is_deleted")
