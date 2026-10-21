"""Keep the fail-fast startup of the backend with more than one uvicorn worker (#2583 S5).

With one worker, a startup failure ends the uvicorn process with exit code 3,
so the container stops and its restart policy applies. With more than one
worker, the uvicorn supervisor starts a new worker each time a worker exits,
also when its startup fails. A failed startup then repeats every 0.5 s and the
container never stops.

:func:`stop_worker_supervisor` sends SIGTERM to the supervisor when this
process is a uvicorn worker. The supervisor then stops all workers and exits.
uvicorn starts its workers with ``multiprocessing`` (spawn), so a worker has a
``multiprocessing.parent_process()``. A single uvicorn process has none.

The ``uvicorn --reload`` server process also has a multiprocessing parent: the
reloader. The reloader must stay alive after a failed startup, so that it can
reload on the next file save. So the helper acts only when ``WEB_CONCURRENCY``
asks for more than one worker; uvicorn ignores the worker count with ``--reload``.
"""

from __future__ import annotations

import multiprocessing
import os
import signal

from src.observability import get_logger

logger = get_logger(__name__)


def stop_worker_supervisor() -> bool:
    """Send SIGTERM to the uvicorn supervisor when this process is one of its workers.

    Returns True when a signal was sent. Returns False in a single uvicorn process,
    under ``uvicorn --reload``, and when the parent process is not alive.
    """
    if _configured_workers() < 2:
        return False
    parent = multiprocessing.parent_process()
    if parent is None or parent.pid is None or not parent.is_alive():
        return False
    logger.critical("worker_startup_failed.stopping_supervisor", supervisor_pid=parent.pid, worker_pid=os.getpid())
    os.kill(parent.pid, signal.SIGTERM)
    return True


def _configured_workers() -> int:
    """Return the uvicorn worker count from ``WEB_CONCURRENCY`` (1 when it is not set or not a number)."""
    try:
        return int(os.environ.get("WEB_CONCURRENCY", "1"))
    except ValueError:
        return 1
