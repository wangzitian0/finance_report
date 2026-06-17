"""llm config per-user scoping: nullable user_id on provider/binding tables (EPIC-023 PR4)

Makes LLM model selection per-user (AC23.4): each user can own provider
instances and scene bindings. ``user_id`` is nullable and additive — ``NULL``
rows remain the deployment default (preserving the AC23.3 deployment-scoped
behaviour), non-null rows belong to that user. Config resolves user rows ->
deployment-default rows -> env fallback.

The single ``scene``-unique constraint becomes two partial unique indexes so the
"one binding per scene" invariant holds *within each scope*:

- ``uq_llm_scene_bindings_user_scene``: one binding per ``(user_id, scene)`` for
  user-owned rows (``user_id IS NOT NULL``).
- ``uq_llm_scene_bindings_default_scene``: one binding per ``scene`` for the
  deployment default (``user_id IS NULL``).

Migration risk: medium (additive nullable FK columns + indexes; one unique
constraint swapped for two partial unique indexes). No data backfill — existing
rows keep ``user_id = NULL`` and remain the deployment default, behaviour
unchanged.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0044_llm_config_per_user"
down_revision = "0043_llm_provider_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_providers", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_llm_providers_user_id",
        "llm_providers",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_llm_providers_user_id", "llm_providers", ["user_id"])

    op.add_column("llm_scene_bindings", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_llm_scene_bindings_user_id",
        "llm_scene_bindings",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_llm_scene_bindings_user_id", "llm_scene_bindings", ["user_id"])

    # Replace the single scene-unique constraint with per-scope partial unique indexes.
    op.drop_constraint("uq_llm_scene_bindings_scene", "llm_scene_bindings", type_="unique")
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


def downgrade() -> None:
    op.drop_index("uq_llm_scene_bindings_default_scene", table_name="llm_scene_bindings")
    op.drop_index("uq_llm_scene_bindings_user_scene", table_name="llm_scene_bindings")
    op.create_unique_constraint("uq_llm_scene_bindings_scene", "llm_scene_bindings", ["scene"])
    op.drop_index("ix_llm_scene_bindings_user_id", table_name="llm_scene_bindings")
    op.drop_constraint("fk_llm_scene_bindings_user_id", "llm_scene_bindings", type_="foreignkey")
    op.drop_column("llm_scene_bindings", "user_id")
    op.drop_index("ix_llm_providers_user_id", table_name="llm_providers")
    op.drop_constraint("fk_llm_providers_user_id", "llm_providers", type_="foreignkey")
    op.drop_column("llm_providers", "user_id")
