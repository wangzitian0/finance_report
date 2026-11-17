"""Deterministic user-facing workflow event derivation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import and_, func, or_, select, text
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
    workflow_session: WorkflowSession | _ProjectedSession,
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


def _deterministic_event_id(user_id: UUID, dedupe_key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"finance-report:workflow-event:{user_id}:{dedupe_key}")


def _deterministic_session_id(user_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"finance-report:workflow-session:{user_id}:{ACTIVE_WORKFLOW_SESSION_DEDUPE_KEY}")


_DOMAIN_STAMP_SQL = text(
    """
    SELECT
        coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') || ':' || coalesce(string_agg(status::text || ':' || coalesce(stage1_status::text, ''), ',' ORDER BY id), '') FROM statement_summaries WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') || ':' || coalesce(string_agg(original_filename, ',' ORDER BY id), '') FROM uploaded_documents WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') || ':' || coalesce(string_agg(name, ',' ORDER BY id), '') FROM accounts WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') FROM journal_entries WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(sum(jl.amount)::text, '0') || ':' || coalesce(max(jl.updated_at)::text, '') FROM journal_lines jl JOIN journal_entries je ON je.id = jl.journal_entry_id WHERE je.user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') FROM opening_position_records WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(rm.updated_at)::text, '') || ':' || coalesce(string_agg(rm.status::text, ',' ORDER BY rm.id), '') FROM reconciliation_matches rm JOIN atomic_transactions atx ON atx.id = rm.atomic_txn_id WHERE atx.user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') FROM bank_custody_bindings WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') FROM manual_valuation_snapshots WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') FROM market_data_override WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') FROM managed_positions WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') FROM atomic_positions WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') FROM investment_transactions WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') FROM dividend_income WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') FROM classification_rules WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(updated_at)::text, '') FROM report_snapshots WHERE user_id = :user_id), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(occurred_at)::text, '') FROM trace_records WHERE scope_kind::text IN ('tenant', 'TENANT') AND scope_id = :user_id_str), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(created_at)::text, '') FROM fx_rates), '')
        || '|' || coalesce((SELECT count(*)::text || ':' || coalesce(max(created_at)::text, '') FROM stock_prices), '')
        || '|' || coalesce((SELECT coalesce(base_currency, '') FROM users WHERE id = :user_id), '')
        || '|' || coalesce((SELECT coalesce(value, '') FROM app_config WHERE key = 'base_currency' LIMIT 1), '')
    """
)


async def workflow_input_stamp(db: AsyncSession, *, user_id: UUID) -> str:
    """Compute a 1-query stamp over explicit domain inputs for cache invalidation."""
    row_stamp = str(await db.scalar(_DOMAIN_STAMP_SQL, {"user_id": user_id, "user_id_str": str(user_id)}) or "")
    raw = f"{row_stamp}|{date.today().isoformat()}"
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=32).hexdigest()


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
                id=_deterministic_session_id(user_id),
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


def _apply_workflow_event_payload(
    event: WorkflowEvent, payload: WorkflowEventCreate, session_id: UUID | None = None
) -> None:
    for field in _EVENT_PAYLOAD_FIELDS:
        setattr(event, field, getattr(payload, field))
    if session_id is not None and event.session_id is None:
        event.session_id = session_id


def _workflow_event_from_payload(
    *, user_id: UUID, payload: WorkflowEventCreate, session_id: UUID | None = None
) -> WorkflowEvent:
    event = WorkflowEvent(
        id=_deterministic_event_id(user_id, payload.dedupe_key),
        user_id=user_id,
        status=WorkflowEventStatus.UNREAD,
        session_id=session_id,
    )
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


@dataclass
class _ProjectedSession:
    id: UUID
    status: WorkflowSessionStatus
    title: str
    summary: str
    started_at: datetime
    last_event_at: datetime | None
    source_count: int
    report_href: str | None


@dataclass
class _ProjectedEvent:
    id: UUID
    user_id: UUID
    session_id: UUID | None
    occurred_at: datetime
    family: WorkflowEventFamily
    severity: WorkflowEventSeverity
    status: WorkflowEventStatus
    title: str
    summary: str
    source_type: str
    source_id: UUID
    action_href: str
    report_impact: WorkflowReportImpact
    dedupe_key: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_row(cls, row: WorkflowEvent) -> _ProjectedEvent:
        return cls(
            id=row.id,
            user_id=row.user_id,
            session_id=row.session_id,
            occurred_at=row.occurred_at,
            family=row.family,
            severity=row.severity,
            status=row.status,
            title=row.title,
            summary=row.summary,
            source_type=row.source_type,
            source_id=row.source_id,
            action_href=row.action_href,
            report_impact=row.report_impact,
            dedupe_key=row.dedupe_key,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @classmethod
    def from_payload(cls, *, user_id: UUID, session_id: UUID, payload: WorkflowEventCreate) -> _ProjectedEvent:
        return cls(
            id=_deterministic_event_id(user_id, payload.dedupe_key),
            user_id=user_id,
            session_id=session_id,
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
            created_at=payload.occurred_at,
            updated_at=payload.occurred_at,
        )

    def apply_payload(self, payload: WorkflowEventCreate, session_id: UUID) -> None:
        for field in _EVENT_PAYLOAD_FIELDS:
            setattr(self, field, getattr(payload, field))
        if self.session_id is None:
            self.session_id = session_id


async def _current_package_readiness_dict(db: AsyncSession, *, user_id: UUID) -> dict:
    try:
        return (await current_package_readiness(db, user_id=user_id)).model_dump(mode="json")
    except ReportError as exc:
        return PersonalReportPackageReadinessResponse(
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


async def _derive_workflow_inputs(
    db: AsyncSession, *, user_id: UUID, package_readiness: dict | None = None
) -> tuple[dict, list[WorkflowEventCreate], list[WorkflowEventCreate], WorkflowEventCreate | None, list[UUID]]:
    """Compute statement uploaded payloads, derived payloads, report-state payload, and readiness read-only."""
    statement_rows = await get_statement_event_sources(db, user_id)
    document_ids = {row.uploaded_document_id for row in statement_rows if row.uploaded_document_id is not None}
    ods_filenames = await get_uploaded_document_filenames(db, document_ids) if document_ids else {}

    uploaded_payloads: list[WorkflowEventCreate] = []
    derived_payloads: list[WorkflowEventCreate] = []
    for statement in statement_rows:
        filename = (
            ods_filenames.get(statement.uploaded_document_id) if statement.uploaded_document_id is not None else None
        ) or statement.file_hash
        uploaded_payloads.append(build_uploaded_statement_event_payload(statement, filename))
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

    resolved_readiness = (
        await _current_package_readiness_dict(db, user_id=user_id) if package_readiness is None else package_readiness
    )
    derived_payloads.extend(
        build_readiness_blocker_event_payload(b) for b in resolved_readiness.get("blockers", [])
    )
    report_state_payload = build_report_state_event_payload(resolved_readiness)
    return (
        resolved_readiness,
        uploaded_payloads,
        derived_payloads,
        report_state_payload,
        [row.id for row in statement_rows],
    )


async def sync_workflow_events_for_user(db: AsyncSession, *, user_id: UUID) -> dict:
    """Derive deterministic workflow events from user records and return package readiness (#987, #1675)."""
    workflow_session: WorkflowSession | None = None
    package_readiness, uploaded_payloads, derived_payloads, report_state_payload, statement_ids = (
        await _derive_workflow_inputs(db, user_id=user_id)
    )
    existing_event_by_source_id = (
        {
            e.source_id: e
            for e in (
                await db.scalars(
                    select(WorkflowEvent).where(
                        WorkflowEvent.user_id == user_id,
                        WorkflowEvent.family == WorkflowEventFamily.SOURCE_UPLOADED,
                        WorkflowEvent.source_type == "bank_statement",
                        WorkflowEvent.source_id.in_(statement_ids),
                    )
                )
            ).all()
        }
        if statement_ids
        else {}
    )

    for payload in uploaded_payloads:
        if workflow_session is None:
            workflow_session = await get_or_create_active_workflow_session(db, user_id=user_id)
        await _apply_or_insert_event(
            db,
            user_id=user_id,
            existing=existing_event_by_source_id.get(payload.source_id),
            payload=payload,
            session_id=workflow_session.id,
        )

    keep_report_dedupe_keys: set[str] = set()
    if report_state_payload is not None:
        existing_same_count = await db.scalar(
            select(func.count(WorkflowEvent.id)).where(
                WorkflowEvent.user_id == user_id,
                WorkflowEvent.family == report_state_payload.family,
                WorkflowEvent.status != WorkflowEventStatus.ARCHIVED,
            )
        )
        if not int(existing_same_count or 0):
            derived_payloads.append(report_state_payload)
        else:
            keep_report_dedupe_keys.add(report_state_payload.dedupe_key)

    if derived_payloads and workflow_session is None:
        workflow_session = await get_or_create_active_workflow_session(db, user_id=user_id)

    active_derived_dedupe_keys = {p.dedupe_key for p in derived_payloads} | keep_report_dedupe_keys
    if derived_payloads and workflow_session is not None:
        event_by_key = {
            e.dedupe_key: e
            for e in (
                await db.scalars(
                    select(WorkflowEvent).where(
                        WorkflowEvent.user_id == user_id,
                        WorkflowEvent.dedupe_key.in_({p.dedupe_key for p in derived_payloads}),
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
    """Return stored readiness when younger than WORKFLOW_SYNC_STATE_MAX_AGE and matching stamp (#2583)."""
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
    stamp = await workflow_input_stamp(db, user_id=user_id)
    return await _reusable_package_readiness(db, user_id=user_id, fingerprint=stamp)


async def _read_package_readiness(db: AsyncSession, *, user_id: UUID) -> tuple[dict, bool]:
    """Read reusable readiness or compute in memory without writing to DB."""
    if (stored := await stored_package_readiness(db, user_id=user_id)) is not None:
        return stored, True
    return await _current_package_readiness_dict(db, user_id=user_id), False


async def ensure_workflow_events_synced(db: AsyncSession, *, user_id: UUID) -> dict:
    """Derive workflow events only when input stamp changed or sync state expired (#2583)."""
    stamp = await workflow_input_stamp(db, user_id=user_id)
    if (stored := await _reusable_package_readiness(db, user_id=user_id, fingerprint=stamp)) is not None:
        return stored

    package_readiness = await sync_workflow_events_for_user(db, user_id=user_id)
    await db.execute(
        postgresql_insert(WorkflowSyncState)
        .values(user_id=user_id, source_fingerprint=stamp, package_readiness=package_readiness)
        .on_conflict_do_update(
            index_elements=[WorkflowSyncState.user_id],
            set_={
                "source_fingerprint": stamp,
                "package_readiness": package_readiness,
                "updated_at": func.now(),
            },
        )
    )
    return package_readiness


async def refresh_workflow_session_summary(db: AsyncSession, *, user_id: UUID, session_id: UUID | None) -> None:
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


def _is_mutable_derived_event(event: _ProjectedEvent) -> bool:
    return (
        event.family in MUTABLE_DERIVED_EVENT_FAMILIES
        and event.source_type in MUTABLE_DERIVED_EVENT_SOURCE_TYPES
        and event.status != WorkflowEventStatus.ARCHIVED
        and (event.source_type != "bank_statement" or event.dedupe_key.startswith("bank_statement:"))
    )


def _merge_projection_in_memory(
    *,
    user_id: UUID,
    persisted_events: list[WorkflowEvent],
    persisted_sessions: list[WorkflowSession],
    package_readiness: dict,
    uploaded_payloads: list[WorkflowEventCreate],
    derived_payloads: list[WorkflowEventCreate],
    report_state_payload: WorkflowEventCreate | None,
) -> tuple[list[_ProjectedEvent], list[_ProjectedSession], _ProjectedSession | None]:
    events = [_ProjectedEvent.from_orm_row(row) for row in persisted_events]
    by_dedupe = {item.dedupe_key: item for item in events}
    uploaded_by_source = {
        item.source_id: item
        for item in events
        if item.family == WorkflowEventFamily.SOURCE_UPLOADED and item.source_type == "bank_statement"
    }

    sessions = [
        _ProjectedSession(
            id=row.id,
            status=row.status,
            title=row.title,
            summary=row.summary,
            started_at=row.started_at,
            last_event_at=row.last_event_at,
            source_count=row.source_count,
            report_href=row.report_href,
        )
        for row in persisted_sessions
    ]
    active_session = next(
        (
            session
            for session, raw in zip(sessions, persisted_sessions, strict=True)
            if raw.status == WorkflowSessionStatus.ACTIVE and raw.dedupe_key == ACTIVE_WORKFLOW_SESSION_DEDUPE_KEY
        ),
        None,
    )
    active_session_persisted = active_session is not None
    if active_session is None:
        now = datetime.now(UTC)
        active_session = _ProjectedSession(
            id=_deterministic_session_id(user_id),
            status=WorkflowSessionStatus.ACTIVE,
            title="Upload-to-report session",
            summary="Current upload, processing, review, and report-readiness work.",
            started_at=now,
            last_event_at=None,
            source_count=0,
            report_href=None,
        )

    for payload in uploaded_payloads:
        existing = uploaded_by_source.get(payload.source_id) or by_dedupe.get(payload.dedupe_key)
        if existing is None:
            created = _ProjectedEvent.from_payload(user_id=user_id, session_id=active_session.id, payload=payload)
            events.append(created)
            by_dedupe[created.dedupe_key] = created
            uploaded_by_source[created.source_id] = created
        else:
            existing.apply_payload(payload, active_session.id)

    payloads_to_apply = list(derived_payloads)
    keep_report_keys: set[str] = set()
    if report_state_payload is not None:
        has_same_family = any(
            item.family == report_state_payload.family and item.status != WorkflowEventStatus.ARCHIVED
            for item in events
        )
        if not has_same_family:
            payloads_to_apply.append(report_state_payload)
        else:
            keep_report_keys.add(report_state_payload.dedupe_key)

    for payload in payloads_to_apply:
        existing = by_dedupe.get(payload.dedupe_key)
        if existing is None:
            created = _ProjectedEvent.from_payload(user_id=user_id, session_id=active_session.id, payload=payload)
            events.append(created)
            by_dedupe[created.dedupe_key] = created
        else:
            existing.apply_payload(payload, active_session.id)

    active_derived_keys = {p.dedupe_key for p in payloads_to_apply} | keep_report_keys
    if payloads_to_apply or str(package_readiness["state"]) in {"draft", "ready"}:
        for item in events:
            if _is_mutable_derived_event(item) and item.dedupe_key not in active_derived_keys:
                item.status = WorkflowEventStatus.ARCHIVED

    for session in sessions:
        session_active_events = [
            e for e in events if e.session_id == session.id and e.status != WorkflowEventStatus.ARCHIVED
        ]
        session.source_count = len(session_active_events)
        session.last_event_at = max((e.occurred_at for e in session_active_events), default=None)

    active_session_events = [
        e for e in events if e.session_id == active_session.id and e.status != WorkflowEventStatus.ARCHIVED
    ]
    if active_session_events and not active_session_persisted:
        active_session.source_count = len(active_session_events)
        active_session.last_event_at = max(e.occurred_at for e in active_session_events)
        sessions.insert(0, active_session)

    exposed_active = active_session if (active_session_events or active_session_persisted) else None
    sessions.sort(key=lambda s: (s.last_event_at or s.started_at, s.started_at), reverse=True)
    return events, sessions, exposed_active


async def _project_user_workflow_in_memory(
    db: AsyncSession,
    *,
    user_id: UUID,
    package_readiness: dict,
    uploaded_payloads: list[WorkflowEventCreate],
    derived_payloads: list[WorkflowEventCreate],
    report_state_payload: WorkflowEventCreate | None,
) -> tuple[list[_ProjectedEvent], list[_ProjectedSession], _ProjectedSession | None]:
    persisted_events = list((await db.scalars(select(WorkflowEvent).where(WorkflowEvent.user_id == user_id))).all())
    persisted_sessions = list(
        (
            await db.scalars(
                select(WorkflowSession)
                .where(WorkflowSession.user_id == user_id)
                .order_by(WorkflowSession.last_event_at.desc().nullslast(), WorkflowSession.created_at.desc())
            )
        ).all()
    )
    return _merge_projection_in_memory(
        user_id=user_id,
        persisted_events=persisted_events,
        persisted_sessions=persisted_sessions,
        package_readiness=package_readiness,
        uploaded_payloads=uploaded_payloads,
        derived_payloads=derived_payloads,
        report_state_payload=report_state_payload,
    )


def _assemble_status_response(
    *,
    package_readiness: dict,
    active_count: int,
    unread_count: int,
    action_required_count: int,
    blocked_count: int,
    processing_count: int,
    ready_count: int,
    blocked_href_fallback: str | None,
    action_href_fallback: str | None,
    active_session: WorkflowSession | _ProjectedSession | None,
) -> WorkflowStatusResponse:
    package_readiness_state = _collapse_package_readiness_state(str(package_readiness["state"]))
    package_blocking_count = int(package_readiness["blocking_count"])

    if blocked_count or package_readiness_state == WorkflowReportReadinessState.BLOCKED:
        primary_state = WorkflowPrimaryState.BLOCKED
        blocked_href = (
            str(package_readiness["action_href"])
            if package_readiness_state == WorkflowReportReadinessState.BLOCKED or not blocked_href_fallback
            else blocked_href_fallback
        )
        next_action = _next_action(
            WorkflowNextActionType.RESOLVE_BLOCKER,
            count=max(blocked_count, package_blocking_count),
            href=blocked_href,
        )
    elif action_required_count:
        primary_state = WorkflowPrimaryState.NEEDS_ACTION
        next_action = _next_action(
            WorkflowNextActionType.REVIEW_REQUIRED,
            count=action_required_count,
            href=action_href_fallback or "/upload",
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


def _status_from_projected_events(
    *,
    package_readiness: dict,
    events: list[_ProjectedEvent],
    active_session: _ProjectedSession | None,
) -> WorkflowStatusResponse:
    active_events = sorted(
        (e for e in events if e.status != WorkflowEventStatus.ARCHIVED),
        key=lambda e: (e.occurred_at, e.created_at),
        reverse=True,
    )
    blocked_event = next((e for e in active_events if e.severity == WorkflowEventSeverity.BLOCKED), None)
    action_event = next((e for e in active_events if e.severity == WorkflowEventSeverity.ACTION_REQUIRED), None)
    return _assemble_status_response(
        package_readiness=package_readiness,
        active_count=len(active_events),
        unread_count=sum(1 for e in active_events if e.status == WorkflowEventStatus.UNREAD),
        action_required_count=sum(1 for e in active_events if e.severity == WorkflowEventSeverity.ACTION_REQUIRED),
        blocked_count=sum(1 for e in active_events if e.severity == WorkflowEventSeverity.BLOCKED),
        processing_count=sum(1 for e in active_events if e.report_impact == WorkflowReportImpact.PROCESSING),
        ready_count=sum(1 for e in active_events if e.report_impact == WorkflowReportImpact.READY),
        blocked_href_fallback=blocked_event.action_href if blocked_event else None,
        action_href_fallback=action_event.action_href if action_event else None,
        active_session=active_session,
    )


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
    """Return bounded event list plus total count and grouped session summaries write-free (#987)."""
    package_readiness, is_synced = await _read_package_readiness(db, user_id=user_id)
    if not is_synced:
        package_readiness, uploaded_payloads, derived_payloads, report_state_payload, _ = await _derive_workflow_inputs(
            db, user_id=user_id, package_readiness=package_readiness
        )
        projected_events, projected_sessions, active_session = await _project_user_workflow_in_memory(
            db,
            user_id=user_id,
            package_readiness=package_readiness,
            uploaded_payloads=uploaded_payloads,
            derived_payloads=derived_payloads,
            report_state_payload=report_state_payload,
        )
        workflow_status = _status_from_projected_events(
            package_readiness=package_readiness, events=projected_events, active_session=active_session
        )
        filtered = [
            e
            for e in projected_events
            if (e.status == status if status is not None else e.status != WorkflowEventStatus.ARCHIVED)
        ]
        filtered.sort(key=lambda e: (e.occurred_at, e.created_at), reverse=True)
        sliced = filtered[:limit]
        page_session_ids = {e.session_id for e in sliced if e.session_id is not None}
        active_summary = workflow_status.active_session
        sessions: list[WorkflowSessionSummaryResponse] = []
        for s in projected_sessions:
            if s.id not in page_session_ids:
                continue
            if active_summary is not None and active_summary.id == s.id:
                sessions.append(active_summary)
            else:
                sess_active = [
                    e for e in projected_events if e.session_id == s.id and e.status != WorkflowEventStatus.ARCHIVED
                ]
                sessions.append(
                    _session_summary_model(
                        s,
                        primary_state=WorkflowPrimaryState.READY,
                        report_readiness=None,
                        counts=WorkflowEventCountsResponse(
                            unread=sum(1 for e in sess_active if e.status == WorkflowEventStatus.UNREAD),
                            action_required=sum(
                                1 for e in sess_active if e.severity == WorkflowEventSeverity.ACTION_REQUIRED
                            ),
                            blocked=sum(1 for e in sess_active if e.severity == WorkflowEventSeverity.BLOCKED),
                        ),
                    )
                )
        return WorkflowEventListResponse(
            items=[WorkflowEventResponse.model_validate(e) for e in sliced],
            total=len(filtered),
            sessions=sessions,
        )

    workflow_status = await get_workflow_status(db, user_id=user_id, synced_package_readiness=package_readiness)

    filters = [
        WorkflowEvent.user_id == user_id,
        WorkflowEvent.status == status if status is not None else WorkflowEvent.status != WorkflowEventStatus.ARCHIVED,
    ]
    total = await db.scalar(select(func.count(WorkflowEvent.id)).where(*filters))
    events = await list_workflow_events(db, user_id=user_id, status=status, limit=limit, include_archived=False)
    session_ids = {e.session_id for e in events if e.session_id is not None}
    sessions = []
    if session_ids:
        session_rows = (
            await db.scalars(
                select(WorkflowSession)
                .where(WorkflowSession.user_id == user_id, WorkflowSession.id.in_(session_ids))
                .order_by(WorkflowSession.last_event_at.desc().nullslast(), WorkflowSession.created_at.desc())
            )
        ).all()
        synced_active = workflow_status.active_session
        remaining_ids = [s.id for s in session_rows if synced_active is None or synced_active.id != s.id]
        counts_by_session: dict[UUID, WorkflowEventCountsResponse] = {}
        if remaining_ids:
            agg_rows = (
                await db.execute(
                    select(
                        WorkflowEvent.session_id,
                        func.count(WorkflowEvent.id)
                        .filter(WorkflowEvent.status == WorkflowEventStatus.UNREAD)
                        .label("unread"),
                        func.count(WorkflowEvent.id)
                        .filter(WorkflowEvent.severity == WorkflowEventSeverity.ACTION_REQUIRED)
                        .label("action_required"),
                        func.count(WorkflowEvent.id)
                        .filter(WorkflowEvent.severity == WorkflowEventSeverity.BLOCKED)
                        .label("blocked"),
                    )
                    .where(
                        WorkflowEvent.user_id == user_id,
                        WorkflowEvent.session_id.in_(remaining_ids),
                        WorkflowEvent.status != WorkflowEventStatus.ARCHIVED,
                    )
                    .group_by(WorkflowEvent.session_id)
                )
            ).all()
            counts_by_session = {
                row.session_id: WorkflowEventCountsResponse(
                    unread=int(row.unread or 0),
                    action_required=int(row.action_required or 0),
                    blocked=int(row.blocked or 0),
                )
                for row in agg_rows
            }
        sessions = [
            synced_active
            if synced_active is not None and synced_active.id == s.id
            else _session_summary_model(
                s,
                primary_state=WorkflowPrimaryState.READY,
                report_readiness=None,
                counts=counts_by_session.get(s.id)
                or WorkflowEventCountsResponse(unread=0, action_required=0, blocked=0),
            )
            for s in session_rows
        ]

    return WorkflowEventListResponse(
        items=[WorkflowEventResponse.model_validate(e) for e in events],
        total=int(total or 0),
        sessions=sessions,
    )


async def get_workflow_status(
    db: AsyncSession,
    *,
    user_id: UUID,
    synced_package_readiness: dict | None = None,
) -> WorkflowStatusResponse:
    """Return compact workflow status write-free for primary UI surfaces (#987, #2583)."""
    if synced_package_readiness is None:
        package_readiness, is_synced = await _read_package_readiness(db, user_id=user_id)
    else:
        package_readiness, is_synced = synced_package_readiness, True

    active_filters: list[ColumnElement[bool]] = [
        WorkflowEvent.user_id == user_id,
        WorkflowEvent.status != WorkflowEventStatus.ARCHIVED,
    ]
    mutable_filter = and_(
        WorkflowEvent.family.in_(MUTABLE_DERIVED_EVENT_FAMILIES),
        WorkflowEvent.source_type.in_(MUTABLE_DERIVED_EVENT_SOURCE_TYPES),
        or_(
            WorkflowEvent.source_type != "bank_statement",
            func.substr(WorkflowEvent.dedupe_key, 1, 15) == "bank_statement:",
        ),
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
                func.count(WorkflowEvent.id).filter(mutable_filter).label("mutable_active"),
            ).where(*active_filters)
        )
    ).one()

    if not is_synced:
        package_readiness, uploaded_payloads, derived_payloads, report_state_payload, _ = (
            await _derive_workflow_inputs(db, user_id=user_id, package_readiness=package_readiness)
        )
        if uploaded_payloads or derived_payloads or report_state_payload is not None or int(agg.mutable_active or 0) > 0:
            projected_events, _, active_session = await _project_user_workflow_in_memory(
                db,
                user_id=user_id,
                package_readiness=package_readiness,
                uploaded_payloads=uploaded_payloads,
                derived_payloads=derived_payloads,
                report_state_payload=report_state_payload,
            )
            return _status_from_projected_events(
                package_readiness=package_readiness,
                events=projected_events,
                active_session=active_session,
            )

    active_count = int(agg.active or 0)
    unread_count = int(agg.unread or 0)
    action_required_count = int(agg.action_required or 0)
    blocked_count = int(agg.blocked or 0)
    processing_count = int(agg.processing or 0)
    ready_count = int(agg.ready or 0)
    package_readiness_state = _collapse_package_readiness_state(str(package_readiness["state"]))

    async def representative_event(*filters: ColumnElement[bool]) -> WorkflowEvent | None:
        return await db.scalar(
            select(WorkflowEvent)
            .where(*active_filters, *filters)
            .order_by(WorkflowEvent.occurred_at.desc(), WorkflowEvent.created_at.desc())
            .limit(1)
        )

    blocked_href_fallback: str | None = None
    action_href_fallback: str | None = None
    if (blocked_count or package_readiness_state == WorkflowReportReadinessState.BLOCKED) and blocked_count:
        blocked_event = await representative_event(WorkflowEvent.severity == WorkflowEventSeverity.BLOCKED)
        blocked_href_fallback = blocked_event.action_href if blocked_event else None
    elif not (blocked_count or package_readiness_state == WorkflowReportReadinessState.BLOCKED) and action_required_count:
        ev = await representative_event(WorkflowEvent.severity == WorkflowEventSeverity.ACTION_REQUIRED)
        action_href_fallback = ev.action_href if ev else None

    active_session_row = await db.scalar(
        select(WorkflowSession)
        .where(WorkflowSession.user_id == user_id, WorkflowSession.status == WorkflowSessionStatus.ACTIVE)
        .order_by(WorkflowSession.last_event_at.desc().nullslast(), WorkflowSession.created_at.desc())
        .limit(1)
    )
    return _assemble_status_response(
        package_readiness=package_readiness,
        active_count=active_count,
        unread_count=unread_count,
        action_required_count=action_required_count,
        blocked_count=blocked_count,
        processing_count=processing_count,
        ready_count=ready_count,
        blocked_href_fallback=blocked_href_fallback,
        action_href_fallback=action_href_fallback,
        active_session=active_session_row,
    )


async def update_workflow_event_status(
    db: AsyncSession, *, event_id: UUID, user_id: UUID, status: WorkflowEventStatus
) -> WorkflowEvent | None:
    """Update read/archive lifecycle state for one user-scoped event."""
    event = await db.scalar(select(WorkflowEvent).where(WorkflowEvent.id == event_id, WorkflowEvent.user_id == user_id))
    if event is None:
        await ensure_workflow_events_synced(db, user_id=user_id)
        event = await db.scalar(
            select(WorkflowEvent).where(WorkflowEvent.id == event_id, WorkflowEvent.user_id == user_id)
        )
        if event is None:
            return None
    event.status = status
    await db.flush()
    await refresh_workflow_session_summary(db, user_id=user_id, session_id=event.session_id)
    return event
