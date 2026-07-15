"""Deterministic user-facing workflow event derivation."""

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.platform.base.types.workflow import (
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
from src.platform.extension.workflow_event_builders import (  # noqa: F401
    PACKAGE_WORKFLOW_SOURCE_ID,
    StatementEventSource,
    build_readiness_blocker_event_payload,
    build_report_state_event_payload,
    build_review_completed_event_payload,
    build_review_required_event_payload,
    build_statement_parsing_failed_event_payload,
    build_uploaded_statement_event_payload,
    build_workflow_dedupe_key,
)
from src.platform.orm.workflow import (
    WorkflowEvent,
    WorkflowEventFamily,
    WorkflowEventSeverity,
    WorkflowEventStatus,
    WorkflowReportImpact,
    WorkflowSession,
    WorkflowSessionStatus,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    # This module always calls the provider as (db: AsyncSession, user_id:
    # UUID) — see _get_readiness_provider()'s call site — so it is typed to
    # that exact signature, not an unconstrained Callable[..., Awaitable[dict]].
    ReadinessProvider = Callable[[AsyncSession, UUID], Awaitable[dict]]

    # Called as (db, document_id) / (db, document_ids) / (db, user_id, file_hash) —
    # see each _get_*_provider()'s call site.
    DocumentFilenameProvider = Callable[[AsyncSession, UUID], Awaitable[str | None]]
    DocumentFilenamesProvider = Callable[[AsyncSession, "set[UUID]"], Awaitable[dict[UUID, str]]]
    DocumentFilenameByHashProvider = Callable[[AsyncSession, UUID, str], Awaitable[str | None]]

    # Called as (db, user_id) — see sync_workflow_events_for_user's call site.
    StatementReader = Callable[[AsyncSession, UUID], Awaitable[list[StatementEventSource]]]

# Raw ``BankStatementStatus``/``Stage1Status`` .value strings (#1675 D6) — this
# L1-infra module compares against these instead of importing the extraction-
# owned enum types; see StatementEventSource's docstring for the inversion.
_STATUS_REJECTED = "rejected"
_STATUS_PARSED = "parsed"
_STAGE1_PENDING_REVIEW = "pending_review"
_STAGE1_APPROVED = "approved"
_STAGE1_REJECTED = "rejected"
_STAGE1_EDITED = "edited"

# `platform` is L1 infra — it must never import reporting-domain logic directly
# (issue #1676: this file previously imported `services.report_readiness`
# module-level, the sole L1-infra→business upward edge in
# common/meta/data/app-boundary-baseline.json). The personal-report-package readiness
# lookup is genuinely reporting-domain logic; platform only needs *a* callable
# with this shape, not that specific implementation. The app composition root
# (`main.py`, itself L4 — allowed to import everything) registers the real
# function at startup; tests register it directly since they don't run the
# app's lifespan.
_readiness_provider: "ReadinessProvider | None" = None


def register_readiness_provider(provider: "ReadinessProvider") -> None:
    """Wire the personal-report-package readiness lookup (see module note above)."""
    global _readiness_provider
    _readiness_provider = provider


def _get_readiness_provider() -> "ReadinessProvider":
    if _readiness_provider is None:
        raise RuntimeError(
            "workflow_events.register_readiness_provider() was never called — "
            "main.py wires it at startup (issue #1676); a test exercising this "
            "path must call it too."
        )
    return _readiness_provider


# Same inversion, same reason (#1675 D3): ``UploadedDocument`` is owned by
# ``extraction`` (L3 domain); this L1-infra module may only depend on *a*
# callable with this shape, never import extraction's ORM or its published
# root directly. main.py wires the real ``src.extraction`` functions at
# startup; tests register fakes/the real functions directly.
_document_filename_provider: "DocumentFilenameProvider | None" = None
_document_filenames_provider: "DocumentFilenamesProvider | None" = None
_document_filename_by_hash_provider: "DocumentFilenameByHashProvider | None" = None


def register_uploaded_document_readers(
    *,
    get_filename: "DocumentFilenameProvider",
    get_filenames: "DocumentFilenamesProvider",
    find_filename_by_hash: "DocumentFilenameByHashProvider",
) -> None:
    """Wire the ``UploadedDocument`` filename lookups (see module note above)."""
    global _document_filename_provider, _document_filenames_provider, _document_filename_by_hash_provider
    _document_filename_provider = get_filename
    _document_filenames_provider = get_filenames
    _document_filename_by_hash_provider = find_filename_by_hash


def _get_document_filename_provider() -> "DocumentFilenameProvider":
    if _document_filename_provider is None:
        raise RuntimeError(
            "workflow_events.register_uploaded_document_readers() was never called — "
            "main.py wires it at startup (#1675 D3); a test exercising this path must call it too."
        )
    return _document_filename_provider


def _get_document_filenames_provider() -> "DocumentFilenamesProvider":
    if _document_filenames_provider is None:
        raise RuntimeError(
            "workflow_events.register_uploaded_document_readers() was never called — "
            "main.py wires it at startup (#1675 D3); a test exercising this path must call it too."
        )
    return _document_filenames_provider


def _get_document_filename_by_hash_provider() -> "DocumentFilenameByHashProvider":
    if _document_filename_by_hash_provider is None:
        raise RuntimeError(
            "workflow_events.register_uploaded_document_readers() was never called — "
            "main.py wires it at startup (#1675 D3); a test exercising this path must call it too."
        )
    return _document_filename_by_hash_provider


# Same inversion, same reason (#1675 D6): ``StatementSummary`` is owned by
# ``extraction`` (L3 domain); this L1-infra module may only depend on the
# plain ``StatementEventSource`` read-model shape, never import the ORM class
# or its enum types directly. main.py wires the real
# ``src.extraction.get_statement_event_sources`` at startup; tests register a
# fake/the real function directly.
_statement_reader: "StatementReader | None" = None


def register_statement_reader(reader: "StatementReader") -> None:
    """Wire the ``StatementSummary`` read model (see module note above)."""
    global _statement_reader
    _statement_reader = reader


def _get_statement_reader() -> "StatementReader":
    if _statement_reader is None:
        raise RuntimeError(
            "workflow_events.register_statement_reader() was never called — "
            "main.py wires it at startup (#1675 D6); a test exercising this path must call it too."
        )
    return _statement_reader


ACTIVE_WORKFLOW_SESSION_DEDUPE_KEY = "active-upload-to-report"
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


async def _get_workflow_event_by_dedupe_key(
    db: AsyncSession, *, user_id: UUID, dedupe_key: str
) -> WorkflowEvent | None:
    result = await db.execute(
        select(WorkflowEvent).where(WorkflowEvent.user_id == user_id).where(WorkflowEvent.dedupe_key == dedupe_key)
    )
    return result.scalar_one_or_none()


async def _insert_workflow_event_conflict_safe(
    db: AsyncSession,
    *,
    user_id: UUID,
    payload: WorkflowEventCreate,
    session_id: UUID | None,
) -> WorkflowEvent:
    """Insert a new workflow event without letting a dedupe-key race poison the outer transaction.

    Concurrent requests/background tasks for the same ``(user_id, dedupe_key)`` can both miss the
    pre-insert SELECT and both attempt the insert; the loser raises a ``UniqueViolationError`` on
    ``uq_workflow_events_user_dedupe_key``. Running the insert + flush inside a SAVEPOINT means that
    on conflict only the nested transaction rolls back (the outer request transaction stays usable),
    after which we re-fetch and update the now-existing row — mirroring the session guard above.
    """
    event = _workflow_event_from_payload(user_id=user_id, payload=payload, session_id=session_id)
    try:
        async with db.begin_nested():
            db.add(event)
            await db.flush()
    except IntegrityError:
        existing = await _get_workflow_event_by_dedupe_key(db, user_id=user_id, dedupe_key=payload.dedupe_key)
        if existing is None:
            raise
        _apply_workflow_event_payload(existing, payload)
        if existing.session_id is None:
            existing.session_id = session_id
        return existing
    return event


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

    event = await _get_workflow_event_by_dedupe_key(db, user_id=user_id, dedupe_key=payload.dedupe_key)
    if event is None:
        event = await _insert_workflow_event_conflict_safe(db, user_id=user_id, payload=payload, session_id=session_id)
    else:
        _apply_workflow_event_payload(event, payload)
        if event.session_id is None:
            event.session_id = session_id

    await db.flush()
    await refresh_workflow_session_summary(db, user_id=user_id, session_id=session_id)
    return event


async def _statement_filename(db: AsyncSession, statement: StatementEventSource) -> str:
    """Resolve the display filename for a statement summary via its ODS document."""
    document_id = statement.uploaded_document_id
    if document_id is not None:
        filename = await _get_document_filename_provider()(db, document_id)
        if filename:
            return filename
    filename = await _get_document_filename_by_hash_provider()(db, statement.user_id, statement.file_hash)
    return filename or statement.file_hash


async def derive_uploaded_statement_event(
    db: AsyncSession,
    statement: StatementEventSource,
    *,
    user_id: UUID,
) -> WorkflowEvent:
    """Upsert the initial uploaded-statement workflow event."""
    if statement.user_id != user_id:
        raise ValueError("statement.user_id must match user_id")

    filename = await _statement_filename(db, statement)
    payload = build_uploaded_statement_event_payload(statement, filename)
    return await upsert_workflow_event(db, user_id=user_id, payload=payload)


async def sync_workflow_events_for_user(db: AsyncSession, *, user_id: UUID) -> dict:
    """Derive deterministic workflow events from existing user-owned records.

    Returns the personal report package readiness computed during the sync so
    callers (e.g. get_workflow_status) can reuse it instead of recomputing the
    multi-query readiness a second time per request (#987 perf fix).
    """
    workflow_session: WorkflowSession | None = None
    # Two queries instead of a cross-domain join (#1675 D6, same shape as the
    # UploadedDocument inversion below): extraction owns StatementSummary;
    # platform only reaches it through the registered StatementEventSource
    # provider (an L1-infra module may never import an L3-domain package,
    # #1676 precedent). The existing-event lookup stays a plain query — it's
    # platform's own WorkflowEvent table.
    statement_rows = await _get_statement_reader()(db, user_id)
    if statement_rows:
        existing_events_result = await db.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.user_id == user_id)
            .where(WorkflowEvent.family == WorkflowEventFamily.SOURCE_UPLOADED)
            .where(WorkflowEvent.source_type == "bank_statement")
            .where(WorkflowEvent.source_id.in_([row.id for row in statement_rows]))
        )
        existing_event_by_source_id = {event.source_id: event for event in existing_events_result.scalars().all()}
    else:
        existing_event_by_source_id = {}
    statements = [(row, existing_event_by_source_id.get(row.id)) for row in statement_rows]
    # One extra query instead of a cross-domain join (#1675 D3): extraction owns
    # UploadedDocument; platform only reaches it through the registered provider
    # (an L1-infra module may never import an L3-domain package, #1676 precedent).
    document_ids = {s.uploaded_document_id for s, _ in statements if s.uploaded_document_id is not None}
    ods_filenames = await _get_document_filenames_provider()(db, document_ids)

    derived_payloads: list[WorkflowEventCreate] = []
    for statement, event in statements:
        if workflow_session is None:
            workflow_session = await get_or_create_active_workflow_session(db, user_id=user_id)
        filename = ods_filenames.get(statement.uploaded_document_id) or statement.file_hash
        payload = build_uploaded_statement_event_payload(statement, filename)
        if event is None:
            await _insert_workflow_event_conflict_safe(
                db, user_id=user_id, payload=payload, session_id=workflow_session.id
            )
        else:
            _apply_workflow_event_payload(event, payload)
            if event.session_id is None:
                event.session_id = workflow_session.id
        if statement.status == _STATUS_REJECTED and statement.stage1_status is None:
            derived_payloads.append(build_statement_parsing_failed_event_payload(statement, filename))
        if statement.status == _STATUS_PARSED and statement.stage1_status is None:
            derived_payloads.append(build_review_required_event_payload(statement, filename))
        elif statement.stage1_status == _STAGE1_PENDING_REVIEW:
            derived_payloads.append(build_review_required_event_payload(statement, filename))
        elif statement.stage1_status in {_STAGE1_APPROVED, _STAGE1_REJECTED, _STAGE1_EDITED}:
            derived_payloads.append(build_review_completed_event_payload(statement, filename))

    package_readiness = await _get_readiness_provider()(db, user_id=user_id)
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
                await _insert_workflow_event_conflict_safe(
                    db, user_id=user_id, payload=payload, session_id=workflow_session.id
                )
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

    return package_readiness


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
    # Sync once here and reuse get_workflow_status as the single source of truth
    # for the active session's derived (primary_state, report_readiness). The
    # readiness computed during sync is injected so get_workflow_status does not
    # sync or recompute the multi-query readiness a second time (#987 perf fix).
    package_readiness = await sync_workflow_events_for_user(db, user_id=user_id)
    workflow_status = await get_workflow_status(
        db,
        user_id=user_id,
        synced_package_readiness=package_readiness,
    )

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
        active_session = workflow_status.active_session
        sessions = [
            await build_workflow_session_summary(
                db,
                workflow_session=session,
                # The active session must not contradict the authoritative
                # workflow status (issue #987); other sessions keep the
                # session-summary default.
                primary_state=(
                    active_session.primary_state
                    if active_session is not None and active_session.id == session.id
                    else WorkflowPrimaryState.READY
                ),
                report_readiness=(
                    active_session.report_readiness
                    if active_session is not None and active_session.id == session.id
                    else None
                ),
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


async def get_workflow_status(
    db: AsyncSession,
    *,
    user_id: UUID,
    synced_package_readiness: dict | None = None,
) -> WorkflowStatusResponse:
    """Return the compact workflow status for primary UI surfaces.

    sync_workflow_events_for_user already computes the personal report package
    readiness, so its return value is reused here instead of recomputing the
    multi-query readiness a second time (#987 perf fix). Callers that have
    already synced (e.g. list_workflow_events_response) inject that readiness via
    synced_package_readiness to skip both the redundant sync and the second
    readiness pass, while still deriving the SAME primary_state/report_readiness.
    """
    if synced_package_readiness is None:
        package_readiness = await sync_workflow_events_for_user(db, user_id=user_id)
    else:
        package_readiness = synced_package_readiness
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
            href=action_required_event.action_href if action_required_event else "/notifications",
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
