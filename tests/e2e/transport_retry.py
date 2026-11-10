'AC-testing.e2e-poll-reconnect.1 AC-testing.e2e-poll-reconnect.2'; from __future__ import annotations; import asyncio; from collections.abc import Mapping; from dataclasses import dataclass; import httpx; MAX_CONSECUTIVE_RECONNECTS = 3; RECONNECT_PAUSE_SECONDS = 0.5; _CLOSED_CONNECTION = (httpx.ReadError, httpx.RemoteProtocolError)
@dataclass
class ReconnectCount: value: int = 0
async def get_with_reconnect(client: httpx.AsyncClient, url: str, count: ReconnectCount, *, params: Mapping[str, str] | None=None, pause: float=RECONNECT_PAUSE_SECONDS) -> httpx.Response:
    consecutive = 0
    while True:
        try: return await client.get(url, params=params)
        except _CLOSED_CONNECTION as exc:
            consecutive += 1
            if consecutive > MAX_CONSECUTIVE_RECONNECTS: raise
            count.value += 1; print(f'transport_retry: reconnect {consecutive}/{MAX_CONSECUTIVE_RECONNECTS} (total={count.value}) for {url} after {type(exc).__name__}'); await asyncio.sleep(pause)
