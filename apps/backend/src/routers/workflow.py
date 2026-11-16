"""Workflow status and event API router."""

from uuid import UUID

from fastapi import APIRouter, Query

from src.deps import CurrentUserId, DbSession
from src.platform import ResourceNotFoundError
from src.schemas.workflow import (
    WorkflowEventListResponse,
    WorkflowEventResponse,
    WorkflowEventStatusUpdate,
    WorkflowStatusResponse,
)
from src.workflow import (
    WorkflowEventStatus,
    get_workflow_status,
    list_workflow_events_response,
    update_workflow_event_status,
)

router = APIRouter(prefix="/workflow", tags=["workflow"])


@router.get("/status", response_model=WorkflowStatusResponse)
async def get_workflow_status_endpoint(
    db: DbSession,
    user_id: CurrentUserId,
) -> WorkflowStatusResponse:
    """Return the compact user-scoped upload-to-report workflow status."""
    return await get_workflow_status(db, user_id=user_id)


@router.get("/events", response_model=WorkflowEventListResponse)
async def list_workflow_events_endpoint(
    db: DbSession,
    user_id: CurrentUserId,
    status_filter: WorkflowEventStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
) -> WorkflowEventListResponse:
    """Return a bounded user-scoped workflow event list."""
    return await list_workflow_events_response(
        db,
        user_id=user_id,
        status=status_filter,
        limit=limit,
    )


@router.patch("/events/{event_id}", response_model=WorkflowEventResponse)
async def update_workflow_event_status_endpoint(
    event_id: UUID,
    payload: WorkflowEventStatusUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> WorkflowEventResponse:
    """Update one user-owned workflow event lifecycle state."""
    event = await update_workflow_event_status(
        db,
        event_id=event_id,
        user_id=user_id,
        status=payload.status,
    )
    if event is None:
        raise ResourceNotFoundError("Workflow event not found")

    await db.flush()
    await db.refresh(event)
    return WorkflowEventResponse.model_validate(event)
