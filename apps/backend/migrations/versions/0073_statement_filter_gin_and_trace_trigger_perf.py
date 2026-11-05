"""Add source_documents GIN index, autovacuum analyze tuning, and trace trigger fast-path (#2630, #2629, #2627).

Revision ID: 0073_stmt_gin_trace_trig_perf
Revises: 0072_users_email_partial_idx
Create Date: 2026-11-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0073_stmt_gin_trace_trig_perf"
down_revision: str | None = "0072_users_email_partial_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTOVACUUM_TUNED_TABLES: tuple[str, ...] = (
    "journal_entries",
    "journal_lines",
    "atomic_transactions",
    "reconciliation_matches",
    "trace_records",
    "statement_summaries",
)


def upgrade() -> None:
    op.create_index(
        "ix_atomic_transactions_source_documents_gin",
        "atomic_transactions",
        ["source_documents"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"source_documents": "jsonb_path_ops"},
    )
    op.create_index(
        "ix_trace_records_supersedes_lookup",
        "trace_records",
        ["scope_kind", "scope_id", "supersedes_id"],
        unique=False,
        postgresql_where=sa.text("supersedes_id IS NOT NULL"),
    )
    op.create_index(
        "ix_trace_record_parents_parent_lookup",
        "trace_record_parents",
        ["scope_kind", "scope_id", "parent_id"],
        unique=False,
    )

    if op.get_bind().dialect.name == "postgresql":
        for table in AUTOVACUUM_TUNED_TABLES:
            op.execute(
                f"ALTER TABLE {table} SET (autovacuum_analyze_scale_factor = 0.02, autovacuum_analyze_threshold = 50)"
            )
        op.execute(
            """
            CREATE OR REPLACE FUNCTION validate_trace_record_links() RETURNS trigger AS $$
            DECLARE
                child trace_records%ROWTYPE;
                child_xmin xid;
                child_record_type trace_record_type;
                child_id uuid;
                child_scope_kind trace_scope_kind;
                child_scope_id text;
                actual_parent_count integer;
                has_unsatisfied_parent boolean;
                has_superseded_parent boolean;
                has_decision_parent boolean;
                has_cross_target_parent boolean;
                has_llm_parent boolean;
                has_code_guard_parent boolean;
            BEGIN
                IF TG_TABLE_NAME = 'trace_records' THEN
                    child := NEW;
                    IF child.record_type = 'OBSERVATION' THEN
                        IF child.parent_count <> 0 THEN
                            RAISE EXCEPTION 'TraceRecord parent link count does not match sealed parent_count';
                        END IF;
                        RETURN NULL;
                    END IF;
                ELSE
                    SELECT xmin, record_type INTO child_xmin, child_record_type FROM trace_records
                     WHERE scope_kind = NEW.scope_kind
                       AND scope_id = NEW.scope_id
                       AND id = NEW.record_id;
                    IF child_record_type = 'OBSERVATION' THEN
                        RAISE EXCEPTION 'OBSERVATION cannot have parent links';
                    END IF;
                    IF child_xmin = pg_current_xact_id()::xid THEN
                        PERFORM 1 FROM trace_records parent
                         WHERE parent.scope_kind = NEW.scope_kind
                           AND parent.scope_id = NEW.scope_id
                           AND parent.id = NEW.parent_id;
                        IF NOT FOUND THEN
                            RAISE EXCEPTION 'TraceRecord parent link references missing parent';
                        END IF;
                        RETURN NULL;
                    END IF;
                    SELECT * INTO child FROM trace_records
                     WHERE scope_kind = NEW.scope_kind
                       AND scope_id = NEW.scope_id
                       AND id = NEW.record_id;
                END IF;

                child_id := child.id;
                child_scope_kind := child.scope_kind;
                child_scope_id := child.scope_id;

                SELECT
                    count(*),
                    coalesce(bool_or(
                        (child.result = 'REJECTED' AND parent.result NOT IN ('PASS', 'AUTHORITATIVE', 'FAIL'))
                        OR
                        (child.result <> 'REJECTED' AND parent.result NOT IN ('PASS', 'AUTHORITATIVE'))
                    ), false),
                    coalesce(bool_or(
                        EXISTS (
                            SELECT 1 FROM trace_records superseder
                             WHERE superseder.scope_kind = link.scope_kind
                               AND superseder.scope_id = link.scope_id
                               AND superseder.supersedes_id = link.parent_id
                        )
                    ), false),
                    coalesce(bool_or(parent.record_type = 'DECISION'), false),
                    coalesce(bool_or(
                        parent.target_kind <> child.target_kind
                        OR parent.target_id <> child.target_id
                        OR parent.target_version <> child.target_version
                        OR parent.execution_id <> child.execution_id
                    ), false),
                    coalesce(bool_or(parent.authority_tier IN ('LLM-LED', 'LLM-ONLY')), false),
                    coalesce(bool_or(
                        parent.record_type = 'DECISION'
                        AND parent.target_kind = child.target_kind
                        AND parent.target_id = child.target_id
                        AND parent.target_version = child.target_version
                        AND parent.target_class = 'FINANCIAL'
                        AND parent.authority_tier = 'CODE-ONLY'
                        AND parent.assertion_kind IN ('invariant', 'promotion')
                        AND parent.result = 'AUTHORITATIVE'
                    ), false)
                INTO
                    actual_parent_count,
                    has_unsatisfied_parent,
                    has_superseded_parent,
                    has_decision_parent,
                    has_cross_target_parent,
                    has_llm_parent,
                    has_code_guard_parent
                FROM trace_record_parents link
                JOIN trace_records parent ON
                     parent.scope_kind = link.scope_kind
                 AND parent.scope_id = link.scope_id
                 AND parent.id = link.parent_id
                WHERE link.scope_kind = child_scope_kind
                  AND link.scope_id = child_scope_id
                  AND link.record_id = child_id;

                IF child.record_type = 'DECISION' AND actual_parent_count = 0 THEN
                    RAISE EXCEPTION 'DECISION requires at least one parent link';
                END IF;
                IF child.parent_count <> actual_parent_count THEN
                    RAISE EXCEPTION 'TraceRecord parent link count does not match sealed parent_count';
                END IF;
                IF child.record_type = 'DECISION' AND has_unsatisfied_parent THEN
                    RAISE EXCEPTION 'DECISION has an unsatisfied parent result';
                END IF;
                IF child.record_type = 'DECISION' AND has_superseded_parent THEN
                    RAISE EXCEPTION 'DECISION requires current parent heads';
                END IF;
                IF child.record_type = 'DECISION' AND has_decision_parent AND EXISTS (
                    WITH RECURSIVE ancestry(parent_id) AS (
                        SELECT link.parent_id
                          FROM trace_record_parents link
                         WHERE link.scope_kind = child_scope_kind
                           AND link.scope_id = child_scope_id
                           AND link.record_id = child_id
                        UNION
                        SELECT link.parent_id
                          FROM ancestry
                          JOIN trace_record_parents link ON
                               link.scope_kind = child_scope_kind
                           AND link.scope_id = child_scope_id
                           AND link.record_id = ancestry.parent_id
                    )
                    SELECT 1 FROM ancestry WHERE parent_id = child_id
                ) THEN
                    RAISE EXCEPTION 'TraceRecord parent graph must be acyclic';
                END IF;
                IF child.record_type = 'DECISION' AND child.causality = 'DIRECT' AND has_cross_target_parent THEN
                    RAISE EXCEPTION 'DIRECT decision has cross-target or cross-execution parent';
                END IF;
                IF child.target_class = 'FINANCIAL'
                   AND child.result = 'AUTHORITATIVE'
                   AND has_llm_parent
                   AND (child.authority_tier <> 'CODE-ONLY' OR NOT has_code_guard_parent) THEN
                    RAISE EXCEPTION 'financial LLM authority requires a CODE-ONLY guard';
                END IF;
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION validate_trace_record_links() RETURNS trigger AS $$
            DECLARE
                child trace_records%ROWTYPE;
                child_id uuid;
                child_scope_kind trace_scope_kind;
                child_scope_id text;
            BEGIN
                IF TG_TABLE_NAME = 'trace_records' THEN
                    child := NEW;
                ELSE
                    SELECT * INTO child FROM trace_records
                     WHERE scope_kind = NEW.scope_kind
                       AND scope_id = NEW.scope_id
                       AND id = NEW.record_id;
                END IF;

                child_id := child.id;
                child_scope_kind := child.scope_kind;
                child_scope_id := child.scope_id;

                IF child.record_type = 'OBSERVATION' AND EXISTS (
                    SELECT 1 FROM trace_record_parents
                     WHERE scope_kind = child_scope_kind
                       AND scope_id = child_scope_id
                       AND record_id = child_id
                ) THEN
                    RAISE EXCEPTION 'OBSERVATION cannot have parent links';
                END IF;
                IF child.record_type = 'DECISION' AND NOT EXISTS (
                    SELECT 1 FROM trace_record_parents
                     WHERE scope_kind = child_scope_kind
                       AND scope_id = child_scope_id
                       AND record_id = child_id
                ) THEN
                    RAISE EXCEPTION 'DECISION requires at least one parent link';
                END IF;
                IF child.parent_count <> (
                    SELECT count(*) FROM trace_record_parents
                     WHERE scope_kind = child_scope_kind
                       AND scope_id = child_scope_id
                       AND record_id = child_id
                ) THEN
                    RAISE EXCEPTION 'TraceRecord parent link count does not match sealed parent_count';
                END IF;
                IF child.record_type = 'DECISION' AND EXISTS (
                    SELECT 1
                      FROM trace_record_parents link
                      JOIN trace_records parent ON
                           parent.scope_kind = link.scope_kind
                       AND parent.scope_id = link.scope_id
                       AND parent.id = link.parent_id
                     WHERE link.scope_kind = child_scope_kind
                       AND link.scope_id = child_scope_id
                       AND link.record_id = child_id
                       AND (
                           (child.result = 'REJECTED' AND parent.result NOT IN
                               ('PASS', 'AUTHORITATIVE', 'FAIL'))
                           OR
                           (child.result <> 'REJECTED' AND parent.result NOT IN
                               ('PASS', 'AUTHORITATIVE'))
                       )
                ) THEN
                    RAISE EXCEPTION 'DECISION has an unsatisfied parent result';
                END IF;
                IF child.record_type = 'DECISION' AND EXISTS (
                    SELECT 1
                      FROM trace_record_parents link
                      JOIN trace_records superseder ON
                           superseder.scope_kind = link.scope_kind
                       AND superseder.scope_id = link.scope_id
                       AND superseder.supersedes_id = link.parent_id
                     WHERE link.scope_kind = child_scope_kind
                       AND link.scope_id = child_scope_id
                       AND link.record_id = child_id
                ) THEN
                    RAISE EXCEPTION 'DECISION requires current parent heads';
                END IF;
                IF child.record_type = 'DECISION' AND EXISTS (
                    WITH RECURSIVE ancestry(parent_id) AS (
                        SELECT link.parent_id
                          FROM trace_record_parents link
                         WHERE link.scope_kind = child_scope_kind
                           AND link.scope_id = child_scope_id
                           AND link.record_id = child_id
                        UNION
                        SELECT link.parent_id
                          FROM trace_record_parents link
                          JOIN ancestry ON link.record_id = ancestry.parent_id
                         WHERE link.scope_kind = child_scope_kind
                           AND link.scope_id = child_scope_id
                    )
                    SELECT 1 FROM ancestry WHERE parent_id = child_id
                ) THEN
                    RAISE EXCEPTION 'TraceRecord parent graph must be acyclic';
                END IF;
                IF child.record_type = 'DECISION' AND child.causality = 'DIRECT' AND EXISTS (
                    SELECT 1
                      FROM trace_record_parents link
                      JOIN trace_records parent ON
                           parent.scope_kind = link.scope_kind
                       AND parent.scope_id = link.scope_id
                       AND parent.id = link.parent_id
                     WHERE link.scope_kind = child_scope_kind
                       AND link.scope_id = child_scope_id
                       AND link.record_id = child_id
                       AND (
                           parent.target_kind <> child.target_kind
                           OR parent.target_id <> child.target_id
                           OR parent.target_version <> child.target_version
                           OR parent.execution_id <> child.execution_id
                       )
                ) THEN
                    RAISE EXCEPTION 'DIRECT decision has cross-target or cross-execution parent';
                END IF;
                IF child.target_class = 'FINANCIAL'
                   AND child.result = 'AUTHORITATIVE'
                   AND EXISTS (
                       SELECT 1
                         FROM trace_record_parents link
                         JOIN trace_records parent ON
                              parent.scope_kind = link.scope_kind
                          AND parent.scope_id = link.scope_id
                          AND parent.id = link.parent_id
                        WHERE link.scope_kind = child_scope_kind
                          AND link.scope_id = child_scope_id
                          AND link.record_id = child_id
                          AND parent.authority_tier IN ('LLM-LED', 'LLM-ONLY')
                   )
                   AND (
                       child.authority_tier <> 'CODE-ONLY'
                       OR NOT EXISTS (
                           SELECT 1
                             FROM trace_record_parents guard_link
                             JOIN trace_records guard_parent ON
                                  guard_parent.scope_kind = guard_link.scope_kind
                              AND guard_parent.scope_id = guard_link.scope_id
                              AND guard_parent.id = guard_link.parent_id
                            WHERE guard_link.scope_kind = child_scope_kind
                              AND guard_link.scope_id = child_scope_id
                              AND guard_link.record_id = child_id
                              AND guard_parent.record_type = 'DECISION'
                              AND guard_parent.target_kind = child.target_kind
                              AND guard_parent.target_id = child.target_id
                              AND guard_parent.target_version = child.target_version
                              AND guard_parent.target_class = 'FINANCIAL'
                              AND guard_parent.authority_tier = 'CODE-ONLY'
                              AND guard_parent.assertion_kind IN ('invariant', 'promotion')
                              AND guard_parent.result = 'AUTHORITATIVE'
                       )
                   ) THEN
                    RAISE EXCEPTION 'financial LLM authority requires a CODE-ONLY guard';
                END IF;
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        for table in AUTOVACUUM_TUNED_TABLES:
            op.execute(f"ALTER TABLE {table} RESET (autovacuum_analyze_scale_factor, autovacuum_analyze_threshold)")

    op.drop_index("ix_trace_record_parents_parent_lookup", table_name="trace_record_parents")
    op.drop_index("ix_trace_records_supersedes_lookup", table_name="trace_records")
    op.drop_index("ix_atomic_transactions_source_documents_gin", table_name="atomic_transactions")
