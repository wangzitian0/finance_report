"""Test helper for AC-ledger.71.5 and AC-reconciliation.named-transfer-legs.2 (#2415).

It proves that one known database session waits for a lock that another session holds.

A fixed sleep cannot prove a wait. On a slow runner the second session may not have started when the sleep ends,
and the test would pass even when the lock is missing. The probe asks ``pg_locks`` about the backend of the second
session. Each poll runs on a fresh autocommit connection, so no poll reads the stale view of an earlier one.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


async def backend_pid(session: AsyncSession) -> int:
    """The process id of the database backend that serves ``session``. It also opens the connection."""
    return int(await session.scalar(text("SELECT pg_backend_pid()")))


async def backend_waits_for_a_lock(engine: AsyncEngine, pid: int, *, seconds: float = 10.0) -> bool:
    """True once the backend ``pid`` waits for a lock. False when it does not wait before the deadline."""
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        async with engine.connect() as probe:
            probe = await probe.execution_options(isolation_level="AUTOCOMMIT")
            waiting = await probe.scalar(
                text("SELECT count(*) FROM pg_locks WHERE pid = :pid AND NOT granted"), {"pid": pid}
            )
        if waiting:
            return True
        await asyncio.sleep(0.05)
    return False
