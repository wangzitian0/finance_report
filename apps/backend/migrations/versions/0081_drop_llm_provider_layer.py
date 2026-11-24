"""Drop the per-user LLM provider tables and their enum types (#2953 stage 3).

Revision ID: 0081_drop_llm_provider_layer
Revises: 0080_stmt_institution_nullable
Create Date: 2026-11-24

The three model roles come from the environment. No code reads or writes ``llm_providers`` or
``llm_scene_bindings`` since stage 2 of #2953. Both tables hold no row on staging and on production
(read-only count, 2026-11-24). The upgrade drops the two tables and the enum types
``llm_protocol_family_enum``, ``llm_scene_enum`` and ``llm_reasoning_effort_enum``. The columns
``prefer_free`` and ``fallback_model_ids`` belong to ``llm_scene_bindings`` and go with it.

The upgrade stops while either table holds a row, so it never drops data. The downgrade recreates both
tables, the enum types and the indexes and keys exactly as revisions 0043, 0044 and 0064 left them. It
restores no row, because none exists.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0081_drop_llm_provider_layer"
down_revision: str | None = "0080_stmt_institution_nullable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Labels in sort order. The last label of the protocol enum came with revision 0064.
_PROTOCOL_VALUES = ("openai-compatible", "anthropic-compatible", "openrouter-compatible", "google-gemini")
_SCENE_VALUES = ("extraction.ocr", "extraction.vision", "extraction.json", "advisor.chat", "statement.summary")
_REASONING_VALUES = ("none", "low", "medium", "high")
_ENUMS = (
    ("llm_protocol_family_enum", _PROTOCOL_VALUES),
    ("llm_scene_enum", _SCENE_VALUES),
    ("llm_reasoning_effort_enum", _REASONING_VALUES),
)


def _create_enum(name: str, values: tuple[str, ...]) -> None:
    labels = ", ".join(f"'{v}'" for v in values)
    op.execute(f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({labels}); EXCEPTION WHEN duplicate_object THEN null; END $$;")


def upgrade() -> None:
    connection = op.get_bind()
    providers = connection.execute(sa.text("SELECT COUNT(*) FROM llm_providers")).scalar()
    bindings = connection.execute(sa.text("SELECT COUNT(*) FROM llm_scene_bindings")).scalar()
    if providers or bindings:
        raise RuntimeError(
            f"llm_providers holds {providers} row(s) and llm_scene_bindings holds {bindings} row(s). "
            "The upgrade drops no data. Export or delete the rows, then run the upgrade again."
        )
    op.drop_table("llm_scene_bindings")
    op.drop_table("llm_providers")
    for name, _values in reversed(_ENUMS):
        op.execute(f"DROP TYPE IF EXISTS {name}")


def downgrade() -> None:
    for name, values in _ENUMS:
        _create_enum(name, values)

    op.create_table(
        "llm_providers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column(
            "protocol",
            postgresql.ENUM(*_PROTOCOL_VALUES, name="llm_protocol_family_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("api_key_ciphertext", sa.String(), nullable=False),
        sa.Column("api_key_version", sa.BigInteger(), nullable=False),
        sa.Column("api_base", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_llm_providers_user_id", ondelete="CASCADE"),
    )
    op.create_index("ix_llm_providers_user_id", "llm_providers", ["user_id"])

    op.create_table(
        "llm_scene_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "scene",
            postgresql.ENUM(*_SCENE_VALUES, name="llm_scene_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column(
            "reasoning",
            postgresql.ENUM(*_REASONING_VALUES, name="llm_reasoning_effort_enum", create_type=False),
            nullable=False,
        ),
        sa.Column("prefer_free", sa.Boolean(), nullable=False),
        sa.Column("fallback_model_ids", sa.String(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["provider_id"], ["llm_providers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_llm_scene_bindings_user_id", ondelete="CASCADE"),
    )
    op.create_index("ix_llm_scene_bindings_provider_id", "llm_scene_bindings", ["provider_id"])
    op.create_index("ix_llm_scene_bindings_user_id", "llm_scene_bindings", ["user_id"])
    op.create_index(
        "uq_llm_scene_bindings_user_scene",
        "llm_scene_bindings",
        ["user_id", "scene"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_llm_scene_bindings_default_scene",
        "llm_scene_bindings",
        ["scene"],
        unique=True,
        postgresql_where=sa.text("user_id IS NULL"),
    )
