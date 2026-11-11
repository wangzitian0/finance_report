"""Deterministic user-facing workflow event derivation."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from src.extraction import get_statement_event_sources, get_uploaded_document_filenames
from src.reconciliation import count_pending_review_items
from src.reporting import ReportError, current_package_readiness
from src.schemas.reporting import (
    PersonalReportPackageReadinessBlocker,
    PersonalReportPackageReadinessResponse,
    PersonalReportPackageReadinessState,
)
from src.workflow.base.types import (
    WorkflowEventCountsResponse,
    WorkflowEventCreate,
    WorkflowEventFamily,
    WorkflowEventListResponse,
    WorkflowEventResponse,
    WorkflowEventSeverity,
    WorkflowEventStatus,
    WorkflowNextActionResponse,
    WorkflowNextActionType,
    WorkflowPrimaryState,
    WorkflowReportImpact,
    WorkflowReportReadinessResponse,
    WorkflowReportReadinessState,
    WorkflowSessionStatus,
    WorkflowSessionSummaryResponse,
    WorkflowStatusResponse,
)
from src.workflow.extension.builders import (  # noqa: F401
    PACKAGE_WORKFLOW_SOURCE_ID,
    build_readiness_blocker_event_payload,
    build_reconciliation_review_event_payload,
    build_report_state_event_payload,
    build_review_completed_event_payload,
    build_review_rejected_event_payload,
    build_review_required_event_payload,
    build_statement_parsing_failed_event_payload,
    build_uploaded_statement_event_payload,
    build_workflow_dedupe_key,
)
from src.workflow.extension.source_fingerprint import workflow_source_fingerprint
from src.workflow.orm.models import WorkflowEvent, WorkflowSession, WorkflowSyncState

_STATUS_REJECTED = "rejected"
_STATUS_PARSED = "parsed"
_STAGE1_PENDING_REVIEW = "pending_review"
_STAGE1_APPROVED = "approved"
_STAGE1_REJECTED = "rejected"
_STAGE1_EDITED = "edited"

ACTIVE_WORKFLOW_SESSION_DEDUPE_KEY = "active-upload-to-report"
WORKFLOW_SYNC_STATE_MAX_AGE = timedelta(minutes=15)
MUTABLE_DERIVED_EVENT_SOURCE_TYPES = {"bank_statement", "readiness_blocker", "reconciliation", "report_package"}
MUTABLE_DERIVED_EVENT_FAMILIES = {
    WorkflowEventFamily.SOURCE_PARSING_FAILED,
    WorkflowEventFamily.REVIEW_REQUIRED,
    WorkflowEventFamily.REVIEW_COMPLETED,
    WorkflowEventFamily.RECONCILIATION_BLOCKED,
    WorkflowEventFamily.REPORT_READY,
    WorkflowEventFamily.REPORT_BLOCKED,
    WorkflowEventFamily.REPORT_GENERATED,
}

_NEXT_ACTION_COPY: dict[WorkflowNextActionType, tuple[str, str]] = {
    WorkflowNextActionType.UPLOAD: (
        "Upload statements",
        "Add source documents to start the upload-to-report workflow.",
    ),
    WorkflowNextActionType.WAIT: (
        "View processing",
        "Automation is processing source files; open the session timeline for progress.",
    ),
    WorkflowNextActionType.REVIEW_REQUIRED: (
        "Review required",
        "Confirm the source or review item so trusted report preparation can continue.",
    ),
    WorkflowNextActionType.RESOLVE_BLOCKER: (
        "Resolve blocker",
        "Resolve the blocking condition before the report package can be trusted.",
    ),
    WorkflowNextActionType.OPEN_REPORT: (
        "Open report package",
        "Inspect the personal report package and its readiness evidence.",
    ),
    WorkflowNextActionType.NONE: ("Open workflow", "Open workflow history for details."),
}

_EVENT_PAYLOAD_FIELDS = (
    "occurred_at",
    "family",
    "severity",
    "title",
    "summary",
    "source_type",
    "source_id",
    "action_href",
    "report_impact",
    "dedupe_key",
)


def _collapse_package_readiness_state(state: str) -> WorkflowReportReadinessState:
    if state == "blocked":
        return WorkflowReportReadinessState.BLOCKED
    if state == "ready":
        return WorkflowReportReadinessState.READY
    return WorkflowReportReadinessState.NONE


def _next_action(action_type: WorkflowNextActionType, *, count: int, href: str) -> WorkflowNextActionResponse:
    label, summary = _NEXT_ACTION_COPY[action_type]
    return WorkflowNextActionResponse(type=action_type, count=count, href=href, label=label, summary=summary)


def _session_summary_model(
    workflow_session: WorkflowSession,
    *,
    primary_state: WorkflowPrimaryState,
    report_readiness: WorkflowReportReadinessResponse | None,
    counts: WorkflowEventCountsResponse,
) -> WorkflowSessionSummaryResponse:
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
        event_counts=counts,
    )


async def _get_active_workflow_session(db: AsyncSession, *, user_id: UUID) -> WorkflowSession | None:
    return await db.scalar(
        select(WorkflowSession)
        .where(
            WorkflowSession.user_id == user_id,
            WorkflowSession.status == WorkflowSessionStatus.ACTIVE,
            WorkflowSession.dedupe_key == ACTIVE_WORKFLOW_SESSION_DEDUPE_KEY,
        )
        .order_by(WorkflowSession.created_at.desc())
        .limit(1)
    )


async def get_or_create_active_workflow_session(db: AsyncSession, *, user_id: UUID) -> WorkflowSession:
    """Return or create the user's active upload-to-report session."""
    session = await _get_active_workflow_session(db, user_id=user_id)
    if session is not None:
        return session

    session_defaults = {
        "status": WorkflowSessionStatus.ACTIVE,
        "title": "Upload-to-report session",
        "summary": "Current upload, processing, review, and report-readiness work.",
    }
    inserted_id = (
        await db.execute(
            postgresql_insert(WorkflowSession)
            .values(
                user_id=user_id,
                dedupe_key=ACTIVE_WORKFLOW_SESSION_DEDUPE_KEY,
                source_count=0,
                **session_defaults,
            )
            .on_conflict_do_nothing(constraint="uq_workflow_sessions_user_dedupe_key")
            .returning(WorkflowSession.id)
        )
    ).scalar_one_or_none()
    if inserted_id is not None:
        return (await db.execute(select(WorkflowSession).where(WorkflowSession.id == inserted_id))).scalar_one()

    session = await _get_active_workflow_session(db, user_id=user_id)
    if session is None:
        session = await db.scalar(
            select(WorkflowSession).where(
                WorkflowSession.user_id == user_id,
                WorkflowSession.dedupe_key == ACTIVE_WORKFLOW_SESSION_DEDUPE_KEY,
            )
        )
        if session is None:
            raise RuntimeError("active workflow session upsert returned no row and no existing session")
        for attr, val in session_defaults.items():
            setattr(session, attr, val)
        if session.source_count is None:
            session.source_count = 0
    return session


def _apply_workflow_event_payload(event: WorkflowEvent, payload: WorkflowEventCreate, session_id: UUID | None = None) -> None:
    for field in _EVENT_PAYLOAD_FIELDS:
        setattr(event, field, getattr(payload, field))
    if session_id is not None and event.session_id is None:
        event.session_id = session_id


def _workflow_event_from_payload(
    *, user_id: UUID, payload: WorkflowEventCreate, session_id: UUID | None = None
) -> WorkflowEvent:
    event = WorkflowEvent(user_id=user_id, status=WorkflowEventStatus.UNREAD, session_id=session_id)
    _apply_workflow_event_payload(event, payload)
    return event


async def _get_workflow_event_by_dedupe_key(
    db: AsyncSession, *, user_id: UUID, dedupe_key: str
) -> WorkflowEvent | None:
    return await db.scalar(
        select(WorkflowEvent).where(WorkflowEvent.user_id == user_id, WorkflowEvent.dedupe_key == dedupe_key)
    )


async def _insert_workflow_event_conflict_safe(
    db: AsyncSession,
    *,
    user_id: UUID,
    payload: WorkflowEventCreate,
    session_id: UUID | None,
) -> WorkflowEvent:
    """Insert a workflow event inside a savepoint so dedupe-key races never poison the outer transaction."""
    event = _workflow_event_from_payload(user_id=user_id, payload=payload, session_id=session_id)
    try:
        async with db.begin_nested():
            db.add(event)
            await db.flush()
    except IntegrityError:
        existing = await _get_workflow_event_by_dedupe_key(db, user_id=user_id, dedupe_key=payload.dedupe_key)
        if existing is None:
            raise
        _apply_workflow_event_payload(existing, payload, session_id)
        return existing
    return event


async def _apply_or_insert_event(
    db: AsyncSession,
    *,
    user_id: UUID,
    existing: WorkflowEvent | None,
    payload: WorkflowEventCreate,
    session_id: UUID,
) -> WorkflowEvent:
    if existing is None:
        return await _insert_workflow_event_conflict_safe(db, user_id=user_id, payload=payload, session_id=session_id)
    _apply_workflow_event_payload(existing, payload, session_id)
    return existing


async def upsert_workflow_event(
    db: AsyncSession,
    *,
    user_id: UUID,
    payload: WorkflowEventCreate,
    session_id: UUID | None = None,
) -> WorkflowEvent:
    """Create or update a deterministic workflow event without committing."""
    if session_id is None:
        session_id = (await get_or_create_active_workflow_session(db, user_id=user_id)).id

    existing = await _get_workflow_event_by_dedupe_key(db, user_id=user_id, dedupe_key=payload.dedupe_key)
    event = await _apply_or_insert_event(db, user_id=user_id, existing=existing, payload=payload, session_id=session_id)
    await db.flush()
    await refresh_workflow_session_summary(db, user_id=user_id, session_id=session_id)
    return event


async def sync_workflow_events_for_user(db: AsyncSession, *, user_id: UUID) -> dict:
    """Derive deterministic workflow events from user records and return package readiness (#987, #1675)."""
    workflow_session: WorkflowSession | None = None
    statement_rows = await get_statement_event_sources(db, user_id)
    existing_event_by_source_id = (
        {
            e.source_id: e
            for e in (
                await db.scalars(
                    select(WorkflowEvent).where(
                        WorkflowEvent.user_id == user_id,
                        WorkflowEvent.family == WorkflowEventFamily.SOURCE_UPLOADED,
                        WorkflowEvent.source_type == "bank_statement",
                        WorkflowEvent.source_id.in_([row.id for row in statement_rows]),
                    )
                )
            ).all()
        }
        if statement_rows
        else {}
    )
    statements = [(row, existing_event_by_source_id.get(row.id)) for row in statement_rows]
    document_ids = {s.uploaded_document_id for s, _ in statements if s.uploaded_document_id is not None}
    ods_filenames = await get_uploaded_document_filenames(db, document_ids)

    derived_payloads: list[WorkflowEventCreate] = []
    for statement, event in statements:
        if workflow_session is None:
            workflow_session = await get_or_create_active_workflow_session(db, user_id=user_id)
        filename = (
            ods_filenames.get(statement.uploaded_document_id) if statement.uploaded_document_id is not None else None
        ) or statement.file_hash
        await _apply_or_insert_event(
            db,
            user_id=user_id,
            existing=event,
            payload=build_uploaded_statement_event_payload(statement, filename),
            session_id=workflow_session.id,
        )
        if statement.status == _STATUS_REJECTED and statement.stage1_status is None:
            derived_payloads.append(build_statement_parsing_failed_event_payload(statement, filename))
        if (
            statement.status == _STATUS_PARSED and statement.stage1_status is None
        ) or statement.stage1_status == _STAGE1_PENDING_REVIEW:
            derived_payloads.append(build_review_required_event_payload(statement, filename))
        elif statement.stage1_status == _STAGE1_REJECTED:
            derived_payloads.append(build_review_rejected_event_payload(statement, filename))
        elif statement.stage1_status in {_STAGE1_APPROVED, _STAGE1_EDITED}:
            derived_payloads.append(build_review_completed_event_payload(statement, filename))

    if pending_reconciliation_count := await count_pending_review_items(db, user_id=user_id):
        derived_payloads.append(build_reconciliation_review_event_payload(pending_reconciliation_count))

    try:
        package_readiness = (await current_package_readiness(db, user_id=user_id)).model_dump(mode="json")
    except ReportError as exc:
        package_readiness = PersonalReportPackageReadinessResponse(
            package_id="personal-financial-report-package",
            state=PersonalReportPackageReadinessState.BLOCKED,
            label="Report package blocked",
            action_href="/reports?tab=package",
            blocking_count=1,
            blockers=[
                PersonalReportPackageReadinessBlocker(
                    code="report_generation_error",
                    label="Report package blocked",
                    severity="blocking",
                    count=1,
                    reason=str(exc),
                    action_href="/reports?tab=package",
                )
            ],
        ).model_dump(mode="json")
    derived_payloads.extend(build_readiness_blocker_event_payload(b) for b in package_readiness.get("blockers", []))
    if (report_state_payload := build_report_state_event_payload(package_readiness)) is not None:
        existing_same_count = await db.scalar(
            select(func.count(WorkflowEvent.id)).where(
                WorkflowEvent.user_id == user_id,
                WorkflowEvent.family == report_state_payload.family,
                WorkflowEvent.status != WorkflowEventStatus.ARCHIVED,
            )
        )
        if not int(existing_same_count or 0):
            derived_payloads.append(report_state_payload)

    if derived_payloads and workflow_session is None:
        workflow_session = await get_or_create_active_workflow_session(db, user_id=user_id)

    active_derived_dedupe_keys = {p.dedupe_key for p in derived_payloads}
    if derived_payloads and workflow_session is not None:
        event_by_key = {
            e.dedupe_key: e
            for e in (
                await db.scalars(
                    select(WorkflowEvent).where(
                        WorkflowEvent.user_id == user_id,
                        WorkflowEvent.dedupe_key.in_(active_derived_dedupe_keys),
                    )
                )
            ).all()
        }
        for payload in derived_payloads:
            await _apply_or_insert_event(
                db,
                user_id=user_id,
                existing=event_by_key.get(payload.dedupe_key),
                payload=payload,
                session_id=workflow_session.id,
            )

    stale_events: list[WorkflowEvent] = []
    if derived_payloads or str(package_readiness["state"]) in {"draft", "ready"}:
        prefix = "bank_statement:"
        stale_query = select(WorkflowEvent).where(
            WorkflowEvent.user_id == user_id,
            WorkflowEvent.family.in_(MUTABLE_DERIVED_EVENT_FAMILIES),
            WorkflowEvent.source_type.in_(MUTABLE_DERIVED_EVENT_SOURCE_TYPES),
            WorkflowEvent.status != WorkflowEventStatus.ARCHIVED,
            or_(
                WorkflowEvent.source_type != "bank_statement",
                func.substr(WorkflowEvent.dedupe_key, 1, len(prefix)) == prefix,
            ),
        )
        if active_derived_dedupe_keys:
            stale_query = stale_query.where(WorkflowEvent.dedupe_key.not_in(active_derived_dedupe_keys))
        stale_events = list((await db.scalars(stale_query)).all())
    stale_session_ids = {e.session_id for e in stale_events if e.session_id is not None}
    for e in stale_events:
        e.status = WorkflowEventStatus.ARCHIVED

    await db.flush()
    if workflow_session is not None:
        await refresh_workflow_session_summary(db, user_id=user_id, session_id=workflow_session.id)
        stale_session_ids.discard(workflow_session.id)
    for session_id in stale_session_ids:
        await refresh_workflow_session_summary(db, user_id=user_id, session_id=session_id)

    return package_readiness


async def _reusable_package_readiness(db: AsyncSession, *, user_id: UUID, fingerprint: str) -> dict | None:
    """Return stored readiness when younger than WORKFLOW_SYNC_STATE_MAX_AGE and matching fingerprint (#2583)."""
    state = (
        await db.execute(
            select(
                WorkflowSyncState.source_fingerprint,
                WorkflowSyncState.package_readiness,
                WorkflowSyncState.updated_at,
            ).where(WorkflowSyncState.user_id == user_id)
        )
    ).one_or_none()
    if (
        state is not None
        and state.source_fingerprint == fingerprint
        and datetime.now(UTC) - state.updated_at < WORKFLOW_SYNC_STATE_MAX_AGE
    ):
        return dict(state.package_readiness)
    return None


async def stored_package_readiness(db: AsyncSession, *, user_id: UUID) -> dict | None:
    """Return cached package readiness without writes if inputs are unchanged, else None (#2583)."""
    fingerprint = await workflow_source_fingerprint(db, user_id=user_id)
    return await _reusable_package_readiness(db, user_id=user_id, fingerprint=fingerprint)


async def ensure_workflow_events_synced(db: AsyncSession, *, user_id: UUID) -> dict:
    """Derive workflow events only when source fingerprint changed or sync state expired (#2583)."""
    fingerprint = await workflow_source_fingerprint(db, user_id=user_id)
    if (stored := await _reusable_package_readiness(db, user_id=user_id, fingerprint=fingerprint)) is not None:
        return stored

    package_readiness = await sync_workflow_events_for_user(db, user_id=user_id)
    await db.execute(
        postgresql_insert(WorkflowSyncState)
        .values(user_id=user_id, source_fingerprint=fingerprint, package_readiness=package_readiness)
        .on_conflict_do_update(
            index_elements=[WorkflowSyncState.user_id],
            set_={
                "source_fingerprint": fingerprint,
                "package_readiness": package_readiness,
                "updated_at": func.now(),
            },
        )
    )
    return package_readiness


async def refresh_workflow_session_summary(
    db: AsyncSession, *, user_id: UUID, session_id: UUID | None
) -> None:
    """Refresh denormalized session counts from its event timeline."""
    if session_id is None:
        return
    workflow_session = await db.scalar(
        select(WorkflowSession).where(WorkflowSession.id == session_id, WorkflowSession.user_id == user_id)
    )
    if workflow_session is None:
        return

    aggregate = (
        await db.execute(
            select(
                func.count(WorkflowEvent.id).label("event_count"),
                func.max(WorkflowEvent.occurred_at).label("last_event_at"),
            ).where(
                WorkflowEvent.user_id == user_id,
                WorkflowEvent.session_id == session_id,
                WorkflowEvent.status != WorkflowEventStatus.ARCHIVED,
            )
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
    return list((await db.scalars(stmt)).all())


async def list_workflow_events_response(
    db: AsyncSession,
    *,
    user_id: UUID,
    status: WorkflowEventStatus | None = None,
    limit: int = 50,
) -> WorkflowEventListResponse:
    """Return bounded event list plus total count and grouped session summaries (#987)."""
    package_readiness = await ensure_workflow_events_synced(db, user_id=user_id)
    workflow_status = await get_workflow_status(db, user_id=user_id, synced_package_readiness=package_readiness)

    filters = [
        WorkflowEvent.user_id == user_id,
        WorkflowEvent.status == status if status is not None else WorkflowEvent.status != WorkflowEventStatus.ARCHIVED,
    ]
    total = await db.scalar(select(func.count(WorkflowEvent.id)).where(*filters))
    events = await list_workflow_events(db, user_id=user_id, status=status, limit=limit, include_archived=False)
    session_ids = {e.session_id for e in events if e.session_id is not None}
    sessions: list[WorkflowSessionSummaryResponse] = []
    if session_ids:
        session_rows = (
            await db.scalars(
                select(WorkflowSession)
                .where(WorkflowSession.user_id == user_id, WorkflowSession.id.in_(session_ids))
                .order_by(WorkflowSession.last_event_at.desc().nullslast(), WorkflowSession.created_at.desc())
            )
        ).all()
        active_session = workflow_status.active_session
        sessions = [
            await build_workflow_session_summary(
                db,
                workflow_session=s,
                primary_state=(
                    active_session.primary_state
                    if active_session is not None and active_session.id == s.id
                    else WorkflowPrimaryState.READY
                ),
                report_readiness=(
                    active_session.report_readiness
                    if active_session is not None and active_session.id == s.id
                    else None
                ),
            )
            for s in session_rows
        ]

    return WorkflowEventListResponse(
        items=[WorkflowEventResponse.model_validate(e) for e in events],
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
                func.count(WorkflowEvent.id).filter(WorkflowEvent.status == WorkflowEventStatus.UNREAD).label("unread"),
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.severity == WorkflowEventSeverity.ACTION_REQUIRED)
                .label("action_required"),
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.severity == WorkflowEventSeverity.BLOCKED)
                .label("blocked"),
            ).where(
                WorkflowEvent.user_id == workflow_session.user_id,
                WorkflowEvent.session_id == workflow_session.id,
                WorkflowEvent.status != WorkflowEventStatus.ARCHIVED,
            )
        )
    ).one()
    return _session_summary_model(
        workflow_session,
        primary_state=primary_state,
        report_readiness=report_readiness,
        counts=WorkflowEventCountsResponse(
            unread=int(aggregate.unread or 0),
            action_required=int(aggregate.action_required or 0),
            blocked=int(aggregate.blocked or 0),
        ),
    )


async def get_workflow_status(
    db: AsyncSession,
    *,
    user_id: UUID,
    synced_package_readiness: dict | None = None,
) -> WorkflowStatusResponse:
    """Return compact workflow status for primary UI surfaces (#987, #2583)."""
    package_readiness = (
        await ensure_workflow_events_synced(db, user_id=user_id)
        if synced_package_readiness is None
        else synced_package_readiness
    )
    package_readiness_state = _collapse_package_readiness_state(str(package_readiness["state"]))
    package_blocking_count = int(package_readiness["blocking_count"])

    active_filters: list[ColumnElement[bool]] = [
        WorkflowEvent.user_id == user_id,
        WorkflowEvent.status != WorkflowEventStatus.ARCHIVED,
    ]

    async def representative_event(*filters: ColumnElement[bool]) -> WorkflowEvent | None:
        return await db.scalar(
            select(WorkflowEvent)
            .where(*active_filters, *filters)
            .order_by(WorkflowEvent.occurred_at.desc(), WorkflowEvent.created_at.desc())
            .limit(1)
        )

    agg = (
        await db.execute(
            select(
                func.count(WorkflowEvent.id).label("active"),
                func.count(WorkflowEvent.id).filter(WorkflowEvent.status == WorkflowEventStatus.UNREAD).label("unread"),
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.severity == WorkflowEventSeverity.ACTION_REQUIRED)
                .label("action_required"),
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.severity == WorkflowEventSeverity.BLOCKED)
                .label("blocked"),
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.report_impact == WorkflowReportImpact.PROCESSING)
                .label("processing"),
                func.count(WorkflowEvent.id)
                .filter(WorkflowEvent.report_impact == WorkflowReportImpact.READY)
                .label("ready"),
            ).where(*active_filters)
        )
    ).one()

    active_count = int(agg.active or 0)
    unread_count = int(agg.unread or 0)
    action_required_count = int(agg.action_required or 0)
    blocked_count = int(agg.blocked or 0)
    processing_count = int(agg.processing or 0)
    ready_count = int(agg.ready or 0)

    if blocked_count or package_readiness_state == WorkflowReportReadinessState.BLOCKED:
        blocked_event = await representative_event(WorkflowEvent.severity == WorkflowEventSeverity.BLOCKED)
        primary_state = WorkflowPrimaryState.BLOCKED
        blocked_href = (
            str(package_readiness["action_href"])
            if package_readiness_state == WorkflowReportReadinessState.BLOCKED or not blocked_event
            else blocked_event.action_href
        )
        next_action = _next_action(
            WorkflowNextActionType.RESOLVE_BLOCKER,
            count=max(blocked_count, package_blocking_count),
            href=blocked_href,
        )
    elif action_required_count:
        ev = await representative_event(WorkflowEvent.severity == WorkflowEventSeverity.ACTION_REQUIRED)
        primary_state = WorkflowPrimaryState.NEEDS_ACTION
        next_action = _next_action(
            WorkflowNextActionType.REVIEW_REQUIRED,
            count=action_required_count,
            href=ev.action_href if ev else "/upload",
        )
    elif ready_count or package_readiness_state in {
        WorkflowReportReadinessState.READY,
        WorkflowReportReadinessState.STALE,
    }:
        primary_state = WorkflowPrimaryState.READY
        next_action = _next_action(WorkflowNextActionType.OPEN_REPORT, count=1, href="/reports?tab=package")
    elif processing_count or package_readiness_state == WorkflowReportReadinessState.PROCESSING:
        primary_state = WorkflowPrimaryState.PROCESSING
        next_action = _next_action(WorkflowNextActionType.WAIT, count=max(processing_count, 1), href="/upload")
    elif active_count:
        primary_state = WorkflowPrimaryState.READY
        next_action = _next_action(WorkflowNextActionType.NONE, count=0, href="/upload")
    else:
        primary_state = WorkflowPrimaryState.EMPTY
        next_action = _next_action(WorkflowNextActionType.UPLOAD, count=0, href="/upload")

    readiness = WorkflowReportReadinessResponse(
        state=package_readiness_state, blocking_count=package_blocking_count, href="/reports?tab=package"
    )
    event_counts = WorkflowEventCountsResponse(
        unread=unread_count, action_required=action_required_count, blocked=blocked_count
    )

    active_session = await db.scalar(
        select(WorkflowSession)
        .where(WorkflowSession.user_id == user_id, WorkflowSession.status == WorkflowSessionStatus.ACTIVE)
        .order_by(WorkflowSession.last_event_at.desc().nullslast(), WorkflowSession.created_at.desc())
        .limit(1)
    )
    active_session_summary = (
        _session_summary_model(
            active_session, primary_state=primary_state, report_readiness=readiness, counts=event_counts
        )
        if active_session is not None and (active_count or active_session.source_count)
        else None
    )

    return WorkflowStatusResponse(
        primary_state=primary_state,
        next_action=next_action,
        report_readiness=readiness,
        event_counts=event_counts,
        active_session=active_session_summary,
    )


async def update_workflow_event_status(
    db: AsyncSession, *, event_id: UUID, user_id: UUID, status: WorkflowEventStatus
) -> WorkflowEvent | None:
    """Update read/archive lifecycle state for one user-scoped event."""
    event = await db.scalar(
        select(WorkflowEvent).where(WorkflowEvent.id == event_id, WorkflowEvent.user_id == user_id)
    )
    if event is None:
        return None
    event.status = status
    await db.flush()
    await refresh_workflow_session_summary(db, user_id=user_id, session_id=event.session_id)
    return event
