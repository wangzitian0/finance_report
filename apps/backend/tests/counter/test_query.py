"""get_count verb — per-user vs global (EPIC-025 AC25.6.4)."""

from uuid import uuid4

import pytest
from common.testing.ac_proof import ac_proof

from src.counter import Count, CounterKey, get_count, increment

from ._fake import InMemoryCounterRepository

pytestmark = pytest.mark.no_db

KEY = CounterKey("report.generated")


@ac_proof(proof_id="test_global_vs_per_user", ac_ids=["AC25.6.4"], ci_tier="pr_ci")
def test_global_vs_per_user_count():
    """AC25.6.4: user_id=None yields the global sum; a user_id yields that user's."""
    repo = InMemoryCounterRepository()
    u1, u2 = uuid4(), uuid4()
    # u1 increments twice, u2 once
    increment(repo, user_id=u1, key=KEY)
    increment(repo, user_id=u1, key=KEY)
    increment(repo, user_id=u2, key=KEY)

    assert get_count(repo, key=KEY, user_id=u1) == Count(2)
    assert get_count(repo, key=KEY, user_id=u2) == Count(1)
    # global = sum across all users
    assert get_count(repo, key=KEY) == Count(3)
    assert get_count(repo, key=KEY, user_id=None) == Count(3)


@ac_proof(proof_id="test_unknown_count_is_zero", ac_ids=["AC25.6.4"], ci_tier="pr_ci")
def test_unknown_key_or_user_is_zero():
    """AC25.6.4: never-incremented (user, key) reads as Count(0), not an error."""
    repo = InMemoryCounterRepository()
    assert get_count(repo, key=KEY) == Count(0)
    assert get_count(repo, key=KEY, user_id=uuid4()) == Count(0)
