"""add evidence lineage graph"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0025_add_evidence_lineage"
down_revision = "0024_add_workflow_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("evidence_nodes",
        sa.Column("node_kind", sa.String(length=50), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "properties",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "node_kind", "entity_type", "entity_id", name="uq_evidence_nodes_user_entity"),
    )
    op.create_index("idx_evidence_nodes_user_entity", "evidence_nodes", ["user_id", "entity_type", "entity_id"])
    op.create_index("idx_evidence_nodes_user_kind", "evidence_nodes", ["user_id", "node_kind"])

    op.create_table("evidence_edges",
        sa.Column("from_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation", sa.String(length=100), nullable=False),
        sa.Column(
            "properties",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["from_node_id"], ["evidence_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_node_id"], ["evidence_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "from_node_id", "to_node_id", "relation", name="uq_evidence_edges_user_relation"),
    )
    op.create_index("idx_evidence_edges_user_from", "evidence_edges", ["user_id", "from_node_id"])
    op.create_index("idx_evidence_edges_user_to", "evidence_edges", ["user_id", "to_node_id"])
    op.create_index(
        "idx_evidence_edges_user_relation_from",
        "evidence_edges",
        ["user_id", "relation", "from_node_id"],
    )
    op.create_index(
        "idx_evidence_edges_user_relation_to",
        "evidence_edges",
        ["user_id", "relation", "to_node_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_evidence_edges_user_relation_to", table_name="evidence_edges")
    op.drop_index("idx_evidence_edges_user_relation_from", table_name="evidence_edges")
    op.drop_index("idx_evidence_edges_user_to", table_name="evidence_edges")
    op.drop_index("idx_evidence_edges_user_from", table_name="evidence_edges")
    op.drop_table("evidence_edges")
    op.drop_index("idx_evidence_nodes_user_kind", table_name="evidence_nodes")
    op.drop_index("idx_evidence_nodes_user_entity", table_name="evidence_nodes")
    op.drop_table("evidence_nodes")
