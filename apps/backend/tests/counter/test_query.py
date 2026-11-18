
from uuid import uuid4
import pytest
from src.counter import Count, CounterKey, get_count, increment
from ._fake import InMemoryCounterRepository

pytestmark = pytest.mark.no_db
KEY = CounterKey("report.generated")


async def test_global_vs_per_user_count():
    repo = InMemoryCounterRepository()
    u1, u2 = (uuid4(), uuid4())
    await increment(repo, user_id=u1, key=KEY)
    await increment(repo, user_id=u1, key=KEY)
    await increment(repo, user_id=u2, key=KEY)
    assert await get_count(repo, key=KEY, user_id=u1) == Count(2)
    assert await get_count(repo, key=KEY, user_id=u2) == Count(1)
    assert await get_count(repo, key=KEY) == Count(3)
    assert await get_count(repo, key=KEY, user_id=None) == Count(3)


async def test_unknown_key_or_user_is_zero():
    repo = InMemoryCounterRepository()
    assert await get_count(repo, key=KEY) == Count(0)
    assert await get_count(repo, key=KEY, user_id=uuid4()) == Count(0)
