"""Deterministic user-facing workflow event derivation."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import BankStatement
from src.models.workflow import WorkflowEvent, WorkflowEventFamily, WorkflowEventSeverity, WorkflowEventStatus
from src.schemas.workflow import WorkflowEventCreate


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
        report_impact="processing",
        dedupe_key=build_workflow_dedupe_key(
            family=family,
            source_type="bank_statement",
            source_id=statement.id,
        ),
    )
    return await upsert_workflow_event(db, user_id=user_id, payload=payload)


async def list_workflow_events(
    db: AsyncSession,
    *,
    user_id: UUID,
    status: WorkflowEventStatus | None = None,
    limit: int = 50,
) -> list[WorkflowEvent]:
    """List user-scoped workflow events for inbox/status consumers."""
    stmt = select(WorkflowEvent).where(WorkflowEvent.user_id == user_id)
    if status is not None:
        stmt = stmt.where(WorkflowEvent.status == status)
    stmt = stmt.order_by(WorkflowEvent.occurred_at.desc(), WorkflowEvent.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


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
