from uuid import uuid4

from src.counter import CounterKey, get_count, increment
from src.counter.extension.facade import read_count
from src.counter.extension.sql import SqlCounterRepository

from ._fake import InMemoryCounterRepository

KEY = CounterKey("report.generated")


async def test_sql_bump_global_per_user_and_sync_parity(db):
    repo, u1, u2 = SqlCounterRepository(db), uuid4(), uuid4()
    assert [await repo.bump(u1, KEY), await repo.bump(u1, KEY), await repo.bump(u2, KEY)] == [1, 2, 1]
    assert (await repo.total(KEY), await repo.for_user(u1, KEY), await repo.for_user(u2, KEY)) == (3, 2, 1)
    assert (
        int(await read_count(db, key=KEY)),
        int(await read_count(db, key=KEY, user_id=u1)),
        int(await read_count(db, key=KEY, user_id=uuid4())),
    ) == (3, 2, 0)

    fake = InMemoryCounterRepository()
    await increment(fake, user_id=u1, key=KEY)
    await increment(fake, user_id=u1, key=KEY)
    assert int(await get_count(fake, key=KEY, user_id=u1)) == await repo.for_user(u1, KEY)
