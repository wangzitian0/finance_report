'AC-ledger.71.5 AC-reconciliation.named-transfer-legs.2'; from __future__ import annotations; import asyncio; from sqlalchemy import text; from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
async def backend_pid(session: AsyncSession) -> int: return int(await session.scalar(text('SELECT pg_backend_pid()')))
async def backend_waits_for_a_lock(engine: AsyncEngine, pid: int, *, seconds: float=10.0) -> bool:
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        async with engine.connect() as probe: probe = await probe.execution_options(isolation_level='AUTOCOMMIT'); waiting = await probe.scalar(text('SELECT count(*) FROM pg_locks WHERE pid = :pid AND NOT granted'), {'pid': pid})
        if waiting: return True
        await asyncio.sleep(0.05)
    return False
