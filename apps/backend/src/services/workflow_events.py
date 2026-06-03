"""Deterministic user-facing workflow event derivation."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import BankStatement
from src.models.workflow import (
    WorkflowEvent,
    WorkflowEventFamily,
    WorkflowEventSeverity,
    WorkflowEventStatus,
    WorkflowReportImpact,
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


async def upsert_workflow_event(
    db: AsyncSession,
    *,
    user_id: UUID,
    payload: WorkflowEventCreate,
) -> WorkflowEvent:
    """Create or update a deterministic workflow event without committing."""
    result = await db.execute(
        select(WorkflowEvent)
        .where(WorkflowEvent.user_id == user_id)
        .where(WorkflowEvent.dedupe_key == payload.dedupe_key)
    )
    event = result.scalar_one_or_none()
    if event is None:
        event = WorkflowEvent(
            user_id=user_id,
            occurred_at=payload.occurred_at,
            family=payload.family,
            severity=payload.severity,
            status=WorkflowEventStatus.UNREAD,
            title=payload.title,
            summary=payload.summary,
            source_type=payload.source_type,
            source_id=payload.source_id,
            action_href=payload.action_href,
            report_impact=payload.report_impact,
            dedupe_key=payload.dedupe_key,
        )
        db.add(event)
    else:
        event.occurred_at = payload.occurred_at
        event.family = payload.family
        event.severity = payload.severity
        event.title = payload.title
        event.summary = payload.summary
        event.source_type = payload.source_type
        event.source_id = payload.source_id
        event.action_href = payload.action_href
        event.report_impact = payload.report_impact

    await db.flush()
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

    family = WorkflowEventFamily.SOURCE_UPLOADED
    payload = WorkflowEventCreate(
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
    return await upsert_workflow_event(db, user_id=user_id, payload=payload)


async def sync_workflow_events_for_user(db: AsyncSession, *, user_id: UUID) -> None:
    """Derive deterministic workflow events from existing user-owned records."""
    existing_uploaded_event = (
        select(WorkflowEvent.id)
        .where(WorkflowEvent.user_id == user_id)
        .where(WorkflowEvent.source_type == "bank_statement")
        .where(WorkflowEvent.source_id == BankStatement.id)
        .where(WorkflowEvent.family == WorkflowEventFamily.SOURCE_UPLOADED)
        .exists()
    )
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.user_id == user_id)
        .where(~existing_uploaded_event)
        .order_by(BankStatement.created_at.asc())
    )
    for statement in result.scalars().all():
        await derive_uploaded_statement_event(db, statement, user_id=user_id)


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
    return WorkflowEventListResponse(
        items=[WorkflowEventResponse.model_validate(event) for event in events],
        total=int(total or 0),
    )


async def get_workflow_status(db: AsyncSession, *, user_id: UUID) -> WorkflowStatusResponse:
    """Return the compact workflow status for primary UI surfaces."""
    await sync_workflow_events_for_user(db, user_id=user_id)
    package_readiness = await get_personal_report_package_readiness(db, user_id=user_id)
    package_readiness_state = _collapse_package_readiness_state(str(package_readiness["state"]))
    package_blocking_count = int(package_readiness["blocking_count"])

    active_filters = [WorkflowEvent.user_id == user_id, WorkflowEvent.status != WorkflowEventStatus.ARCHIVED]

    async def count_where(*filters: object) -> int:
        value = await db.scalar(select(func.count(WorkflowEvent.id)).where(*active_filters, *filters))
        return int(value or 0)

    async def representative_event(*filters: object) -> WorkflowEvent | None:
        result = await db.execute(
            select(WorkflowEvent)
            .where(*active_filters, *filters)
            .order_by(WorkflowEvent.occurred_at.desc(), WorkflowEvent.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    active_count = await count_where()
    unread_count = await count_where(WorkflowEvent.status == WorkflowEventStatus.UNREAD)
    action_required_count = await count_where(WorkflowEvent.severity == WorkflowEventSeverity.ACTION_REQUIRED)
    blocked_count = await count_where(WorkflowEvent.severity == WorkflowEventSeverity.BLOCKED)
    processing_count = await count_where(WorkflowEvent.report_impact == WorkflowReportImpact.PROCESSING)
    ready_count = await count_where(WorkflowEvent.report_impact == WorkflowReportImpact.READY)

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

    return WorkflowStatusResponse(
        primary_state=primary_state,
        next_action=next_action,
        report_readiness=readiness,
        event_counts=WorkflowEventCountsResponse(
            unread=unread_count,
            action_required=action_required_count,
            blocked=blocked_count,
        ),
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
    return event
