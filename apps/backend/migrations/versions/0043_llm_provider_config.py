"""llm provider config: provider instances + scene->model bindings (EPIC-023 EPIC B)

Adds two additive, deployment-scoped tables for DB-backed LLM configuration:

- ``llm_providers``: a configured provider instance per row. The API key is
  stored encrypted (Fernet ciphertext + the key fingerprint that sealed it; see
  ``src/llm/common/secrets.py``), never as plaintext.
- ``llm_scene_bindings``: one row per scene (unique) pinning which provider+model
  serves it, plus per-scene reasoning depth / free-tier preference / fallbacks.

Migration risk: low (new additive tables, no backfill, no changes to existing
tables). Three new enum types back the protocol family, scene, and reasoning
depth columns.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0043_llm_provider_config"
down_revision = "0042_fx_conversions"
branch_labels = None
depends_on = None


_PROTOCOL_VALUES = ("openai-compatible", "anthropic-compatible", "openrouter-compatible")
_SCENE_VALUES = ("extraction.ocr", "extraction.vision", "extraction.json", "advisor.chat", "statement.summary")
_REASONING_VALUES = ("none", "low", "medium", "high")


def _create_enum(name: str, values: tuple[str, ...]) -> None:
    labels = ", ".join(f"'{v}'" for v in values)
    op.execute(f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({labels}); EXCEPTION WHEN duplicate_object THEN null; END $$;")


def upgrade() -> None:
    _create_enum("llm_protocol_family_enum", _PROTOCOL_VALUES)
    _create_enum("llm_scene_enum", _SCENE_VALUES)
    _create_enum("llm_reasoning_effort_enum", _REASONING_VALUES)

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
        sa.Column("api_key_version", sa.Integer(), nullable=False),
        sa.Column("api_base", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

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
        sa.ForeignKeyConstraint(["provider_id"], ["llm_providers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("scene", name="uq_llm_scene_bindings_scene"),
    )
    op.create_index("ix_llm_scene_bindings_provider_id", "llm_scene_bindings", ["provider_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_scene_bindings_provider_id", table_name="llm_scene_bindings")
    op.drop_table("llm_scene_bindings")
    op.drop_table("llm_providers")
    op.execute("DROP TYPE IF EXISTS llm_reasoning_effort_enum")
    op.execute("DROP TYPE IF EXISTS llm_scene_enum")
    op.execute("DROP TYPE IF EXISTS llm_protocol_family_enum")
