"""DB-backed SqlCounterRepository — atomic upsert + per-user/global reads.

Exercises the only role that touches the ORM against the real ``counter_tally``
table (EPIC-025 AC-counter.1.3 / AC-counter.1.4). The bump is an atomic upsert-increment, so
the second bump of the same (user, key) returns 2 rather than colliding on the
unique (user_id, key) primary key.
"""

from uuid import uuid4

import pytest
from common.testing.ac_proof import ac_proof

from src.counter import CounterKey, get_count, increment
from src.counter.extension.facade import read_count
from src.counter.extension.sql import SqlCounterRepository

KEY = CounterKey("report.generated")


@ac_proof(proof_id="test_sql_counter_atomic", ac_ids=["AC-counter.1.3"], ci_tier="pr_ci")
@pytest.mark.asyncio
async def test_sql_bump_is_atomic_and_per_user(db):
    """AC-counter.1.3: repeated bumps increment the same (user, key) row atomically."""
    repo = SqlCounterRepository(db)
    u1, u2 = uuid4(), uuid4()

    assert await repo.bump(u1, KEY) == 1
    assert await repo.bump(u1, KEY) == 2
    assert await repo.bump(u1, KEY) == 3
    assert await repo.bump(u2, KEY) == 1  # different user starts fresh

    assert await repo.for_user(u1, KEY) == 3
    assert await repo.for_user(u2, KEY) == 1


@ac_proof(proof_id="test_sql_counter_global", ac_ids=["AC-counter.1.4"], ci_tier="pr_ci")
@pytest.mark.asyncio
async def test_sql_global_and_per_user_reads(db):
    """AC-counter.1.4: total() sums across users; read_count bridges to a Count."""
    repo = SqlCounterRepository(db)
    u1, u2 = uuid4(), uuid4()
    await repo.bump(u1, KEY)
    await repo.bump(u1, KEY)
    await repo.bump(u2, KEY)

    assert await repo.total(KEY) == 3
    assert await repo.for_user(u1, KEY) == 2

    # the api boundary returns validated Count value objects
    assert int(await read_count(db, key=KEY)) == 3
    assert int(await read_count(db, key=KEY, user_id=u1)) == 2
    assert int(await read_count(db, key=KEY, user_id=uuid4())) == 0


@ac_proof(proof_id="test_sql_ops_port_parity", ac_ids=["AC-counter.1.4"], ci_tier="pr_ci")
@pytest.mark.asyncio
async def test_sql_repo_satisfies_read_via_ops_after_sync_snapshot(db):
    """AC-counter.1.4: ops over an in-memory snapshot of the SQL state agree with the DB."""
    from tests.counter._fake import InMemoryCounterRepository

    repo = SqlCounterRepository(db)
    u1 = uuid4()
    await repo.bump(u1, KEY)
    await repo.bump(u1, KEY)

    # mirror the persisted state into the sync fake and check the sync verbs
    fake = InMemoryCounterRepository()
    increment(fake, user_id=u1, key=KEY)
    increment(fake, user_id=u1, key=KEY)
    assert int(get_count(fake, key=KEY, user_id=u1)) == await repo.for_user(u1, KEY)
