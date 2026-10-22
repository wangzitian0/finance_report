"""The opening-position projection reads a fixed number of rows and statements (#2583 S7, #2602).

Each balance sheet with trust signals, each cash flow and each package readiness reads
``list_opening_positions``. At 960 statement transactions the projection issued 18 SQL
statements and used about 170 ms of CPU per call. It loaded the journal entry of each
opening record with one statement per record, and it loaded every anchored journal
entry with its lines to find the few system opening-balance entries. Until #2602 it also
loaded every current decision of the user (3,864 rows at 960 transactions).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    initialize_opening_positions,
    list_opening_positions,
)
from src.ledger.extension.anchored_posting import submit_system_journal_entry
from tests.factories import UserFactory

RECORD_COUNT = 6
ACTIVITY_COUNT = 20
# Opening records, their journal entries (one batch), the historical system opening-balance
# entries, the lines and accounts of those entries, and the authority decisions.
PROJECTION_SQL_BUDGET = 6
PROJECTION_MARKER = "invalid_trace_records"
# The decisions that the projection must return: one per opening record, one per journal
# entry of an opening record, and one for the historical system opening entry (#2602).
NEEDED_DECISION_COUNT = 2 * RECORD_COUNT + 1


async def _account(db, user_id, name: str) -> Account:
    row = Account(user_id=user_id, name=name, type=AccountType.ASSET, currency="SGD")
    db.add(row)
    await db.flush()
    return row


async def _seed_openings_and_activity(sessions) -> tuple[UUID, list[UUID], set[UUID], UUID, UUID]:
    """Write 6 opening records, 1 historical system opening entry and 20 other anchored entries.

    Return the user id, the opening account ids, the journal entry ids of the opening records,
    and the account id and the journal entry id of the historical opening entry.
    """
    async with sessions() as setup:
        user = await UserFactory.create_async(setup, email=f"opening-budget-{uuid4()}@example.invalid")
        accounts = [await _account(setup, user.id, f"Opening {index}") for index in range(RECORD_COUNT)]
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

        # A historical system opening operation without an opening record still projects a position.
        legacy = await _account(setup, user.id, "Legacy opening")
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
        # Anchored activity that is not an opening operation.
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
        return user.id, [account.id for account in accounts], record_entry_ids, legacy.id, legacy_entry.id


async def test_AC_ledger_opening_position_10_projection_reads_fixed_statements_and_only_opening_entries(
    db_engine,
) -> None:
    """AC-ledger.opening-position.10: ``list_opening_positions`` issues at most 6 SQL statements
    for 6 opening records, 1 historical system opening entry and 20 other anchored entries.
    It loads only the journal entries of opening positions, and its output keeps every position."""
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    user_id, account_ids, record_entry_ids, legacy_id, legacy_entry_id = await _seed_openings_and_activity(sessions)

    statements = {"count": 0}
    loaded_entry_ids: set = set()

    def _count(conn, cursor, statement, parameters, context, executemany) -> None:
        statements["count"] += 1

    def _loaded(target: JournalEntry, _context) -> None:
        loaded_entry_ids.add(target.id)

    async with sessions() as session:
        event.listen(db_engine.sync_engine, "before_cursor_execute", _count)
        event.listen(JournalEntry, "load", _loaded)
        try:
            positions = await list_opening_positions(session, user_id=user_id, as_of=date(2026, 1, 31))
        finally:
            event.remove(db_engine.sync_engine, "before_cursor_execute", _count)
            event.remove(JournalEntry, "load", _loaded)

    by_account = {position.account_id: position for position in positions}
    assert len(positions) == RECORD_COUNT + 1
    assert {by_account[account_id].amount for account_id in account_ids} == {
        Decimal(100 + i) for i in range(RECORD_COUNT)
    }
    assert all(by_account[account_id].state == "authoritative" for account_id in account_ids)
    assert by_account[legacy_id].amount == Decimal("50")
    assert by_account[legacy_id].journal_entry_id == legacy_entry_id
    assert by_account[legacy_id].decision is not None
    assert loaded_entry_ids == record_entry_ids | {legacy_entry_id}, "the projection loaded non-opening entries"
    assert statements["count"] <= PROJECTION_SQL_BUDGET, f"the projection issued {statements['count']} statements"


async def test_AC_ledger_opening_position_11_projection_reads_only_the_decisions_it_needs(db_engine) -> None:
    """AC-ledger.opening-position.11: ``list_opening_positions`` runs the current-authority
    projection once. The projection returns only the decisions of the opening records, of
    their journal entries and of the historical opening entry, not the 20 decisions of the
    other anchored entries (#2602). Before #2602 the projection ran twice and returned every
    current decision of the user."""
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    user_id, account_ids, _record_entry_ids, legacy_id, legacy_entry_id = await _seed_openings_and_activity(sessions)

    projection_rows: list[int] = []

    def _rows(conn, cursor, statement, parameters, context, executemany) -> None:
        if PROJECTION_MARKER in statement:
            projection_rows.append(cursor.rowcount)

    async with sessions() as session:
        event.listen(db_engine.sync_engine, "after_cursor_execute", _rows)
        try:
            positions = await list_opening_positions(session, user_id=user_id, as_of=date(2026, 1, 31))
        finally:
            event.remove(db_engine.sync_engine, "after_cursor_execute", _rows)

    by_account = {position.account_id: position for position in positions}
    assert set(by_account) == {*account_ids, legacy_id}
    assert all(position.state == "authoritative" and position.decision is not None for position in positions)
    assert by_account[legacy_id].journal_entry_id == legacy_entry_id
    assert len(projection_rows) == 1, f"the projection ran {len(projection_rows)} times"
    assert projection_rows[0] == NEEDED_DECISION_COUNT, f"the projection returned {projection_rows[0]} decisions"
