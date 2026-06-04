"""Deterministic user-facing workflow event derivation."""

from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.models import BankStatement
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
    WorkflowEventCountsResponse,
    WorkflowEventCreate,
    WorkflowEventListResponse,
    WorkflowEventResponse,
    WorkflowNextActionResponse,
    WorkflowNextActionType,
    WorkflowPrimaryState,
    WorkflowReportReadinessResponse,
    WorkflowReportReadinessState,
    WorkflowSessionSummaryResponse,
    WorkflowStatusResponse,
)
from src.services.report_readiness import get_personal_report_package_readiness


def _collapse_package_readiness_state(state: str) -> WorkflowReportReadinessState:
    """Collapse package readiness into the compact workflow vocabulary."""
    if state == "draft":
        return WorkflowReportReadinessState.NONE
    if state == "processing":
        return WorkflowReportReadinessState.PROCESSING
    if state == "blocked":
        return WorkflowReportReadinessState.BLOCKED
    if state in {"ready", "generated"}:
        return WorkflowReportReadinessState.READY
    if state == "stale":
        return WorkflowReportReadinessState.STALE
    return WorkflowReportReadinessState.NONE


def build_workflow_dedupe_key(*, family: WorkflowEventFamily, source_type: str, source_id: UUID) -> str:
    """Build the stable per-user dedupe key for a source-derived workflow event."""
    return f"{source_type}:{source_id}:{family.value}"


async def get_or_create_active_workflow_session(db: AsyncSession, *, user_id: UUID) -> WorkflowSession:
    """Return the user's active upload-to-report session, creating the v1 synthetic session when needed."""
    result = await db.execute(
        select(WorkflowSession)
        .where(WorkflowSession.user_id == user_id)
        .where(WorkflowSession.status == WorkflowSessionStatus.ACTIVE)
        .where(WorkflowSession.dedupe_key == "active-upload-to-report")
        .order_by(WorkflowSession.created_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if session is not None:
        return session

    session = WorkflowSession(
        user_id=user_id,
        status=WorkflowSessionStatus.ACTIVE,
        title="Upload-to-report session",
        summary="Current upload, processing, review, and report-readiness work.",
        dedupe_key="active-upload-to-report",
        source_count=0,
    )
    db.add(session)
    await db.flush()
    return session


def _apply_workflow_event_payload(event: WorkflowEvent, payload: WorkflowEventCreate) -> None:
    event.occurred_at = payload.occurred_at
    event.family = payload.family
    event.severity = payload.severity
    event.title = payload.title
    event.summary = payload.summary
    event.source_type = payload.source_type
    event.source_id = payload.source_id
    event.action_href = payload.action_href
    event.report_impact = payload.report_impact
    event.dedupe_key = payload.dedupe_key


def _workflow_event_from_payload(
    *,
    user_id: UUID,
    payload: WorkflowEventCreate,
    session_id: UUID | None = None,
) -> WorkflowEvent:
    event = WorkflowEvent(user_id=user_id, status=WorkflowEventStatus.UNREAD, session_id=session_id)
    _apply_workflow_event_payload(event, payload)
    return event


def build_uploaded_statement_event_payload(statement: BankStatement) -> WorkflowEventCreate:
    """Build the deterministic uploaded-statement workflow event payload."""
    family = WorkflowEventFamily.SOURCE_UPLOADED
    return WorkflowEventCreate(
        occurred_at=statement.created_at,
        family=family,
        severity=WorkflowEventSeverity.INFO,
        title="Statement uploaded",
        summary=f"{statement.original_filename} was uploaded and is ready for processing.",
        source_type="bank_statement",
        source_id=statement.id,
        action_href=f"/statements/{statement.id}",
        report_impact=WorkflowReportImpact.PROCESSING,
        dedupe_key=build_workflow_dedupe_key(
            family=family,
            source_type="bank_statement",
            source_id=statement.id,
        ),
    )


async def upsert_workflow_event(
    db: AsyncSession,
    *,
    user_id: UUID,
    payload: WorkflowEventCreate,
    session_id: UUID | None = None,
) -> WorkflowEvent:
    """Create or update a deterministic workflow event without committing."""
    workflow_session = None
    if session_id is None:
        workflow_session = await get_or_create_active_workflow_session(db, user_id=user_id)
        session_id = workflow_session.id

    result = await db.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.user_id == user_id)
        .where(WorkflowEvent.dedupe_key == payload.dedupe_key)
    )
    event = result.scalar_one_or_none()
    if event is None:
        event = _workflow_event_from_payload(user_id=user_id, payload=payload, session_id=session_id)
        db.add(event)
    else:
        _apply_workflow_event_payload(event, payload)
        if event.session_id is None:
            event.session_id = session_id

    await db.flush()
    await refresh_workflow_session_summary(db, user_id=user_id, session_id=session_id)
    return event


async def derive_uploaded_statement_event(
    db: AsyncSession,
    statement: BankStatement,
    *,
    user_id: UUID,
) -> WorkflowEvent:
    """Upsert the initial uploaded-statement workflow event."""
    if statement.user_id != user_id:
        raise ValueError("statement.user_id must match user_id")

    payload = build_uploaded_statement_event_payload(statement)
    return await upsert_workflow_event(db, user_id=user_id, payload=payload)


async def sync_workflow_events_for_user(db: AsyncSession, *, user_id: UUID) -> None:
    """Derive deterministic workflow events from existing user-owned records."""
    workflow_session: WorkflowSession | None = None
    existing_event = aliased(WorkflowEvent)
    result = await db.execute(
        select(BankStatement, existing_event)
        .outerjoin(
            existing_event,
            and_(
                existing_event.user_id == user_id,
                existing_event.family == WorkflowEventFamily.SOURCE_UPLOADED,
                existing_event.source_type == "bank_statement",
                existing_event.source_id == BankStatement.id,
            ),
        )
        .where(BankStatement.user_id == user_id)
        .order_by(BankStatement.created_at.asc())
    )
    for statement, event in result.all():
        if workflow_session is None:
            workflow_session = await get_or_create_active_workflow_session(db, user_id=user_id)
        payload = build_uploaded_statement_event_payload(statement)
        if event is None:
            db.add(_workflow_event_from_payload(user_id=user_id, payload=payload, session_id=workflow_session.id))
        else:
            _apply_workflow_event_payload(event, payload)
            if event.session_id is None:
                event.session_id = workflow_session.id

    await db.flush()
    if workflow_session is not None:
        await refresh_workflow_session_summary(db, user_id=user_id, session_id=workflow_session.id)


async def refresh_workflow_session_summary(
    db: AsyncSession,
    *,
    user_id: UUID,
    session_id: UUID | None,
) -> None:
    """Refresh denormalized session counts from its event timeline."""
    if session_id is None:
        return
    result = await db.execute(
        select(WorkflowSession).where(WorkflowSession.id == session_id).where(WorkflowSession.user_id == user_id)
    )
    workflow_session = result.scalar_one_or_none()
    if workflow_session is None:
        return

    aggregate = (
        await db.execute(
            select(
                func.count(WorkflowEvent.id).label("event_count"),
                func.max(WorkflowEvent.occurred_at).label("last_event_at"),
            )
            .where(WorkflowEvent.user_id == user_id)
            .where(WorkflowEvent.session_id == session_id)
            .where(WorkflowEvent.status != WorkflowEventStatus.ARCHIVED)
        )
    ).one()
    workflow_session.source_count = int(aggregate.event_count or 0)
    workflow_session.last_event_at = aggregate.last_event_at


async def list_workflow_events(
    db: AsyncSession,
    *,
    user_id: UUID,
    status: WorkflowEventStatus | None = None,
    limit: int = 50,
    include_archived: bool = False,
) -> list[WorkflowEvent]:
    """List user-scoped workflow events for inbox/status consumers."""
    stmt = select(WorkflowEvent).where(WorkflowEvent.user_id == user_id)
    if status is not None:
        stmt = stmt.where(WorkflowEvent.status == status)
    elif not include_archived:
        stmt = stmt.where(WorkflowEvent.status != WorkflowEventStatus.ARCHIVED)
    stmt = stmt.order_by(WorkflowEvent.occurred_at.desc(), WorkflowEvent.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_workflow_events_response(
    db: AsyncSession,
    *,
    user_id: UUID,
    status: WorkflowEventStatus | None = None,
    limit: int = 50,
) -> WorkflowEventListResponse:
    """Return a bounded event list plus total count for the same filter."""
    await sync_workflow_events_for_user(db, user_id=user_id)

    filters = [WorkflowEvent.user_id == user_id]
    if status is not None:
        filters.append(WorkflowEvent.status == status)
    else:
        filters.append(WorkflowEvent.status != WorkflowEventStatus.ARCHIVED)

    total = await db.scalar(select(func.count(WorkflowEvent.id)).where(*filters))
    events = await list_workflow_events(
        db,
        user_id=user_id,
        status=status,
        limit=limit,
        include_archived=False,
    )
    session_ids = {event.session_id for event in events if event.session_id is not None}
    sessions: list[WorkflowSessionSummaryResponse] = []
    if session_ids:
        session_result = await db.execute(
            select(WorkflowSession)
            .where(WorkflowSession.user_id == user_id)
            .where(WorkflowSession.id.in_(session_ids))
            .order_by(WorkflowSession.last_event_at.desc().nullslast(), WorkflowSession.created_at.desc())
        )
        sessions = [
            await build_workflow_session_summary(
                db,
                workflow_session=session,
                primary_state=WorkflowPrimaryState.READY,
                report_readiness=None,
            )
            for session in session_result.scalars().all()
        ]

    return WorkflowEventListResponse(
        items=[WorkflowEventResponse.model_validate(event) for event in events],
        total=int(total or 0),
        sessions=sessions,
    )


async def build_workflow_session_summary(
    db: AsyncSession,
    *,
    workflow_session: WorkflowSession,
    primary_state: WorkflowPrimaryState,
    report_readiness: WorkflowReportReadinessResponse | None,
) -> WorkflowSessionSummaryResponse:
    """Build a compact session summary for status and timeline grouping."""
    aggregate = (
        await db.execute(
            select(
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.status == WorkflowEventStatus.UNREAD)
                .label("unread_count"),
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.severity == WorkflowEventSeverity.ACTION_REQUIRED)
                .label("action_required_count"),
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.severity == WorkflowEventSeverity.BLOCKED)
                .label("blocked_count"),
            )
            .where(WorkflowEvent.user_id == workflow_session.user_id)
            .where(WorkflowEvent.session_id == workflow_session.id)
            .where(WorkflowEvent.status != WorkflowEventStatus.ARCHIVED)
        )
    ).one()
    return WorkflowSessionSummaryResponse(
        id=workflow_session.id,
        status=workflow_session.status,
        title=workflow_session.title,
        summary=workflow_session.summary,
        started_at=workflow_session.started_at,
        last_event_at=workflow_session.last_event_at,
        source_count=workflow_session.source_count,
        report_href=workflow_session.report_href,
        primary_state=primary_state,
        report_readiness=report_readiness
        or WorkflowReportReadinessResponse(state=WorkflowReportReadinessState.NONE, blocking_count=0, href="/reports"),
        event_counts=WorkflowEventCountsResponse(
            unread=int(aggregate.unread_count or 0),
            action_required=int(aggregate.action_required_count or 0),
            blocked=int(aggregate.blocked_count or 0),
        ),
    )


async def get_workflow_status(db: AsyncSession, *, user_id: UUID) -> WorkflowStatusResponse:
    """Return the compact workflow status for primary UI surfaces."""
    await sync_workflow_events_for_user(db, user_id=user_id)
    package_readiness = await get_personal_report_package_readiness(db, user_id=user_id)
    package_readiness_state = _collapse_package_readiness_state(str(package_readiness["state"]))
    package_blocking_count = int(package_readiness["blocking_count"])

    active_filters = [WorkflowEvent.user_id == user_id, WorkflowEvent.status != WorkflowEventStatus.ARCHIVED]

    async def representative_event(*filters: object) -> WorkflowEvent | None:
        result = await db.execute(
            select(WorkflowEvent)
            .where(*active_filters, *filters)
            .order_by(WorkflowEvent.occurred_at.desc(), WorkflowEvent.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    aggregate_row = (
        await db.execute(
            select(
                func.count(WorkflowEvent.id).label("active_count"),
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.status == WorkflowEventStatus.UNREAD)
                .label("unread_count"),
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.severity == WorkflowEventSeverity.ACTION_REQUIRED)
                .label("action_required_count"),
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.severity == WorkflowEventSeverity.BLOCKED)
                .label("blocked_count"),
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.report_impact == WorkflowReportImpact.PROCESSING)
                .label("processing_count"),
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.report_impact == WorkflowReportImpact.READY)
                .label("ready_count"),
            ).where(*active_filters)
        )
    ).one()

    active_count = int(aggregate_row.active_count or 0)
    unread_count = int(aggregate_row.unread_count or 0)
    action_required_count = int(aggregate_row.action_required_count or 0)
    blocked_count = int(aggregate_row.blocked_count or 0)
    processing_count = int(aggregate_row.processing_count or 0)
    ready_count = int(aggregate_row.ready_count or 0)

    if blocked_count or package_readiness_state == WorkflowReportReadinessState.BLOCKED:
        blocked_event = await representative_event(WorkflowEvent.severity == WorkflowEventSeverity.BLOCKED)
        primary_state = WorkflowPrimaryState.BLOCKED
        next_action = WorkflowNextActionResponse(
            type=WorkflowNextActionType.RESOLVE_BLOCKER,
            count=max(blocked_count, package_blocking_count),
            href=blocked_event.action_href if blocked_event else str(package_readiness["action_href"]),
        )
    elif action_required_count:
        action_required_event = await representative_event(
            WorkflowEvent.severity == WorkflowEventSeverity.ACTION_REQUIRED
        )
        primary_state = WorkflowPrimaryState.NEEDS_ACTION
        next_action = WorkflowNextActionResponse(
            type=WorkflowNextActionType.REVIEW_REQUIRED,
            count=action_required_count,
            href=action_required_event.action_href if action_required_event else "/review",
        )
    elif processing_count or package_readiness_state == WorkflowReportReadinessState.PROCESSING:
        primary_state = WorkflowPrimaryState.PROCESSING
        next_action = WorkflowNextActionResponse(
            type=WorkflowNextActionType.WAIT,
            count=max(processing_count, 1),
            href="/statements",
        )
    elif ready_count or package_readiness_state in {
        WorkflowReportReadinessState.READY,
        WorkflowReportReadinessState.STALE,
    }:
        primary_state = WorkflowPrimaryState.READY
        next_action = WorkflowNextActionResponse(
            type=WorkflowNextActionType.OPEN_REPORT,
            count=max(ready_count, 1),
            href="/reports",
        )
    elif active_count:
        primary_state = WorkflowPrimaryState.READY
        next_action = WorkflowNextActionResponse(type=WorkflowNextActionType.NONE, count=0, href="/events")
    else:
        primary_state = WorkflowPrimaryState.EMPTY
        next_action = WorkflowNextActionResponse(
            type=WorkflowNextActionType.UPLOAD,
            count=0,
            href="/statements/upload",
        )

    readiness = WorkflowReportReadinessResponse(
        state=package_readiness_state,
        blocking_count=package_blocking_count,
        href="/reports",
    )

    active_session_result = await db.execute(
        select(WorkflowSession)
        .where(WorkflowSession.user_id == user_id)
        .where(WorkflowSession.status == WorkflowSessionStatus.ACTIVE)
        .order_by(WorkflowSession.last_event_at.desc().nullslast(), WorkflowSession.created_at.desc())
        .limit(1)
    )
    active_session = active_session_result.scalar_one_or_none()
    active_session_summary = None
    if active_session is not None and (active_count or active_session.source_count):
        active_session_summary = WorkflowSessionSummaryResponse(
            id=active_session.id,
            status=active_session.status,
            title=active_session.title,
            summary=active_session.summary,
            started_at=active_session.started_at,
            last_event_at=active_session.last_event_at,
            source_count=active_session.source_count,
            report_href=active_session.report_href,
            primary_state=primary_state,
            report_readiness=readiness,
            event_counts=WorkflowEventCountsResponse(
                unread=unread_count,
                action_required=action_required_count,
                blocked=blocked_count,
            ),
        )

    return WorkflowStatusResponse(
        primary_state=primary_state,
        next_action=next_action,
        report_readiness=readiness,
        event_counts=WorkflowEventCountsResponse(
            unread=unread_count,
            action_required=action_required_count,
            blocked=blocked_count,
        ),
        active_session=active_session_summary,
    )


async def update_workflow_event_status(
    db: AsyncSession,
    *,
    event_id: UUID,
    user_id: UUID,
    status: WorkflowEventStatus,
) -> WorkflowEvent | None:
    """Update read/archive lifecycle state for one user-scoped event."""
    result = await db.execute(
        select(WorkflowEvent).where(WorkflowEvent.id == event_id).where(WorkflowEvent.user_id == user_id)
    )
    event = result.scalar_one_or_none()
    if event is None:
        return None
    event.status = status
    await db.flush()
    await refresh_workflow_session_summary(db, user_id=user_id, session_id=event.session_id)
    return event
