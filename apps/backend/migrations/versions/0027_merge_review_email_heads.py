"""merge review scope and normalized email heads

Revision ID: 0027_merge_review_email_heads
Revises: 0026_add_review_run_scope, 0026_user_email_norm_idx
Create Date: 2026-06-06 00:00:00.000000

"""

from __future__ import annotations

revision = "0027_merge_review_email_heads"
down_revision = ("0026_add_review_run_scope", "0026_user_email_norm_idx")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
