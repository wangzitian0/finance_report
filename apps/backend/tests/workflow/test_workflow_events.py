"""Workflow event contract tests for EPIC-019."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, inspect, select

from src.models import BankStatement, BankStatementStatus, User
from src.models.workflow import (
    WorkflowEvent,
    WorkflowEventFamily,
    WorkflowEventSeverity,
    WorkflowEventStatus,
    WorkflowReportImpact,
    WorkflowSession,
    WorkflowSessionStatus,
)
from src.schemas.workflow import WorkflowEventCreate, WorkflowEventResponse
from src.services.workflow_events import (
    derive_uploaded_statement_event,
    get_workflow_status,
    list_workflow_events,
    sync_workflow_events_for_user,
    update_workflow_event_status,
    upsert_workflow_event,
)

ROOT_DIR = Path(__file__).resolve().parents[4]


def test_AC19_1_1_workflow_event_ssot_registers_manifest_owner() -> None:
    """AC19.1.1: workflow event SSOT is registered as a single manifest owner."""
    manifest_path = ROOT_DIR / "docs" / "ssot" / "MANIFEST.yaml"
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = fh.read()

    assert "workflow_events:" in manifest
    assert "owner: docs/ssot/workflow-events.md" in manifest
    assert "docs/project/EPIC-019.event-driven-upload-to-report-ux.md" in manifest


def test_AC19_3_8_workflow_notification_ssot_documents_frontend_surfaces() -> None:
    """AC19.3.8: workflow notification UI contract is documented in SSOT and EPIC."""
    ssot = (ROOT_DIR / "docs" / "ssot" / "workflow-events.md").read_text(encoding="utf-8")
    epic = (ROOT_DIR / "docs" / "project" / "EPIC-019.event-driven-upload-to-report-ux.md").read_text(encoding="utf-8")

    for phrase in (
        "Header badge",
        "Event inbox",
        "Status feed",
        "Routine automation",
        "WorkflowNotificationCenter",
        "WorkflowStatusFeed",
    ):
        assert phrase in ssot

    assert "AC19.3.1" in epic
    assert "AC19.3.8" in epic


def test_AC19_4_1_upload_first_home_ssot_documents_dashboard_contract() -> None:
    """AC19.4.1: /dashboard is the upload-first home and metrics are secondary."""
    ssot = (ROOT_DIR / "docs" / "ssot" / "workflow-events.md").read_text(encoding="utf-8")
    epic = (ROOT_DIR / "docs" / "project" / "EPIC-019.event-driven-upload-to-report-ux.md").read_text(encoding="utf-8")

    for phrase in (
        "`/dashboard` is the authenticated home for the upload-to-report workflow",
        "UploadToReportHome",
        "Dashboard first viewport",
        "Secondary dashboard metric loading or failure must not hide the workflow",
    ):
        assert phrase in ssot

    assert "AC19.4.1" in epic
    assert "AC19.4.7" in epic
    normalized_epic = " ".join(epic.split())
    assert "secondary analytics below the workflow entry surface" in normalized_epic
    assert "must not block upload, event, or report readiness actions" in normalized_epic


def test_AC19_6_1_workflow_navigation_ssot_documents_primary_and_advanced_groups() -> None:
    """AC19.6.1: workflow navigation IA is documented in SSOT and EPIC."""
    ssot = (ROOT_DIR / "docs" / "ssot" / "workflow-events.md").read_text(encoding="utf-8")
    epic = (ROOT_DIR / "docs" / "project" / "EPIC-019.event-driven-upload-to-report-ux.md").read_text(encoding="utf-8")

    for phrase in (
        "Primary navigation:",
        "Upload Pipeline -> /dashboard",
        "AI -> /chat",
        "Advanced navigation:",
        "Statements -> /statements",
        "AI Settings -> /settings/ai",
        "Navigation attention indicators must use `GET /api/workflow/status` through",
    ):
        assert phrase in ssot

    assert "AC19.6.1" in epic
    assert "AC19.6.7" in epic


def test_AC19_7_1_workflow_session_ssot_separates_chat_sessions() -> None:
    """AC19.7.1: WorkflowSession is the workflow domain object; chat sessions are AI UI state."""
    ssot = (ROOT_DIR / "docs" / "ssot" / "workflow-events.md").read_text(encoding="utf-8")
    epic = (ROOT_DIR / "docs" / "project" / "EPIC-019.event-driven-upload-to-report-ux.md").read_text(encoding="utf-8")
    normalized_ssot = " ".join(ssot.split())

    for phrase in (
        "WorkflowSession is the EPIC-019 product object",
        "event timeline belongs to exactly one workflow session",
        "AI chat sessions are internal `/chat` UI state",
        "not workflow session ownership",
    ):
        assert phrase in normalized_ssot

    assert "AC19.7.1" in epic
    assert "AC19.7.8" in epic


def test_AC19_7_2_workflow_session_model_contract() -> None:
    """AC19.7.2: workflow_sessions and workflow_events.session_id expose the v1 session contract."""
    session_table = WorkflowSession.__table__
    event_table = WorkflowEvent.__table__

    assert session_table.name == "workflow_sessions"
    assert session_table.c.status.type.name == "workflow_session_status_enum"
    assert event_table.c.session_id.foreign_keys
    assert event_table.c.session_id.nullable is True

    unique_constraints = {
        tuple(constraint.columns.keys()): constraint.name
        for constraint in session_table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert unique_constraints[("user_id", "dedupe_key")] == "uq_workflow_sessions_user_dedupe_key"

    check_constraints = {
        constraint.name
        for constraint in session_table.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    assert "ck_workflow_sessions_report_href_internal" in check_constraints

    session_indexes = {index.name: tuple(index.columns.keys()) for index in session_table.indexes}
    event_indexes = {index.name: tuple(index.columns.keys()) for index in event_table.indexes}
    assert session_indexes["idx_workflow_sessions_user_status_last_event"] == (
        "user_id",
        "status",
        "last_event_at",
    )
    assert event_indexes["idx_workflow_events_user_session_occurred"] == ("user_id", "session_id", "occurred_at")
    assert {status.value for status in WorkflowSessionStatus} == {"active", "generated", "archived"}


def test_AC19_1_2_workflow_event_model_contract() -> None:
    """AC19.1.2: workflow_events model exposes lifecycle, dedupe, and read indexes."""
    table = WorkflowEvent.__table__
    assert table.name == "workflow_events"

    enum_names = {
        table.c.family.type.name,
        table.c.severity.type.name,
        table.c.status.type.name,
        table.c.report_impact.type.name,
    }
    assert enum_names == {
        "workflow_event_family_enum",
        "workflow_event_severity_enum",
        "workflow_event_status_enum",
        "workflow_report_impact_enum",
    }

    check_constraints = {
        constraint.name for constraint in table.constraints if constraint.__class__.__name__ == "CheckConstraint"
    }
    assert "ck_workflow_events_action_href_internal" in check_constraints

    unique_constraints = {
        tuple(constraint.columns.keys()): constraint.name
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert unique_constraints[("user_id", "dedupe_key")] == "uq_workflow_events_user_dedupe_key"

    indexes = {index.name: tuple(index.columns.keys()) for index in table.indexes}
    assert indexes["idx_workflow_events_user_status_occurred"] == ("user_id", "status", "occurred_at")
    assert indexes["idx_workflow_events_user_severity_occurred"] == ("user_id", "severity", "occurred_at")
    assert indexes["idx_workflow_events_user_family_occurred"] == ("user_id", "family", "occurred_at")
    assert indexes["idx_workflow_events_user_source"] == ("user_id", "source_type", "source_id")

    mapper_columns = {column.key for column in inspect(WorkflowEvent).columns}
    assert {
        "id",
        "user_id",
        "occurred_at",
        "family",
        "severity",
        "status",
        "title",
        "summary",
        "source_type",
        "source_id",
        "action_href",
        "report_impact",
        "dedupe_key",
        "created_at",
        "updated_at",
    }.issubset(mapper_columns)


def test_AC19_1_3_workflow_event_schema_rejects_external_action_href() -> None:
    """AC19.1.3: workflow event schemas only allow internal relative action links."""
    valid = WorkflowEventCreate(
        family=WorkflowEventFamily.SOURCE_UPLOADED,
        severity=WorkflowEventSeverity.INFO,
        title="Statement uploaded",
        summary="Processing will start shortly.",
        source_type="bank_statement",
        source_id=uuid4(),
        action_href="/statements/123",
        report_impact=WorkflowReportImpact.PROCESSING,
        dedupe_key="bank-statement:123:source.uploaded",
        occurred_at=datetime.now(UTC),
    )
    assert valid.action_href == "/statements/123"
    assert valid.report_impact == WorkflowReportImpact.PROCESSING

    for href in ("https://example.com/review", "//example.com/review", "javascript:alert(1)", "statements/123"):
        with pytest.raises(ValidationError):
            WorkflowEventCreate(
                family=WorkflowEventFamily.SOURCE_UPLOADED,
                severity=WorkflowEventSeverity.INFO,
                title="Statement uploaded",
                summary="Processing will start shortly.",
                source_type="bank_statement",
                source_id=uuid4(),
                action_href=href,
                report_impact=WorkflowReportImpact.PROCESSING,
                dedupe_key=f"bad:{href}",
                occurred_at=datetime.now(UTC),
            )

    with pytest.raises(ValidationError):
        WorkflowEventCreate(
            family=WorkflowEventFamily.REPORT_READY,
            severity=WorkflowEventSeverity.SUCCESS,
            title="Report ready",
            summary="The report can be opened.",
            source_type="report",
            source_id=uuid4(),
            action_href="/reports/current",
            report_impact="published",
            dedupe_key="report:current:report.ready",
            occurred_at=datetime.now(UTC),
        )

    with pytest.raises(ValidationError):
        WorkflowEventResponse.model_validate(
            SimpleNamespace(
                id=uuid4(),
                user_id=uuid4(),
                occurred_at=datetime.now(UTC),
                family=WorkflowEventFamily.REPORT_READY,
                severity=WorkflowEventSeverity.SUCCESS,
                status=WorkflowEventStatus.UNREAD,
                title="Report ready",
                summary="The report can be opened.",
                source_type="report",
                source_id=uuid4(),
                action_href="/reports/current",
                report_impact="published",
                dedupe_key="report:current:report.ready",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )


@pytest.mark.asyncio
async def test_AC19_1_4_upsert_uploaded_statement_event_is_deterministic(db, test_user) -> None:
    """AC19.1.4: uploaded statement event derivation is deterministic and idempotent."""
    statement = BankStatement(
        user_id=test_user.id,
        file_path="statements/demo.csv",
        file_hash="a" * 64,
        original_filename="demo.csv",
        institution="Demo Bank",
        status=BankStatementStatus.UPLOADED,
    )
    db.add(statement)
    await db.flush()

    first = await derive_uploaded_statement_event(db, statement, user_id=test_user.id)
    second = await derive_uploaded_statement_event(db, statement, user_id=test_user.id)
    await db.flush()

    assert first.id == second.id
    assert first.family == WorkflowEventFamily.SOURCE_UPLOADED
    assert first.severity == WorkflowEventSeverity.INFO
    assert first.status == WorkflowEventStatus.UNREAD
    assert first.action_href == f"/statements/{statement.id}"
    assert first.report_impact == WorkflowReportImpact.PROCESSING
    assert first.session_id is not None

    count = await db.scalar(select(func.count(WorkflowEvent.id)).where(WorkflowEvent.user_id == test_user.id))
    assert count == 1


@pytest.mark.asyncio
async def test_AC19_1_5_workflow_event_lifecycle_is_user_isolated(db, test_user) -> None:
    """AC19.1.5: workflow event reads and lifecycle changes are scoped by user_id."""
    other_user = User(email=f"other-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other_user)
    await db.flush()

    statement = BankStatement(
        user_id=test_user.id,
        file_path="statements/owned.csv",
        file_hash="b" * 64,
        original_filename="owned.csv",
        institution="Demo Bank",
        status=BankStatementStatus.UPLOADED,
    )
    db.add(statement)
    await db.flush()

    with pytest.raises(ValueError, match="statement.user_id must match user_id"):
        await derive_uploaded_statement_event(db, statement, user_id=other_user.id)

    event = await upsert_workflow_event(
        db,
        user_id=test_user.id,
        payload=WorkflowEventCreate(
            family=WorkflowEventFamily.REVIEW_REQUIRED,
            severity=WorkflowEventSeverity.ACTION_REQUIRED,
            title="Review required",
            summary="One statement needs confirmation.",
            source_type="bank_statement",
            source_id=uuid4(),
            action_href="/review",
            report_impact=WorkflowReportImpact.BLOCKED,
            dedupe_key="bank-statement:review-required:test",
            occurred_at=datetime.now(UTC),
        ),
    )
    await db.flush()

    assert [item.id for item in await list_workflow_events(db, user_id=test_user.id)] == [event.id]
    assert await list_workflow_events(db, user_id=other_user.id) == []

    assert (
        await update_workflow_event_status(
            db,
            event_id=event.id,
            user_id=other_user.id,
            status=WorkflowEventStatus.READ,
        )
        is None
    )

    updated = await update_workflow_event_status(
        db,
        event_id=event.id,
        user_id=test_user.id,
        status=WorkflowEventStatus.ARCHIVED,
    )
    assert updated is not None
    assert updated.status == WorkflowEventStatus.ARCHIVED
    assert WorkflowEventResponse.model_validate(updated).status == WorkflowEventStatus.ARCHIVED


@pytest.mark.asyncio
async def test_AC19_3_1_sync_refreshes_mutable_uploaded_event_fields_without_lifecycle_reset(db, test_user) -> None:
    """AC19.3.1: derived sync updates mutable display fields without lifecycle reset."""
    statement = BankStatement(
        user_id=test_user.id,
        file_path="statements/original.csv",
        file_hash="e" * 64,
        original_filename="original.csv",
        institution="Demo Bank",
        status=BankStatementStatus.UPLOADED,
    )
    db.add(statement)
    await db.flush()

    await sync_workflow_events_for_user(db, user_id=test_user.id)
    event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.source_id == statement.id)
        )
    ).scalar_one()
    event.status = WorkflowEventStatus.ARCHIVED
    statement.original_filename = "renamed.csv"
    await db.flush()

    await sync_workflow_events_for_user(db, user_id=test_user.id)
    events = (
        (
            await db.execute(
                select(WorkflowEvent)
                .where(WorkflowEvent.user_id == test_user.id)
                .where(WorkflowEvent.source_id == statement.id)
            )
        )
        .scalars()
        .all()
    )

    assert len(events) == 1
    assert events[0].id == event.id
    assert events[0].status == WorkflowEventStatus.ARCHIVED
    assert "renamed.csv" in events[0].summary


@pytest.mark.asyncio
async def test_AC19_3_1_sync_uses_bounded_workflow_event_lookup(db, db_engine, test_user) -> None:
    """AC19.3.1: derived sync avoids per-statement workflow event lookups."""
    from sqlalchemy import event as sqlalchemy_event

    for index in range(3):
        db.add(
            BankStatement(
                user_id=test_user.id,
                file_path=f"statements/bulk-{index}.csv",
                file_hash=f"{index}" * 64,
                original_filename=f"bulk-{index}.csv",
                institution="Demo Bank",
                status=BankStatementStatus.UPLOADED,
            )
        )
    await db.commit()

    statements: list[str] = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and "workflow_events" in normalized:
            statements.append(normalized)

    sqlalchemy_event.listen(db_engine.sync_engine, "before_cursor_execute", capture_sql)
    try:
        await sync_workflow_events_for_user(db, user_id=test_user.id)
    finally:
        sqlalchemy_event.remove(db_engine.sync_engine, "before_cursor_execute", capture_sql)

    assert len(statements) <= 2
    assert "join workflow_events" in statements[0]


@pytest.mark.asyncio
async def test_AC19_3_2_workflow_status_uses_single_aggregate_for_badge_counts(
    db,
    db_engine,
    test_user,
) -> None:
    """AC19.3.2: status uses one aggregate count query and one winning representative query."""
    from sqlalchemy import event as sqlalchemy_event

    await upsert_workflow_event(
        db,
        user_id=test_user.id,
        payload=WorkflowEventCreate(
            family=WorkflowEventFamily.REVIEW_REQUIRED,
            severity=WorkflowEventSeverity.ACTION_REQUIRED,
            title="Review required",
            summary="One statement needs confirmation.",
            source_type="bank_statement",
            source_id=uuid4(),
            action_href="/review",
            report_impact=WorkflowReportImpact.BLOCKED,
            dedupe_key="bank-statement:review-required:aggregate",
            occurred_at=datetime.now(UTC),
        ),
    )
    await upsert_workflow_event(
        db,
        user_id=test_user.id,
        payload=WorkflowEventCreate(
            family=WorkflowEventFamily.REPORT_PROCESSING,
            severity=WorkflowEventSeverity.INFO,
            title="Report processing",
            summary="Automation is running.",
            source_type="report",
            source_id=uuid4(),
            action_href="/reports",
            report_impact=WorkflowReportImpact.PROCESSING,
            dedupe_key="report:processing:aggregate",
            occurred_at=datetime.now(UTC),
        ),
    )
    await db.commit()

    statements: list[str] = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        normalized = " ".join(statement.lower().split())
        if "workflow_events" in normalized:
            statements.append(normalized)

    sqlalchemy_event.listen(db_engine.sync_engine, "before_cursor_execute", capture_sql)
    try:
        status = await get_workflow_status(db, user_id=test_user.id)
    finally:
        sqlalchemy_event.remove(db_engine.sync_engine, "before_cursor_execute", capture_sql)

    count_queries = [statement for statement in statements if "count(" in statement]
    representative_queries = [
        statement for statement in statements if "select workflow_events." in statement and "count(" not in statement
    ]

    assert status.primary_state.value == "needs_action"
    assert len(count_queries) == 1
    assert len(representative_queries) == 1
