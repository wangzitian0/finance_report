"""Add Layer 1 and Layer 2 tables for 4-layer architecture.

Revision ID: 0008_add_layer1_layer2_tables
Revises: 0007_normalize_all_enums
Create Date: 2026-01-23

This migration adds the foundational tables for the 4-layer architecture:
- Layer 1: uploaded_documents (raw file metadata)
- Layer 2: atomic_transactions, atomic_positions (deduplicated records)

These tables are backward compatible and do not affect existing functionality.
This is Phase 1 of the migration strategy (no code changes required).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_layer12"
down_revision = "bb0888e6fc7d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    document_type_enum = sa.Enum(
        "bank_statement",
        "brokerage_statement",
        "esop_grant",
        "property_appraisal",
        name="document_type_enum",
    )
    document_status_enum = sa.Enum(
        "uploaded",
        "processing",
        "completed",
        "failed",
        name="document_status_enum",
    )
    transaction_direction_enum = sa.Enum(
        "IN",
        "OUT",
        name="transaction_direction_enum",
    )

    op.create_table(
        "uploaded_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "file_path",
            sa.String(length=500),
            nullable=False,
            comment="MinIO object key",
        ),
        sa.Column(
            "file_hash",
            sa.String(length=64),
            nullable=False,
            comment="SHA256 for deduplication",
        ),
        sa.Column(
            "original_filename",
            sa.String(length=255),
            nullable=False,
            comment="User-provided filename",
        ),
        sa.Column(
            "document_type",
            document_type_enum,
            nullable=False,
            comment="Document classification",
        ),
        sa.Column(
            "status",
            document_status_enum,
            nullable=False,
            server_default="uploaded",
            comment="Processing status",
        ),
        sa.Column(
            "extraction_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="AI extraction logs, confidence scores",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "file_hash", name="uq_uploaded_documents_user_file_hash"),
    )

    op.create_table(
        "atomic_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("txn_date", sa.Date(), nullable=False),
        sa.Column(
            "amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            comment="Absolute value",
        ),
        sa.Column("direction", transaction_direction_enum, nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            comment="ISO currency code",
        ),
        sa.Column(
            "dedup_hash",
            sa.String(length=64),
            nullable=False,
            comment="SHA256(user_id|date|amount|dir|desc|ref)",
        ),
        sa.Column(
            "source_documents",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment='[{"doc_id": "uuid", "doc_type": "bank_statement"}]',
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "dedup_hash", name="uq_atomic_transactions_user_dedup_hash"),
    )

    op.create_table(
        "atomic_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column(
            "asset_identifier",
            sa.String(length=100),
            nullable=False,
            comment="Ticker (AAPL), ISIN, property address",
        ),
        sa.Column(
            "broker",
            sa.String(length=100),
            nullable=True,
            comment="Moomoo, Ping An Securities, etc.",
        ),
        sa.Column(
            "quantity",
            sa.Numeric(precision=18, scale=6),
            nullable=False,
            comment="Shares, units",
        ),
        sa.Column(
            "market_value",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            comment="Fair value in asset's currency",
        ),
        sa.Column(
            "currency",
            sa.String(length=3),
            nullable=False,
            comment="Asset currency",
        ),
        sa.Column(
            "dedup_hash",
            sa.String(length=64),
            nullable=False,
            comment="SHA256(user_id|date|asset|broker)",
        ),
        sa.Column(
            "source_documents",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment='[{"doc_id": "uuid", "doc_type": "brokerage_statement"}]',
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "dedup_hash", name="uq_atomic_positions_user_dedup_hash"),
    )

    op.create_index(
        "idx_atomic_txn_dedup",
        "atomic_transactions",
        ["user_id", "dedup_hash"],
        unique=False,
    )
    op.create_index(
        "idx_atomic_pos_dedup",
        "atomic_positions",
        ["user_id", "dedup_hash"],
        unique=False,
    )
    op.create_index(
        "idx_atomic_txn_date",
        "atomic_transactions",
        ["user_id", "txn_date"],
        unique=False,
    )
    op.create_index(
        "idx_atomic_pos_date",
        "atomic_positions",
        ["user_id", "snapshot_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_atomic_pos_date", table_name="atomic_positions")
    op.drop_index("idx_atomic_txn_date", table_name="atomic_transactions")
    op.drop_index("idx_atomic_pos_dedup", table_name="atomic_positions")
    op.drop_index("idx_atomic_txn_dedup", table_name="atomic_transactions")

    op.drop_table("atomic_positions")
    op.drop_table("atomic_transactions")
    op.drop_table("uploaded_documents")

    op.execute("DROP TYPE IF EXISTS transaction_direction_enum")
    op.execute("DROP TYPE IF EXISTS document_status_enum")
    op.execute("DROP TYPE IF EXISTS document_type_enum")
