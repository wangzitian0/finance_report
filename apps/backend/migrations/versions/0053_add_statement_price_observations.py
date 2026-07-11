"""add statement_price_observations — pricing's PriceObserved ingest store (#1642)

The event-fed, id-referenced copy of extraction's statement-extracted unit
prices (boundary ruling 4, #1610): the authoritative document-fact stays in
extraction; pricing keeps its own denormalized row so resolve() treats
statement prices as first-class candidates. Zero FK by design (Decision B,
#1416 — ids carried as provenance, no shared transaction); the UNIQUE
constraint on source_observation_id is the idempotency backstop for
at-least-once outbox delivery.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0053_statement_price_obs"
down_revision = "0052_signed_positions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "statement_price_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_kind", sa.String(length=20), nullable=False),
        sa.Column("subject_key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.DECIMAL(precision=18, scale=6), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_observation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_observation_id",
            name="uq_statement_price_observations_source_id",
        ),
        sa.CheckConstraint("value > 0", name="ck_statement_price_observations_value_positive"),
    )
    op.create_index(
        "idx_statement_price_observations_lookup",
        "statement_price_observations",
        ["subject_kind", "subject_key", "as_of"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_statement_price_observations_lookup",
        table_name="statement_price_observations",
    )
    op.drop_table("statement_price_observations")
