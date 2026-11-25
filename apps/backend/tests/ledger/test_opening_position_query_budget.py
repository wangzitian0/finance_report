from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.ledger import AccountType, Direction, JournalEntry, initialize_opening_positions, list_opening_positions
from src.ledger.extension.anchored_posting import submit_system_journal_entry
from tests.factories import UserFactory
from tests.ledger._ledger_helpers import make_account

RECORD_COUNT = 6
ACTIVITY_COUNT = 20
PROJECTION_SQL_BUDGET = 6
PROJECTION_MARKER = "invalid_trace_records"
NEEDED_DECISION_COUNT = 2 * RECORD_COUNT + 1


async def _seed_openings_and_activity(sessions) -> tuple[UUID, list[UUID], set[UUID], UUID, UUID]:
    async with sessions() as setup:
        user = await UserFactory.create_async(setup, email=f"opening-budget-{uuid4()}@example.invalid")
        accounts = [
            await make_account(setup, user.id, f"Opening {index}", AccountType.ASSET) for index in range(RECORD_COUNT)
        ]
        record_entry_ids = set()
        for index, account in enumerate(accounts):
            entry = await initialize_opening_positions(
                setup,
                user.id,
                entry_date=date(2026, 1, 1),
                balances={account.id: Decimal(100 + index)},
                currency="SGD",
                base_currency="SGD",
            )
            record_entry_ids.add(entry.id)
        await setup.refresh(entry, ["lines"])
        equity_id = next(line.account_id for line in entry.lines if line.account_id != accounts[-1].id)
        legacy = await make_account(setup, user.id, "Legacy opening", AccountType.ASSET)
        legacy_entry = await submit_system_journal_entry(
            setup,
            user_id=user.id,
            entry_date=date(2026, 1, 1),
            memo="Historical opening balance",
            operation="opening-balance",
            base_currency="SGD",
            lines_data=[
                {"account_id": legacy.id, "direction": Direction.DEBIT, "amount": Decimal("50"), "currency": "SGD"},
                {"account_id": equity_id, "direction": Direction.CREDIT, "amount": Decimal("50"), "currency": "SGD"},
            ],
        )
        for index in range(ACTIVITY_COUNT):
            await submit_system_journal_entry(
                setup,
                user_id=user.id,
                entry_date=date(2026, 1, 2 + index),
                memo=f"Anchored activity {index}",
                operation="budget-activity",
                base_currency="SGD",
                lines_data=[
                    {"account_id": legacy.id, "direction": Direction.DEBIT, "amount": Decimal("1"), "currency": "SGD"},
                    {"account_id": equity_id, "direction": Direction.CREDIT, "amount": Decimal("1"), "currency": "SGD"},
                ],
            )
        await setup.commit()
        return user.id, [a.id for a in accounts], record_entry_ids, legacy.id, legacy_entry.id


async def test_opening_projection_statement_and_decision_budgets(db_engine) -> None:
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    user_id, account_ids, record_entry_ids, legacy_id, legacy_entry_id = await _seed_openings_and_activity(sessions)
    statements = {"count": 0}
    loaded_entry_ids: set = set()
    projection_rows: list[int] = []

    def _count(_conn, _cursor, _stmt, _params, _ctx, _many) -> None:
        statements["count"] += 1

    def _rows(_conn, cursor, statement, _params, _ctx, _many) -> None:
        if PROJECTION_MARKER in statement:
            projection_rows.append(cursor.rowcount)

    def _loaded(target: JournalEntry, _ctx) -> None:
        loaded_entry_ids.add(target.id)

    async with sessions() as session:
        event.listen(db_engine.sync_engine, "before_cursor_execute", _count)
        event.listen(db_engine.sync_engine, "after_cursor_execute", _rows)
        event.listen(JournalEntry, "load", _loaded)
        try:
            positions = await list_opening_positions(session, user_id=user_id, as_of=date(2026, 1, 31))
        finally:
            event.remove(db_engine.sync_engine, "before_cursor_execute", _count)
            event.remove(db_engine.sync_engine, "after_cursor_execute", _rows)
            event.remove(JournalEntry, "load", _loaded)

    by_account = {p.account_id: p for p in positions}
    assert set(by_account) == {*account_ids, legacy_id}
    assert {by_account[aid].amount for aid in account_ids} == {Decimal(100 + i) for i in range(RECORD_COUNT)}
    assert all(p.state == "authoritative" and p.decision is not None for p in positions)
    assert by_account[legacy_id].amount == Decimal("50") and by_account[legacy_id].journal_entry_id == legacy_entry_id
    assert loaded_entry_ids == record_entry_ids | {legacy_entry_id}
    assert statements["count"] <= PROJECTION_SQL_BUDGET
    assert projection_rows == [NEEDED_DECISION_COUNT]
