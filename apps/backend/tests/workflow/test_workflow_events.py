"""Workflow event contract tests for EPIC-019."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.models import BankStatementStatus, Stage1Status, StatementSummary, User
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.workflow import (
    WorkflowEvent,
    WorkflowEventFamily,
    WorkflowEventSeverity,
    WorkflowEventStatus,
    WorkflowReportImpact,
    WorkflowSession,
    WorkflowSessionStatus,
)
from src.schemas.workflow import (
    WorkflowEventCreate,
    WorkflowEventResponse,
    WorkflowPrimaryState,
    WorkflowReportReadinessState,
)
from src.services.workflow_events import (
    _insert_workflow_event_conflict_safe,
    _workflow_event_from_payload,
    build_uploaded_statement_event_payload,
    derive_uploaded_statement_event,
    get_or_create_active_workflow_session,
    get_workflow_status,
    list_workflow_events,
    list_workflow_events_response,
    sync_workflow_events_for_user,
    update_workflow_event_status,
    upsert_workflow_event,
)

ROOT_DIR = Path(__file__).resolve().parents[4]


async def _make_statement(
    db: AsyncSession,
    user_id,
    *,
    original_filename: str,
    file_hash: str,
    institution: str = "Demo Bank",
    status: BankStatementStatus = BankStatementStatus.UPLOADED,
    stage1_status: Stage1Status | None = None,
    stage1_reviewed_at: datetime | None = None,
) -> tuple[StatementSummary, UploadedDocument]:
    """Create a StatementSummary linked to an UploadedDocument for workflow derivation."""
    document = UploadedDocument(
        user_id=user_id,
        file_path=f"statements/{original_filename}",
        file_hash=file_hash,
        original_filename=original_filename,
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(document)
    await db.flush()

    statement = StatementSummary(
        user_id=user_id,
        uploaded_document_id=document.id,
        file_hash=file_hash,
        institution=institution,
        status=status,
        stage1_status=stage1_status,
        stage1_reviewed_at=stage1_reviewed_at,
    )
    db.add(statement)
    await db.flush()
    return statement, document


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
        "workflow.status.next_action.label",
        "Ready actions route directly to `/reports/package`",
        "Secondary dashboard metric loading or failure must not hide the workflow",
    ):
        assert phrase in ssot

    assert "AC19.4.1" in epic
    assert "AC19.4.8" in epic
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


def test_AC19_8_1_workflow_session_ssot_separates_chat_sessions() -> None:
    """AC19.8.1: WorkflowSession is the workflow domain object; chat sessions are AI UI state."""
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

    assert "AC19.8.1" in epic
    assert "AC19.8.8" in epic


def test_AC19_12_1_lightweight_derivation_boundary_is_documented() -> None:
    """AC19.12.1: workflow events stay lightweight and user-facing."""
    ssot = (ROOT_DIR / "docs" / "ssot" / "workflow-events.md").read_text(encoding="utf-8")
    epic = (ROOT_DIR / "docs" / "project" / "EPIC-019.event-driven-upload-to-report-ux.md").read_text(encoding="utf-8")
    normalized_ssot = " ".join(ssot.split())

    for phrase in (
        "AC19.12 completes the first lightweight user-facing derivation set",
        "not a low-level event log",
        "normalized owner tables",
        "What needs my action now?",
        "Processing account blockers exposed through package readiness",
        "archive mutable derived action/blocker events when the underlying condition is resolved",
    ):
        assert phrase in normalized_ssot

    assert "AC19.12 — Lightweight Workflow Derivation Completion" in epic
    assert "AC19.12.1" in epic
    assert "AC19.12.6" in epic


def test_AC19_8_2_workflow_session_model_contract() -> None:
    """AC19.8.2: workflow_sessions and workflow_events.session_id expose the v1 session contract."""
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


async def test_AC19_8_9_active_workflow_session_get_or_create_is_concurrency_safe(db_engine, test_user) -> None:
    """AC19.8.9: Concurrent status/events reads share the synthetic active workflow session."""
    sessionmaker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with sessionmaker() as first_session, sessionmaker() as second_session:
        first = await get_or_create_active_workflow_session(first_session, user_id=test_user.id)

        second_task = asyncio.create_task(get_or_create_active_workflow_session(second_session, user_id=test_user.id))
        await asyncio.sleep(0.2)
        await first_session.commit()

        second = await asyncio.wait_for(second_task, timeout=5)
        await second_session.commit()

    async with sessionmaker() as verify_session:
        sessions = (
            (
                await verify_session.execute(
                    select(WorkflowSession)
                    .where(WorkflowSession.user_id == test_user.id)
                    .where(WorkflowSession.dedupe_key == "active-upload-to-report")
                )
            )
            .scalars()
            .all()
        )

    assert first.id == second.id
    assert len(sessions) == 1
    assert sessions[0].status == WorkflowSessionStatus.ACTIVE


async def test_AC19_8_9_active_workflow_session_reactivates_existing_inactive_dedupe_row(db, test_user) -> None:
    """AC19.8.9: Inactive synthetic sessions do not make active-session creation fail."""
    archived_session = WorkflowSession(
        user_id=test_user.id,
        status=WorkflowSessionStatus.ARCHIVED,
        title="Upload-to-report session",
        summary="Archived synthetic session.",
        dedupe_key="active-upload-to-report",
        source_count=0,
    )
    db.add(archived_session)
    await db.flush()

    active_session = await get_or_create_active_workflow_session(db, user_id=test_user.id)
    await db.flush()

    assert active_session.id == archived_session.id
    assert active_session.status == WorkflowSessionStatus.ACTIVE
    assert active_session.summary == "Current upload, processing, review, and report-readiness work."


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


async def test_AC19_1_4_upsert_uploaded_statement_event_is_deterministic(db, test_user) -> None:
    """AC19.1.4: uploaded statement event derivation is deterministic and idempotent."""
    statement, _document = await _make_statement(
        db,
        test_user.id,
        original_filename="demo.csv",
        file_hash="a" * 64,
    )

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


async def test_AC19_1_5_workflow_event_lifecycle_is_user_isolated(db, test_user) -> None:
    """AC19.1.5: workflow event reads and lifecycle changes are scoped by user_id."""
    other_user = User(email=f"other-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other_user)
    await db.flush()

    statement, _document = await _make_statement(
        db,
        test_user.id,
        original_filename="owned.csv",
        file_hash="b" * 64,
    )

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


async def test_AC19_3_1_sync_refreshes_mutable_uploaded_event_fields_without_lifecycle_reset(db, test_user) -> None:
    """AC19.3.1: derived sync updates mutable display fields without lifecycle reset."""
    statement, document = await _make_statement(
        db,
        test_user.id,
        original_filename="original.csv",
        file_hash="e" * 64,
    )

    await sync_workflow_events_for_user(db, user_id=test_user.id)
    event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.source_id == statement.id)
        )
    ).scalar_one()
    event.status = WorkflowEventStatus.ARCHIVED
    document.original_filename = "renamed.csv"
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


async def test_AC19_12_2_review_events_are_current_user_actions_with_lifecycle_preserved(db, test_user) -> None:
    """AC19.12.2 AC19.12.6 AC22.2.2 AC22.2.5: review events are idempotent, current, lifecycle-safe, and deep-link to the statement review page."""
    statement, _document = await _make_statement(
        db,
        test_user.id,
        original_filename="review.csv",
        file_hash="1" * 64,
        institution="Review Bank",
        status=BankStatementStatus.PARSED,
        stage1_status=Stage1Status.PENDING_REVIEW,
    )

    await sync_workflow_events_for_user(db, user_id=test_user.id)
    review_event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.REVIEW_REQUIRED)
        )
    ).scalar_one()
    review_event.status = WorkflowEventStatus.READ
    await db.flush()

    await sync_workflow_events_for_user(db, user_id=test_user.id)
    same_review_event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.REVIEW_REQUIRED)
        )
    ).scalar_one()
    assert same_review_event.id == review_event.id
    assert same_review_event.status == WorkflowEventStatus.READ
    assert same_review_event.severity == WorkflowEventSeverity.ACTION_REQUIRED
    assert same_review_event.action_href == f"/statements/{same_review_event.source_id}/review"

    statement.stage1_status = Stage1Status.APPROVED
    statement.stage1_reviewed_at = datetime.now(UTC)
    await db.flush()
    await sync_workflow_events_for_user(db, user_id=test_user.id)

    resolved_review_event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.REVIEW_REQUIRED)
        )
    ).scalar_one()
    completed_event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.REVIEW_COMPLETED)
        )
    ).scalar_one()
    assert resolved_review_event.status == WorkflowEventStatus.ARCHIVED
    assert completed_event.status == WorkflowEventStatus.UNREAD
    assert completed_event.severity == WorkflowEventSeverity.SUCCESS
    assert completed_event.action_href == f"/statements/{statement.id}"


async def test_AC19_12_2_review_derivation_treats_null_stage1_as_pending_without_parse_failure(db, test_user) -> None:
    """AC19.12.2 AC19.12.6: legacy NULL Stage 1 rows derive the correct review event."""
    pending_statement, _pending_document = await _make_statement(
        db,
        test_user.id,
        original_filename="null-stage1.csv",
        file_hash="6" * 64,
        institution="Review Bank",
        status=BankStatementStatus.PARSED,
        stage1_status=None,
    )
    rejected_by_review, _rejected_review_document = await _make_statement(
        db,
        test_user.id,
        original_filename="review-rejected.csv",
        file_hash="7" * 64,
        institution="Review Bank",
        status=BankStatementStatus.REJECTED,
        stage1_status=Stage1Status.REJECTED,
        stage1_reviewed_at=datetime.now(UTC),
    )
    rejected_by_parser, _rejected_parser_document = await _make_statement(
        db,
        test_user.id,
        original_filename="parser-rejected.csv",
        file_hash="8" * 64,
        institution="Review Bank",
        status=BankStatementStatus.REJECTED,
        stage1_status=None,
    )

    await sync_workflow_events_for_user(db, user_id=test_user.id)

    pending_review_event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.REVIEW_REQUIRED)
            .where(WorkflowEvent.source_id == pending_statement.id)
        )
    ).scalar_one()
    review_completed_event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.REVIEW_COMPLETED)
            .where(WorkflowEvent.source_id == rejected_by_review.id)
        )
    ).scalar_one()
    parsing_failed_count = await db.scalar(
        select(func.count(WorkflowEvent.id))
        .where(WorkflowEvent.user_id == test_user.id)
        .where(WorkflowEvent.family == WorkflowEventFamily.SOURCE_PARSING_FAILED)
        .where(WorkflowEvent.source_id == rejected_by_review.id)
    )
    parsing_failed_event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.SOURCE_PARSING_FAILED)
            .where(WorkflowEvent.source_id == rejected_by_parser.id)
        )
    ).scalar_one()

    assert pending_review_event.status == WorkflowEventStatus.UNREAD
    assert pending_review_event.action_href == f"/statements/{pending_review_event.source_id}/review"
    assert review_completed_event.status == WorkflowEventStatus.UNREAD
    assert parsing_failed_count == 0
    assert parsing_failed_event.status == WorkflowEventStatus.UNREAD
    assert parsing_failed_event.action_href == f"/statements/{rejected_by_parser.id}"


async def test_AC19_12_3_report_readiness_events_follow_package_readiness_without_stale_blockers(
    db,
    test_user,
    monkeypatch,
) -> None:
    """AC19.12.3 AC19.12.6: readiness events follow package state and archive stale blockers."""
    blocker_payload = {
        "state": "blocked",
        "action_href": "/review",
        "blocking_count": 2,
        "blockers": [
            {
                "code": "pending_review",
                "label": "Pending source review",
                "count": 2,
                "reason": "Statement review must be completed before the package can be marked ready.",
                "action_href": "/review",
            }
        ],
    }
    ready_payload = {
        "state": "ready",
        "action_href": "/reports/package",
        "blocking_count": 0,
        "blockers": [],
    }
    generated_payload = {
        "state": "generated",
        "action_href": "/reports/package",
        "blocking_count": 0,
        "blockers": [],
    }
    current_payload = blocker_payload

    async def fake_readiness(_db, **_kwargs):
        return current_payload

    monkeypatch.setattr("src.services.workflow_events.get_personal_report_package_readiness", fake_readiness)

    await sync_workflow_events_for_user(db, user_id=test_user.id)
    blocked_event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.REPORT_BLOCKED)
        )
    ).scalar_one()
    blocked_event.status = WorkflowEventStatus.READ
    await db.flush()

    await sync_workflow_events_for_user(db, user_id=test_user.id)
    same_blocked_event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.REPORT_BLOCKED)
        )
    ).scalar_one()
    assert same_blocked_event.id == blocked_event.id
    assert same_blocked_event.status == WorkflowEventStatus.READ
    assert same_blocked_event.report_impact == WorkflowReportImpact.BLOCKED

    current_payload = ready_payload
    await sync_workflow_events_for_user(db, user_id=test_user.id)
    archived_blocker = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.REPORT_BLOCKED)
        )
    ).scalar_one()
    ready_event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.REPORT_READY)
        )
    ).scalar_one()
    assert archived_blocker.status == WorkflowEventStatus.ARCHIVED
    assert ready_event.status == WorkflowEventStatus.UNREAD
    assert ready_event.action_href == "/reports/package"

    current_payload = generated_payload
    await sync_workflow_events_for_user(db, user_id=test_user.id)
    generated_event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.REPORT_GENERATED)
        )
    ).scalar_one()
    ready_event_after_generation = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.REPORT_READY)
        )
    ).scalar_one()
    assert generated_event.status == WorkflowEventStatus.UNREAD
    assert generated_event.action_href == "/reports/package"
    assert ready_event_after_generation.status == WorkflowEventStatus.ARCHIVED


async def test_AC19_12_3_sync_archives_last_resolved_blocker_when_no_derived_payloads(
    db,
    test_user,
    monkeypatch,
) -> None:
    """AC19.12.3 AC19.12.6: stale blockers archive when no current derived payload remains."""
    blocker_payload = {
        "state": "blocked",
        "action_href": "/review",
        "blocking_count": 1,
        "blockers": [
            {
                "code": "pending_review",
                "label": "Pending source review",
                "count": 1,
                "reason": "Statement review must be completed before the package can be marked ready.",
                "action_href": "/review",
            }
        ],
    }
    empty_payload = {
        "state": "draft",
        "action_href": "/statements/upload",
        "blocking_count": 0,
        "blockers": [],
    }
    current_payload = blocker_payload

    async def fake_readiness(_db, **_kwargs):
        return current_payload

    monkeypatch.setattr("src.services.workflow_events.get_personal_report_package_readiness", fake_readiness)

    await sync_workflow_events_for_user(db, user_id=test_user.id)
    blocked_event = (
        await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == test_user.id)
            .where(WorkflowEvent.family == WorkflowEventFamily.REPORT_BLOCKED)
        )
    ).scalar_one()

    current_payload = empty_payload
    await sync_workflow_events_for_user(db, user_id=test_user.id)

    assert blocked_event.status == WorkflowEventStatus.ARCHIVED


async def test_AC19_12_3_ready_package_status_wins_over_long_lived_upload_processing(
    db,
    test_user,
    monkeypatch,
) -> None:
    """AC19.12.3: package readiness drives the primary open-report action once ready."""
    await _make_statement(
        db,
        test_user.id,
        original_filename="ready.csv",
        file_hash="2" * 64,
        institution="Ready Bank",
        status=BankStatementStatus.PARSED,
        stage1_status=Stage1Status.APPROVED,
        stage1_reviewed_at=datetime.now(UTC),
    )

    async def fake_readiness(_db, **_kwargs):
        return {
            "state": "ready",
            "action_href": "/reports/package",
            "blocking_count": 0,
            "blockers": [],
        }

    monkeypatch.setattr("src.services.workflow_events.get_personal_report_package_readiness", fake_readiness)

    status = await get_workflow_status(db, user_id=test_user.id)

    assert status.primary_state.value == "ready"
    assert status.next_action.type.value == "open_report"
    assert status.next_action.href == "/reports/package"


async def test_AC19_12_4_readiness_blocker_events_are_user_action_scoped(db, test_user, monkeypatch) -> None:
    """AC19.12.4 AC19.12.6: reconciliation and Processing blockers are lightweight user actions."""

    async def fake_readiness(_db, **_kwargs):
        return {
            "state": "blocked",
            "action_href": "/reconciliation/review-queue",
            "blocking_count": 3,
            "blockers": [
                {
                    "code": "reconciliation_blocked",
                    "label": "Reconciliation blockers",
                    "count": 2,
                    "reason": "Pending reconciliation matches must be accepted or rejected.",
                    "action_href": "/reconciliation/review-queue",
                },
                {
                    "code": "processing_account_unresolved",
                    "label": "Processing account unresolved",
                    "count": 1,
                    "reason": "In-transit transfer legs must net to zero.",
                    "action_href": "/accounts/processing",
                },
            ],
        }

    monkeypatch.setattr("src.services.workflow_events.get_personal_report_package_readiness", fake_readiness)

    await sync_workflow_events_for_user(db, user_id=test_user.id)
    events = (
        (
            await db.execute(
                select(WorkflowEvent)
                .where(WorkflowEvent.user_id == test_user.id)
                .where(
                    WorkflowEvent.family.in_(
                        [WorkflowEventFamily.RECONCILIATION_BLOCKED, WorkflowEventFamily.REPORT_BLOCKED]
                    )
                )
                .order_by(WorkflowEvent.family)
            )
        )
        .scalars()
        .all()
    )

    assert [(event.family, event.action_href, event.source_type) for event in events] == [
        (
            WorkflowEventFamily.RECONCILIATION_BLOCKED,
            "/reconciliation/review-queue",
            "readiness_blocker",
        ),
        (WorkflowEventFamily.REPORT_BLOCKED, "/accounts/processing", "readiness_blocker"),
    ]
    assert all(event.severity == WorkflowEventSeverity.BLOCKED for event in events)
    assert all(event.report_impact == WorkflowReportImpact.BLOCKED for event in events)


async def test_AC19_3_1_sync_uses_bounded_workflow_event_lookup(db, db_engine, test_user) -> None:
    """AC19.3.1: derived sync avoids per-statement workflow event lookups."""
    from sqlalchemy import event as sqlalchemy_event

    for index in range(3):
        await _make_statement(
            db,
            test_user.id,
            original_filename=f"bulk-{index}.csv",
            file_hash=f"{index}" * 64,
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
        statement
        for statement in statements
        if "select workflow_events." in statement
        and "count(" not in statement
        and "order by workflow_events.occurred_at desc" in statement
    ]

    assert status.primary_state.value == "needs_action"
    assert len(count_queries) == 1
    assert len(representative_queries) == 1


async def test_AC22_4_1_pending_stage2_match_surfaces_reconciliation_review_event(db, test_user):
    """AC22.4.1: a pending Stage 2 reconciliation match surfaces a reconciliation-review
    event in the inbox that deep-links to /reconciliation/review-queue, and re-syncing
    does not duplicate it."""
    from tests.factories import AtomicTransactionFactory, ReconciliationMatchFactory

    atomic_txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id)
    await ReconciliationMatchFactory.create_async(db, atomic_txn_id=atomic_txn.id, journal_entry_ids=[])
    await db.commit()

    await sync_workflow_events_for_user(db, user_id=test_user.id)
    events = await list_workflow_events(db, user_id=test_user.id)
    recon = [e for e in events if e.family == WorkflowEventFamily.RECONCILIATION_BLOCKED]
    # Exactly one aggregate reconciliation-review card (not one per pending match).
    assert len(recon) == 1, "pending Stage 2 matches must surface a single reconciliation-review card"
    assert recon[0].action_href == "/reconciliation/review-queue"
    original_event_id = recon[0].id

    # Re-sync is idempotent: still exactly one event, and the same row is reused.
    await sync_workflow_events_for_user(db, user_id=test_user.id)
    events_again = await list_workflow_events(db, user_id=test_user.id)
    recon_again = [e for e in events_again if e.family == WorkflowEventFamily.RECONCILIATION_BLOCKED]
    assert len(recon_again) == 1
    assert recon_again[0].id == original_event_id


async def test_AC19_14_1_concurrent_upsert_same_dedupe_key_does_not_500(db_engine, test_user) -> None:
    """AC19.14.1: Two concurrent upserts of the same (user_id, dedupe_key) workflow event both
    succeed without a duplicate-key 500; exactly one row exists and both calls return it."""
    sessionmaker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    source_id = uuid4()
    payload = build_uploaded_statement_event_payload(
        SimpleNamespace(id=source_id, created_at=datetime.now(UTC)),
        "concurrent.pdf",
    )

    async with sessionmaker() as first_session, sessionmaker() as second_session:
        first = await upsert_workflow_event(first_session, user_id=test_user.id, payload=payload)

        second_task = asyncio.create_task(upsert_workflow_event(second_session, user_id=test_user.id, payload=payload))
        await asyncio.sleep(0.2)
        await first_session.commit()

        second = await asyncio.wait_for(second_task, timeout=5)
        await second_session.commit()

    async with sessionmaker() as verify_session:
        events = (
            (
                await verify_session.execute(
                    select(WorkflowEvent)
                    .where(WorkflowEvent.user_id == test_user.id)
                    .where(WorkflowEvent.dedupe_key == payload.dedupe_key)
                )
            )
            .scalars()
            .all()
        )

    assert len(events) == 1
    assert first.dedupe_key == payload.dedupe_key
    assert second.dedupe_key == payload.dedupe_key


async def test_AC19_14_2_duplicate_insert_does_not_poison_outer_transaction(db, test_user) -> None:
    """AC19.14.2: When the same (user_id, dedupe_key) is inserted twice within one session, the
    second insert recovers via savepoint, returns the existing row, and the outer transaction stays
    usable for subsequent reads/flushes (no 'transaction has been rolled back')."""
    source_id = uuid4()
    payload = build_uploaded_statement_event_payload(
        SimpleNamespace(id=source_id, created_at=datetime.now(UTC)),
        "duplicate.pdf",
    )

    workflow_session = await get_or_create_active_workflow_session(db, user_id=test_user.id)

    # Pre-existing row with the same dedupe key, committed so it is visible to the next insert.
    existing = _workflow_event_from_payload(user_id=test_user.id, payload=payload, session_id=workflow_session.id)
    db.add(existing)
    await db.commit()

    # Force the racing path: a fresh ORM object inserted directly via the conflict-safe helper.
    recovered = await _insert_workflow_event_conflict_safe(
        db, user_id=test_user.id, payload=payload, session_id=workflow_session.id
    )
    assert recovered.id == existing.id

    # The outer transaction must still be alive: this flush/read would raise if it were poisoned.
    await db.flush()
    count = await db.scalar(
        select(func.count(WorkflowEvent.id))
        .where(WorkflowEvent.user_id == test_user.id)
        .where(WorkflowEvent.dedupe_key == payload.dedupe_key)
    )
    assert count == 1


async def test_AC19_14_3_sync_tolerates_concurrent_event_creation(db_engine, test_user) -> None:
    """AC19.14.3: Concurrent sync_workflow_events_for_user runs over the same source state do not
    500 on the workflow-event dedupe key; the derived uploaded event is created exactly once."""
    sessionmaker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    file_hash = uuid4().hex
    async with sessionmaker() as setup_session:
        await _make_statement(
            setup_session,
            test_user.id,
            original_filename="race.pdf",
            file_hash=file_hash,
            status=BankStatementStatus.UPLOADED,
        )
        await setup_session.commit()

    async with sessionmaker() as first_session, sessionmaker() as second_session:
        await sync_workflow_events_for_user(first_session, user_id=test_user.id)
        second_task = asyncio.create_task(sync_workflow_events_for_user(second_session, user_id=test_user.id))
        await asyncio.sleep(0.2)
        await first_session.commit()
        await asyncio.wait_for(second_task, timeout=5)
        await second_session.commit()

    async with sessionmaker() as verify_session:
        uploaded = (
            (
                await verify_session.execute(
                    select(WorkflowEvent)
                    .where(WorkflowEvent.user_id == test_user.id)
                    .where(WorkflowEvent.family == WorkflowEventFamily.SOURCE_UPLOADED)
                )
            )
            .scalars()
            .all()
        )
    assert len(uploaded) == 1


async def test_AC19_2_7_events_session_summary_agrees_with_status_when_blocked(
    db,
    test_user,
    monkeypatch,
) -> None:
    """AC19.2.7: the /workflow/events session summary must reuse the authoritative
    status derivation, so a blocked active session never reports primary_state=ready
    or report_readiness=none while /workflow/status reports blocked."""

    async def fake_readiness(_db, **_kwargs):
        return {
            "state": "blocked",
            "action_href": "/reports/package",
            "blocking_count": 1,
            "blockers": [
                {
                    "code": "balance_mismatch",
                    "label": "Balance validation mismatch",
                    "count": 1,
                    "reason": "Balance mismatch: expected 52754.77, got 52842.53.",
                    "action_href": "/review",
                }
            ],
        }

    monkeypatch.setattr("src.services.workflow_events.get_personal_report_package_readiness", fake_readiness)

    # A blocked active session derived from a balance-validation blocker.
    await sync_workflow_events_for_user(db, user_id=test_user.id)
    await db.flush()

    status = await get_workflow_status(db, user_id=test_user.id)
    events = await list_workflow_events_response(db, user_id=test_user.id, limit=10)

    # Status authoritatively reports blocked for the active session.
    assert status.primary_state == WorkflowPrimaryState.BLOCKED
    assert status.report_readiness.state == WorkflowReportReadinessState.BLOCKED
    assert status.active_session is not None

    # The events session summary for that same active session must agree (no
    # hardcoded ready/none divergence).
    active_summaries = [session for session in events.sessions if session.id == status.active_session.id]
    assert active_summaries, "events response must include the active session summary"
    active_summary = active_summaries[0]
    assert active_summary.primary_state == status.active_session.primary_state
    assert active_summary.report_readiness.state == status.active_session.report_readiness.state
    assert active_summary.primary_state == WorkflowPrimaryState.BLOCKED
    assert active_summary.report_readiness.state == WorkflowReportReadinessState.BLOCKED
