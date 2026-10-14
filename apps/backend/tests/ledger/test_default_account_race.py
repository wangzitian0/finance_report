"""AC-ledger.71.5: two requests of one user create each default account once (#2415).

The accounts table has no unique index for the Processing account or for a default account.
Both helpers read first and insert after. A user who uploads several statements at once makes
several workers reach the insert together. A second row then breaks every later lookup, which
expects one row. The test holds the first transaction open, so the second request runs while
the first has not committed. Only a lock makes the second request wait.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.extraction.extension.review_queue import get_or_create_account
from src.ledger import PROCESSING_ACCOUNT_CODE, Account, AccountType, get_or_create_processing_account
from tests.factories import UserFactory

pytestmark = pytest.mark.asyncio

#: Time that the second request gets to run before the first commits. Without a lock it inserts a row.
SECOND_REQUEST_HEAD_START = 0.5


async def _race(db_engine, create):
    """Run ``create(session, user_id)`` in two sessions. The first session commits after the second has run."""
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as setup:
        user = await UserFactory.create_async(setup, email=f"race-{uuid4()}@example.invalid")
        user_id = user.id
        await setup.commit()

    first, second = sessions(), sessions()
    try:
        first_account = await create(first, user_id)
        pending = asyncio.create_task(create(second, user_id))
        await asyncio.sleep(SECOND_REQUEST_HEAD_START)
        await first.commit()
        second_account = await asyncio.wait_for(pending, timeout=15)
        await second.commit()
    finally:
        await first.close()
        await second.close()
    return sessions, user_id, first_account, second_account


async def test_AC_ledger_71_5_two_requests_create_one_processing_account(db_engine):
    """AC-ledger.71.5: the second request waits, then finds the account of the first."""
    sessions, user_id, first_account, second_account = await _race(
        db_engine, lambda session, uid: get_or_create_processing_account(session, uid, currency="SGD")
    )

    async with sessions() as check:
        count = await check.scalar(
            select(func.count(Account.id)).where(Account.user_id == user_id, Account.code == PROCESSING_ACCOUNT_CODE)
        )
    assert count == 1
    assert second_account.id == first_account.id


async def test_AC_ledger_71_5_two_requests_create_one_default_account(db_engine):
    """AC-ledger.71.5: a default account such as `General Expense (SGD)` has one row per user, type and currency."""
    sessions, user_id, first_account, second_account = await _race(
        db_engine,
        lambda session, uid: get_or_create_account(
            session, name="General Expense (SGD)", account_type=AccountType.EXPENSE, currency="SGD", user_id=uid
        ),
    )

    async with sessions() as check:
        count = await check.scalar(
            select(func.count(Account.id)).where(Account.user_id == user_id, Account.name == "General Expense (SGD)")
        )
    assert count == 1
    assert second_account.id == first_account.id


async def test_AC_ledger_71_5_the_account_creators_of_one_user_share_one_lock(db_engine):
    """AC-ledger.71.5: two creators that need two accounts in opposite order cannot wait for each other.

    The first transaction creates account A and then account B. The second creates B and then A. A lock key
    per account would make them wait in a circle, and the database would abort one of them.
    """
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as setup:
        user = await UserFactory.create_async(setup, email=f"order-{uuid4()}@example.invalid")
        user_id = user.id
        await setup.commit()

    async def create(session, name):
        return await get_or_create_account(
            session, name=name, account_type=AccountType.EXPENSE, currency="SGD", user_id=user_id
        )

    async def worker(first_name, second_name):
        async with sessions() as session:
            await create(session, first_name)
            await asyncio.sleep(SECOND_REQUEST_HEAD_START)
            await create(session, second_name)
            await session.commit()

    await asyncio.wait_for(asyncio.gather(worker("Account A", "Account B"), worker("Account B", "Account A")), 20)

    async with sessions() as check:
        names = (await check.execute(select(Account.name).where(Account.user_id == user_id))).scalars().all()
    assert sorted(names) == ["Account A", "Account B"]
