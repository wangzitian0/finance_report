"""A minimal ASGI app for the worker-concurrency test (AC-runtime.workers.2).

``GET /cheap`` answers at once. ``GET /cpu?ms=N`` holds the event loop of its
worker for N milliseconds with pure Python work, as a CPU-bound report request
does. Each response body is the process id of the worker that served it.
"""

from __future__ import annotations

import os
import time
from urllib.parse import parse_qs


async def app(scope, receive, send) -> None:  # noqa: ANN001 - raw ASGI callable
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    if scope["path"] == "/cpu":
        milliseconds = int(parse_qs(scope["query_string"].decode()).get("ms", ["1000"])[0])
        deadline = time.perf_counter() + milliseconds / 1000
        counter = 0
        while time.perf_counter() < deadline:
            counter += 1
    body = str(os.getpid()).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": body})


async def failing_app(scope, receive, send) -> None:  # noqa: ANN001 - raw ASGI callable
    """An app whose startup fails, as a failed ``Bootloader.validate`` does.

    With ``PROBE_STOP_SUPERVISOR=1`` the startup first calls the production helper
    ``stop_worker_supervisor``, as ``src.main.lifespan`` does on a startup failure.
    """
    if scope["type"] != "lifespan":
        return
    await receive()
    if os.environ.get("PROBE_STOP_SUPERVISOR") == "1":
        from src.runtime.extension.worker_process import stop_worker_supervisor

        stop_worker_supervisor()
    await send({"type": "lifespan.startup.failed", "message": "probe startup failure"})
