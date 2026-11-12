"""Add statement_runs: one row per extraction or classification attempt (#2994).

The partial unique index allows at most one requested or running run per statement. The upgrade
backfills one running extract run for each statement that is parsing now: those jobs started before
this release and have no run. The reaper fails them when no heartbeat arrives.

Revision ID: 0074_statement_runs
Revises: 0073_stmt_gin_trace_trig_perf
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0074_statement_runs"
down_revision: str | None = "0073_stmt_gin_trace_trig_perf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

run_kind = postgresql.ENUM("extract", "classify", name="statement_run_kind_enum", create_type=False)
run_state = postgresql.ENUM(
    "requested", "running", "succeeded", "failed", "cancelled", name="statement_run_state_enum", create_type=False
)
run_actor_kind = postgresql.ENUM("user", "ai", "system", name="statement_run_actor_kind_enum", create_type=False)
run_trigger = postgresql.ENUM(
    "upload", "rerun", "auto_classify", "auto_retry", "backfill", name="statement_run_trigger_enum", create_type=False
)
ENUM_TYPES = (run_kind, run_state, run_actor_kind, run_trigger)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in ENUM_TYPES:
        enum_type.create(bind, checkfirst=True)
    op.create_table(
        "statement_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("statement_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, comment="1-based attempt number within the statement"),
        sa.Column("kind", run_kind, nullable=False),
        sa.Column("state", run_state, nullable=False),
        sa.Column(
            "actor_kind",
            run_actor_kind,
            nullable=False,
            comment="Set from the authenticated principal, never from the request body",
        ),
        sa.Column("trigger", run_trigger, nullable=False),
        sa.Column("parent_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("hints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("prompt_template_version", sa.String(length=64), nullable=True),
        sa.Column("prompt_digest", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("extraction_result_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result_summary", postgresql.JSONB(astext_type=sa.Text(), none_as_null=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True, comment="Redacted by the caller"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["user_id", "statement_id"],
            ["statement_summaries.user_id", "statement_summaries.id"],
            name="fk_statement_runs_statement_owner",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "statement_id", "extraction_result_id"],
            [
                "statement_extraction_results.user_id",
                "statement_extraction_results.statement_id",
                "statement_extraction_results.id",
            ],
            name="fk_statement_runs_result_owner",
        ),
        sa.ForeignKeyConstraint(
            ["parent_run_id"], ["statement_runs.id"], name="fk_statement_runs_parent", ondelete="SET NULL"
        ),
        sa.UniqueConstraint("statement_id", "seq", name="uq_statement_runs_statement_seq"),
    )
    op.create_index("ix_statement_runs_user_id", "statement_runs", ["user_id"])
    op.create_index(
        "uq_statement_runs_one_active",
        "statement_runs",
        ["statement_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('requested', 'running')"),
    )
    op.execute(
        """
        INSERT INTO statement_runs (
            id, user_id, statement_id, seq, kind, state, actor_kind, trigger, hints,
            requested_at, started_at, heartbeat_at
        )
        SELECT
            gen_random_uuid(), s.user_id, s.id, 1,
            CAST('extract' AS statement_run_kind_enum),
            CAST('running' AS statement_run_state_enum),
            CAST('system' AS statement_run_actor_kind_enum),
            CAST('upload' AS statement_run_trigger_enum),
            CAST('{}' AS jsonb),
            s.created_at, s.updated_at, s.updated_at
        FROM statement_summaries AS s
        WHERE s.status = 'parsing'
        """
    )


def downgrade() -> None:
    op.drop_index("uq_statement_runs_one_active", table_name="statement_runs")
    op.drop_index("ix_statement_runs_user_id", table_name="statement_runs")
    op.drop_table("statement_runs")
    bind = op.get_bind()
    for enum_type in reversed(ENUM_TYPES):
        enum_type.drop(bind, checkfirst=True)
