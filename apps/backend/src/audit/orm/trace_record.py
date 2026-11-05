"""Normalized SQL representation of the TraceRecord wire contract."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.audit.base.trace import (
    TraceCausality,
    TraceRecordType,
    TraceResult,
    TraceScopeKind,
    TraceTargetClass,
)
from src.database import Base


class TraceRecordRow(Base):
    __tablename__ = "trace_records"
    __table_args__ = (
        sa.UniqueConstraint(
            "scope_kind",
            "scope_id",
            "id",
            name="uq_trace_records_scope_id",
        ),
        sa.UniqueConstraint(
            "content_digest",
            name="uq_trace_records_content_digest",
        ),
        sa.UniqueConstraint(
            "supersedes_id",
            name="uq_trace_records_supersedes_once",
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
        sa.Index(
            "ix_trace_records_scope",
            "scope_kind",
            "scope_id",
        ),
        sa.Index(
            "ix_trace_records_lineage",
            "scope_kind",
            "scope_id",
            "target_kind",
            "target_id",
            "assertion_kind",
            "assertion_id",
        ),
        sa.Index(
            "ix_trace_records_supersedes_lookup",
            "scope_kind",
            "scope_id",
            "supersedes_id",
            postgresql_where=sa.text("supersedes_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    scope_kind: Mapped[TraceScopeKind] = mapped_column(sa.Enum(TraceScopeKind, name="trace_scope_kind"), nullable=False)
    scope_id: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    schema_version: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    record_type: Mapped[TraceRecordType] = mapped_column(
        sa.Enum(TraceRecordType, name="trace_record_type"), nullable=False
    )
    target_kind: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    target_id: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    target_version: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    target_class: Mapped[TraceTargetClass] = mapped_column(
        sa.Enum(TraceTargetClass, name="trace_target_class"), nullable=False
    )
    assertion_kind: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    assertion_id: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    assertion_version: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    authority_package: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    authority_tier: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    proof_kind: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    provenance: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    execution_stage: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    assertion_owner_digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    producer_version: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    result: Mapped[TraceResult] = mapped_column(sa.Enum(TraceResult, name="trace_result"), nullable=False)
    execution_id: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    causality: Mapped[TraceCausality | None] = mapped_column(
        sa.Enum(TraceCausality, name="trace_causality"), nullable=True
    )
    evidence_manifest_digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    parent_count: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    score: Mapped[Decimal | None] = mapped_column(sa.Numeric(20, 18), nullable=True)
    reason_code: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    content_digest: Mapped[str] = mapped_column(sa.String(64), nullable=False)


class TraceRecordParentRow(Base):
    __tablename__ = "trace_record_parents"
    __table_args__ = (
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
        sa.Index(
            "ix_trace_record_parents_parent_lookup",
            "scope_kind",
            "scope_id",
            "parent_id",
        ),
    )

    scope_kind: Mapped[TraceScopeKind] = mapped_column(
        sa.Enum(
            TraceScopeKind,
            name="trace_scope_kind",
            create_type=False,
        ),
        primary_key=True,
    )
    scope_id: Mapped[str] = mapped_column(sa.String(200), primary_key=True)
    record_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    parent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)


def _reject_trace_mutation(_mapper, _connection, target) -> None:
    identity = getattr(target, "id", getattr(target, "record_id", "unknown"))
    raise ValueError(f"TraceRecord rows are append-only; mutation of {identity} is forbidden")


sa.event.listen(TraceRecordRow, "before_update", _reject_trace_mutation)
sa.event.listen(TraceRecordRow, "before_delete", _reject_trace_mutation)
sa.event.listen(TraceRecordParentRow, "before_update", _reject_trace_mutation)
sa.event.listen(TraceRecordParentRow, "before_delete", _reject_trace_mutation)

_CREATE_APPEND_ONLY_FUNCTION = sa.DDL(
    """
    CREATE OR REPLACE FUNCTION reject_trace_record_mutation() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'TraceRecord assurance rows are append-only';
    END;
    $$ LANGUAGE plpgsql
    """
).execute_if(dialect="postgresql")
_CREATE_RECORD_TRIGGER = sa.DDL(
    """
    CREATE TRIGGER trace_records_append_only
    BEFORE UPDATE OR DELETE ON trace_records
    FOR EACH ROW EXECUTE FUNCTION reject_trace_record_mutation()
    """
).execute_if(dialect="postgresql")
_CREATE_PARENT_TRIGGER = sa.DDL(
    """
    CREATE TRIGGER trace_record_parents_append_only
    BEFORE UPDATE OR DELETE ON trace_record_parents
    FOR EACH ROW EXECUTE FUNCTION reject_trace_record_mutation()
    """
).execute_if(dialect="postgresql")
_DROP_APPEND_ONLY_FUNCTION = sa.DDL("DROP FUNCTION IF EXISTS reject_trace_record_mutation()").execute_if(
    dialect="postgresql"
)
_CREATE_LINK_VALIDATION_FUNCTION = sa.DDL(
    """
    CREATE OR REPLACE FUNCTION validate_trace_record_links() RETURNS trigger AS $$
    DECLARE
        child trace_records%%ROWTYPE;
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
).execute_if(dialect="postgresql")
_CREATE_INSERT_VALIDATION_FUNCTION = sa.DDL(
    """
    CREATE OR REPLACE FUNCTION validate_trace_record_insert() RETURNS trigger AS $$
    DECLARE
        previous trace_records%%ROWTYPE;
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
).execute_if(dialect="postgresql")
_CREATE_INSERT_VALIDATION_TRIGGER = sa.DDL(
    """
    CREATE TRIGGER trace_records_validate_insert
    BEFORE INSERT ON trace_records
    FOR EACH ROW EXECUTE FUNCTION validate_trace_record_insert()
    """
).execute_if(dialect="postgresql")
_CREATE_RECORD_LINK_VALIDATION_TRIGGER = sa.DDL(
    """
    CREATE CONSTRAINT TRIGGER trace_records_validate_links
    AFTER INSERT ON trace_records
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION validate_trace_record_links()
    """
).execute_if(dialect="postgresql")
_CREATE_PARENT_LINK_VALIDATION_TRIGGER = sa.DDL(
    """
    CREATE CONSTRAINT TRIGGER trace_record_parents_validate_links
    AFTER INSERT ON trace_record_parents
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION validate_trace_record_links()
    """
).execute_if(dialect="postgresql")
_DROP_LINK_VALIDATION_FUNCTION = sa.DDL("DROP FUNCTION IF EXISTS validate_trace_record_links()").execute_if(
    dialect="postgresql"
)
_DROP_INSERT_VALIDATION_FUNCTION = sa.DDL("DROP FUNCTION IF EXISTS validate_trace_record_insert()").execute_if(
    dialect="postgresql"
)

sa.event.listen(TraceRecordRow.__table__, "after_create", _CREATE_APPEND_ONLY_FUNCTION)
sa.event.listen(TraceRecordRow.__table__, "after_create", _CREATE_RECORD_TRIGGER)
sa.event.listen(TraceRecordParentRow.__table__, "after_create", _CREATE_PARENT_TRIGGER)
sa.event.listen(
    TraceRecordParentRow.__table__,
    "after_create",
    _CREATE_LINK_VALIDATION_FUNCTION,
)
sa.event.listen(
    TraceRecordParentRow.__table__,
    "after_create",
    _CREATE_INSERT_VALIDATION_FUNCTION,
)
sa.event.listen(
    TraceRecordParentRow.__table__,
    "after_create",
    _CREATE_INSERT_VALIDATION_TRIGGER,
)
sa.event.listen(
    TraceRecordParentRow.__table__,
    "after_create",
    _CREATE_RECORD_LINK_VALIDATION_TRIGGER,
)
sa.event.listen(
    TraceRecordParentRow.__table__,
    "after_create",
    _CREATE_PARENT_LINK_VALIDATION_TRIGGER,
)
sa.event.listen(TraceRecordRow.__table__, "after_drop", _DROP_APPEND_ONLY_FUNCTION)
sa.event.listen(TraceRecordRow.__table__, "after_drop", _DROP_LINK_VALIDATION_FUNCTION)
sa.event.listen(TraceRecordRow.__table__, "after_drop", _DROP_INSERT_VALIDATION_FUNCTION)
