"""AC-testing.e2e-poll-reconnect.1: bounded reconnect for an idempotent GET poll in an e2e journey (#2610).

A journey polls a status endpoint on one pooled httpx client. The network path
can close an idle connection before the request reaches the application. The
application log shows no entry for that poll, and a new connection succeeds.
httpx raises ReadError or RemoteProtocolError on the closed socket. The helper
retries the GET request on a new connection.

The helper bounds and counts every retry. It retries a closed connection at most
MAX_CONSECUTIVE_RECONNECTS times in a row. Timeouts, refused connections, and
HTTP error statuses are not retried.
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
    """Total reconnects in one journey. Print this count to keep transport retries visible."""

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
        except _CLOSED_CONNECTION as exc:
            consecutive += 1
            if consecutive > MAX_CONSECUTIVE_RECONNECTS:
                raise
            count.value += 1
            print(
                f"transport_retry: reconnect {consecutive}/{MAX_CONSECUTIVE_RECONNECTS} "
                f"(total={count.value}) for {url} after {type(exc).__name__}"
            )
            await asyncio.sleep(pause)
