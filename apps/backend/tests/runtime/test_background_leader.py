"""AC-runtime.workers.1: the background loops run in exactly one worker process (#2583 S5).

The backend runs more than one uvicorn worker. Each worker runs the app
lifespan. These tests start two real lifespans of ``src.main`` against one
test database. The two lifespans stand for two worker processes: each lifespan
opens its own lock session, and a PostgreSQL advisory lock is held per session.
"""

from __future__ import annotations

import asyncio
import contextvars
import socket
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import pytest
from sqlalchemy import text

import src.main as main_module
from src.config import settings
from src.runtime import BackgroundLeader
from src.runtime.extension import background_leader as leader_module

#: The four loops of the lifespan, as module globals of ``src.main``.
LOOP_GLOBALS = {
    "parsing_supervisor": "run_parsing_supervisor",
    "market_data_scheduler": "run_market_data_scheduler",
    "storage_sweep": "run_storage_sweep",
    "outbox_relay": "run_outbox_relay",
}
ALL_LOOPS = frozenset(LOOP_GLOBALS)

RETRY_SECONDS = 0.5
HEARTBEAT_SECONDS = 0.25
#: Time for one connect and one lock query on a loaded CI runner.
CONNECT_MARGIN_SECONDS = 0.5

_WORKER: contextvars.ContextVar[str] = contextvars.ContextVar("worker")


class LoopRecorder:
    """Record which loop runs in which worker, and when each loop stops."""

    def __init__(self) -> None:
        self.active: dict[str, set[str]] = {"A": set(), "B": set()}
        self.stopped_at: dict[str, dict[str, float]] = {"A": {}, "B": {}}

    def loop(self, name: str) -> Callable[..., object]:
        async def _loop(stop_event: asyncio.Event, *_args: object) -> None:
            worker = _WORKER.get()
            self.active[worker].add(name)
            try:
                await stop_event.wait()
            finally:
                self.active[worker].discard(name)
                self.stopped_at[worker][name] = time.monotonic()

        return _loop

    def sole_runner(self) -> str | None:
        """Return the worker that runs all four loops while the other runs none."""
        for worker, other in (("A", "B"), ("B", "A")):
            if self.active[worker] == ALL_LOOPS and not self.active[other]:
                return worker
        return None

    def describe(self) -> str:
        return f"A={sorted(self.active['A'])} B={sorted(self.active['B'])}"


async def _wait_until(predicate: Callable[[], bool], timeout: float) -> float | None:
    """Return the seconds until ``predicate`` is true, or None after ``timeout``."""
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if predicate():
            return time.monotonic() - started
        await asyncio.sleep(0.02)
    return None


async def _enter_worker(name: str) -> AbstractAsyncContextManager[None]:
    """Enter one app lifespan in the context of worker ``name``."""
    token = _WORKER.set(name)
    try:
        lifespan = main_module.lifespan(main_module.app)
        await lifespan.__aenter__()
    finally:
        _WORKER.reset(token)
    return lifespan


async def _lock_holder_pids(db_engine) -> list[int]:
    async with db_engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted "
                "AND objid = :key AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
            ),
            {"key": leader_module.BACKGROUND_LEADER_LOCK_KEY},
        )
        return [int(row[0]) for row in result]


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch, db_engine, test_database_url: str) -> LoopRecorder:
    """Replace the four loops with recorders and point the lifespan at the test database."""
    loops = LoopRecorder()
    for name, attribute in LOOP_GLOBALS.items():
        monkeypatch.setattr(main_module, attribute, loops.loop(name))
    monkeypatch.setattr(settings, "database_url", test_database_url)
    monkeypatch.setattr(leader_module, "LEADER_RETRY_SECONDS", RETRY_SECONDS)
    monkeypatch.setattr(leader_module, "LEADER_HEARTBEAT_SECONDS", HEARTBEAT_SECONDS)
    return loops


async def test_AC_runtime_workers_1_each_background_loop_runs_in_exactly_one_worker(
    recorder: LoopRecorder, db_engine
) -> None:
    """AC-runtime.workers.1: two worker lifespans share one database.

    Each of the four background loops runs in exactly one worker. A lost lock
    session stops the loops of the old leader within one heartbeat. When the
    leader stops, the other worker starts all four loops within the retry
    interval.
    """
    lifespans = {"A": await _enter_worker("A"), "B": await _enter_worker("B")}
    try:
        # 1. Exactly one worker runs the loops, also after three retry periods.
        assert await _wait_until(lambda: recorder.sole_runner() is not None, timeout=5.0) is not None, (
            f"no worker runs all four loops alone: {recorder.describe()}"
        )
        await asyncio.sleep(3 * RETRY_SECONDS)
        leader = recorder.sole_runner()
        assert leader is not None, f"two workers run background loops: {recorder.describe()}"
        holders = await _lock_holder_pids(db_engine)
        assert len(holders) == 1, f"expected one lock session, found {holders}"

        # 2. The lock session of the leader ends (the server terminates it).
        async with db_engine.connect() as connection:
            await connection.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": holders[0]})
        terminated_at = time.monotonic()
        assert await _wait_until(lambda: not recorder.active[leader], timeout=5.0) is not None, (
            f"the old leader {leader} kept its loops after it lost the lock: {recorder.describe()}"
        )
        stop_delay = max(recorder.stopped_at[leader].values()) - terminated_at
        assert stop_delay <= HEARTBEAT_SECONDS + CONNECT_MARGIN_SECONDS, (
            f"the old leader stopped its loops {stop_delay:.2f}s after the session loss"
        )
        assert await _wait_until(lambda: recorder.sole_runner() is not None, timeout=5.0) is not None, (
            f"no worker took the leadership back: {recorder.describe()}"
        )
        await asyncio.sleep(3 * RETRY_SECONDS)
        leader = recorder.sole_runner()
        assert leader is not None, f"two workers run background loops: {recorder.describe()}"

        # 3. The leader stops. The other worker starts all four loops within the retry interval.
        follower = "B" if leader == "A" else "A"
        stopped_at = time.monotonic()
        await lifespans.pop(leader).__aexit__(None, None, None)
        takeover = await _wait_until(lambda: recorder.active[follower] == ALL_LOOPS, timeout=5.0)
        assert takeover is not None, f"worker {follower} did not take over: {recorder.describe()}"
        takeover_seconds = time.monotonic() - stopped_at
        assert takeover_seconds <= RETRY_SECONDS + CONNECT_MARGIN_SECONDS, (
            f"takeover took {takeover_seconds:.2f}s; the retry interval is {RETRY_SECONDS}s"
        )
        assert not recorder.active[leader]
    finally:
        for lifespan in lifespans.values():
            await lifespan.__aexit__(None, None, None)

    # 4. After both workers stop, no loop runs and no session holds the lock.
    assert recorder.active == {"A": set(), "B": set()}
    assert await _lock_holder_pids(db_engine) == []


def test_AC_runtime_workers_1_lifespan_guards_all_four_loops() -> None:
    """AC-runtime.workers.1: the leader guards every loop that the lifespan starts."""
    assert frozenset(main_module.background_loops()) == ALL_LOOPS


def _closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _run_briefly(leader: BackgroundLeader, seconds: float) -> None:
    stop_event = asyncio.Event()
    task = asyncio.create_task(leader.run(stop_event))
    await asyncio.sleep(seconds)
    assert not leader.is_leader
    stop_event.set()
    await asyncio.wait_for(task, timeout=2.0)


async def test_AC_runtime_workers_1_unreachable_database_runs_no_loop() -> None:
    """AC-runtime.workers.1: without a lock session, a worker runs no loop and keeps retrying."""
    started: list[str] = []

    async def loop(stop_event: asyncio.Event) -> None:
        started.append("loop")
        await stop_event.wait()

    leader = BackgroundLeader(
        f"postgresql+asyncpg://postgres:postgres@127.0.0.1:{_closed_port()}/none",
        {"loop": loop},
        retry_seconds=0.05,
    )
    assert leader.retry_seconds == 0.05
    assert leader.loop_names == frozenset({"loop"})
    await _run_briefly(leader, 0.3)
    assert started == []


async def test_AC_runtime_workers_1_failed_lock_query_runs_no_loop(test_database_url: str, db_engine) -> None:
    """AC-runtime.workers.1: a lock query that fails counts as a lock that is not available."""
    started: list[str] = []

    async def loop(stop_event: asyncio.Event) -> None:
        started.append("loop")
        await stop_event.wait()

    # A key outside the bigint range makes the lock query fail on the server side.
    leader = BackgroundLeader(test_database_url, {"loop": loop}, lock_key=2**70, retry_seconds=0.05)
    await _run_briefly(leader, 0.3)
    assert started == []
