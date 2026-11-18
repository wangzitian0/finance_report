from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event as sqlalchemy_event, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import src.workflow.extension.events as workflow_events
from src.extraction import BankStatementStatus, DocumentType, Stage1Status, StatementEventSource, UploadedDocument
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.reporting import current_package_readiness
from src.workflow import (
    WorkflowEvent,
    WorkflowEventCreate,
    WorkflowEventFamily,
    WorkflowEventResponse,
    WorkflowEventSeverity,
    WorkflowEventStatus,
    WorkflowPrimaryState,
    WorkflowReportImpact,
    WorkflowReportReadinessState,
    WorkflowSession,
    WorkflowSessionStatus,
)
from src.workflow.extension.builders import build_review_rejected_event_payload
from src.workflow.extension.events import (
    _apply_or_insert_event,
    _get_workflow_event_by_dedupe_key,
    _insert_workflow_event_conflict_safe,
    _workflow_event_from_payload,
    build_uploaded_statement_event_payload,
    get_or_create_active_workflow_session,
    get_workflow_status,
    list_workflow_events,
    list_workflow_events_response,
    refresh_workflow_session_summary,
    sync_workflow_events_for_user,
    update_workflow_event_status,
)
from tests.factories import AtomicTransactionFactory, ReconciliationMatchFactory


@pytest.fixture(autouse=True)
def _restore_readiness_read() -> Iterator[None]:
    workflow_events.current_package_readiness = current_package_readiness
    yield
    workflow_events.current_package_readiness = current_package_readiness


def _override_readiness_for_test(provider) -> None:
    async def readiness_provider(db, *, user_id, base_currency=None):
        del base_currency
        payload = await provider(db, user_id=user_id)
        return SimpleNamespace(model_dump=lambda mode="json": payload)

    workflow_events.current_package_readiness = readiness_provider


def _event_create(**overrides) -> WorkflowEventCreate:
    return WorkflowEventCreate(
        **{
            "family": WorkflowEventFamily.SOURCE_UPLOADED, "severity": WorkflowEventSeverity.INFO,
            "title": "Statement uploaded", "summary": "Processing will start shortly.",
            "source_type": "bank_statement", "source_id": uuid4(), "action_href": "/statements/123",
            "report_impact": WorkflowReportImpact.PROCESSING, "dedupe_key": f"test:{uuid4()}", "occurred_at": datetime.now(UTC),
            **overrides,
        }
    )


async def _seed_workflow_event(db: AsyncSession, *, user_id, payload: WorkflowEventCreate) -> WorkflowEvent:
    session_id = (await get_or_create_active_workflow_session(db, user_id=user_id)).id
    existing = await _get_workflow_event_by_dedupe_key(db, user_id=user_id, dedupe_key=payload.dedupe_key)
    event = await _apply_or_insert_event(db, user_id=user_id, existing=existing, payload=payload, session_id=session_id)
    await db.flush()
    await refresh_workflow_session_summary(db, user_id=user_id, session_id=session_id)
    return event


async def _sync_fetch(db: AsyncSession, user_id, *, family: WorkflowEventFamily, source_id=None) -> WorkflowEvent:
    await sync_workflow_events_for_user(db, user_id=user_id, base_currency="SGD")
    return await _fetch_event(db, user_id, family=family, source_id=source_id)


async def _fetch_event(db: AsyncSession, user_id, *, family: WorkflowEventFamily | None = None, source_id=None) -> WorkflowEvent:
    stmt = select(WorkflowEvent).where(WorkflowEvent.user_id == user_id)
    if family is not None:
        stmt = stmt.where(WorkflowEvent.family == family)
    if source_id is not None:
        stmt = stmt.where(WorkflowEvent.source_id == source_id)
    return (await db.execute(stmt)).scalar_one()


async def _make_statement(
    db: AsyncSession, user_id, *, original_filename: str, file_hash: str, institution: str = "Demo Bank",
    status: BankStatementStatus = BankStatementStatus.UPLOADED, stage1_status: Stage1Status | None = None, stage1_reviewed_at: datetime | None = None,
) -> tuple[StatementSummary, UploadedDocument]:
    doc = UploadedDocument(user_id=user_id, file_path=f"statements/{original_filename}", file_hash=file_hash, original_filename=original_filename, document_type=DocumentType.BANK_STATEMENT)
    db.add(doc)
    await db.flush()
    stmt = StatementSummary(user_id=user_id, uploaded_document_id=doc.id, file_hash=file_hash, institution=institution, status=status, stage1_status=stage1_status, stage1_reviewed_at=stage1_reviewed_at)
    db.add(stmt)
    await db.flush()
    return (stmt, doc)


@contextmanager
def _capture_sql(db_engine, pred) -> Iterator[list[str]]:
    stmts: list[str] = []
    cb = lambda _c, _cur, stmt, *_a: stmts.append(" ".join(stmt.lower().split())) if pred(" ".join(stmt.lower().split())) else None
    sqlalchemy_event.listen(db_engine.sync_engine, "before_cursor_execute", cb)
    try:
        yield stmts
    finally:
        sqlalchemy_event.remove(db_engine.sync_engine, "before_cursor_execute", cb)


async def _run_concurrent(db_engine, step1, step2):
    sm = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s1, sm() as s2:
        r1 = await step1(s1)
        t2 = asyncio.create_task(step2(s2))
        await asyncio.sleep(0.2)
        await s1.commit()
        r2 = await asyncio.wait_for(t2, timeout=5)
        await s2.commit()
    return (sm, r1, r2)


def test_AC19_1_and_8_workflow_model_and_schema_contracts() -> None:
    st, et = WorkflowSession.__table__, WorkflowEvent.__table__
    uqs = lambda tbl: {tuple(c.columns.keys()): c.name for c in tbl.constraints if c.__class__.__name__ == "UniqueConstraint"}
    cks = lambda tbl: {c.name for c in tbl.constraints if c.__class__.__name__ == "CheckConstraint"}
    idxs = lambda tbl: {i.name: tuple(i.columns.keys()) for i in tbl.indexes}
    assert (st.name, et.name, st.c.status.type.name, bool(et.c.session_id.foreign_keys), et.c.session_id.nullable, {s.value for s in WorkflowSessionStatus}, uqs(st)["user_id", "dedupe_key"], uqs(et)["user_id", "dedupe_key"], "ck_workflow_sessions_report_href_internal" in cks(st), "ck_workflow_events_action_href_internal" in cks(et)) == (
        "workflow_sessions", "workflow_events", "workflow_session_status_enum", True, True, {"active", "generated", "archived"}, "uq_workflow_sessions_user_dedupe_key", "uq_workflow_events_user_dedupe_key", True, True,
    )
    assert {et.c.family.type.name, et.c.severity.type.name, et.c.status.type.name, et.c.report_impact.type.name} == {"workflow_event_family_enum", "workflow_event_severity_enum", "workflow_event_status_enum", "workflow_report_impact_enum"}
    assert idxs(st)["idx_workflow_sessions_user_status_last_event"] == ("user_id", "status", "last_event_at")
    assert {k: idxs(et)[k] for k in ("idx_workflow_events_user_session_occurred", "idx_workflow_events_user_status_occurred", "idx_workflow_events_user_severity_occurred", "idx_workflow_events_user_family_occurred", "idx_workflow_events_user_source")} == {
        "idx_workflow_events_user_session_occurred": ("user_id", "session_id", "occurred_at"),
        "idx_workflow_events_user_status_occurred": ("user_id", "status", "occurred_at"),
        "idx_workflow_events_user_severity_occurred": ("user_id", "severity", "occurred_at"),
        "idx_workflow_events_user_family_occurred": ("user_id", "family", "occurred_at"),
        "idx_workflow_events_user_source": ("user_id", "source_type", "source_id"),
    }
    assert {"id", "user_id", "occurred_at", "family", "severity", "status", "title", "summary", "source_type", "source_id", "action_href", "report_impact", "dedupe_key", "created_at", "updated_at"} <= {c.key for c in inspect(WorkflowEvent).columns}

    valid = _event_create()
    assert (valid.action_href, valid.report_impact) == ("/statements/123", WorkflowReportImpact.PROCESSING)
    for fn in (
        *[lambda h=h: _event_create(action_href=h, dedupe_key=f"bad:{h}") for h in ("https://example.com/review", "//example.com/review", "javascript:alert(1)", "statements/123")],
        lambda: _event_create(family=WorkflowEventFamily.REPORT_READY, severity=WorkflowEventSeverity.SUCCESS, action_href="/reports/current", report_impact="published"),
        lambda: WorkflowEventResponse.model_validate(SimpleNamespace(id=uuid4(), user_id=uuid4(), occurred_at=datetime.now(UTC), family=WorkflowEventFamily.REPORT_READY, severity=WorkflowEventSeverity.SUCCESS, status=WorkflowEventStatus.UNREAD, title="Report ready", summary="The report can be opened.", source_type="report", source_id=uuid4(), action_href="/reports/current", report_impact="published", dedupe_key="report:current:report.ready", created_at=datetime.now(UTC), updated_at=datetime.now(UTC))),
    ):
        with pytest.raises(ValidationError):
            fn()


def test_statement_rejection_emits_warning_severity_and_rejected_title() -> None:
    now = datetime.now(UTC)
    stmt = StatementEventSource(id=uuid4(), user_id=uuid4(), uploaded_document_id=uuid4(), file_hash="dummyhash", status="rejected", stage1_status="_STAGE1_REJECTED", created_at=now, updated_at=now, stage1_reviewed_at=now)
    payload = build_review_rejected_event_payload(stmt, filename="margin_2025.csv")
    assert (payload.severity, payload.title, "rejected" in payload.summary.lower(), payload.action_href) == (WorkflowEventSeverity.WARNING, "Source review rejected", True, f"/statements/{stmt.id}")


async def test_AC19_8_9_active_workflow_session_concurrency_and_reactivation(db, db_engine, test_user) -> None:
    sm, first, second = await _run_concurrent(db_engine, lambda s: get_or_create_active_workflow_session(s, user_id=test_user.id), lambda s: get_or_create_active_workflow_session(s, user_id=test_user.id))
    async with sm() as verify:
        rows = (await verify.execute(select(WorkflowSession).where(WorkflowSession.user_id == test_user.id, WorkflowSession.dedupe_key == "active-upload-to-report"))).scalars().all()
    assert (first.id == second.id, len(rows), rows[0].status) == (True, 1, WorkflowSessionStatus.ACTIVE)

    rows[0].status, rows[0].summary = WorkflowSessionStatus.ARCHIVED, "Archived synthetic session."
    await db.merge(rows[0])
    await db.flush()
    reactivated = await get_or_create_active_workflow_session(db, user_id=test_user.id)
    assert (reactivated.id, reactivated.status, reactivated.summary) == (rows[0].id, WorkflowSessionStatus.ACTIVE, "Current upload, processing, review, and report-readiness work.")


async def test_AC19_1_and_3_statement_upsert_refresh_and_user_isolation(db, test_user) -> None:
    statement, document = await _make_statement(db, test_user.id, original_filename="demo.csv", file_hash="a" * 64)
    first = await _sync_fetch(db, test_user.id, family=WorkflowEventFamily.SOURCE_UPLOADED, source_id=statement.id)
    assert (first.severity, first.status, first.action_href, first.report_impact, first.session_id is not None) == (WorkflowEventSeverity.INFO, WorkflowEventStatus.UNREAD, f"/statements/{statement.id}", WorkflowReportImpact.PROCESSING, True)
    first.status, document.original_filename = WorkflowEventStatus.ARCHIVED, "renamed.csv"
    await db.flush()
    second = await _sync_fetch(db, test_user.id, family=WorkflowEventFamily.SOURCE_UPLOADED, source_id=statement.id)
    assert (second.id, second.status, "renamed.csv" in second.summary) == (first.id, WorkflowEventStatus.ARCHIVED, True)

    other_user = User(email=f"other-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other_user)
    await db.flush()
    isolated = await _seed_workflow_event(db, user_id=test_user.id, payload=_event_create(family=WorkflowEventFamily.REVIEW_REQUIRED, severity=WorkflowEventSeverity.ACTION_REQUIRED, title="Review required", summary="One statement needs confirmation.", action_href="/audit", report_impact=WorkflowReportImpact.BLOCKED, dedupe_key="bank-statement:review-required:test"))
    assert isolated.id in [i.id for i in await list_workflow_events(db, user_id=test_user.id)] and await list_workflow_events(db, user_id=other_user.id) == []
    assert await update_workflow_event_status(db, event_id=isolated.id, user_id=other_user.id, status=WorkflowEventStatus.READ, base_currency="SGD") is None
    updated = await update_workflow_event_status(db, event_id=isolated.id, user_id=test_user.id, status=WorkflowEventStatus.ARCHIVED, base_currency="SGD")
    assert (updated.status, WorkflowEventResponse.model_validate(updated).status) == (WorkflowEventStatus.ARCHIVED, WorkflowEventStatus.ARCHIVED)


async def test_AC19_12_2_review_lifecycle_and_null_stage1_derivation(db, test_user) -> None:
    stmt, _ = await _make_statement(db, test_user.id, original_filename="review.csv", file_hash="1" * 64, institution="Review Bank", status=BankStatementStatus.PARSED, stage1_status=Stage1Status.PENDING_REVIEW)
    review_ev = await _sync_fetch(db, test_user.id, family=WorkflowEventFamily.REVIEW_REQUIRED)
    review_ev.status = WorkflowEventStatus.READ
    await db.flush()
    same_ev = await _sync_fetch(db, test_user.id, family=WorkflowEventFamily.REVIEW_REQUIRED)
    assert (same_ev.id, same_ev.status, same_ev.severity, same_ev.action_href) == (review_ev.id, WorkflowEventStatus.READ, WorkflowEventSeverity.ACTION_REQUIRED, f"/statements/{same_ev.source_id}")

    stmt.stage1_status, stmt.stage1_reviewed_at = Stage1Status.APPROVED, datetime.now(UTC)
    await db.flush()
    resolved = await _sync_fetch(db, test_user.id, family=WorkflowEventFamily.REVIEW_REQUIRED)
    completed = await _fetch_event(db, test_user.id, family=WorkflowEventFamily.REVIEW_COMPLETED)
    assert (resolved.status, completed.status, completed.severity, completed.action_href) == (WorkflowEventStatus.ARCHIVED, WorkflowEventStatus.UNREAD, WorkflowEventSeverity.SUCCESS, f"/statements/{stmt.id}")

    pending_stmt, _ = await _make_statement(db, test_user.id, original_filename="null-stage1.csv", file_hash="6" * 64, status=BankStatementStatus.PARSED, stage1_status=None)
    rej_rev, _ = await _make_statement(db, test_user.id, original_filename="review-rejected.csv", file_hash="7" * 64, status=BankStatementStatus.REJECTED, stage1_status=Stage1Status.REJECTED, stage1_reviewed_at=datetime.now(UTC))
    rej_parse, _ = await _make_statement(db, test_user.id, original_filename="parser-rejected.csv", file_hash="8" * 64, status=BankStatementStatus.REJECTED, stage1_status=None)
    pending_ev = await _sync_fetch(db, test_user.id, family=WorkflowEventFamily.REVIEW_REQUIRED, source_id=pending_stmt.id)
    rev_comp_ev = await _fetch_event(db, test_user.id, family=WorkflowEventFamily.REVIEW_COMPLETED, source_id=rej_rev.id)
    parse_fail_ev = await _fetch_event(db, test_user.id, family=WorkflowEventFamily.SOURCE_PARSING_FAILED, source_id=rej_parse.id)
    fail_cnt = await db.scalar(select(func.count(WorkflowEvent.id)).where(WorkflowEvent.user_id == test_user.id, WorkflowEvent.family == WorkflowEventFamily.SOURCE_PARSING_FAILED, WorkflowEvent.source_id == rej_rev.id))
    assert (pending_ev.status, pending_ev.action_href, rev_comp_ev.status, fail_cnt, parse_fail_ev.status, parse_fail_ev.action_href) == (
        WorkflowEventStatus.UNREAD, f"/statements/{pending_stmt.id}", WorkflowEventStatus.UNREAD, 0, WorkflowEventStatus.UNREAD, f"/statements/{rej_parse.id}",
    )


async def test_AC19_12_3_and_4_readiness_transitions_and_blocker_scopes(db, test_user) -> None:
    blocker_payload = {"state": "blocked", "action_href": "/audit", "blocking_count": 2, "blockers": [{"code": "pending_review", "label": "Pending source review", "count": 2, "reason": "Review needed.", "action_href": "/audit"}]}
    current = blocker_payload
    _override_readiness_for_test(lambda _db, **_kw: asyncio.sleep(0, result=current))

    blocked_ev = await _sync_fetch(db, test_user.id, family=WorkflowEventFamily.REPORT_BLOCKED)
    blocked_ev.status = WorkflowEventStatus.READ
    await db.flush()
    same = await _sync_fetch(db, test_user.id, family=WorkflowEventFamily.REPORT_BLOCKED)
    assert (same.id, same.status, same.report_impact) == (blocked_ev.id, WorkflowEventStatus.READ, WorkflowReportImpact.BLOCKED)

    current = {"state": "ready", "action_href": "/reports?tab=package", "blocking_count": 0, "blockers": []}
    ready_ev = await _sync_fetch(db, test_user.id, family=WorkflowEventFamily.REPORT_READY)
    assert (same.status, ready_ev.status, ready_ev.action_href) == (WorkflowEventStatus.ARCHIVED, WorkflowEventStatus.UNREAD, "/reports?tab=package")

    current = {"state": "generated", "action_href": "/reports?tab=package", "blocking_count": 0, "blockers": []}
    gen_ev = await _sync_fetch(db, test_user.id, family=WorkflowEventFamily.REPORT_GENERATED)
    assert (gen_ev.status, gen_ev.action_href, ready_ev.status) == (WorkflowEventStatus.UNREAD, "/reports?tab=package", WorkflowEventStatus.ARCHIVED)

    current = blocker_payload
    await sync_workflow_events_for_user(db, user_id=test_user.id, base_currency="SGD")
    current = {"state": "draft", "action_href": "/upload", "blocking_count": 0, "blockers": []}
    assert (await _sync_fetch(db, test_user.id, family=WorkflowEventFamily.REPORT_BLOCKED)).status == WorkflowEventStatus.ARCHIVED

    current = {
        "state": "blocked", "action_href": "/reconciliation?tab=review-queue", "blocking_count": 3,
        "blockers": [
            {"code": "reconciliation_blocked", "label": "Reconciliation blockers", "count": 2, "reason": "Pending reconciliation.", "action_href": "/reconciliation?tab=review-queue"},
            {"code": "processing_account_unresolved", "label": "Processing account unresolved", "count": 1, "reason": "Must net to zero.", "action_href": "/upload"},
        ],
    }
    await sync_workflow_events_for_user(db, user_id=test_user.id, base_currency="SGD")
    events = (await db.execute(select(WorkflowEvent).where(WorkflowEvent.user_id == test_user.id, WorkflowEvent.status != WorkflowEventStatus.ARCHIVED, WorkflowEvent.family.in_([WorkflowEventFamily.RECONCILIATION_BLOCKED, WorkflowEventFamily.REPORT_BLOCKED])).order_by(WorkflowEvent.family))).scalars().all()
    assert [(e.family, e.action_href, e.source_type, e.severity, e.report_impact) for e in events] == [
        (WorkflowEventFamily.RECONCILIATION_BLOCKED, "/reconciliation?tab=review-queue", "readiness_blocker", WorkflowEventSeverity.BLOCKED, WorkflowReportImpact.BLOCKED),
        (WorkflowEventFamily.REPORT_BLOCKED, "/upload", "readiness_blocker", WorkflowEventSeverity.BLOCKED, WorkflowReportImpact.BLOCKED),
    ]

    await _make_statement(db, test_user.id, original_filename="ready.csv", file_hash="2" * 64, institution="Ready Bank", status=BankStatementStatus.PARSED, stage1_status=Stage1Status.APPROVED, stage1_reviewed_at=datetime.now(UTC))
    current = {"state": "ready", "action_href": "/reports?tab=package", "blocking_count": 0, "blockers": []}
    status = await get_workflow_status(db, user_id=test_user.id, base_currency="SGD")
    assert (status.primary_state.value, status.next_action.type.value, status.next_action.href) == ("ready", "open_report", "/reports?tab=package")


async def test_AC19_3_1_sync_uses_bounded_workflow_event_lookup(db, db_engine, test_user) -> None:
    for index in range(3):
        await _make_statement(db, test_user.id, original_filename=f"bulk-{index}.csv", file_hash=f"{index}" * 64)
    await db.commit()
    with _capture_sql(db_engine, lambda s: s.startswith("select") and "workflow_events" in s) as stmts:
        await sync_workflow_events_for_user(db, user_id=test_user.id, base_currency="SGD")
    assert len(stmts) <= 3 and "source_id in (" in stmts[0]


async def test_AC19_3_2_and_22_4_badge_aggregate_and_pending_recon(db, db_engine, test_user) -> None:
    await _seed_workflow_event(db, user_id=test_user.id, payload=_event_create(family=WorkflowEventFamily.REVIEW_REQUIRED, severity=WorkflowEventSeverity.ACTION_REQUIRED, action_href="/audit", report_impact=WorkflowReportImpact.BLOCKED))
    await _seed_workflow_event(db, user_id=test_user.id, payload=_event_create(family=WorkflowEventFamily.REPORT_PROCESSING, severity=WorkflowEventSeverity.INFO, action_href="/reports", report_impact=WorkflowReportImpact.PROCESSING))
    await db.commit()
    with _capture_sql(db_engine, lambda s: "workflow_events" in s) as stmts:
        status = await get_workflow_status(db, user_id=test_user.id, base_currency="SGD")
    count_q = [s for s in stmts if "count(" in s]
    rep_q = [s for s in stmts if "select workflow_events." in s and "count(" not in s and "order by workflow_events.occurred_at desc" in s]
    assert (status.primary_state.value, len(count_q), len(rep_q)) == ("needs_action", 1, 1)

    atomic_txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id)
    await ReconciliationMatchFactory.create_async(db, atomic_txn_id=atomic_txn.id, journal_entry_ids=[])
    await db.commit()
    await sync_workflow_events_for_user(db, user_id=test_user.id, base_currency="SGD")
    recon = [e for e in await list_workflow_events(db, user_id=test_user.id) if e.family == WorkflowEventFamily.RECONCILIATION_BLOCKED]
    await sync_workflow_events_for_user(db, user_id=test_user.id, base_currency="SGD")
    recon2 = [e for e in await list_workflow_events(db, user_id=test_user.id) if e.family == WorkflowEventFamily.RECONCILIATION_BLOCKED]
    assert (len(recon), recon[0].action_href, len(recon2), recon2[0].id) == (1, "/reconciliation?tab=review-queue", 1, recon[0].id)


async def test_AC19_14_concurrent_upsert_sync_and_duplicate_conflict_safe(db, db_engine, test_user) -> None:
    payload = build_uploaded_statement_event_payload(SimpleNamespace(id=uuid4(), created_at=datetime.now(UTC)), "concurrent.pdf")
    sm, first, second = await _run_concurrent(db_engine, lambda s: _seed_workflow_event(s, user_id=test_user.id, payload=payload), lambda s: _seed_workflow_event(s, user_id=test_user.id, payload=payload))
    async with sm() as verify:
        events = (await verify.execute(select(WorkflowEvent).where(WorkflowEvent.user_id == test_user.id, WorkflowEvent.dedupe_key == payload.dedupe_key))).scalars().all()
    assert (len(events), first.dedupe_key, second.dedupe_key) == (1, payload.dedupe_key, payload.dedupe_key)

    dup_payload = build_uploaded_statement_event_payload(SimpleNamespace(id=uuid4(), created_at=datetime.now(UTC)), "duplicate.pdf")
    ws = await get_or_create_active_workflow_session(db, user_id=test_user.id)
    existing = _workflow_event_from_payload(user_id=test_user.id, payload=dup_payload, session_id=ws.id)
    db.add(existing)
    await db.commit()
    recovered = await _insert_workflow_event_conflict_safe(db, user_id=test_user.id, payload=dup_payload, session_id=ws.id)
    await db.flush()
    cnt = await db.scalar(select(func.count(WorkflowEvent.id)).where(WorkflowEvent.user_id == test_user.id, WorkflowEvent.dedupe_key == dup_payload.dedupe_key))
    assert (recovered.id, cnt) == (existing.id, 1)

    async with sm() as setup:
        stmt, _ = await _make_statement(setup, test_user.id, original_filename="race.pdf", file_hash=uuid4().hex, status=BankStatementStatus.UPLOADED)
        await setup.commit()
    await _run_concurrent(db_engine, lambda s: sync_workflow_events_for_user(s, user_id=test_user.id, base_currency="SGD"), lambda s: sync_workflow_events_for_user(s, user_id=test_user.id, base_currency="SGD"))
    async with sm() as verify:
        uploaded = (await verify.execute(select(WorkflowEvent).where(WorkflowEvent.user_id == test_user.id, WorkflowEvent.source_id == stmt.id, WorkflowEvent.family == WorkflowEventFamily.SOURCE_UPLOADED))).scalars().all()
    assert len(uploaded) == 1


async def test_AC19_2_7_events_session_summary_agrees_with_status_and_reads_once(db, test_user) -> None:
    call_count = 0

    async def counting_readiness(_db, **_kwargs):
        nonlocal call_count
        call_count += 1
        return {"state": "blocked", "action_href": "/reports?tab=package", "blocking_count": 1, "blockers": [{"code": "balance_mismatch", "label": "Balance validation mismatch", "count": 1, "reason": "Balance mismatch: expected 52754.77, got 52842.53.", "action_href": "/audit"}]}

    _override_readiness_for_test(counting_readiness)
    await sync_workflow_events_for_user(db, user_id=test_user.id, base_currency="SGD")
    await db.flush()
    call_count = 0
    events = await list_workflow_events_response(db, user_id=test_user.id, limit=10, base_currency="SGD")
    assert call_count == 1
    status = await get_workflow_status(db, user_id=test_user.id, base_currency="SGD")
    active = next(s for s in events.sessions if s.id == status.active_session.id)
    assert (bool(events.sessions), status.primary_state, status.report_readiness.state, active.primary_state, active.report_readiness.state) == (
        True, WorkflowPrimaryState.BLOCKED, WorkflowReportReadinessState.BLOCKED, WorkflowPrimaryState.BLOCKED, WorkflowReportReadinessState.BLOCKED,
    )
