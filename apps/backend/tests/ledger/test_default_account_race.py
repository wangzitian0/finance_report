from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.extraction import BankStatementStatus, create_statement_account_from_confirmation
from src.extraction.orm.statement_summary import StatementSummary
from src.extraction.extension.review_queue import get_or_create_account
from src.ledger import PROCESSING_ACCOUNT_CODE, Account, AccountType, get_or_create_processing_account
from src.ledger.extension import account_service
from src.portfolio.extension.positions import PositionService
from src.request_context import RequestContext
from src.routers.reconciliation import post_reconciliation_adjustment
from src.schemas.reconciliation import ReconciliationAdjustmentRequest
from tests.db_lock_probe import backend_pid, backend_waits_for_a_lock
from tests.factories import UserFactory

pytestmark = pytest.mark.asyncio
NO_WAIT_SECONDS = 10


async def _committed_user(db_engine):
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as setup:
        user = await UserFactory.create_async(setup, email=f"race-{uuid4()}@example.invalid")
        user_id = user.id
        await setup.commit()
    return sessions, user_id


def _one_click_general_expense(session, user_id):
    from src.composition import _get_or_create_default_counter_account

    return _get_or_create_default_counter_account(session, user_id, AccountType.EXPENSE, "SGD")


_processing = lambda session, uid: get_or_create_processing_account(session, uid, currency="SGD")
_CREATORS = [
    pytest.param(_processing, Account.code == PROCESSING_ACCOUNT_CODE, id="processing"),
    pytest.param(
        lambda s, uid: get_or_create_account(
            s, name="General Expense (SGD)", account_type=AccountType.EXPENSE, currency="SGD", user_id=uid
        ),
        Account.name == "General Expense (SGD)",
        id="default-account",
    ),
    pytest.param(_one_click_general_expense, Account.name == "General Expense (SGD)", id="one-click-default"),
]


@pytest.mark.parametrize(("create", "count_filter"), _CREATORS)
async def test_AC_ledger_71_5_a_second_request_neither_waits_for_the_open_transaction_nor_creates_a_row(
    db_engine, create, count_filter
):
    sessions, user_id = await _committed_user(db_engine)
    first, second = sessions(), sessions()
    try:
        first_account = await create(first, user_id)
        second_account = await asyncio.wait_for(create(second, user_id), timeout=NO_WAIT_SECONDS)
        assert second_account.id == first_account.id
    finally:
        await first.rollback()
        await second.rollback()
        await first.close()
        await second.close()
    async with sessions() as check:
        assert await check.scalar(select(func.count(Account.id)).where(Account.user_id == user_id, count_filter)) == 1


@pytest.mark.parametrize(("create", "count_filter"), _CREATORS)
async def test_AC_ledger_71_5_eight_requests_at_once_create_one_account(db_engine, create, count_filter):
    sessions, user_id = await _committed_user(db_engine)

    async def request():
        async with sessions() as session:
            account = await create(session, user_id)
            await session.commit()
            return account.id

    ids = await asyncio.wait_for(asyncio.gather(*(request() for _ in range(8))), timeout=60)
    assert len(set(ids)) == 1
    async with sessions() as check:
        assert await check.scalar(select(func.count(Account.id)).where(Account.user_id == user_id, count_filter)) == 1


async def test_AC_ledger_71_5_two_requests_that_create_two_accounts_in_opposite_order_never_wait(db_engine):
    sessions, user_id = await _committed_user(db_engine)
    first_done = {"Account A": asyncio.Event(), "Account B": asyncio.Event()}

    async def worker(first_name, second_name):
        async with sessions() as session:
            await get_or_create_account(
                session, name=first_name, account_type=AccountType.EXPENSE, currency="SGD", user_id=user_id
            )
            first_done[first_name].set()
            await asyncio.wait_for(first_done[second_name].wait(), timeout=NO_WAIT_SECONDS)
            await get_or_create_account(
                session, name=second_name, account_type=AccountType.EXPENSE, currency="SGD", user_id=user_id
            )
            await session.commit()

    await asyncio.wait_for(
        asyncio.gather(worker("Account A", "Account B"), worker("Account B", "Account A")), timeout=NO_WAIT_SECONDS * 2
    )
    async with sessions() as check:
        names = (await check.execute(select(Account.name).where(Account.user_id == user_id))).scalars().all()
    assert sorted(names) == ["Account A", "Account B"]


async def test_AC_ledger_71_5_account_creation_transaction_boundaries(db_engine, db):
    sessions, user_id = await _committed_user(db_engine)
    async with sessions() as caller:
        created_id = (await _processing(caller, user_id)).id
        await caller.rollback()
    async with sessions() as check:
        assert (await _processing(check, user_id)).id == created_id

    user = await UserFactory.create_async(db, email=f"uncommitted-{uuid4()}@example.invalid")
    uncommitted_sessions = async_sessionmaker(db.bind, expire_on_commit=False)
    account_id = (await _processing(db, user.id)).id
    async with uncommitted_sessions() as other:
        assert await other.get(Account, account_id) is None
    await db.rollback()
    async with uncommitted_sessions() as other:
        assert await other.get(Account, account_id) is None


async def test_AC_ledger_71_5_without_an_own_session_the_caller_creates_the_account_under_the_lock(
    db_engine, monkeypatch
):
    monkeypatch.setattr(
        account_service,
        "create_session_maker_from_db",
        lambda _db: (_ for _ in ()).throw(RuntimeError("Async engine unavailable")),
    )
    sessions, user_id = await _committed_user(db_engine)
    first, second = sessions(), sessions()
    try:
        first_account = await _processing(first, user_id)
        second_pid = await backend_pid(second)
        waiting = asyncio.create_task(_processing(second, user_id))
        assert await backend_waits_for_a_lock(db_engine, second_pid), "the second caller must wait for the lock"
        await first.commit()
        second_account = await asyncio.wait_for(waiting, timeout=NO_WAIT_SECONDS)
        await second.commit()
    finally:
        await first.close()
        await second.close()
    assert second_account.id == first_account.id


async def test_AC_ledger_71_5_a_lock_that_the_caller_holds_makes_the_creation_fail_instead_of_hang(
    db_engine, monkeypatch
):
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
    calls: list[UUID] = []
    original = account_service.find_or_create_account

    async def spy_find_or_create(session, *, user_id, find, build):
        calls.append(user_id)
        return await original(session, user_id=user_id, find=find, build=build)

    monkeypatch.setattr(account_service, "find_or_create_account", spy_find_or_create)
    obe = await account_service.get_or_create_opening_balance_equity_account(db, test_user.id, "SGD")
    uge = await account_service.get_or_create_unexplained_gap_equity_account(db, test_user.id, "SGD")
    broker = await PositionService()._get_or_create_broker_account(db, test_user.id, "Interactive Brokers", "USD")
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
    bank_acc = await create_statement_account_from_confirmation(db, stmt, test_user.id)
    adj_resp = await post_reconciliation_adjustment(
        payload=ReconciliationAdjustmentRequest(
            account_id=bank_acc.id,
            bank_balance=Decimal("100.02"),
            book_balance=Decimal("100.00"),
            threshold=Decimal("0.05"),
            entry_date=date(2025, 1, 31),
        ),
        ctx=RequestContext(db, test_user.id),
    )
    assert (
        obe.code,
        uge.code,
        broker.code,
        broker.currency,
        bank_acc.code,
        stmt.account_id,
        adj_resp.difference,
        len(calls),
    ) == (
        account_service.OPENING_BALANCE_EQUITY_CODE,
        account_service.UNEXPLAINED_GAP_EQUITY_CODE,
        "AUTO-ASSET",
        "USD",
        "AUTO-BANK",
        bank_acc.id,
        Decimal("0.02"),
        5,
    )
