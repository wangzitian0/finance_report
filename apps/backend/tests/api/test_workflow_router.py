"""Workflow status API tests for EPIC-019."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user_id
from src.main import app
from src.models import (
    Account,
    AccountType,
    BankStatementStatus,
    ClassificationRule,
    JournalEntry,
    JournalEntryStatus,
    ReportSnapshot,
    ReportType,
    RuleType,
    Stage1Status,
    StatementSummary,
    User,
)
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.workflow import (
    WorkflowEvent,
    WorkflowEventFamily,
    WorkflowEventSeverity,
    WorkflowEventStatus,
    WorkflowReportImpact,
    WorkflowSession,
)
from src.schemas.workflow import (
    WorkflowEventCreate,
    WorkflowEventListResponse,
    WorkflowNextActionType,
    WorkflowPrimaryState,
    WorkflowReportReadinessState,
    WorkflowStatusResponse,
)
from src.services.workflow_events import upsert_workflow_event

pytestmark = pytest.mark.asyncio

ROOT_DIR = Path(__file__).resolve().parents[4]


async def _create_event(
    db: AsyncSession,
    *,
    user_id: UUID,
    family: WorkflowEventFamily,
    severity: WorkflowEventSeverity,
    report_impact: WorkflowReportImpact,
    action_href: str,
    title: str,
    occurred_at: datetime | None = None,
    status: WorkflowEventStatus = WorkflowEventStatus.UNREAD,
    source_id: UUID | None = None,
) -> WorkflowEvent:
    source_id = source_id or uuid4()
    event = await upsert_workflow_event(
        db,
        user_id=user_id,
        payload=WorkflowEventCreate(
            family=family,
            severity=severity,
            title=title,
            summary=f"{title} summary",
            source_type="workflow_test",
            source_id=source_id,
            action_href=action_href,
            report_impact=report_impact,
            dedupe_key=f"workflow-test:{source_id}:{family.value}",
            occurred_at=occurred_at or datetime.now(UTC),
        ),
    )
    event.status = status
    await db.flush()
    return event


async def _get_as_user(public_client: AsyncClient, user_id: UUID, path: str) -> dict:
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    try:
        response = await public_client.get(path)
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    assert response.status_code == 200
    return response.json()


def _next_action(
    action_type: str,
    *,
    count: int,
    href: str,
    label: str,
    summary: str,
) -> dict:
    return {"type": action_type, "count": count, "href": href, "label": label, "summary": summary}


async def _make_statement(
    db: AsyncSession,
    user_id: UUID,
    *,
    original_filename: str,
    file_hash: str,
    institution: str = "Demo Bank",
    status: BankStatementStatus = BankStatementStatus.UPLOADED,
    stage1_status: Stage1Status | None = None,
    balance_validated: bool | None = None,
    validation_error: str | None = None,
) -> StatementSummary:
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
        balance_validated=balance_validated,
        validation_error=validation_error,
    )
    db.add(statement)
    await db.flush()
    return statement


def _approved_statement(user_id: UUID, *, account_id: UUID | None = None, updated_at: datetime | None = None):
    timestamp = updated_at or datetime.now(UTC)
    return StatementSummary(
        user_id=user_id,
        account_id=account_id,
        file_hash=uuid4().hex,
        institution="Workflow Readiness Bank",
        status=BankStatementStatus.APPROVED,
        stage1_status=Stage1Status.APPROVED,
        balance_validated=True,
        created_at=timestamp,
        updated_at=timestamp,
    )


async def _report_snapshot(db: AsyncSession, user_id: UUID, *, updated_at: datetime) -> ReportSnapshot:
    rule = ClassificationRule(
        user_id=user_id,
        version_number=1,
        effective_date=date(2026, 1, 1),
        rule_name=f"workflow-readiness-{uuid4()}",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["workflow"]},
        created_by=user_id,
    )
    db.add(rule)
    await db.flush()
    snapshot = ReportSnapshot(
        user_id=user_id,
        report_type=ReportType.BALANCE_SHEET,
        as_of_date=date(2026, 5, 31),
        start_date=None,
        rule_version_id=rule.id,
        report_data={"total_assets": "100.00"},
        is_latest=True,
        created_at=updated_at,
        updated_at=updated_at,
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


async def test_AC19_2_1_workflow_status_schema_contract() -> None:
    """AC19.2.1: workflow status schemas expose stable contracts for UI consumers."""
    status = WorkflowStatusResponse(
        primary_state=WorkflowPrimaryState.NEEDS_ACTION,
        next_action={
            "type": WorkflowNextActionType.REVIEW_REQUIRED,
            "count": 2,
            "href": "/review?source=events",
            "label": "Review required",
            "summary": "Confirm source records before reporting.",
        },
        report_readiness={
            "state": WorkflowReportReadinessState.BLOCKED,
            "blocking_count": 1,
            "href": "/reports",
        },
        event_counts={"unread": 4, "action_required": 2, "blocked": 1},
    )

    assert status.model_dump(mode="json") == {
        "primary_state": "needs_action",
        "next_action": {
            "type": "review_required",
            "count": 2,
            "href": "/review?source=events",
            "label": "Review required",
            "summary": "Confirm source records before reporting.",
        },
        "report_readiness": {
            "state": "blocked",
            "blocking_count": 1,
            "href": "/reports",
        },
        "event_counts": {"unread": 4, "action_required": 2, "blocked": 1},
        "active_session": None,
    }


async def test_AC19_2_2_workflow_status_endpoint_returns_priority_summaries(
    public_client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC19.2.2: GET /workflow/status returns user-scoped summary states with priority rules."""
    empty = await _get_as_user(public_client, test_user.id, "/workflow/status")
    assert empty["primary_state"] == "empty"
    assert empty["next_action"] == _next_action(
        "upload",
        count=0,
        href="/statements/upload",
        label="Upload statements",
        summary="Add source documents to start the upload-to-report workflow.",
    )
    assert empty["report_readiness"] == {"state": "none", "blocking_count": 0, "href": "/reports/package"}
    assert empty["event_counts"] == {"unread": 0, "action_required": 0, "blocked": 0}
    assert empty["active_session"] is None

    await _make_statement(
        db,
        test_user.id,
        original_filename="status-demo.csv",
        file_hash="c" * 64,
    )
    await db.commit()

    processing = await _get_as_user(public_client, test_user.id, "/workflow/status")
    assert processing["primary_state"] == "processing"
    assert processing["next_action"] == _next_action(
        "wait",
        count=1,
        href="/events",
        label="View processing",
        summary="Automation is processing source files; open the session timeline for progress.",
    )
    assert processing["report_readiness"] == {"state": "processing", "blocking_count": 0, "href": "/reports/package"}
    assert processing["event_counts"] == {"unread": 1, "action_required": 0, "blocked": 0}
    assert processing["active_session"]["title"] == "Upload-to-report session"
    assert processing["active_session"]["source_count"] == 1
    assert processing["active_session"]["primary_state"] == "processing"

    await _create_event(
        db,
        user_id=test_user.id,
        family=WorkflowEventFamily.REVIEW_REQUIRED,
        severity=WorkflowEventSeverity.ACTION_REQUIRED,
        report_impact=WorkflowReportImpact.BLOCKED,
        action_href="/review?source=events",
        title="Review required",
    )
    await db.commit()

    needs_action = await _get_as_user(public_client, test_user.id, "/workflow/status")
    assert needs_action["primary_state"] == "needs_action"
    assert needs_action["next_action"] == _next_action(
        "review_required",
        count=1,
        href="/review?source=events",
        label="Review required",
        summary="Confirm the source or review item so trusted report preparation can continue.",
    )
    assert needs_action["report_readiness"] == {"state": "processing", "blocking_count": 0, "href": "/reports/package"}
    assert needs_action["event_counts"] == {"unread": 2, "action_required": 1, "blocked": 0}

    await _create_event(
        db,
        user_id=test_user.id,
        family=WorkflowEventFamily.RECONCILIATION_BLOCKED,
        severity=WorkflowEventSeverity.BLOCKED,
        report_impact=WorkflowReportImpact.BLOCKED,
        action_href="/reconciliation/unmatched",
        title="Reconciliation blocked",
    )
    await db.commit()

    blocked = await _get_as_user(public_client, test_user.id, "/workflow/status")
    assert blocked["primary_state"] == "blocked"
    assert blocked["next_action"] == _next_action(
        "resolve_blocker",
        count=1,
        href="/reconciliation/unmatched",
        label="Resolve blocker",
        summary="Resolve the blocking condition before the report package can be trusted.",
    )
    assert blocked["report_readiness"] == {"state": "processing", "blocking_count": 0, "href": "/reports/package"}
    assert blocked["event_counts"] == {"unread": 3, "action_required": 1, "blocked": 1}

    ready_user = User(email=f"ready-{uuid4()}@example.com", hashed_password="hashed")
    db.add(ready_user)
    await db.flush()
    await _create_event(
        db,
        user_id=ready_user.id,
        family=WorkflowEventFamily.REPORT_READY,
        severity=WorkflowEventSeverity.SUCCESS,
        report_impact=WorkflowReportImpact.READY,
        action_href="/reports",
        title="Report ready",
    )
    db.add(
        JournalEntry(
            user_id=ready_user.id,
            entry_date=date(2026, 5, 31),
            memo="Ready report input",
            status=JournalEntryStatus.POSTED,
        )
    )
    await db.commit()

    ready = await _get_as_user(public_client, ready_user.id, "/workflow/status")
    assert ready["primary_state"] == "ready"
    assert ready["next_action"] == _next_action(
        "open_report",
        count=1,
        href="/reports/package",
        label="Open report package",
        summary="Inspect the personal report package and its readiness evidence.",
    )
    assert ready["report_readiness"] == {"state": "ready", "blocking_count": 0, "href": "/reports/package"}
    assert ready["event_counts"] == {"unread": 1, "action_required": 0, "blocked": 0}


async def test_AC19_2_2_workflow_status_consumes_package_readiness_fact_source(
    public_client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC19.2.2: workflow status collapses package readiness instead of recalculating blockers."""
    account = Account(user_id=test_user.id, name="Workflow Cash", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()
    source_time = datetime(2026, 5, 1, tzinfo=UTC)
    statement = _approved_statement(test_user.id, account_id=account.id, updated_at=source_time)
    db.add(statement)
    await db.commit()

    ready = await _get_as_user(public_client, test_user.id, "/workflow/status")
    assert ready["report_readiness"] == {"state": "ready", "blocking_count": 0, "href": "/reports/package"}

    await _report_snapshot(db, test_user.id, updated_at=datetime(2026, 5, 2, tzinfo=UTC))
    await db.commit()
    generated = await _get_as_user(public_client, test_user.id, "/workflow/status")
    assert generated["report_readiness"] == {"state": "ready", "blocking_count": 0, "href": "/reports/package"}

    statement.updated_at = datetime(2026, 5, 3, tzinfo=UTC)
    await db.commit()
    stale = await _get_as_user(public_client, test_user.id, "/workflow/status")
    assert stale["report_readiness"] == {"state": "stale", "blocking_count": 0, "href": "/reports/package"}

    blocked_user = User(email=f"package-blocked-{uuid4()}@example.com", hashed_password="hashed")
    db.add(blocked_user)
    await db.flush()
    await _make_statement(
        db,
        blocked_user.id,
        original_filename=f"{uuid4()}.csv",
        file_hash=uuid4().hex,
        institution="Workflow Blocker Bank",
        status=BankStatementStatus.REJECTED,
        stage1_status=Stage1Status.PENDING_REVIEW,
        balance_validated=False,
        validation_error="Closing balance mismatch",
    )
    await db.commit()

    blocked = await _get_as_user(public_client, blocked_user.id, "/workflow/status")
    assert blocked["primary_state"] == "blocked"
    assert blocked["next_action"] == _next_action(
        "resolve_blocker",
        count=3,
        href="/statements",
        label="Resolve blocker",
        summary="Resolve the blocking condition before the report package can be trusted.",
    )
    assert blocked["report_readiness"] == {"state": "blocked", "blocking_count": 3, "href": "/reports/package"}


async def test_AC19_2_3_workflow_events_endpoint_lists_bounded_user_events(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC19.2.3: GET /workflow/events returns bounded active events and supports status filtering."""
    other_user = User(email=f"other-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other_user)
    await db.flush()

    now = datetime.now(UTC)
    archived = await _create_event(
        db,
        user_id=test_user.id,
        family=WorkflowEventFamily.SOURCE_UPLOADED,
        severity=WorkflowEventSeverity.INFO,
        report_impact=WorkflowReportImpact.PROCESSING,
        action_href="/statements/archived",
        title="Archived event",
        occurred_at=now - timedelta(minutes=3),
        status=WorkflowEventStatus.ARCHIVED,
    )
    older = await _create_event(
        db,
        user_id=test_user.id,
        family=WorkflowEventFamily.REPORT_PROCESSING,
        severity=WorkflowEventSeverity.INFO,
        report_impact=WorkflowReportImpact.PROCESSING,
        action_href="/reports",
        title="Older active event",
        occurred_at=now - timedelta(minutes=2),
    )
    newer = await _create_event(
        db,
        user_id=test_user.id,
        family=WorkflowEventFamily.REVIEW_REQUIRED,
        severity=WorkflowEventSeverity.ACTION_REQUIRED,
        report_impact=WorkflowReportImpact.BLOCKED,
        action_href="/review",
        title="Newer active event",
        occurred_at=now - timedelta(minutes=1),
    )
    await _create_event(
        db,
        user_id=other_user.id,
        family=WorkflowEventFamily.REPORT_BLOCKED,
        severity=WorkflowEventSeverity.BLOCKED,
        report_impact=WorkflowReportImpact.BLOCKED,
        action_href="/reports",
        title="Other user event",
        occurred_at=now,
    )
    await db.commit()

    response = await client.get("/workflow/events")
    assert response.status_code == 200
    data = WorkflowEventListResponse.model_validate(response.json())
    assert data.total == 2
    assert [item.id for item in data.items] == [newer.id, older.id]
    assert all(item.session_id is not None for item in data.items)
    assert len(data.sessions) == 1
    assert data.sessions[0].source_count == 2

    limited = await client.get("/workflow/events?limit=1")
    assert limited.status_code == 200
    limited_data = WorkflowEventListResponse.model_validate(limited.json())
    assert limited_data.total == 2
    assert [item.id for item in limited_data.items] == [newer.id]

    archived_response = await client.get("/workflow/events?status=archived")
    assert archived_response.status_code == 200
    archived_data = WorkflowEventListResponse.model_validate(archived_response.json())
    assert archived_data.total == 1
    assert [item.id for item in archived_data.items] == [archived.id]


async def test_AC19_2_4_workflow_event_patch_is_user_scoped(
    client: AsyncClient,
    public_client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC19.2.4: PATCH /workflow/events/{id} updates only the authenticated user's event."""
    other_user = User(email=f"patch-other-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other_user)
    await db.flush()

    event = await _create_event(
        db,
        user_id=test_user.id,
        family=WorkflowEventFamily.REVIEW_REQUIRED,
        severity=WorkflowEventSeverity.ACTION_REQUIRED,
        report_impact=WorkflowReportImpact.BLOCKED,
        action_href="/review",
        title="Patch owned event",
    )
    await db.commit()

    response = await client.patch(f"/workflow/events/{event.id}", json={"status": "read"})
    assert response.status_code == 200
    assert response.json()["status"] == "read"

    app.dependency_overrides[get_current_user_id] = lambda: other_user.id
    try:
        forbidden = await public_client.patch(f"/workflow/events/{event.id}", json={"status": "archived"})
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)

    assert forbidden.status_code == 404
    await db.refresh(event)
    assert event.status == WorkflowEventStatus.READ

    missing = await client.patch(f"/workflow/events/{uuid4()}", json={"status": "read"})
    assert missing.status_code == 404


async def test_AC19_2_5_workflow_reads_sync_derived_events_without_lifecycle_reset(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC19.2.5: workflow reads derive statement events idempotently without lifecycle reset."""
    statement = await _make_statement(
        db,
        test_user.id,
        original_filename="idempotent.csv",
        file_hash="d" * 64,
    )
    await db.commit()

    first = await client.get("/workflow/events")
    assert first.status_code == 200
    first_data = WorkflowEventListResponse.model_validate(first.json())
    assert first_data.total == 1
    event_id = first_data.items[0].id
    assert first_data.items[0].session_id is not None
    assert first_data.sessions[0].title == "Upload-to-report session"

    patch = await client.patch(f"/workflow/events/{event_id}", json={"status": "archived"})
    assert patch.status_code == 200

    second = await client.get("/workflow/status")
    assert second.status_code == 200

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
    assert events[0].id == event_id
    assert events[0].status == WorkflowEventStatus.ARCHIVED
    workflow_session = await db.scalar(select(WorkflowSession).where(WorkflowSession.id == first_data.sessions[0].id))
    assert workflow_session is not None
    assert workflow_session.source_count == 0


async def test_AC19_2_6_workflow_router_and_ssot_document_compact_read_path() -> None:
    """AC19.2.6: workflow router is mounted and documented as the compact read path."""
    route_paths = {route.path for route in app.routes}
    assert "/workflow/status" in route_paths
    assert "/workflow/events" in route_paths
    assert "/workflow/events/{event_id}" in route_paths

    ssot = (ROOT_DIR / "docs" / "ssot" / "workflow-events.md").read_text(encoding="utf-8")
    assert "GET /workflow/status" in ssot
    assert "GET /workflow/events" in ssot
    assert "PATCH /workflow/events/{event_id}" in ssot
    assert "GET /api/reports/package/readiness" in ssot
    assert "generated -> ready" in ssot


async def test_AC19_8_3_workflow_status_and_events_expose_session_timeline(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC19.8.3: workflow status exposes active session and events return session-scoped timeline data."""
    await _make_statement(
        db,
        test_user.id,
        original_filename="session-demo.csv",
        file_hash="f" * 64,
    )
    await db.commit()

    status_response = await client.get("/workflow/status")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    active_session = status_payload["active_session"]
    assert active_session["status"] == "active"
    assert active_session["title"] == "Upload-to-report session"
    assert active_session["primary_state"] == "processing"
    assert active_session["event_counts"] == {"unread": 1, "action_required": 0, "blocked": 0}

    events_response = await client.get("/workflow/events")
    assert events_response.status_code == 200
    events_payload = events_response.json()
    assert events_payload["items"][0]["session_id"] == active_session["id"]
    assert events_payload["sessions"][0]["id"] == active_session["id"]
    assert events_payload["sessions"][0]["last_event_at"] == events_payload["items"][0]["occurred_at"]
