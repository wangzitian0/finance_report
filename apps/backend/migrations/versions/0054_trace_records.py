"""Add the append-only TraceRecord assurance store (#1906)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0054_trace_records"
down_revision = "0053_statement_price_obs"
branch_labels = None
depends_on = None

trace_scope_kind = postgresql.ENUM("TENANT", "REPOSITORY", "ENVIRONMENT", name="trace_scope_kind", create_type=False)
trace_record_type = postgresql.ENUM("OBSERVATION", "DECISION", name="trace_record_type", create_type=False)
trace_target_class = postgresql.ENUM("GENERAL", "FINANCIAL", name="trace_target_class", create_type=False)
trace_causality = postgresql.ENUM("DIRECT", "MANIFEST", name="trace_causality", create_type=False)
trace_result = postgresql.ENUM(
    "PASS",
    "FAIL",
    "ERROR",
    "SKIPPED",
    "UNPROVEN",
    "AUTHORITATIVE",
    "REVIEW",
    "REJECTED",
    name="trace_result",
    create_type=False,
)


def upgrade() -> None:
    trace_scope_kind.create(op.get_bind(), checkfirst=True)
    trace_record_type.create(op.get_bind(), checkfirst=True)
    trace_target_class.create(op.get_bind(), checkfirst=True)
    trace_causality.create(op.get_bind(), checkfirst=True)
    trace_result.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "trace_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope_kind", trace_scope_kind, nullable=False),
        sa.Column("scope_id", sa.String(length=200), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("record_type", trace_record_type, nullable=False),
        sa.Column("target_kind", sa.String(length=200), nullable=False),
        sa.Column("target_id", sa.String(length=200), nullable=False),
        sa.Column("target_version", sa.String(length=200), nullable=False),
        sa.Column("target_class", trace_target_class, nullable=False),
        sa.Column("assertion_kind", sa.String(length=200), nullable=False),
        sa.Column("assertion_id", sa.String(length=200), nullable=False),
        sa.Column("assertion_version", sa.String(length=200), nullable=False),
        sa.Column("authority_package", sa.String(length=100), nullable=False),
        sa.Column("authority_tier", sa.String(length=20), nullable=False),
        sa.Column("proof_kind", sa.String(length=20), nullable=False),
        sa.Column("provenance", sa.String(length=200), nullable=False),
        sa.Column("execution_stage", sa.String(length=100), nullable=False),
        sa.Column("assertion_owner_digest", sa.String(length=64), nullable=False),
        sa.Column("producer_version", sa.String(length=200), nullable=False),
        sa.Column("result", trace_result, nullable=False),
        sa.Column("execution_id", sa.String(length=200), nullable=False),
        sa.Column("causality", trace_causality, nullable=True),
        sa.Column("evidence_manifest_digest", sa.String(length=64), nullable=False),
        sa.Column("parent_count", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("score", sa.Numeric(precision=20, scale=18), nullable=True),
        sa.Column("reason_code", sa.String(length=200), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)",
            name="ck_trace_records_score_ratio",
        ),
        sa.CheckConstraint(
            "schema_version = '1'",
            name="ck_trace_records_schema_version",
        ),
        sa.CheckConstraint(
            "(record_type = 'OBSERVATION' AND parent_count = 0) OR (record_type = 'DECISION' AND parent_count > 0)",
            name="ck_trace_records_parent_count",
        ),
        sa.CheckConstraint(
            "(record_type = 'OBSERVATION' AND result IN "
            "('PASS', 'FAIL', 'ERROR', 'SKIPPED', 'UNPROVEN') "
            "AND causality IS NULL) OR "
            "(record_type = 'DECISION' AND result IN "
            "('AUTHORITATIVE', 'REVIEW', 'REJECTED') "
            "AND causality IS NOT NULL)",
            name="ck_trace_records_type_result_causality",
        ),
        sa.ForeignKeyConstraint(
            ["scope_kind", "scope_id", "supersedes_id"],
            [
                "trace_records.scope_kind",
                "trace_records.scope_id",
                "trace_records.id",
            ],
            name="fk_trace_supersedes_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_digest", name="uq_trace_records_content_digest"),
        sa.UniqueConstraint("supersedes_id", name="uq_trace_records_supersedes_once"),
        sa.UniqueConstraint("scope_kind", "scope_id", "id", name="uq_trace_records_scope_id"),
    )
    op.create_index(
        "ix_trace_records_scope",
        "trace_records",
        ["scope_kind", "scope_id"],
    )
    op.create_index(
        "ix_trace_records_lineage",
        "trace_records",
        [
            "scope_kind",
            "scope_id",
            "target_kind",
            "target_id",
            "assertion_kind",
            "assertion_id",
        ],
    )
    op.create_table(
        "trace_record_parents",
        sa.Column("scope_kind", trace_scope_kind, nullable=False),
        sa.Column("scope_id", sa.String(length=200), nullable=False),
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["scope_kind", "scope_id", "record_id"],
            [
                "trace_records.scope_kind",
                "trace_records.scope_id",
                "trace_records.id",
            ],
            name="fk_trace_parent_child_scope",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scope_kind", "scope_id", "parent_id"],
            [
                "trace_records.scope_kind",
                "trace_records.scope_id",
                "trace_records.id",
            ],
            name="fk_trace_parent_parent_scope",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("scope_kind", "scope_id", "record_id", "parent_id"),
    )
    _create_integrity_functions_and_triggers()


def _create_integrity_functions_and_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_trace_record_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'TraceRecord assurance rows are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_trace_record_insert() RETURNS trigger AS $$
        DECLARE
            previous trace_records%ROWTYPE;
        BEGIN
            PERFORM pg_advisory_xact_lock(hashtextextended(concat_ws(E'\\x1f',
                NEW.scope_kind::text, NEW.scope_id, NEW.target_kind, NEW.target_id,
                NEW.assertion_kind, NEW.assertion_id), 0));

            IF NEW.supersedes_id IS NOT NULL THEN
                SELECT * INTO previous FROM trace_records
                 WHERE scope_kind = NEW.scope_kind
                   AND scope_id = NEW.scope_id
                   AND id = NEW.supersedes_id;
                IF FOUND AND (
                    previous.record_type <> NEW.record_type
                    OR previous.target_kind <> NEW.target_kind
                    OR previous.target_id <> NEW.target_id
                    OR previous.target_class <> NEW.target_class
                    OR previous.assertion_kind <> NEW.assertion_kind
                    OR previous.assertion_id <> NEW.assertion_id
                ) THEN
                    RAISE EXCEPTION 'TraceRecord supersession changed stable lineage';
                END IF;
                IF FOUND AND EXISTS (
                    SELECT 1 FROM trace_records superseder
                     WHERE superseder.scope_kind = NEW.scope_kind
                       AND superseder.scope_id = NEW.scope_id
                       AND superseder.supersedes_id = previous.id
                ) THEN
                    RAISE EXCEPTION 'TraceRecord can only supersede a current head';
                END IF;
            ELSIF NEW.record_type = 'DECISION' AND EXISTS (
                SELECT 1 FROM trace_records current_record
                 WHERE current_record.scope_kind = NEW.scope_kind
                   AND current_record.scope_id = NEW.scope_id
                   AND current_record.record_type = 'DECISION'
                   AND current_record.target_kind = NEW.target_kind
                   AND current_record.target_id = NEW.target_id
                   AND current_record.assertion_kind = NEW.assertion_kind
                   AND current_record.assertion_id = NEW.assertion_id
                   AND NOT EXISTS (
                       SELECT 1 FROM trace_records superseder
                        WHERE superseder.scope_kind = NEW.scope_kind
                          AND superseder.scope_id = NEW.scope_id
                          AND superseder.supersedes_id = current_record.id
                   )
            ) THEN
                RAISE EXCEPTION 'TraceRecord decision lineage already has a current head';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE FUNCTION validate_trace_record_links() RETURNS trigger AS $$
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
    op.execute(
        """
        CREATE TRIGGER trace_records_validate_insert
            BEFORE INSERT ON trace_records
            FOR EACH ROW EXECUTE FUNCTION validate_trace_record_insert()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trace_records_append_only
            BEFORE UPDATE OR DELETE ON trace_records
            FOR EACH ROW EXECUTE FUNCTION reject_trace_record_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trace_record_parents_append_only
            BEFORE UPDATE OR DELETE ON trace_record_parents
            FOR EACH ROW EXECUTE FUNCTION reject_trace_record_mutation()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trace_records_validate_links
            AFTER INSERT ON trace_records
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION validate_trace_record_links()
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trace_record_parents_validate_links
            AFTER INSERT ON trace_record_parents
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION validate_trace_record_links()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER trace_record_parents_validate_links ON trace_record_parents")
    op.execute("DROP TRIGGER trace_records_validate_links ON trace_records")
    op.execute("DROP TRIGGER trace_record_parents_append_only ON trace_record_parents")
    op.execute("DROP TRIGGER trace_records_append_only ON trace_records")
    op.execute("DROP TRIGGER trace_records_validate_insert ON trace_records")
    op.execute("DROP FUNCTION validate_trace_record_links")
    op.execute("DROP FUNCTION validate_trace_record_insert")
    op.execute("DROP FUNCTION reject_trace_record_mutation")
    op.drop_table("trace_record_parents")
    op.drop_index("ix_trace_records_lineage", table_name="trace_records")
    op.drop_index("ix_trace_records_scope", table_name="trace_records")
    op.drop_table("trace_records")
    trace_result.drop(op.get_bind(), checkfirst=True)
    trace_causality.drop(op.get_bind(), checkfirst=True)
    trace_target_class.drop(op.get_bind(), checkfirst=True)
    trace_record_type.drop(op.get_bind(), checkfirst=True)
    trace_scope_kind.drop(op.get_bind(), checkfirst=True)
