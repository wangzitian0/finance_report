"""Test helper for AC-ledger.71.5 and AC-reconciliation.named-transfer-legs.2 (#2415).

It proves that a database session waits for a lock that another session holds.

A fixed sleep cannot prove a wait. On a slow runner the second session may not have started when the sleep ends,
and the test would pass even when the lock is missing. This probe returns only when the database reports a backend
that waits for a lock, or when the deadline passes.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker


async def a_session_waits_for_a_lock(engine: AsyncEngine, *, seconds: float = 10.0) -> bool:
    """True once a backend of the current database waits for a lock. False when none waits before the deadline."""
    deadline = asyncio.get_running_loop().time() + seconds
    async with async_sessionmaker(engine)() as probe:
        while asyncio.get_running_loop().time() < deadline:
            waiting = await probe.scalar(
                # A wait for a row lock shows as an ungranted `transactionid` lock, which has no database column.
                # So the probe joins the backend that waits, not the database of the lock.
                text(
                    "SELECT count(*) FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                    "WHERE NOT l.granted AND a.datname = current_database()"
                )
            )
            if waiting:
                return True
            await asyncio.sleep(0.05)
    return False
