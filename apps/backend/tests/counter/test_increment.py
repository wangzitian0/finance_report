from uuid import uuid4

import pytest
from src.counter import Count, CounterKey, increment
from src.platform import RecordingEventBus

from ._fake import InMemoryCounterRepository

pytestmark = pytest.mark.no_db
KEY = CounterKey("report.generated")
OTHER = CounterKey("statement.uploaded")


async def test_increment_per_user_and_emits_event():
    repo, bus, u1, u2 = InMemoryCounterRepository(), RecordingEventBus(), uuid4(), uuid4()
    assert await increment(repo, user_id=u1, key=KEY, bus=bus) == Count(1)
    assert await increment(repo, user_id=u1, key=KEY) == Count(2)
    assert await increment(repo, user_id=u2, key=KEY) == Count(1)
    assert await increment(repo, user_id=u1, key=OTHER) == Count(1)
    assert (await repo.for_user(u1, KEY), await repo.for_user(u2, KEY), await repo.for_user(u1, OTHER)) == (2, 1, 1)

    assert len(bus.published) == 1
    ev = bus.published[0]
    assert (ev.user_id, ev.key, ev.count, ev.event_type) == (u1, KEY, 1, "counter.Incremented") and ev.occurred_at is not None
