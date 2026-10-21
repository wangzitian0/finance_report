"""A read path can reuse the stored workflow readiness without a write (#2583 S7)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import event, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import User
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.workflow import stored_package_readiness
from src.workflow.extension.events import WORKFLOW_SYNC_STATE_MAX_AGE, ensure_workflow_events_synced
from src.workflow.orm.models import WorkflowSyncState

_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE")


async def _stored_readiness_with_statements(db: AsyncSession, db_engine, user_id) -> tuple[dict | None, list[str]]:
    statements: list[str] = []

    def _record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(statement.lstrip())

    event.listen(db_engine.sync_engine, "before_cursor_execute", _record)
    try:
        readiness = await stored_package_readiness(db, user_id=user_id)
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _record)
    return readiness, statements


async def _post_manual_entry(db: AsyncSession, user_id) -> None:
    bank = Account(user_id=user_id, name="Bank", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=user_id, name="Salary", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, salary])
    await db.flush()
    entry = JournalEntry(user_id=user_id, entry_date=date.today(), memo="Salary", status=JournalEntryStatus.POSTED)
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=bank.id,
                direction=Direction.DEBIT,
                amount=Decimal("10.00"),
                currency="SGD",
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=salary.id,
                direction=Direction.CREDIT,
                amount=Decimal("10.00"),
                currency="SGD",
            ),
        ]
    )
    await db.commit()


async def test_AC_workflow_sync_6_stored_readiness_is_returned_only_while_the_derivation_is_reusable(
    db: AsyncSession, db_engine, test_user: User
) -> None:
    """AC-workflow.sync.6: ``stored_package_readiness`` returns the readiness of the last derivation
    while ``ensure_workflow_events_synced`` would reuse it, and None before a derivation, after a
    source change, and after the max age. It sends two SQL statements and no write."""
    user_id = test_user.id

    readiness, statements = await _stored_readiness_with_statements(db, db_engine, user_id)
    assert readiness is None
    assert len(statements) == 2 and not any(s[:6].upper() in _WRITE_PREFIXES for s in statements)

    derived = await ensure_workflow_events_synced(db, user_id=user_id)
    await db.commit()
    readiness, statements = await _stored_readiness_with_statements(db, db_engine, user_id)
    assert readiness == derived
    assert readiness == await ensure_workflow_events_synced(db, user_id=user_id)
    assert len(statements) == 2 and not any(s[:6].upper() in _WRITE_PREFIXES for s in statements)

    await _post_manual_entry(db, user_id)
    assert await stored_package_readiness(db, user_id=user_id) is None

    rederived = await ensure_workflow_events_synced(db, user_id=user_id)
    await db.commit()
    assert rederived != derived
    assert await stored_package_readiness(db, user_id=user_id) == rederived

    await db.execute(
        update(WorkflowSyncState)
        .where(WorkflowSyncState.user_id == user_id)
        .values(updated_at=datetime.now(UTC) - WORKFLOW_SYNC_STATE_MAX_AGE - timedelta(minutes=1))
    )
    await db.commit()
    assert await stored_package_readiness(db, user_id=user_id) is None
