"""Bounded reconnect for an idempotent GET poll in an e2e journey (#2610).

A journey polls a status endpoint on one pooled httpx client. The deployed path
(runner, tunnel, proxy) sometimes closes a reused connection before the request
reaches the app: the app log has no line for that poll, and a new connection works
a second later. httpx raises ReadError or RemoteProtocolError. A browser retries
such a GET on a new connection, so the journey does too.

The retry is bounded and counted. A closed connection is retried at most
MAX_CONSECUTIVE_RECONNECTS times in a row. A timeout, a refused connection and an
HTTP error status are never retried: the app is down or wrong in those cases.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

MAX_CONSECUTIVE_RECONNECTS = 3
RECONNECT_PAUSE_SECONDS = 0.5
_CLOSED_CONNECTION = (httpx.ReadError, httpx.RemoteProtocolError)


@dataclass
class ReconnectCount:
    """Total reconnects in one journey. Print it, so a flaky path stays visible."""

    value: int = 0


async def get_with_reconnect(
    client: httpx.AsyncClient,
    url: str,
    count: ReconnectCount,
    *,
    pause: float = RECONNECT_PAUSE_SECONDS,
) -> httpx.Response:
    consecutive = 0
    while True:
        try:
            return await client.get(url)
        except _CLOSED_CONNECTION:
            consecutive += 1
            if consecutive > MAX_CONSECUTIVE_RECONNECTS:
                raise
            count.value += 1
            await asyncio.sleep(pause)
