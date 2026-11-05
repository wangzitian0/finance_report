"""Make users email uniqueness partial on is_deleted = false (#2674).

Revision ID: 0072_users_email_partial_idx
Revises: 0071_entry_base_currency_guard
Create Date: 2026-11-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0072_users_email_partial_idx"
down_revision: str | None = "0071_entry_base_currency_guard"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_email_key")
    op.drop_index("uq_users_email_normalized", table_name="users")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)")
    op.create_index(
        "uq_users_email_normalized",
        "users",
        [sa.text("lower(email)")],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
        sqlite_where=sa.text("is_deleted = 0"),
    )


def downgrade() -> None:
    op.drop_index("uq_users_email_normalized", table_name="users")
    op.execute("DROP INDEX IF EXISTS ix_users_email")
    op.create_index(
        "uq_users_email_normalized",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_unique_constraint("users_email_key", "users", ["email"])
