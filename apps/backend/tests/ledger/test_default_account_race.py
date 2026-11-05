"""AC-ledger.71.5: requests of one user create each default account once and never wait for each other (#2415).

The accounts table has no unique index for the Processing account or for a default account. Both helpers
read first and insert after. A user who uploads several statements at once makes several workers reach the
insert together. A second row breaks every later lookup and the netting of the Processing account.

A lock that lasts to the end of the caller's transaction fixes the duplicate and creates a worse problem: a
worker that waits for the lock can hold a lock that the holder needs, and the database aborts one of them.
So the creation commits in its own short transaction. The tests hold the first transaction open and prove
that the second request neither waits nor creates a second row.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.extraction.extension.review_queue import get_or_create_account
from src.ledger import PROCESSING_ACCOUNT_CODE, Account, AccountType, get_or_create_processing_account
from tests.db_lock_probe import backend_pid, backend_waits_for_a_lock
from tests.factories import UserFactory

pytestmark = pytest.mark.asyncio

#: A request that waits for a lock would need far more time than this. A request that does not wait needs milliseconds.
NO_WAIT_SECONDS = 10


async def _committed_user(db_engine):
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as setup:
        user = await UserFactory.create_async(setup, email=f"race-{uuid4()}@example.invalid")
        user_id = user.id
        await setup.commit()
    return sessions, user_id


def _processing(session, user_id):
    return get_or_create_processing_account(session, user_id, currency="SGD")


def _general_expense(session, user_id):
    return get_or_create_account(
        session, name="General Expense (SGD)", account_type=AccountType.EXPENSE, currency="SGD", user_id=user_id
    )


def _one_click_general_expense(session, user_id):
    """The helper of the one-click approval. It must create the same default account with the same safety."""
    from src.composition import _get_or_create_default_counter_account

    return _get_or_create_default_counter_account(session, user_id, AccountType.EXPENSE, "SGD")


@pytest.mark.parametrize(
    ("create", "count_filter"),
    [
        pytest.param(_processing, Account.code == PROCESSING_ACCOUNT_CODE, id="processing"),
        pytest.param(_general_expense, Account.name == "General Expense (SGD)", id="default-account"),
        pytest.param(_one_click_general_expense, Account.name == "General Expense (SGD)", id="one-click-default"),
    ],
)
async def test_AC_ledger_71_5_a_second_request_neither_waits_for_the_open_transaction_nor_creates_a_row(
    db_engine, create, count_filter
):
    """AC-ledger.71.5: the first request keeps its transaction open. The second request finishes and finds the row."""
    sessions, user_id = await _committed_user(db_engine)
    first, second = sessions(), sessions()
    try:
        first_account = await create(first, user_id)  # the first transaction stays open from here

        second_account = await asyncio.wait_for(create(second, user_id), timeout=NO_WAIT_SECONDS)

        assert second_account.id == first_account.id
    finally:
        await first.rollback()
        await second.rollback()
        await first.close()
        await second.close()
    async with sessions() as check:
        count = await check.scalar(select(func.count(Account.id)).where(Account.user_id == user_id, count_filter))
    assert count == 1


@pytest.mark.parametrize(
    ("create", "count_filter"),
    [
        pytest.param(_processing, Account.code == PROCESSING_ACCOUNT_CODE, id="processing"),
        pytest.param(_general_expense, Account.name == "General Expense (SGD)", id="default-account"),
        pytest.param(_one_click_general_expense, Account.name == "General Expense (SGD)", id="one-click-default"),
    ],
)
async def test_AC_ledger_71_5_eight_requests_at_once_create_one_account(db_engine, create, count_filter):
    """AC-ledger.71.5: the lock inside the own transaction keeps the lookup and the insert together.

    The test counts the rows in the table. The lookup returns the oldest row, so the ids that the requests
    get cannot show a second row.
    """
    sessions, user_id = await _committed_user(db_engine)

    async def request():
        async with sessions() as session:
            account = await create(session, user_id)
            await session.commit()
            return account.id

    ids = await asyncio.wait_for(asyncio.gather(*(request() for _ in range(8))), timeout=60)

    assert len(set(ids)) == 1
    async with sessions() as check:
        count = await check.scalar(select(func.count(Account.id)).where(Account.user_id == user_id, count_filter))
    assert count == 1


async def test_AC_ledger_71_5_two_requests_that_create_two_accounts_in_opposite_order_never_wait(db_engine):
    """AC-ledger.71.5: each creation commits at once, so no request holds one account while it waits for another.

    Each worker creates its first account and keeps its transaction open. Both must reach that point before
    either creates its second account. A creator that held a lock until the end of the transaction would block
    the second worker at its first creation, and the barrier would never open.
    """
    sessions, user_id = await _committed_user(db_engine)
    first_done = {"Account A": asyncio.Event(), "Account B": asyncio.Event()}

    async def create(session, name):
        return await get_or_create_account(
            session, name=name, account_type=AccountType.EXPENSE, currency="SGD", user_id=user_id
        )

    async def worker(first_name, second_name):
        async with sessions() as session:
            await create(session, first_name)
            first_done[first_name].set()
            await asyncio.wait_for(first_done[second_name].wait(), timeout=NO_WAIT_SECONDS)  # the other worker is there
            await create(session, second_name)
            await session.commit()

    await asyncio.wait_for(
        asyncio.gather(worker("Account A", "Account B"), worker("Account B", "Account A")),
        timeout=NO_WAIT_SECONDS * 2,
    )

    async with sessions() as check:
        names = (await check.execute(select(Account.name).where(Account.user_id == user_id))).scalars().all()
    assert sorted(names) == ["Account A", "Account B"]


async def test_AC_ledger_71_5_a_created_account_stays_when_the_caller_rolls_back(db_engine):
    """AC-ledger.71.5: the creation is its own transaction, so a rollback of the caller does not undo it.

    An account without entries changes no balance. The next request finds the account instead of creating a copy.
    """
    sessions, user_id = await _committed_user(db_engine)
    async with sessions() as caller:
        created_id = (await _processing(caller, user_id)).id
        await caller.rollback()

    async with sessions() as check:
        found = await _processing(check, user_id)
    assert found.id == created_id


async def test_AC_ledger_71_5_a_user_that_the_caller_has_not_committed_gets_the_account_in_the_callers_transaction(
    db,
):
    """AC-ledger.71.5: the registration flow creates the user and its accounts in one transaction.

    The own transaction cannot see that user, so the caller's session creates the account. No other session sees
    the account, and a rollback of the caller removes it together with the user.
    """
    user = await UserFactory.create_async(db, email=f"uncommitted-{uuid4()}@example.invalid")
    sessions = async_sessionmaker(db.bind, expire_on_commit=False)

    account_id = (await _processing(db, user.id)).id

    async with sessions() as other:
        assert await other.get(Account, account_id) is None  # not committed
    await db.rollback()
    async with sessions() as other:
        assert await other.get(Account, account_id) is None  # and not created behind the back of the caller


async def test_AC_ledger_71_5_without_an_own_session_the_caller_creates_the_account_under_the_lock(
    db_engine, monkeypatch
):
    """AC-ledger.71.5: when no engine is available for an own transaction, the caller's session creates it once.

    The first caller holds its transaction open. The second caller must wait for the lock and then find the row.
    """
    from src.ledger.extension import account_service

    def no_engine(_db):
        raise RuntimeError("Async engine unavailable for session maker creation")

    monkeypatch.setattr(account_service, "create_session_maker_from_db", no_engine)
    sessions, user_id = await _committed_user(db_engine)
    first, second = sessions(), sessions()
    try:
        first_account = await _processing(first, user_id)  # holds the lock until its transaction ends
        second_pid = await backend_pid(second)  # opens the connection of the second session first
        waiting = asyncio.create_task(_processing(second, user_id))
        assert await backend_waits_for_a_lock(db_engine, second_pid), "the second caller must wait for the lock"
        await first.commit()
        second_account = await asyncio.wait_for(waiting, timeout=NO_WAIT_SECONDS)
        await second.commit()
    finally:
        await first.close()
        await second.close()

    assert second_account.id == first_account.id
    async with sessions() as check:
        count = await check.scalar(
            select(func.count(Account.id)).where(Account.user_id == user_id, Account.code == PROCESSING_ACCOUNT_CODE)
        )
    assert count == 1


async def test_AC_ledger_71_5_a_lock_that_the_caller_holds_makes_the_creation_fail_instead_of_hang(
    db_engine, monkeypatch
):
    """AC-ledger.71.5: the caller waits for the own transaction. A lock of the caller would block it for good.

    The database cannot see that cycle, because the caller waits in Python. The lock timeout turns it into an error.
    """
    from src.ledger.extension import account_service

    monkeypatch.setattr(account_service, "ACCOUNT_CREATION_LOCK_TIMEOUT", "300ms")
    sessions, user_id = await _committed_user(db_engine)
    caller = sessions()
    try:
        await caller.execute(account_service._ACCOUNT_CREATION_LOCK, {"key": f"account-creation:{user_id}"})

        with pytest.raises(Exception, match="lock timeout"):
            await asyncio.wait_for(_processing(caller, user_id), timeout=NO_WAIT_SECONDS)
    finally:
        await caller.rollback()
        await caller.close()


async def test_AC_ledger_2674_1_all_default_and_system_account_creators_route_through_find_or_create_account(
    db, test_user, monkeypatch
) -> None:
    """AC-ledger.2674.1: All 5 default/system account creation sites converge on find_or_create_account (#2674)."""
    from datetime import date
    from decimal import Decimal
    from uuid import UUID

    from src.extraction import BankStatementStatus
    from src.extraction.orm.statement_summary import StatementSummary
    from src.ledger.extension import account_service
    from src.portfolio.extension.positions import PositionService
    from src.routers.reconciliation import post_reconciliation_adjustment
    from src.routers.statements import _create_statement_account_from_confirmation
    from src.schemas.reconciliation import ReconciliationAdjustmentRequest

    calls: list[UUID] = []
    original = account_service.find_or_create_account

    async def spy_find_or_create(session, *, user_id, find, build):
        calls.append(user_id)
        return await original(session, user_id=user_id, find=find, build=build)

    monkeypatch.setattr(account_service, "find_or_create_account", spy_find_or_create)

    # 1. Opening Balance Equity (3199)
    obe = await account_service.get_or_create_opening_balance_equity_account(db, test_user.id, "SGD")
    assert obe.code == account_service.OPENING_BALANCE_EQUITY_CODE
    assert len(calls) == 1

    # 2. Unexplained Gap Equity (3198)
    uge = await account_service.get_or_create_unexplained_gap_equity_account(db, test_user.id, "SGD")
    assert uge.code == account_service.UNEXPLAINED_GAP_EQUITY_CODE
    assert len(calls) == 2

    # 3. AUTO-ASSET broker account in PositionService
    pos_service = PositionService()
    broker_acc = await pos_service._get_or_create_broker_account(db, test_user.id, "Interactive Brokers", "USD")
    assert broker_acc.code == "AUTO-ASSET"
    assert broker_acc.currency == "USD"
    assert len(calls) == 3

    # 4. AUTO-BANK statement account (account_last4=None hits AUTO-BANK fallback)
    stmt = StatementSummary(
        user_id=test_user.id,
        file_hash="hash_auto_bank_2674",
        institution="DBS Bank",
        account_last4=None,
        currency="SGD",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("100.00"),
        status=BankStatementStatus.PARSED,
    )
    db.add(stmt)
    await db.flush()
    bank_acc = await _create_statement_account_from_confirmation(db, stmt, test_user.id)
    assert bank_acc.code == "AUTO-BANK"
    assert stmt.account_id == bank_acc.id
    assert len(calls) == 4

    # 5. BankRoundingDifference in reconciliation adjustment
    adj_resp = await post_reconciliation_adjustment(
        payload=ReconciliationAdjustmentRequest(
            account_id=bank_acc.id,
            bank_balance=Decimal("100.02"),
            book_balance=Decimal("100.00"),
            threshold=Decimal("0.05"),
            entry_date=date(2025, 1, 31),
        ),
        db=db,
        user_id=test_user.id,
    )
    assert adj_resp.difference == Decimal("0.02")
    assert len(calls) == 5
