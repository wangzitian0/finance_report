"""Deterministic user-facing workflow event derivation."""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.models import BankStatementStatus, Stage1Status, StatementSummary
from src.models.layer1 import UploadedDocument
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

ACTIVE_WORKFLOW_SESSION_DEDUPE_KEY = "active-upload-to-report"
PACKAGE_WORKFLOW_SOURCE_ID = uuid5(NAMESPACE_URL, "finance-report:personal-financial-report-package")
MUTABLE_DERIVED_EVENT_SOURCE_TYPES = {"bank_statement", "readiness_blocker", "report_package"}
MUTABLE_DERIVED_EVENT_FAMILIES = {
    WorkflowEventFamily.SOURCE_PARSING_FAILED,
    WorkflowEventFamily.REVIEW_REQUIRED,
    WorkflowEventFamily.REVIEW_COMPLETED,
    WorkflowEventFamily.RECONCILIATION_BLOCKED,
    WorkflowEventFamily.REPORT_READY,
    WorkflowEventFamily.REPORT_BLOCKED,
    WorkflowEventFamily.REPORT_GENERATED,
}


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


def _next_action(
    action_type: WorkflowNextActionType,
    *,
    count: int,
    href: str,
) -> WorkflowNextActionResponse:
    """Build the cockpit-ready single next-action contract."""
    copy = {
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
        WorkflowNextActionType.NONE: (
            "Open workflow",
            "Open workflow history for details.",
        ),
    }[action_type]
    return WorkflowNextActionResponse(type=action_type, count=count, href=href, label=copy[0], summary=copy[1])


def build_workflow_dedupe_key(*, family: WorkflowEventFamily, source_type: str, source_id: UUID) -> str:
    """Build the stable per-user dedupe key for a source-derived workflow event."""
    return f"{source_type}:{source_id}:{family.value}"


async def _get_active_workflow_session(db: AsyncSession, *, user_id: UUID) -> WorkflowSession | None:
    result = await db.execute(
        select(WorkflowSession)
        .where(WorkflowSession.user_id == user_id)
        .where(WorkflowSession.status == WorkflowSessionStatus.ACTIVE)
        .where(WorkflowSession.dedupe_key == ACTIVE_WORKFLOW_SESSION_DEDUPE_KEY)
        .order_by(WorkflowSession.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_or_create_active_workflow_session(db: AsyncSession, *, user_id: UUID) -> WorkflowSession:
    """Return the user's active upload-to-report session, creating the v1 synthetic session when needed."""
    session = await _get_active_workflow_session(db, user_id=user_id)
    if session is not None:
        return session

    insert_result = await db.execute(
        postgresql_insert(WorkflowSession)
        .values(
            user_id=user_id,
            status=WorkflowSessionStatus.ACTIVE,
            title="Upload-to-report session",
            summary="Current upload, processing, review, and report-readiness work.",
            dedupe_key=ACTIVE_WORKFLOW_SESSION_DEDUPE_KEY,
            source_count=0,
        )
        .on_conflict_do_nothing(constraint="uq_workflow_sessions_user_dedupe_key")
        .returning(WorkflowSession.id)
    )
    inserted_id = insert_result.scalar_one_or_none()
    if inserted_id is not None:
        result = await db.execute(select(WorkflowSession).where(WorkflowSession.id == inserted_id))
        return result.scalar_one()

    session = await _get_active_workflow_session(db, user_id=user_id)
    if session is None:
        result = await db.execute(
            select(WorkflowSession)
            .where(WorkflowSession.user_id == user_id)
            .where(WorkflowSession.dedupe_key == ACTIVE_WORKFLOW_SESSION_DEDUPE_KEY)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise RuntimeError("active workflow session upsert returned no row and no existing session")
        session.status = WorkflowSessionStatus.ACTIVE
        session.title = "Upload-to-report session"
        session.summary = "Current upload, processing, review, and report-readiness work."
        if session.source_count is None:
            session.source_count = 0
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


def build_uploaded_statement_event_payload(statement: StatementSummary, filename: str) -> WorkflowEventCreate:
    """Build the deterministic uploaded-statement workflow event payload."""
    family = WorkflowEventFamily.SOURCE_UPLOADED
    return WorkflowEventCreate(
        occurred_at=statement.created_at,
        family=family,
        severity=WorkflowEventSeverity.INFO,
        title="Statement uploaded",
        summary=f"{filename} was uploaded and is ready for processing.",
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


def build_statement_parsing_failed_event_payload(statement: StatementSummary, filename: str) -> WorkflowEventCreate:
    """Build the user-action event for a failed statement parse."""
    family = WorkflowEventFamily.SOURCE_PARSING_FAILED
    return WorkflowEventCreate(
        occurred_at=statement.updated_at or statement.created_at,
        family=family,
        severity=WorkflowEventSeverity.ACTION_REQUIRED,
        title="Statement parsing failed",
        summary=f"{filename} could not be parsed and needs attention.",
        source_type="bank_statement",
        source_id=statement.id,
        action_href=f"/statements/{statement.id}",
        report_impact=WorkflowReportImpact.BLOCKED,
        dedupe_key=build_workflow_dedupe_key(
            family=family,
            source_type="bank_statement",
            source_id=statement.id,
        ),
    )


def build_review_required_event_payload(statement: StatementSummary, filename: str) -> WorkflowEventCreate:
    """Build the user-action event for pending Stage 1 review."""
    family = WorkflowEventFamily.REVIEW_REQUIRED
    return WorkflowEventCreate(
        occurred_at=statement.updated_at or statement.created_at,
        family=family,
        severity=WorkflowEventSeverity.ACTION_REQUIRED,
        title="Source review required",
        summary=f"{filename} needs source review before report readiness can advance.",
        source_type="bank_statement",
        source_id=statement.id,
        action_href="/review",
        report_impact=WorkflowReportImpact.BLOCKED,
        dedupe_key=build_workflow_dedupe_key(
            family=family,
            source_type="bank_statement",
            source_id=statement.id,
        ),
    )


def build_review_completed_event_payload(statement: StatementSummary, filename: str) -> WorkflowEventCreate:
    """Build the routine success event for completed Stage 1 review."""
    family = WorkflowEventFamily.REVIEW_COMPLETED
    reviewed_at = statement.stage1_reviewed_at or statement.updated_at or statement.created_at
    return WorkflowEventCreate(
        occurred_at=reviewed_at,
        family=family,
        severity=WorkflowEventSeverity.SUCCESS,
        title="Source review completed",
        summary=f"{filename} source review is complete.",
        source_type="bank_statement",
        source_id=statement.id,
        action_href=f"/statements/{statement.id}",
        report_impact=WorkflowReportImpact.NONE,
        dedupe_key=build_workflow_dedupe_key(
            family=family,
            source_type="bank_statement",
            source_id=statement.id,
        ),
    )


def _readiness_blocker_source_id(code: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"finance-report:readiness-blocker:{code}")


def build_readiness_blocker_event_payload(blocker: dict[str, str | int]) -> WorkflowEventCreate:
    """Build a lightweight user-facing event from a report-readiness blocker."""
    code = str(blocker["code"])
    family = (
        WorkflowEventFamily.RECONCILIATION_BLOCKED
        if code == "reconciliation_blocked"
        else WorkflowEventFamily.REPORT_BLOCKED
    )
    count = int(blocker.get("count", 1))
    return WorkflowEventCreate(
        occurred_at=datetime.now(UTC),
        family=family,
        severity=WorkflowEventSeverity.BLOCKED,
        title=str(blocker["label"]),
        summary=f"{blocker['reason']} ({count} item{'s' if count != 1 else ''}).",
        source_type="readiness_blocker",
        source_id=_readiness_blocker_source_id(code),
        action_href=str(blocker["action_href"]),
        report_impact=WorkflowReportImpact.BLOCKED,
        dedupe_key=f"readiness-blocker:{code}:{family.value}",
    )


def build_report_state_event_payload(package_readiness: dict) -> WorkflowEventCreate | None:
    """Build report ready/generated events from package readiness."""
    state = str(package_readiness["state"])
    if state not in {"ready", "generated"}:
        return None
    family = WorkflowEventFamily.REPORT_GENERATED if state == "generated" else WorkflowEventFamily.REPORT_READY
    title = "Report package generated" if state == "generated" else "Report package ready"
    summary = (
        "The personal report package has been generated."
        if state == "generated"
        else "The personal report package is ready to review."
    )
    return WorkflowEventCreate(
        occurred_at=datetime.now(UTC),
        family=family,
        severity=WorkflowEventSeverity.SUCCESS,
        title=title,
        summary=summary,
        source_type="report_package",
        source_id=PACKAGE_WORKFLOW_SOURCE_ID,
        action_href=str(package_readiness["action_href"]),
        report_impact=WorkflowReportImpact.READY,
        dedupe_key=f"report-package:{family.value}",
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


async def _statement_filename(db: AsyncSession, statement: StatementSummary) -> str:
    """Resolve the display filename for a statement summary via its ODS document."""
    document_id = statement.uploaded_document_id
    if document_id is not None:
        filename = await db.scalar(
            select(UploadedDocument.original_filename).where(UploadedDocument.id == document_id)
        )
        if filename:
            return filename
    filename = await db.scalar(
        select(UploadedDocument.original_filename)
        .where(UploadedDocument.user_id == statement.user_id)
        .where(UploadedDocument.file_hash == statement.file_hash)
        .order_by(UploadedDocument.created_at.desc(), UploadedDocument.id.desc())
        .limit(1)
    )
    return filename or statement.file_hash


async def derive_uploaded_statement_event(
    db: AsyncSession,
    statement: StatementSummary,
    *,
    user_id: UUID,
) -> WorkflowEvent:
    """Upsert the initial uploaded-statement workflow event."""
    if statement.user_id != user_id:
        raise ValueError("statement.user_id must match user_id")

    filename = await _statement_filename(db, statement)
    payload = build_uploaded_statement_event_payload(statement, filename)
    return await upsert_workflow_event(db, user_id=user_id, payload=payload)


async def sync_workflow_events_for_user(db: AsyncSession, *, user_id: UUID) -> None:
    """Derive deterministic workflow events from existing user-owned records."""
    workflow_session: WorkflowSession | None = None
    existing_event = aliased(WorkflowEvent)
    ods_document = aliased(UploadedDocument)
    result = await db.execute(
        select(StatementSummary, existing_event, ods_document.original_filename)
        .outerjoin(
            existing_event,
            and_(
                existing_event.user_id == user_id,
                existing_event.family == WorkflowEventFamily.SOURCE_UPLOADED,
                existing_event.source_type == "bank_statement",
                existing_event.source_id == StatementSummary.id,
            ),
        )
        .outerjoin(ods_document, ods_document.id == StatementSummary.uploaded_document_id)
        .where(StatementSummary.user_id == user_id)
        .order_by(StatementSummary.created_at.asc())
    )
    derived_payloads: list[WorkflowEventCreate] = []
    for statement, event, ods_filename in result.all():
        if workflow_session is None:
            workflow_session = await get_or_create_active_workflow_session(db, user_id=user_id)
        filename = ods_filename or statement.file_hash
        payload = build_uploaded_statement_event_payload(statement, filename)
        if event is None:
            db.add(_workflow_event_from_payload(user_id=user_id, payload=payload, session_id=workflow_session.id))
        else:
            _apply_workflow_event_payload(event, payload)
            if event.session_id is None:
                event.session_id = workflow_session.id
        if statement.status == BankStatementStatus.REJECTED and statement.stage1_status is None:
            derived_payloads.append(build_statement_parsing_failed_event_payload(statement, filename))
        if statement.status == BankStatementStatus.PARSED and statement.stage1_status is None:
            derived_payloads.append(build_review_required_event_payload(statement, filename))
        elif statement.stage1_status == Stage1Status.PENDING_REVIEW:
            derived_payloads.append(build_review_required_event_payload(statement, filename))
        elif statement.stage1_status in {Stage1Status.APPROVED, Stage1Status.REJECTED, Stage1Status.EDITED}:
            derived_payloads.append(build_review_completed_event_payload(statement, filename))

    package_readiness = await get_personal_report_package_readiness(db, user_id=user_id)
    for blocker in package_readiness.get("blockers", []):
        derived_payloads.append(build_readiness_blocker_event_payload(blocker))
    report_state_payload = build_report_state_event_payload(package_readiness)
    if report_state_payload is not None:
        existing_same_report_state_count = await db.scalar(
            select(func.count(WorkflowEvent.id))
            .where(WorkflowEvent.user_id == user_id)
            .where(WorkflowEvent.family == report_state_payload.family)
            .where(WorkflowEvent.status != WorkflowEventStatus.ARCHIVED)
        )
        if not int(existing_same_report_state_count or 0):
            derived_payloads.append(report_state_payload)

    if derived_payloads and workflow_session is None:
        workflow_session = await get_or_create_active_workflow_session(db, user_id=user_id)

    active_derived_dedupe_keys = {payload.dedupe_key for payload in derived_payloads}
    should_archive_stale_events = derived_payloads or str(package_readiness["state"]) in {
        "draft",
        "ready",
        "generated",
        "stale",
    }
    if derived_payloads and workflow_session is not None:
        existing_payload_events = (
            (
                await db.execute(
                    select(WorkflowEvent)
                    .where(WorkflowEvent.user_id == user_id)
                    .where(WorkflowEvent.dedupe_key.in_(active_derived_dedupe_keys))
                )
            )
            .scalars()
            .all()
        )
        event_by_dedupe_key = {event.dedupe_key: event for event in existing_payload_events}
        for payload in derived_payloads:
            event = event_by_dedupe_key.get(payload.dedupe_key)
            if event is None:
                db.add(_workflow_event_from_payload(user_id=user_id, payload=payload, session_id=workflow_session.id))
            else:
                _apply_workflow_event_payload(event, payload)
                if event.session_id is None:
                    event.session_id = workflow_session.id

    stale_events: list[WorkflowEvent] = []
    if should_archive_stale_events:
        bank_statement_dedupe_prefix = "bank_statement:"
        stale_event_query = (
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == user_id)
            .where(WorkflowEvent.family.in_(MUTABLE_DERIVED_EVENT_FAMILIES))
            .where(WorkflowEvent.source_type.in_(MUTABLE_DERIVED_EVENT_SOURCE_TYPES))
            .where(WorkflowEvent.status != WorkflowEventStatus.ARCHIVED)
            .where(
                or_(
                    WorkflowEvent.source_type != "bank_statement",
                    func.substr(WorkflowEvent.dedupe_key, 1, len(bank_statement_dedupe_prefix))
                    == bank_statement_dedupe_prefix,
                )
            )
        )
        if active_derived_dedupe_keys:
            stale_event_query = stale_event_query.where(WorkflowEvent.dedupe_key.not_in(active_derived_dedupe_keys))
        stale_events = (await db.execute(stale_event_query)).scalars().all()
    stale_session_ids = {event.session_id for event in stale_events if event.session_id is not None}
    for event in stale_events:
        event.status = WorkflowEventStatus.ARCHIVED

    await db.flush()
    if workflow_session is not None:
        await refresh_workflow_session_summary(db, user_id=user_id, session_id=workflow_session.id)
        stale_session_ids.discard(workflow_session.id)
    for session_id in stale_session_ids:
        await refresh_workflow_session_summary(db, user_id=user_id, session_id=session_id)


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
        blocked_href = (
            str(package_readiness["action_href"])
            if package_readiness_state == WorkflowReportReadinessState.BLOCKED
            else blocked_event.action_href
            if blocked_event
            else str(package_readiness["action_href"])
        )
        next_action = _next_action(
            WorkflowNextActionType.RESOLVE_BLOCKER,
            count=max(blocked_count, package_blocking_count),
            href=blocked_href,
        )
    elif action_required_count:
        action_required_event = await representative_event(
            WorkflowEvent.severity == WorkflowEventSeverity.ACTION_REQUIRED
        )
        primary_state = WorkflowPrimaryState.NEEDS_ACTION
        next_action = _next_action(
            WorkflowNextActionType.REVIEW_REQUIRED,
            count=action_required_count,
            href=action_required_event.action_href if action_required_event else "/review",
        )
    elif ready_count or package_readiness_state in {
        WorkflowReportReadinessState.READY,
        WorkflowReportReadinessState.STALE,
    }:
        primary_state = WorkflowPrimaryState.READY
        next_action = _next_action(
            WorkflowNextActionType.OPEN_REPORT,
            count=1,
            href="/reports/package",
        )
    elif processing_count or package_readiness_state == WorkflowReportReadinessState.PROCESSING:
        primary_state = WorkflowPrimaryState.PROCESSING
        next_action = _next_action(
            WorkflowNextActionType.WAIT,
            count=max(processing_count, 1),
            href="/events",
        )
    elif active_count:
        primary_state = WorkflowPrimaryState.READY
        next_action = _next_action(WorkflowNextActionType.NONE, count=0, href="/events")
    else:
        primary_state = WorkflowPrimaryState.EMPTY
        next_action = _next_action(
            WorkflowNextActionType.UPLOAD,
            count=0,
            href="/statements/upload",
        )

    readiness = WorkflowReportReadinessResponse(
        state=package_readiness_state,
        blocking_count=package_blocking_count,
        href="/reports/package",
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
