"""add the app_config table for runtime app-level settings (#1340, Phase D)

Creates a single key/value ``app_config`` table so app-level settings (starting
with the base reporting currency) can be overridden at runtime instead of being
env-only. ``key`` is unique so each setting has exactly one row; the effective
value is "persisted row else ``settings.base_currency``" (see
``src.config_app.get_effective_base_currency``).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0050_add_app_config"
down_revision = "0049_add_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_config",
        sa.Column("id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_app_config"),
        sa.UniqueConstraint("key", name="uq_app_config_key"),
    )


def downgrade() -> None:
    op.drop_table("app_config")
