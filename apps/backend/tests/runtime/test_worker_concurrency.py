"""AC-runtime.workers.2 / .3: the backend image runs more than one uvicorn worker (#2583 S5).

One uvicorn process has one event loop. A CPU-bound request holds that loop, so
every other request waits. The image sets ``WEB_CONCURRENCY``; uvicorn reads it
when the command line has no ``--workers`` flag. The production command
(``scripts/entrypoint.sh`` and the infra2 compose entrypoint) has no such flag.
"""

from __future__ import annotations

import http.client
import os
import re
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from src.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[2]
DOCKERFILE = BACKEND_DIR / "Dockerfile"
ENTRYPOINT = BACKEND_DIR / "scripts" / "entrypoint.sh"
PREFECT_ENTRYPOINT = BACKEND_DIR / "scripts" / "prefect_worker_entrypoint.sh"
PROBE_DIR = Path(__file__).resolve().parent

#: uvicorn runs one worker when ``WEB_CONCURRENCY`` is not set.
UVICORN_DEFAULT_WORKERS = 1
CPU_REQUEST_MS = 2000
#: The median cheap GET during the CPU-bound GET stays below this value.
CHEAP_MEDIAN_LIMIT_MS = 50.0
#: Every cheap GET stays below this value. A cheap GET that waits for the CPU-bound
#: GET takes at least 600 ms here: the last one starts 1.3 s into the 2 s request.
#: The gap between 250 ms and 600 ms absorbs scheduler delay on a loaded CI runner.
CHEAP_MAX_LIMIT_MS = 250.0


def image_web_concurrency() -> int:
    """Return the worker count that the backend image gives uvicorn."""
    match = re.search(r"^ENV WEB_CONCURRENCY=(\d+)\s*$", DOCKERFILE.read_text(), flags=re.MULTILINE)
    return int(match.group(1)) if match else UVICORN_DEFAULT_WORKERS


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get(port: int, path: str) -> tuple[float, str]:
    """GET ``path`` on a new connection; return (milliseconds, response body)."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    started = time.perf_counter()
    connection.request("GET", path, headers={"Connection": "close"})
    response = connection.getresponse()
    body = response.read().decode()
    elapsed_ms = (time.perf_counter() - started) * 1000
    connection.close()
    assert response.status == 200, body
    return elapsed_ms, body


class UvicornServer:
    """A uvicorn subprocess started with the production command shape (no ``--workers`` flag)."""

    def __init__(
        self, workers: int, app: str = "worker_probe_app:app", extra_env: dict[str, str] | None = None
    ) -> None:
        self.workers = workers
        self.port = _free_port()
        self._started = 0
        self._failed = 0
        self._lines: list[str] = []
        self._ready = threading.Event()
        env = {key: value for key, value in os.environ.items() if key != "WEB_CONCURRENCY"}
        env["WEB_CONCURRENCY"] = str(workers)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(BACKEND_DIR), env.get("PYTHONPATH")]))
        env.update(extra_env or {})
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                app,
                "--app-dir",
                str(PROBE_DIR),
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            cwd=BACKEND_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        threading.Thread(target=self._read_log, daemon=True).start()

    def _read_log(self) -> None:
        # One worker binds the socket after its startup; a supervisor binds it before
        # it spawns the workers. Ready means: socket bound and every worker started.
        assert self.process.stderr is not None
        bound = False
        for line in self.process.stderr:
            self._lines.append(line.rstrip())
            bound = bound or "Uvicorn running on" in line
            if "Application startup complete" in line:
                self._started += 1
            if "Application startup failed" in line:
                self._failed += 1
            if bound and self._started >= self.workers:
                self._ready.set()

    def wait_ready(self, timeout: float = 30.0) -> None:
        assert self._ready.wait(timeout), "uvicorn workers did not start:\n" + "\n".join(self._lines[-20:])

    def startup_failures(self) -> int:
        """Return how many worker startups failed so far."""
        return self._failed

    def log_tail(self) -> str:
        return "\n".join(self._lines[-20:])

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


@pytest.mark.integration
@pytest.mark.no_db
def test_AC_runtime_workers_2_cheap_get_stays_fast_while_a_cpu_bound_get_runs() -> None:
    """AC-runtime.workers.2: with the image worker count, a cheap GET takes < 50 ms during a CPU-bound GET.

    The test starts uvicorn as the image does: ``WEB_CONCURRENCY`` from the
    Dockerfile and no ``--workers`` flag. One request holds the event loop of
    one worker for 2 s. Six cheap requests on new connections during that time
    must go to another worker process. Their median must be below 50 ms, and
    each must be below 250 ms, far below the 600 ms a blocked request waits.
    """
    server = UvicornServer(image_web_concurrency())
    try:
        server.wait_ready()
        heavy: dict[str, object] = {}

        def run_heavy() -> None:
            try:
                heavy["ms"], heavy["pid"] = _get(server.port, f"/cpu?ms={CPU_REQUEST_MS}")
            except Exception as exc:  # noqa: BLE001 - reported by the assertion below
                heavy["error"] = repr(exc)

        heavy_thread = threading.Thread(target=run_heavy)
        heavy_thread.start()
        time.sleep(0.3)
        cheap = []
        for _ in range(6):
            cheap.append(_get(server.port, "/cheap"))
            time.sleep(0.2)
        heavy_thread.join(timeout=30)

        assert "error" not in heavy, heavy
        assert float(heavy["ms"]) >= CPU_REQUEST_MS * 0.95, f"the CPU-bound request took {heavy['ms']} ms"
        latencies = sorted(round(ms, 1) for ms, _pid in cheap)
        context = f"workers={server.workers} cheap_ms={latencies} cheap_pids={[pid for _ms, pid in cheap]} heavy_pid={heavy['pid']}"
        assert all(pid != heavy["pid"] for _ms, pid in cheap), f"a cheap GET went to the busy worker: {context}"
        assert statistics.median(latencies) < CHEAP_MEDIAN_LIMIT_MS, context
        assert latencies[-1] < CHEAP_MAX_LIMIT_MS, context
    finally:
        server.stop()


@pytest.mark.integration
@pytest.mark.no_db
def test_AC_runtime_workers_4_a_failed_worker_startup_stops_the_supervisor() -> None:
    """AC-runtime.workers.4: a worker startup failure ends the uvicorn process, as with one worker.

    Without the helper, the supervisor starts a new worker after each failed
    startup, and the process does not end. With ``stop_worker_supervisor`` in the
    failed startup (as in ``src.main.lifespan``), the supervisor ends.
    """
    workers = image_web_concurrency()
    restart_loop = UvicornServer(workers, app="worker_probe_app:failing_app")
    try:
        deadline = time.monotonic() + 30
        while restart_loop.startup_failures() <= workers and time.monotonic() < deadline:
            time.sleep(0.2)
        assert restart_loop.startup_failures() > workers, restart_loop.log_tail()
        assert restart_loop.process.poll() is None, "without the helper the supervisor keeps restarting workers"
    finally:
        restart_loop.stop()

    fail_fast = UvicornServer(workers, app="worker_probe_app:failing_app", extra_env={"PROBE_STOP_SUPERVISOR": "1"})
    try:
        fail_fast.process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pytest.fail("the supervisor did not stop after a failed worker startup:\n" + fail_fast.log_tail())
    finally:
        fail_fast.stop()


@pytest.mark.no_db
async def test_AC_runtime_workers_4_lifespan_startup_failure_stops_the_supervisor(monkeypatch) -> None:
    """AC-runtime.workers.4: a failed boot validation in the lifespan calls ``stop_worker_supervisor``."""
    import src.main as main_module

    calls: list[str] = []

    async def validate_fails(*_args: object, **_kwargs: object) -> bool:
        raise SystemExit(1)

    monkeypatch.setattr(main_module.Bootloader, "validate", validate_fails)
    monkeypatch.setattr(main_module, "stop_worker_supervisor", lambda: calls.append("stop") or True)
    with pytest.raises(SystemExit):
        async with main_module.lifespan(main_module.app):
            pytest.fail("the lifespan started after a failed boot validation")
    assert calls == ["stop"]


@pytest.mark.no_db
async def test_AC_runtime_workers_4_lifespan_shutdown_is_bounded(monkeypatch) -> None:
    """AC-runtime.workers.4: a leader that does not stop cannot hold the lifespan shutdown."""
    import asyncio

    import src.main as main_module

    async def validate_ok(*_args: object, **_kwargs: object) -> bool:
        return True

    async def run_forever(_self: object, _stop_event: asyncio.Event) -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(main_module.Bootloader, "validate", validate_ok)
    monkeypatch.setattr(main_module.BackgroundLeader, "run", run_forever)
    monkeypatch.setattr(main_module, "LEADER_SHUTDOWN_SECONDS", 0.2)
    lifespan = main_module.lifespan(main_module.app)
    await lifespan.__aenter__()
    started = time.monotonic()
    await lifespan.__aexit__(None, None, None)
    assert time.monotonic() - started < 2.0


@pytest.mark.no_db
def test_AC_runtime_workers_4_stop_worker_supervisor_signals_only_a_worker(monkeypatch) -> None:
    """AC-runtime.workers.4: the helper sends SIGTERM to the parent of a worker, and nothing in a single process."""
    import multiprocessing

    from src.runtime import stop_worker_supervisor

    kills: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: kills.append((pid, sig)))

    monkeypatch.setattr(multiprocessing, "parent_process", lambda: None)
    assert stop_worker_supervisor() is False
    assert kills == []

    class Supervisor:
        pid = 4242

    monkeypatch.setattr(multiprocessing, "parent_process", lambda: Supervisor())
    assert stop_worker_supervisor() is True
    assert kills == [(4242, signal.SIGTERM)]


# ── AC-runtime.workers.3: the worker count fits the memory and connection budgets ──
#
# The values below are measurements and deployment facts. The app does not
# read infra2 source (AC-runtime.deploy-request.4), so this test states them.
#: infra2 ``finance_report/finance_report/10.app/compose.yaml``: backend ``mem_limit: 768m``.
BACKEND_MEM_LIMIT_MB = 768
#: Peak RSS of one worker of the image, measured at 960 transactions after two parallel
#: ``GET /reports/package`` calls in one worker (325 MB). Idle: 264-289 MB (#2583 S5 PR).
WORKER_RSS_MB = 325
#: RSS of the uvicorn supervisor (22-24 MB) plus the multiprocessing resource tracker (8-10 MB).
SUPERVISOR_RSS_MB = 34
#: Memory that stays free for ledger growth beyond the measured 960 transactions.
HEADROOM_MB = 64
#: ``postgres:16-alpine`` defaults; the infra2 postgres compose sets no override.
POSTGRES_MAX_CONNECTIONS = 100
POSTGRES_SUPERUSER_RESERVED = 3
#: Connections outside the backend workers: one migration session, and one prefect-worker
#: flow run with its own pool (same image, same pool settings).
OTHER_SESSIONS = 1


@pytest.mark.no_db
def test_AC_runtime_workers_3_worker_count_fits_memory_and_connection_budgets() -> None:
    """AC-runtime.workers.3: N workers fit the 768 MB limit and the Postgres connection limit."""
    workers = image_web_concurrency()
    assert workers >= 2, "the image must run more than one worker (#2583 S5)"

    memory_mb = workers * WORKER_RSS_MB + SUPERVISOR_RSS_MB + HEADROOM_MB
    assert memory_mb <= BACKEND_MEM_LIMIT_MB, f"{workers} workers need {memory_mb} MB"

    defaults = Settings.model_fields
    pool = int(defaults["db_pool_size"].default) + int(defaults["db_pool_max_overflow"].default)
    # Each worker: its pool plus one leader-lock session. The prefect worker: one pool.
    connections = workers * (pool + 1) + pool + OTHER_SESSIONS
    budget = POSTGRES_MAX_CONNECTIONS - POSTGRES_SUPERUSER_RESERVED
    assert connections <= budget, f"{workers} workers can open {connections} connections; the budget is {budget}"


@pytest.mark.no_db
def test_AC_runtime_workers_3_start_commands_let_web_concurrency_decide() -> None:
    """AC-runtime.workers.3: the API start command lets ``WEB_CONCURRENCY`` decide; the Prefect worker unsets it.

    The API command has no ``--workers`` flag. The Prefect worker container runs
    the same image but no API server, so its entrypoint unsets the variable
    before it starts Prefect.
    """
    exec_lines = [line for line in ENTRYPOINT.read_text().splitlines() if line.startswith("exec uvicorn")]
    assert exec_lines == ["exec uvicorn src.main:app --host 0.0.0.0 --port 8000"]

    prefect_entrypoint = PREFECT_ENTRYPOINT.read_text()
    assert "\nunset WEB_CONCURRENCY\n" in prefect_entrypoint
    assert prefect_entrypoint.index("unset WEB_CONCURRENCY") < prefect_entrypoint.index("exec prefect worker start")
