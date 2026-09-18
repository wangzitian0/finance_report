"""Ensure enum casing compatibility for journal, chat, and confidence enums.

Revision ID: 0063_enum_case_compat
Revises: 0062_bank_custody
Create Date: 2026-09-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic (must be <= 32 chars).
revision: str = "0063_enum_case_compat"
down_revision: str | None = "0062_bank_custody"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enums that may have drifted between uppercase (historical default SQLAlchemy naming)
# and lowercase (explicit values_callable wire strings).
ENUM_VALUES_TO_ENSURE: dict[str, list[str]] = {
    "journal_entry_status_enum": [
        "draft",
        "posted",
        "reconciled",
        "void",
        "DRAFT",
        "POSTED",
        "RECONCILED",
        "VOID",
    ],
    "chat_session_status_enum": [
        "active",
        "deleted",
        "ACTIVE",
        "DELETED",
    ],
    "chat_message_role_enum": [
        "user",
        "assistant",
        "system",
        "USER",
        "ASSISTANT",
        "SYSTEM",
    ],
    "confidence_level_enum": [
        "high",
        "medium",
        "low",
        "HIGH",
        "MEDIUM",
        "LOW",
    ],
    "bank_statement_status_enum": [
        "uploaded",
        "parsing",
        "parsed",
        "approved",
        "rejected",
        "retired",
        "UPLOADED",
        "PARSING",
        "PARSED",
        "APPROVED",
        "REJECTED",
        "RETIRED",
    ],
}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Check which types exist in pg_type before altering
    for enum_type_name, values in ENUM_VALUES_TO_ENSURE.items():
        exists = bind.execute(
            sa.text("SELECT 1 FROM pg_type WHERE typname = :typname"),
            {"typname": enum_type_name},
        ).scalar()
        if exists:
            for val in values:
                op.execute(f"ALTER TYPE {enum_type_name} ADD VALUE IF NOT EXISTS '{val}'")


def downgrade() -> None:
    # PostgreSQL does not support dropping enum values without rebuilding the type.
    # Additive values are completely safe and backward-compatible.
    pass
