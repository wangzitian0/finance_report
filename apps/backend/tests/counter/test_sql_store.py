
from uuid import uuid4
import pytest
from src.counter import CounterKey, get_count, increment
from src.counter.extension.facade import read_count
from src.counter.extension.sql import SqlCounterRepository

KEY = CounterKey("report.generated")


async def test_sql_bump_is_atomic_and_per_user(db):
    repo = SqlCounterRepository(db)
    u1, u2 = (uuid4(), uuid4())
    assert await repo.bump(u1, KEY) == 1
    assert await repo.bump(u1, KEY) == 2
    assert await repo.bump(u1, KEY) == 3
    assert await repo.bump(u2, KEY) == 1
    assert await repo.for_user(u1, KEY) == 3
    assert await repo.for_user(u2, KEY) == 1


async def test_sql_global_and_per_user_reads(db):
    repo = SqlCounterRepository(db)
    u1, u2 = (uuid4(), uuid4())
    await repo.bump(u1, KEY)
    await repo.bump(u1, KEY)
    await repo.bump(u2, KEY)
    assert await repo.total(KEY) == 3
    assert await repo.for_user(u1, KEY) == 2
    assert int(await read_count(db, key=KEY)) == 3
    assert int(await read_count(db, key=KEY, user_id=u1)) == 2
    assert int(await read_count(db, key=KEY, user_id=uuid4())) == 0


async def test_sql_repo_satisfies_read_via_ops_after_sync_snapshot(db):
    from tests.counter._fake import InMemoryCounterRepository

    repo = SqlCounterRepository(db)
    u1 = uuid4()
    await repo.bump(u1, KEY)
    await repo.bump(u1, KEY)
    fake = InMemoryCounterRepository()
    await increment(fake, user_id=u1, key=KEY)
    await increment(fake, user_id=u1, key=KEY)
    assert int(await get_count(fake, key=KEY, user_id=u1)) == await repo.for_user(u1, KEY)
