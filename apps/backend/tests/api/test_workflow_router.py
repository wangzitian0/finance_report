from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.routing import iter_route_contexts
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import BankStatementStatus, DocumentType, RuleType, Stage1Status, UploadedDocument
from src.extraction.orm.layer3 import ClassificationRule
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User, get_current_user_id
from src.ledger import AccountType
from src.main import app
from src.reporting import ReportSnapshot, ReportType, current_package_readiness
from src.workflow import (
    WorkflowEvent,
    WorkflowEventCreate,
    WorkflowEventFamily,
    WorkflowEventListResponse,
    WorkflowEventSeverity,
    WorkflowEventStatus,
    WorkflowNextActionType,
    WorkflowPrimaryState,
    WorkflowReportImpact,
    WorkflowReportReadinessState,
    WorkflowSession,
    WorkflowStatusResponse,
)
from src.workflow.extension.events import (
    _apply_or_insert_event,
    _get_workflow_event_by_dedupe_key,
    get_or_create_active_workflow_session,
    refresh_workflow_session_summary,
)
from tests.api._statement_router_fixtures import add_statement
from tests.factories import AccountFactory, UserFactory
from tests.ledger._ledger_helpers import create_valid_posted_entry

pytestmark = pytest.mark.asyncio
_next_action = lambda t, *, count, href, label, summary: {
    "type": t,
    "count": count,
    "href": href,
    "label": label,
    "summary": summary,
}


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
) -> WorkflowEvent:
    sid, session_id = uuid4(), (await get_or_create_active_workflow_session(db, user_id=user_id)).id
    payload = WorkflowEventCreate(
        family=family,
        severity=severity,
        title=title,
        summary=f"{title} summary",
        source_type="workflow_test",
        source_id=sid,
        action_href=action_href,
        report_impact=report_impact,
        dedupe_key=f"workflow-test:{sid}:{family.value}",
        occurred_at=occurred_at or datetime.now(UTC),
    )
    event = await _apply_or_insert_event(
        db,
        user_id=user_id,
        existing=await _get_workflow_event_by_dedupe_key(db, user_id=user_id, dedupe_key=payload.dedupe_key),
        payload=payload,
        session_id=session_id,
    )
    event.status = status
    await db.flush()
    await refresh_workflow_session_summary(db, user_id=user_id, session_id=session_id)
    return event


async def _req_as_user(public_client: AsyncClient, user_id: UUID, method: str, path: str, **kwargs):
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    try:
        return await public_client.request(method, path, **kwargs)
    finally:
        app.dependency_overrides.pop(get_current_user_id, None)


async def _make_statement(
    db: AsyncSession, user_id: UUID, *, original_filename: str, file_hash: str, **kwargs
) -> StatementSummary:
    doc = UploadedDocument(
        user_id=user_id,
        file_path=f"statements/{original_filename}",
        file_hash=file_hash,
        original_filename=original_filename,
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(doc)
    await db.flush()
    return await add_statement(
        db,
        user_id,
        file_hash,
        uploaded_document_id=doc.id,
        institution=kwargs.pop("institution", "Demo Bank"),
        status=kwargs.pop("status", BankStatementStatus.UPLOADED),
        closing=None,
        **kwargs,
    )


async def test_AC19_2_1_and_AC19_2_6_workflow_contract_and_routes() -> None:
    model = WorkflowStatusResponse(
        primary_state=WorkflowPrimaryState.NEEDS_ACTION,
        next_action={
            "type": WorkflowNextActionType.REVIEW_REQUIRED,
            "count": 2,
            "href": "/review?source=events",
            "label": "Review required",
            "summary": "Confirm source records before reporting.",
        },
        report_readiness={"state": WorkflowReportReadinessState.BLOCKED, "blocking_count": 1, "href": "/reports"},
        event_counts={"unread": 4, "action_required": 2, "blocked": 1},
    )
    assert model.model_dump(mode="json") == {
        "primary_state": "needs_action",
        "next_action": {
            "type": "review_required",
            "count": 2,
            "href": "/review?source=events",
            "label": "Review required",
            "summary": "Confirm source records before reporting.",
        },
        "report_readiness": {"state": "blocked", "blocking_count": 1, "href": "/reports"},
        "event_counts": {"unread": 4, "action_required": 2, "blocked": 1},
        "active_session": None,
    }
    assert {"/workflow/status", "/workflow/events", "/workflow/events/{event_id}"} <= {
        getattr(c.route, "path", None) for c in iter_route_contexts(app.routes)
    }


async def test_AC19_2_2_workflow_status_endpoint_returns_priority_summaries(
    public_client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    empty = (await _req_as_user(public_client, test_user.id, "GET", "/workflow/status")).json()
    assert (
        empty["primary_state"],
        empty["next_action"],
        empty["report_readiness"],
        empty["event_counts"],
        empty["active_session"],
    ) == (
        "empty",
        _next_action(
            "upload",
            count=0,
            href="/upload",
            label="Upload statements",
            summary="Add source documents to start the upload-to-report workflow.",
        ),
        {"state": "none", "blocking_count": 0, "href": "/reports?tab=package"},
        {"unread": 0, "action_required": 0, "blocked": 0},
        None,
    )

    await _make_statement(db, test_user.id, original_filename="status-demo.csv", file_hash="c" * 64)
    await db.commit()
    proc = (await _req_as_user(public_client, test_user.id, "GET", "/workflow/status")).json()
    assert (
        proc["primary_state"],
        proc["next_action"],
        proc["report_readiness"],
        proc["event_counts"],
        proc["active_session"]["title"],
        proc["active_session"]["source_count"],
        proc["active_session"]["primary_state"],
    ) == (
        "processing",
        _next_action(
            "wait",
            count=1,
            href="/upload",
            label="View processing",
            summary="Automation is processing source files; open the session timeline for progress.",
        ),
        {"state": "none", "blocking_count": 0, "href": "/reports?tab=package"},
        {"unread": 1, "action_required": 0, "blocked": 0},
        "Upload-to-report session",
        1,
        "processing",
    )

    for fam, sev, href, title, state, action, label, summary, exp_counts in [
        (
            WorkflowEventFamily.REVIEW_REQUIRED,
            WorkflowEventSeverity.ACTION_REQUIRED,
            "/review?source=events",
            "Review required",
            "needs_action",
            "review_required",
            "Review required",
            "Confirm the source or review item so trusted report preparation can continue.",
            {"unread": 2, "action_required": 1, "blocked": 0},
        ),
        (
            WorkflowEventFamily.RECONCILIATION_BLOCKED,
            WorkflowEventSeverity.BLOCKED,
            "/reconciliation?tab=unmatched",
            "Reconciliation blocked",
            "blocked",
            "resolve_blocker",
            "Resolve blocker",
            "Resolve the blocking condition before the report package can be trusted.",
            {"unread": 3, "action_required": 1, "blocked": 1},
        ),
    ]:
        await _create_event(
            db,
            user_id=test_user.id,
            family=fam,
            severity=sev,
            report_impact=WorkflowReportImpact.BLOCKED,
            action_href=href,
            title=title,
        )
        await db.commit()
        res = (await _req_as_user(public_client, test_user.id, "GET", "/workflow/status")).json()
        assert (res["primary_state"], res["next_action"], res["event_counts"]) == (
            state,
            _next_action(action, count=1, href=href, label=label, summary=summary),
            exp_counts,
        )

    unproven_user = await UserFactory.create_async(db)
    await _create_event(
        db,
        user_id=unproven_user.id,
        family=WorkflowEventFamily.REPORT_READY,
        severity=WorkflowEventSeverity.SUCCESS,
        report_impact=WorkflowReportImpact.READY,
        action_href="/reports",
        title="Report ready",
    )
    await create_valid_posted_entry(
        db,
        unproven_user.id,
        entry_date=date(2026, 5, 31),
        memo="Ready report input",
        debit_account_type=AccountType.EXPENSE,
    )
    unproven = (await _req_as_user(public_client, unproven_user.id, "GET", "/workflow/status")).json()
    assert {
        b.code: b.count
        for b in (await current_package_readiness(db, user_id=unproven_user.id, base_currency="SGD")).blockers
    } == {"cash_identity_missing": 1, "cash_balance_input_missing": 1, "unproven_package_input": 3}
    assert (
        unproven["primary_state"],
        unproven["next_action"],
        unproven["report_readiness"],
        unproven["event_counts"],
    ) == (
        "blocked",
        _next_action(
            "resolve_blocker",
            count=5,
            href="/reports?tab=package",
            label="Resolve blocker",
            summary="Resolve the blocking condition before the report package can be trusted.",
        ),
        {"state": "blocked", "blocking_count": 5, "href": "/reports?tab=package"},
        {"unread": 4, "action_required": 0, "blocked": 3},
    )


async def test_AC19_2_2_workflow_status_consumes_package_readiness_fact_source(
    public_client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    acc = await AccountFactory.create_async(db, user_id=test_user.id, name="Workflow Cash", type=AccountType.ASSET)
    rule = ClassificationRule(
        user_id=test_user.id,
        version_number=1,
        effective_date=date(2026, 1, 1),
        rule_name=f"workflow-{uuid4()}",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["workflow"]},
        created_by=test_user.id,
    )
    db.add(rule)
    await db.flush()
    stmt = StatementSummary(
        user_id=test_user.id,
        account_id=acc.id,
        file_hash=uuid4().hex,
        institution="Workflow Bank",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
        status=BankStatementStatus.APPROVED,
        stage1_status=Stage1Status.APPROVED,
        balance_validated=True,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    snap = ReportSnapshot(
        user_id=test_user.id,
        report_type=ReportType.BALANCE_SHEET,
        as_of_date=date(2026, 5, 31),
        start_date=None,
        rule_version_id=rule.id,
        report_data={"total_assets": "100.00"},
        is_latest=True,
        created_at=datetime(2026, 5, 2, tzinfo=UTC),
        updated_at=datetime(2026, 5, 2, tzinfo=UTC),
    )
    for mutate in (
        lambda: db.add(stmt),
        lambda: db.add(snap),
        lambda: setattr(stmt, "updated_at", datetime(2026, 5, 3, tzinfo=UTC)),
    ):
        mutate()
        await db.commit()
        assert (await _req_as_user(public_client, test_user.id, "GET", "/workflow/status")).json()[
            "report_readiness"
        ] == {"state": "none", "blocking_count": 0, "href": "/reports?tab=package"}

    blocked_user = await UserFactory.create_async(db)
    blocked_stmt = await _make_statement(
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
    blocked = (await _req_as_user(public_client, blocked_user.id, "GET", "/workflow/status")).json()
    assert (blocked["primary_state"], blocked["next_action"], blocked["report_readiness"], blocked["event_counts"]) == (
        "needs_action",
        _next_action(
            "review_required",
            count=1,
            href=f"/statements/{blocked_stmt.id}",
            label="Review required",
            summary="Confirm the source or review item so trusted report preparation can continue.",
        ),
        {"state": "none", "blocking_count": 0, "href": "/reports?tab=package"},
        {"unread": 2, "action_required": 1, "blocked": 0},
    )


async def test_AC19_2_3_workflow_events_endpoint_lists_bounded_user_events(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    other, now = await UserFactory.create_async(db), datetime.now(UTC)
    archived, older, newer, _ = [
        await _create_event(
            db,
            user_id=uid,
            family=fam,
            severity=sev,
            report_impact=imp,
            action_href=href,
            title=title,
            occurred_at=now - timedelta(minutes=mins),
            status=st,
        )
        for uid, fam, sev, imp, href, title, mins, st in [
            (
                test_user.id,
                WorkflowEventFamily.SOURCE_UPLOADED,
                WorkflowEventSeverity.INFO,
                WorkflowReportImpact.PROCESSING,
                "/statements/archived",
                "Archived",
                3,
                WorkflowEventStatus.ARCHIVED,
            ),
            (
                test_user.id,
                WorkflowEventFamily.REPORT_PROCESSING,
                WorkflowEventSeverity.INFO,
                WorkflowReportImpact.PROCESSING,
                "/reports",
                "Older",
                2,
                WorkflowEventStatus.UNREAD,
            ),
            (
                test_user.id,
                WorkflowEventFamily.REVIEW_REQUIRED,
                WorkflowEventSeverity.ACTION_REQUIRED,
                WorkflowReportImpact.BLOCKED,
                "/audit",
                "Newer",
                1,
                WorkflowEventStatus.UNREAD,
            ),
            (
                other.id,
                WorkflowEventFamily.REPORT_BLOCKED,
                WorkflowEventSeverity.BLOCKED,
                WorkflowReportImpact.BLOCKED,
                "/reports",
                "Other",
                0,
                WorkflowEventStatus.UNREAD,
            ),
        ]
    ]
    await db.commit()
    data, limited, arch = [
        WorkflowEventListResponse.model_validate((await client.get(url)).json())
        for url in ("/workflow/events", "/workflow/events?limit=1", "/workflow/events?status=archived")
    ]
    assert (data.total, [i.id for i in data.items], len(data.sessions), data.sessions[0].source_count) == (
        2,
        [newer.id, older.id],
        1,
        2,
    ) and all(i.session_id is not None for i in data.items)
    assert (limited.total, [i.id for i in limited.items], arch.total, [i.id for i in arch.items]) == (
        2,
        [newer.id],
        1,
        [archived.id],
    )


async def test_AC19_2_4_workflow_event_patch_is_user_scoped(
    client: AsyncClient, public_client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    other = await UserFactory.create_async(db)
    event = await _create_event(
        db,
        user_id=test_user.id,
        family=WorkflowEventFamily.REVIEW_REQUIRED,
        severity=WorkflowEventSeverity.ACTION_REQUIRED,
        report_impact=WorkflowReportImpact.BLOCKED,
        action_href="/audit",
        title="Patch owned event",
    )
    await db.commit()
    resp = await client.patch(f"/workflow/events/{event.id}", json={"status": "read"})
    assert (
        resp.status_code == 200
        and resp.json()["status"] == "read"
        and (
            await _req_as_user(
                public_client, other.id, "PATCH", f"/workflow/events/{event.id}", json={"status": "archived"}
            )
        ).status_code
        == 404
    )
    await db.refresh(event)
    assert (
        event.status == WorkflowEventStatus.READ
        and (await client.patch(f"/workflow/events/{uuid4()}", json={"status": "read"})).status_code == 404
    )


async def test_AC19_2_5_and_AC19_8_3_sync_derived_events_and_session_timeline(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    stmt = await _make_statement(db, test_user.id, original_filename="idempotent.csv", file_hash="d" * 64)
    await db.commit()
    active = (await client.get("/workflow/status")).json()["active_session"]
    first_data = WorkflowEventListResponse.model_validate((await client.get("/workflow/events")).json())
    assert (
        active["status"],
        active["title"],
        active["primary_state"],
        active["event_counts"],
        first_data.total,
        str(first_data.items[0].session_id),
        str(first_data.sessions[0].id),
        first_data.sessions[0].title,
    ) == (
        "active",
        "Upload-to-report session",
        "processing",
        {"unread": 1, "action_required": 0, "blocked": 0},
        1,
        active["id"],
        active["id"],
        "Upload-to-report session",
    )
    assert (
        await client.patch(f"/workflow/events/{first_data.items[0].id}", json={"status": "archived"})
    ).status_code == 200 and (await client.get("/workflow/status")).status_code == 200
    events = (
        (
            await db.execute(
                select(WorkflowEvent).where(WorkflowEvent.user_id == test_user.id, WorkflowEvent.source_id == stmt.id)
            )
        )
        .scalars()
        .all()
    )
    ws = await db.scalar(select(WorkflowSession).where(WorkflowSession.id == first_data.sessions[0].id))
    assert len(events) == 1 and (events[0].id, events[0].status, ws.source_count) == (
        first_data.items[0].id,
        WorkflowEventStatus.ARCHIVED,
        0,
    )
