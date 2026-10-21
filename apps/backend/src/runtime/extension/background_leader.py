"""Run the process-wide background loops in exactly one worker process.

The backend can run more than one uvicorn worker process (``WEB_CONCURRENCY``,
#2583 S5). Each worker runs the app lifespan, so each worker would start its own
copy of the background loops. Two copies of a loop do duplicate work: two
outbox relays dispatch the same pending row twice, and two market-data
schedulers call the external providers twice at 22:00 SGT.

:class:`BackgroundLeader` elects one leader among the workers with a
PostgreSQL session-level advisory lock. The worker that holds the lock runs the
loops. The other workers try the lock again every ``retry_seconds``. The lock
belongs to one database session, so PostgreSQL releases it when the leader
process stops or its connection closes. Then the next attempt of another worker
gets the lock, and the loops move to that worker.

The lock session uses its own engine with ``NullPool`` and ``AUTOCOMMIT``:

- ``NullPool`` closes the connection on release, so a released connection can
  never go back to a pool with the lock still held.
- ``AUTOCOMMIT`` keeps the session out of a transaction. A session that stays
  "idle in transaction" holds back vacuum.
- ``idle_session_timeout`` (PostgreSQL 14 and later) lets the server end a lock
  session that sends no query for ``LEADER_IDLE_SESSION_TIMEOUT_MS``. A leader
  that lost its network without a TCP reset then loses the lock on the server
  too, and another worker can become the leader.

The leader runs ``SELECT 1`` on its lock session every ``heartbeat_seconds``.
When the query fails or takes longer than ``LEADER_SESSION_TIMEOUT_SECONDS``,
the leader stops its loops. When the server ends the session, the query fails
at once, so the old leader stops within one heartbeat period. When the network
is silent, the old leader stops within one heartbeat period plus the session
timeout (10 s).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Mapping
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from src.observability import get_logger

logger = get_logger(__name__)

#: The advisory-lock key of the background leader. It differs from the
#: migration lock key in ``scripts/entrypoint.sh`` (1862534).
BACKGROUND_LEADER_LOCK_KEY: Final = 25830005

#: Seconds a worker without the lock waits before it tries the lock again.
#: This is the maximum time from a leader stop to the next leader start.
LEADER_RETRY_SECONDS: float = 10.0

#: Seconds between two checks of the lock session by the leader.
LEADER_HEARTBEAT_SECONDS: float = 5.0

#: Upper limit in seconds for one connect, query, unlock or close of the lock session.
#: A hung session cannot hold a lock attempt or a shutdown for longer.
LEADER_SESSION_TIMEOUT_SECONDS: float = 5.0

#: The server ends a lock session that sends no query for this time. The leader
#: sends one every heartbeat (5 s), so a live leader keeps its session.
LEADER_IDLE_SESSION_TIMEOUT_MS: int = 60_000

#: Seconds the lifespan shutdown waits for the leader to stop its loops and
#: release its lock session; then it cancels the leader task.
LEADER_SHUTDOWN_SECONDS: float = 5.0

#: A loop factory: it gets a stop event and runs until the event is set.
BackgroundLoop = Callable[[asyncio.Event], Coroutine[Any, Any, None]]


async def _wait_for_stop(stop_event: asyncio.Event, seconds: float) -> bool:
    """Wait until ``stop_event`` is set or ``seconds`` pass; return True on stop."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True


class BackgroundLeader:
    """Run a set of background loops only while this process holds the leader lock."""

    def __init__(
        self,
        database_url: str | URL,
        loops: Mapping[str, BackgroundLoop],
        *,
        lock_key: int = BACKGROUND_LEADER_LOCK_KEY,
        retry_seconds: float | None = None,
        heartbeat_seconds: float | None = None,
    ) -> None:
        self._database_url = database_url
        self._loops = dict(loops)
        self._lock_key = lock_key
        self._retry_seconds = LEADER_RETRY_SECONDS if retry_seconds is None else retry_seconds
        self._heartbeat_seconds = LEADER_HEARTBEAT_SECONDS if heartbeat_seconds is None else heartbeat_seconds
        self._is_leader = False

    @property
    def loop_names(self) -> frozenset[str]:
        """The names of the loops that this leader runs."""
        return frozenset(self._loops)

    @property
    def is_leader(self) -> bool:
        """True while this process holds the lock and runs the loops."""
        return self._is_leader

    @property
    def retry_seconds(self) -> float:
        """Seconds between two lock attempts of a worker without the lock."""
        return self._retry_seconds

    async def run(self, stop_event: asyncio.Event) -> None:
        """Try the lock until ``stop_event`` is set; run the loops while the lock is held."""
        engine = create_async_engine(
            self._database_url,
            poolclass=NullPool,
            isolation_level="AUTOCOMMIT",
            connect_args={"server_settings": {"idle_session_timeout": str(LEADER_IDLE_SESSION_TIMEOUT_MS)}},
        )
        try:
            while not stop_event.is_set():
                connection = await self._try_acquire(engine)
                if connection is None:
                    await _wait_for_stop(stop_event, self._retry_seconds)
                    continue
                try:
                    if not stop_event.is_set():
                        await self._lead(connection, stop_event)
                finally:
                    await self._release(connection)
                if not stop_event.is_set():
                    # Leadership was lost. Wait one retry period, so that a
                    # worker with a live session can get the lock first.
                    await _wait_for_stop(stop_event, self._retry_seconds)
        finally:
            await engine.dispose()

    async def _try_acquire(self, engine: AsyncEngine) -> AsyncConnection | None:
        """Return a connection that holds the lock, or None when the lock is not available."""
        try:
            connection = await asyncio.wait_for(engine.connect(), timeout=LEADER_SESSION_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("background_leader.connect_failed", error_type=type(exc).__name__, error=str(exc))
            return None
        try:
            result = await asyncio.wait_for(
                connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": self._lock_key}),
                timeout=LEADER_SESSION_TIMEOUT_SECONDS,
            )
            acquired = bool(result.scalar_one())
        except Exception as exc:
            logger.warning("background_leader.lock_query_failed", error_type=type(exc).__name__, error=str(exc))
            await self._close_quietly(connection)
            return None
        if not acquired:
            await self._close_quietly(connection)
            return None
        return connection

    async def _lead(self, connection: AsyncConnection, stop_event: asyncio.Event) -> None:
        """Run the loops until ``stop_event`` is set or the lock session fails a check."""
        loops_stop = asyncio.Event()
        tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(loop(loops_stop), name=f"background-leader:{name}")
            for name, loop in self._loops.items()
        ]
        self._is_leader = True
        logger.info("background_leader.acquired", lock_key=self._lock_key, loops=sorted(self._loops))
        try:
            while not await _wait_for_stop(stop_event, self._heartbeat_seconds):
                if not await self._session_is_alive(connection):
                    logger.warning("background_leader.lost", lock_key=self._lock_key)
                    break
        finally:
            self._is_leader = False
            loops_stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _session_is_alive(self, connection: AsyncConnection) -> bool:
        """Return True when the lock session answers a query within the session timeout."""
        try:
            await asyncio.wait_for(connection.execute(text("SELECT 1")), timeout=LEADER_SESSION_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("background_leader.heartbeat_failed", error_type=type(exc).__name__, error=str(exc))
            return False
        return True

    async def _release(self, connection: AsyncConnection) -> None:
        """Release the lock and close the lock session; a dead session releases the lock itself."""
        try:
            await asyncio.wait_for(
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self._lock_key}),
                timeout=LEADER_SESSION_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.info("background_leader.unlock_skipped", error_type=type(exc).__name__)
        await self._close_quietly(connection)
        logger.info("background_leader.released", lock_key=self._lock_key)

    @staticmethod
    async def _close_quietly(connection: AsyncConnection) -> None:
        try:
            await asyncio.wait_for(connection.close(), timeout=LEADER_SESSION_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.info("background_leader.close_failed", error_type=type(exc).__name__)
