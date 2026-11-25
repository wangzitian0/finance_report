from uuid import uuid4

import pytest
from src.counter import Count, CounterKey, get_count, increment

from ._fake import InMemoryCounterRepository

pytestmark = pytest.mark.no_db
KEY = CounterKey("report.generated")


async def test_global_vs_per_user_and_unknown_count():
    repo, u1, u2 = InMemoryCounterRepository(), uuid4(), uuid4()
    assert (await get_count(repo, key=KEY), await get_count(repo, key=KEY, user_id=uuid4())) == (Count(0), Count(0))
    await increment(repo, user_id=u1, key=KEY)
    await increment(repo, user_id=u1, key=KEY)
    await increment(repo, user_id=u2, key=KEY)
    assert (
        await get_count(repo, key=KEY, user_id=u1),
        await get_count(repo, key=KEY, user_id=u2),
        await get_count(repo, key=KEY),
        await get_count(repo, key=KEY, user_id=None),
    ) == (
        Count(2),
        Count(1),
        Count(3),
        Count(3),
    )
