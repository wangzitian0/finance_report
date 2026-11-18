from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import src.reporting.extension.package_document as package_document_mod
import src.routers.workflow as workflow_router
import src.workflow.extension.events as workflow_events
from src.audit import JournalEntrySourceType, Money
from src.extraction import BankStatementStatus, DocumentType, Stage1Status, UploadedDocument
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import Account, AccountType, Direction, Entry, JournalEntry, JournalEntryAuthorityState, JournalEntryStatus, JournalLine, post_entry
from src.pricing import FxRate
from src.reporting import ReportError
from src.workflow import WorkflowEvent, WorkflowEventFamily, WorkflowEventStatus, WorkflowPrimaryState, WorkflowReportReadinessState, get_workflow_status, stored_package_readiness
from src.workflow.extension.events import WORKFLOW_SYNC_STATE_MAX_AGE, ensure_workflow_events_synced, workflow_input_stamp
from src.workflow.orm.models import WorkflowSyncState

_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE")


class _SqlCounter:
    def __init__(self, engine) -> None:
        self._engine, self.statements = engine.sync_engine, []
        self._cb = lambda _c, _cur, stmt, *_a: self.statements.append(stmt.lstrip())

    def __enter__(self) -> _SqlCounter:
        event.listen(self._engine, "before_cursor_execute", self._cb)
        return self

    def __exit__(self, *_exc) -> None:
        event.remove(self._engine, "before_cursor_execute", self._cb)

    @property
    def writes(self) -> list[str]:
        return [s for s in self.statements if s[:6].upper() in _WRITE_PREFIXES]


async def _seed_year_of_manual_entries(db: AsyncSession, user_id) -> None:
    bank, salary = Account(user_id=user_id, name="Bank", code="1001", type=AccountType.ASSET, currency="SGD"), Account(user_id=user_id, name="Salary", code="4001", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, salary])
    await db.flush()
    now, today, entry_ids = datetime.now(UTC), date.today(), [uuid4() for _ in range(1000)]
    await db.execute(
        insert(JournalEntry),
        [
            {"id": eid, "user_id": user_id, "entry_date": today - timedelta(days=i % 360), "memo": f"txn {i}", "source_type": JournalEntrySourceType.MANUAL, "source_id": None, "decision_anchor_id": None, "decision_authority_state": JournalEntryAuthorityState.LEGACY_UNPROVEN, "status": JournalEntryStatus.POSTED, "void_reason": None, "void_reversal_entry_id": None, "created_at": now, "updated_at": now}
            for i, eid in enumerate(entry_ids)
        ],
    )
    await db.execute(
        insert(JournalLine),
        [
            {"id": uuid4(), "journal_entry_id": eid, "account_id": acct.id, "direction": d, "amount": Decimal("100.00"), "currency": "SGD", "fx_rate": None, "event_type": None, "tags": None, "line_no": ln, "created_at": now, "updated_at": now}
            for eid in entry_ids
            for ln, (acct, d) in enumerate(((bank, Direction.DEBIT), (salary, Direction.CREDIT)))
        ],
    )
    await db.commit()


async def _make_statement(db: AsyncSession, user_id, *, status: BankStatementStatus) -> StatementSummary:
    doc = UploadedDocument(user_id=user_id, file_path="statements/fresh.csv", file_hash="f" * 64, original_filename="fresh.csv", document_type=DocumentType.BANK_STATEMENT)
    db.add(doc)
    await db.flush()
    stmt = StatementSummary(user_id=user_id, uploaded_document_id=doc.id, file_hash="f" * 64, institution="Demo Bank", status=status)
    db.add(stmt)
    await db.commit()
    return stmt


async def _event_states(db: AsyncSession, user_id) -> dict[WorkflowEventFamily, WorkflowEventStatus]:
    db.expire_all()
    return {item.family: item.status for item in (await db.execute(select(WorkflowEvent).where(WorkflowEvent.user_id == user_id))).scalars().all()}


async def test_AC_workflow_sync_1_year_scale_status_read_is_bounded_and_write_free(client: AsyncClient, db: AsyncSession, db_engine, test_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    await _seed_year_of_manual_entries(db, test_user.id)
    real_traceability, traceability_calls = package_document_mod.build_personal_report_package_traceability_payload, 0

    async def counting_traceability(**kwargs):
        nonlocal traceability_calls
        traceability_calls += 1
        return await real_traceability(**kwargs)

    monkeypatch.setattr(package_document_mod, "build_personal_report_package_traceability_payload", counting_traceability)
    with _SqlCounter(db_engine) as cold:
        first = await client.get("/workflow/status")
    assert (first.status_code, first.json()["report_readiness"]["state"], traceability_calls, cold.writes) == (200, "blocked", 0, [])

    await ensure_workflow_events_synced(db, user_id=test_user.id, base_currency="SGD")
    await db.commit()
    snapshots = []
    for _ in range(2):
        with _SqlCounter(db_engine) as counter:
            rep = await client.get("/workflow/status")
        assert rep.status_code == 200 and traceability_calls == 0 and counter.writes == [] and len(counter.statements) < 40
        snapshots.append(rep.json())
    assert snapshots[0] == snapshots[1] and (snapshots[0]["primary_state"], snapshots[0]["report_readiness"], snapshots[0]["event_counts"]) == (
        first.json()["primary_state"], first.json()["report_readiness"], first.json()["event_counts"],
    )


async def test_AC_workflow_sync_2_a_source_change_derives_events_again(client: AsyncClient, db: AsyncSession, db_engine, test_user: User) -> None:
    user_id = test_user.id
    with _SqlCounter(db_engine) as counter:
        empty = await client.get("/workflow/status")
        assert empty.status_code == 200 and empty.json()["primary_state"] == "empty"
        statement_id = (await _make_statement(db, user_id, status=BankStatementStatus.PARSED)).id
        counter.statements.clear()
        needs_review, needs_events = await client.get("/workflow/status"), await client.get("/workflow/events")
        assert (needs_review.json()["next_action"]["type"], needs_events.status_code, counter.writes, {i["family"]: i["status"] for i in needs_events.json()["items"]}[WorkflowEventFamily.REVIEW_REQUIRED.value]) == (
            "review_required", 200, [], WorkflowEventStatus.UNREAD.value,
        )

    assert await _event_states(db, user_id) == {}
    await ensure_workflow_events_synced(db, user_id=user_id, base_currency="SGD")
    await db.commit()
    assert (await _event_states(db, user_id))[WorkflowEventFamily.REVIEW_REQUIRED] == WorkflowEventStatus.UNREAD

    await db.execute(update(StatementSummary).where(StatementSummary.id == statement_id).values(stage1_status=Stage1Status.APPROVED, stage1_reviewed_at=datetime.now(UTC)))
    await db.commit()
    with _SqlCounter(db_engine) as read_counter:
        events = await client.get("/workflow/events")
        families = {i["family"]: i["status"] for i in events.json()["items"]}
        assert (events.status_code, WorkflowEventFamily.REVIEW_REQUIRED.value in families, families[WorkflowEventFamily.REVIEW_COMPLETED.value], (await client.get("/workflow/status")).json()["next_action"]["type"] != "review_required", read_counter.writes) == (
            200, False, WorkflowEventStatus.UNREAD.value, True, [],
        )
    await ensure_workflow_events_synced(db, user_id=user_id, base_currency="SGD")
    await db.commit()
    states = await _event_states(db, user_id)
    assert (states[WorkflowEventFamily.REVIEW_REQUIRED], states[WorkflowEventFamily.REVIEW_COMPLETED]) == (WorkflowEventStatus.ARCHIVED, WorkflowEventStatus.UNREAD)


@pytest.mark.no_db
def test_AC_workflow_sync_3_workflow_reads_use_readonly_session_without_table_scan() -> None:
    backend_src = Path(__file__).resolve().parents[2] / "src"
    events_src = (backend_src / "workflow/extension/events.py").read_text(encoding="utf-8")
    assert not (backend_src / "workflow/extension/source_fingerprint.py").exists() and "Base.metadata.tables" not in events_src and "source_fingerprint" in events_src
    assert all("ReadCtx" in inspect.getsource(ep) for ep in (workflow_router.get_workflow_status_endpoint, workflow_router.list_workflow_events_endpoint))


async def test_AC_workflow_sync_4_input_stamp_and_tenant_scope(db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    async def stamp() -> str:
        await db.commit()
        return await workflow_input_stamp(db, user_id=test_user.id)

    baseline = await stamp()
    other = User(id=uuid4(), email=f"other-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other)
    await db.flush()
    db.add_all((Account(user_id=other.id, name="Other bank", type=AccountType.ASSET, currency="SGD"), WorkflowEvent(user_id=test_user.id, family=WorkflowEventFamily.REPORT_READY, severity="info", title="Ready", summary="Ready", source_type="report_package", source_id=uuid4(), action_href="/reports?tab=package", dedupe_key="excluded-table-probe")))
    assert await stamp() == baseline
    seen = {baseline}

    account, income = Account(user_id=test_user.id, name="Bank", type=AccountType.ASSET, currency="SGD"), Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    entry = JournalEntry(user_id=test_user.id, entry_date=date.today(), memo="Owner-joined probe", source_type=JournalEntrySourceType.MANUAL, status=JournalEntryStatus.DRAFT)
    line = JournalLine(journal_entry_id=entry.id, account_id=account.id, direction=Direction.DEBIT, amount=Decimal("1.00"), currency="SGD")

    async def _add_entry_line():
        db.add(entry)
        await db.flush()
        line.journal_entry_id, line.account_id = entry.id, account.id
        db.add(line)

    mutations = (
        lambda: db.add_all((account, income)),
        lambda: setattr(account, "name", "Renamed bank"),
        _add_entry_line,
        lambda: setattr(line, "amount", Decimal("2.00")),
        lambda: db.add(FxRate(base_currency="TST", quote_currency="XYZ", rate=Decimal("1.5"), rate_date=date.today(), source="t")),
        lambda: setattr(test_user, "base_currency", "USD"),
        lambda: post_entry(db, user_id=test_user.id, entry_date=date.today(), memo="Anchored entry", entry=Entry.transfer(debit=account.id, credit=income.id, money=Money(Decimal("10"), "SGD")), base_currency="SGD"),
        lambda: monkeypatch.setattr(workflow_events, "date", type("_Tomorrow", (date,), {"today": classmethod(lambda cls: date.today() + timedelta(days=1))})),
    )
    for step in mutations:
        res = step()
        if inspect.isawaitable(res):
            await res
        current = await stamp()
        assert current not in seen
        seen.add(current)


async def test_AC_workflow_sync_5_and_6_stored_readiness_age_and_invalidation(db: AsyncSession, db_engine, test_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    user_id, real_readiness, derivations = test_user.id, workflow_events.current_package_readiness, 0
    with _SqlCounter(db_engine) as cold:
        assert await stored_package_readiness(db, user_id=user_id) is None
    assert len(cold.statements) == 2 and not cold.writes

    async def counting_readiness(db, *, user_id, base_currency=None):
        nonlocal derivations
        derivations += 1
        return await real_readiness(db, user_id=user_id, base_currency=base_currency)

    monkeypatch.setattr(workflow_events, "current_package_readiness", counting_readiness)
    derived = await ensure_workflow_events_synced(db, user_id=user_id, base_currency="SGD")
    await db.commit()
    with _SqlCounter(db_engine) as warm:
        cached = await stored_package_readiness(db, user_id=user_id)
    assert (cached == derived == await ensure_workflow_events_synced(db, user_id=user_id, base_currency="SGD"), derivations, len(warm.statements), warm.writes) == (True, 1, 2, [])

    bank, salary = Account(user_id=user_id, name="Bank", type=AccountType.ASSET, currency="SGD"), Account(user_id=user_id, name="Salary", type=AccountType.INCOME, currency="SGD")
    je = JournalEntry(user_id=user_id, entry_date=date.today(), memo="Salary", status=JournalEntryStatus.POSTED)
    db.add_all([bank, salary, je])
    await db.flush()
    db.add_all([JournalLine(journal_entry_id=je.id, account_id=bank.id, direction=Direction.DEBIT, amount=Decimal("10.00"), currency="SGD"), JournalLine(journal_entry_id=je.id, account_id=salary.id, direction=Direction.CREDIT, amount=Decimal("10.00"), currency="SGD")])
    await db.commit()
    assert await stored_package_readiness(db, user_id=user_id) is None
    rederived = await ensure_workflow_events_synced(db, user_id=user_id, base_currency="SGD")
    await db.commit()
    assert rederived != derived and await stored_package_readiness(db, user_id=user_id) == rederived and derivations == 2

    await db.execute(update(WorkflowSyncState).where(WorkflowSyncState.user_id == user_id).values(updated_at=datetime.now(UTC) - WORKFLOW_SYNC_STATE_MAX_AGE - timedelta(minutes=1)))
    await db.commit()
    assert await stored_package_readiness(db, user_id=user_id) is None
    await ensure_workflow_events_synced(db, user_id=user_id, base_currency="SGD")
    await db.commit()
    assert derivations == 3


async def test_AC_workflow_sync_7_report_error_becomes_blocked_readiness_state(db: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_readiness(_db, **_kwargs):
        raise ReportError("No registered L1 mapping for ledger account 00000000-0000-0000-0000-000000000001")

    monkeypatch.setattr(workflow_events, "current_package_readiness", failing_readiness)
    status = await get_workflow_status(db, user_id=test_user.id, base_currency="SGD")
    await ensure_workflow_events_synced(db, user_id=test_user.id, base_currency="SGD")
    await db.commit()
    cached = await stored_package_readiness(db, user_id=test_user.id)
    assert (status.primary_state, status.report_readiness.state, status.report_readiness.blocking_count, status.report_readiness.href, cached["state"], cached["blocking_count"], cached["blockers"][0]["code"]) == (
        WorkflowPrimaryState.BLOCKED, WorkflowReportReadinessState.BLOCKED, 1, "/reports?tab=package", "blocked", 1, "report_generation_error",
    )
    assert "No registered L1 mapping" in cached["blockers"][0]["reason"]
