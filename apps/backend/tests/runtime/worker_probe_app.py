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
