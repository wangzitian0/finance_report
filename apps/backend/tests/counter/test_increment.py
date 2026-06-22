"""increment verb — per-user bump + Incremented event (EPIC-025 AC25.6.3)."""

from uuid import uuid4

import pytest
from common.testing.ac_proof import ac_proof

from src.counter import Count, CounterKey, increment
from src.platform import RecordingEventBus

from ._fake import InMemoryCounterRepository

pytestmark = pytest.mark.no_db

KEY = CounterKey("report.generated")
OTHER = CounterKey("statement.uploaded")


@ac_proof(proof_id="test_increment_per_user", ac_ids=["AC25.6.3"], ci_tier="pr_ci")
def test_increment_is_per_user():
    """AC25.6.3: increment bumps THIS user's tally and returns the new Count."""
    repo = InMemoryCounterRepository()
    u1, u2 = uuid4(), uuid4()

    assert increment(repo, user_id=u1, key=KEY) == Count(1)
    assert increment(repo, user_id=u1, key=KEY) == Count(2)
    # a different user's tally is untouched
    assert increment(repo, user_id=u2, key=KEY) == Count(1)
    # a different key is untouched
    assert increment(repo, user_id=u1, key=OTHER) == Count(1)


@ac_proof(proof_id="test_increment_emits_event", ac_ids=["AC25.6.3"], ci_tier="pr_ci")
def test_increment_emits_incremented_event():
    """AC25.6.3: increment publishes an Incremented domain event through the bus."""
    repo = InMemoryCounterRepository()
    u1 = uuid4()
    bus = RecordingEventBus()

    increment(repo, user_id=u1, key=KEY, bus=bus)

    assert len(bus.published) == 1
    event = bus.published[0]
    assert event.user_id == u1
    assert event.key == KEY
    assert event.count == 1
    assert event.event_type == "counter.Incremented"
    assert event.occurred_at is not None


@ac_proof(proof_id="test_keys_users_isolated", ac_ids=["AC25.6.3"], ci_tier="pr_ci")
def test_two_keys_two_users_do_not_interfere():
    """AC25.6.3: (user, key) pairs are independent tallies."""
    repo = InMemoryCounterRepository()
    u1, u2 = uuid4(), uuid4()
    increment(repo, user_id=u1, key=KEY)
    increment(repo, user_id=u1, key=KEY)
    increment(repo, user_id=u2, key=OTHER)
    assert repo.for_user(u1, KEY) == 2
    assert repo.for_user(u2, KEY) == 0
    assert repo.for_user(u1, OTHER) == 0
    assert repo.for_user(u2, OTHER) == 1
