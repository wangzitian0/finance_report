"""Workflow reads derive events only when a derivation input changed (#2583)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import src.reporting.extension.package_document as package_document_mod
import src.workflow.extension.source_fingerprint as source_fingerprint_mod
from src.audit import JournalEntrySourceType
from src.config import settings
from src.database import Base
from src.extraction import BankStatementStatus, DocumentType, Stage1Status, UploadedDocument
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryAuthorityState,
    JournalEntryStatus,
    JournalLine,
)
from src.pricing import FxRate
from src.workflow import WorkflowEvent, WorkflowEventFamily, WorkflowEventStatus
from src.workflow.extension.source_fingerprint import (
    EXCLUDED_SOURCE_TABLES,
    GLOBAL_SOURCE_TABLES,
    OWNER_JOINED_SOURCE_TABLES,
    TENANT_SCOPED_SOURCE_TABLES,
    workflow_source_fingerprint,
)

YEAR_SCALE_ENTRY_COUNT = 1000
STEADY_READ_SQL_BUDGET = 40
_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE")


class _SqlCounter:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, _conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        self.statements.append(statement.lstrip())

    @property
    def writes(self) -> list[str]:
        return [statement for statement in self.statements if statement[:6].upper() in _WRITE_PREFIXES]


async def _seed_year_of_manual_entries(db: AsyncSession, user_id) -> None:
    bank = Account(user_id=user_id, name="Bank", code="1001", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=user_id, name="Salary", code="4001", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, salary])
    await db.flush()
    now = datetime.now(UTC)
    today = date.today()
    entries = []
    lines = []
    for index in range(YEAR_SCALE_ENTRY_COUNT):
        entry_id = uuid4()
        entries.append(
            {
                "id": entry_id,
                "user_id": user_id,
                "entry_date": today - timedelta(days=index % 360),
                "memo": f"txn {index}",
                "source_type": JournalEntrySourceType.MANUAL,
                "source_id": None,
                "decision_anchor_id": None,
                "decision_authority_state": JournalEntryAuthorityState.LEGACY_UNPROVEN,
                "status": JournalEntryStatus.POSTED,
                "void_reason": None,
                "void_reversal_entry_id": None,
                "created_at": now,
                "updated_at": now,
            }
        )
        for line_no, (account, direction) in enumerate(((bank, Direction.DEBIT), (salary, Direction.CREDIT))):
            lines.append(
                {
                    "id": uuid4(),
                    "journal_entry_id": entry_id,
                    "account_id": account.id,
                    "direction": direction,
                    "amount": Decimal("100.00"),
                    "currency": "SGD",
                    "fx_rate": None,
                    "event_type": None,
                    "tags": None,
                    "line_no": line_no,
                    "created_at": now,
                    "updated_at": now,
                }
            )
    await db.execute(insert(JournalEntry), entries)
    await db.execute(insert(JournalLine), lines)
    await db.commit()


async def test_AC_workflow_sync_1_year_scale_status_read_is_bounded_and_write_free(
    client: AsyncClient,
    db: AsyncSession,
    db_engine,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-workflow.sync.1: at year scale a status read skips the appendix, and a repeated read is cheap and writes nothing."""
    await _seed_year_of_manual_entries(db, test_user.id)

    real_traceability = package_document_mod.build_personal_report_package_traceability_payload
    traceability_calls = 0

    async def counting_traceability(**kwargs):
        nonlocal traceability_calls
        traceability_calls += 1
        return await real_traceability(**kwargs)

    monkeypatch.setattr(
        package_document_mod, "build_personal_report_package_traceability_payload", counting_traceability
    )

    first = await client.get("/workflow/status")
    assert first.status_code == 200, first.text
    assert traceability_calls == 0
    # The legacy manual entries are unproven inputs, so the derivation found blockers.
    assert first.json()["report_readiness"]["state"] == "blocked"

    for _ in range(2):
        counter = _SqlCounter()
        event.listen(db_engine.sync_engine, "before_cursor_execute", counter)
        try:
            repeated = await client.get("/workflow/status")
        finally:
            event.remove(db_engine.sync_engine, "before_cursor_execute", counter)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json() == first.json()
        assert traceability_calls == 0
        assert counter.writes == []
        assert len(counter.statements) < STEADY_READ_SQL_BUDGET, counter.statements


async def _make_statement(db: AsyncSession, user_id, *, status: BankStatementStatus) -> StatementSummary:
    document = UploadedDocument(
        user_id=user_id,
        file_path="statements/fresh.csv",
        file_hash="f" * 64,
        original_filename="fresh.csv",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(document)
    await db.flush()
    statement = StatementSummary(
        user_id=user_id,
        uploaded_document_id=document.id,
        file_hash="f" * 64,
        institution="Demo Bank",
        status=status,
    )
    db.add(statement)
    await db.commit()
    return statement


async def _event_states(db: AsyncSession, user_id) -> dict[WorkflowEventFamily, WorkflowEventStatus]:
    db.expire_all()
    events = (await db.execute(select(WorkflowEvent).where(WorkflowEvent.user_id == user_id))).scalars().all()
    return {item.family: item.status for item in events}


async def test_AC_workflow_sync_2_a_source_change_derives_events_again(
    client: AsyncClient,
    db: AsyncSession,
    db_engine,
    test_user: User,
) -> None:
    """AC-workflow.sync.2: an insert or an update of a source row makes the next read derive fresh events."""
    user_id = test_user.id
    empty = await client.get("/workflow/status")
    assert empty.status_code == 200, empty.text
    assert empty.json()["primary_state"] == "empty"

    statement_id = (await _make_statement(db, user_id, status=BankStatementStatus.PARSED)).id
    needs_review = await client.get("/workflow/status")
    assert needs_review.json()["next_action"]["type"] == "review_required"
    assert (await _event_states(db, user_id))[WorkflowEventFamily.REVIEW_REQUIRED] == WorkflowEventStatus.UNREAD

    # An update keeps the row count. The changed updated_at must still trigger a new derivation.
    await db.execute(
        update(StatementSummary)
        .where(StatementSummary.id == statement_id)
        .values(stage1_status=Stage1Status.APPROVED, stage1_reviewed_at=datetime.now(UTC))
    )
    await db.commit()
    events = await client.get("/workflow/events")
    assert events.status_code == 200, events.text
    states = await _event_states(db, user_id)
    assert states[WorkflowEventFamily.REVIEW_REQUIRED] == WorkflowEventStatus.ARCHIVED
    assert states[WorkflowEventFamily.REVIEW_COMPLETED] == WorkflowEventStatus.UNREAD
    assert (await client.get("/workflow/status")).json()["next_action"]["type"] != "review_required"

    counter = _SqlCounter()
    event.listen(db_engine.sync_engine, "before_cursor_execute", counter)
    try:
        for path in ("/workflow/events", "/notifications", "/workflow/status"):
            assert (await client.get(path)).status_code == 200
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", counter)
    assert counter.writes == []


def test_AC_workflow_sync_3_fingerprint_classifies_every_table() -> None:
    """AC-workflow.sync.3: every model table is a fingerprint input unless an explicit exclusion names it."""
    import src.main  # noqa: F401  -- registers every model of the running app

    tables = Base.metadata.tables
    classified = (
        set(EXCLUDED_SOURCE_TABLES)
        | set(OWNER_JOINED_SOURCE_TABLES)
        | set(TENANT_SCOPED_SOURCE_TABLES)
        | set(GLOBAL_SOURCE_TABLES)
    )
    assert classified <= set(tables), sorted(classified - set(tables))
    unclassified = sorted(
        name
        for name, table in tables.items()
        if "user_id" not in table.c and name != "users" and name not in classified
    )
    assert unclassified == [], "Classify each table in src/workflow/extension/source_fingerprint.py"

    for name, (column, parent) in OWNER_JOINED_SOURCE_TABLES.items():
        table = tables[name]
        assert "user_id" not in table.c, name
        assert "user_id" in tables[parent].c, name
        assert not table.c[column].nullable, name
        assert {fk.column.table.name for fk in table.c[column].foreign_keys} == {parent}, name
    for name in TENANT_SCOPED_SOURCE_TABLES:
        assert {"scope_kind", "scope_id"} <= set(tables[name].c.keys()), name
    for name in GLOBAL_SOURCE_TABLES:
        assert "user_id" not in tables[name].c, name


async def test_AC_workflow_sync_4_fingerprint_changes_only_with_an_input(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-workflow.sync.4: each kind of input change moves the fingerprint; excluded and foreign rows do not."""

    async def fingerprint() -> str:
        await db.commit()
        return await workflow_source_fingerprint(db, user_id=test_user.id)

    baseline = await fingerprint()
    assert await fingerprint() == baseline

    other = User(id=uuid4(), email=f"other-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other)
    await db.flush()
    db.add(Account(user_id=other.id, name="Other bank", type=AccountType.ASSET, currency="SGD"))
    assert await fingerprint() == baseline

    db.add(
        WorkflowEvent(
            user_id=test_user.id,
            family=WorkflowEventFamily.REPORT_READY,
            severity="info",
            title="Ready",
            summary="Ready",
            source_type="report_package",
            source_id=uuid4(),
            action_href="/reports?tab=package",
            dedupe_key="excluded-table-probe",
        )
    )
    assert await fingerprint() == baseline

    seen = {baseline}

    async def assert_changed() -> None:
        current = await fingerprint()
        assert current not in seen
        seen.add(current)

    account = Account(user_id=test_user.id, name="Bank", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await assert_changed()

    account.name = "Renamed bank"
    await assert_changed()

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Owner-joined probe",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()
    line = JournalLine(
        journal_entry_id=entry.id,
        account_id=account.id,
        direction=Direction.DEBIT,
        amount=Decimal("1.00"),
        currency="SGD",
    )
    db.add(line)
    await assert_changed()

    line.amount = Decimal("2.00")
    await assert_changed()

    db.add(FxRate(base_currency="TST", quote_currency="XYZ", rate=Decimal("1.5"), rate_date=date.today(), source="t"))
    await assert_changed()

    monkeypatch.setattr(settings, "base_currency", "USD" if settings.base_currency != "USD" else "EUR")
    await assert_changed()

    class _Tomorrow(date):
        @classmethod
        def today(cls) -> date:
            return date.today() + timedelta(days=1)

    monkeypatch.setattr(source_fingerprint_mod, "date", _Tomorrow)
    await assert_changed()


async def test_AC_workflow_sync_4_tenant_scope_matches_stored_trace_records(db: AsyncSession, test_user: User) -> None:
    """AC-workflow.sync.4: the tenant-scope filter selects the trace records of the user."""
    from src.audit.money import Money
    from src.ledger import Entry, post_entry

    bank = Account(user_id=test_user.id, name="Bank", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=test_user.id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all((bank, income))
    await db.flush()
    await post_entry(
        db,
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Anchored entry",
        entry=Entry.transfer(debit=bank.id, credit=income.id, money=Money(Decimal("10"), "SGD")),
    )
    await db.commit()

    table = Base.metadata.tables["trace_records"]
    row = (await db.execute(source_fingerprint_mod._source_select(table, test_user.id))).one()
    assert row.row_count > 0


async def test_AC_workflow_sync_5_a_state_older_than_the_max_age_derives_again(
    db: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-workflow.sync.5: an equal fingerprint reuses the state only while it is younger than the max age."""
    import src.workflow.extension.events as workflow_events
    from src.workflow.extension.events import WORKFLOW_SYNC_STATE_MAX_AGE, ensure_workflow_events_synced
    from src.workflow.orm.models import WorkflowSyncState

    user_id = test_user.id
    real_readiness = workflow_events.current_package_readiness
    derivations = 0

    async def counting_readiness(db, *, user_id):
        nonlocal derivations
        derivations += 1
        return await real_readiness(db, user_id=user_id)

    monkeypatch.setattr(workflow_events, "current_package_readiness", counting_readiness)

    await ensure_workflow_events_synced(db, user_id=user_id)
    await db.commit()
    assert derivations == 1

    await ensure_workflow_events_synced(db, user_id=user_id)
    await db.commit()
    assert derivations == 1

    await db.execute(
        update(WorkflowSyncState)
        .where(WorkflowSyncState.user_id == user_id)
        .values(updated_at=datetime.now(UTC) - WORKFLOW_SYNC_STATE_MAX_AGE - timedelta(minutes=1))
    )
    await db.commit()
    await ensure_workflow_events_synced(db, user_id=user_id)
    await db.commit()
    assert derivations == 2
