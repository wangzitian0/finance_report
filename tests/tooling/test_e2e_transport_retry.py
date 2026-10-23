"""AC-testing.e2e-poll-reconnect.1: a journey poll reconnects on a closed connection, bounded and counted (#2610)."""

import httpx
import pytest
from tests.e2e import transport_retry
from tests.e2e.transport_retry import (
    MAX_CONSECUTIVE_RECONNECTS,
    ReconnectCount,
    get_with_reconnect,
)

URL = "https://example.test/statements/1"


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _failing_first(failures: int, exc: Exception):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= failures:
            raise exc
        return httpx.Response(200, json={"status": "parsed"})

    return handler, calls


@pytest.mark.parametrize(
    "exc", [httpx.ReadError("reset"), httpx.RemoteProtocolError("closed")]
)
async def test_AC_testing_e2e_poll_reconnect_1_a_closed_connection_is_retried_and_counted(
    exc,
):
    handler, calls = _failing_first(2, exc)
    count = ReconnectCount()
    async with _client(handler) as client:
        response = await get_with_reconnect(client, URL, count, pause=0)

    assert response.json() == {"status": "parsed"}
    assert count.value == 2
    assert calls["n"] == 3


async def test_AC_testing_e2e_poll_reconnect_1_the_fourth_closed_connection_in_a_row_fails():
    handler, calls = _failing_first(10, httpx.ReadError("reset"))
    count = ReconnectCount()
    async with _client(handler) as client:
        with pytest.raises(httpx.ReadError):
            await get_with_reconnect(client, URL, count, pause=0)

    # The AC says three. Compare with the number, not only the constant.
    assert MAX_CONSECUTIVE_RECONNECTS == 3
    assert count.value == 3
    assert calls["n"] == 4


async def test_AC_testing_e2e_poll_reconnect_1_the_consecutive_limit_resets_after_a_success():
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] % 2:  # every first attempt of a poll fails, every second succeeds
            raise httpx.ReadError("reset")
        return httpx.Response(200, json={"n": state["n"]})

    count = ReconnectCount()
    async with _client(handler) as client:
        for _ in range(MAX_CONSECUTIVE_RECONNECTS + 2):
            await get_with_reconnect(client, URL, count, pause=0)

    assert count.value == MAX_CONSECUTIVE_RECONNECTS + 2


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("refused"),
        httpx.ConnectTimeout("no route"),
    ],
)
async def test_AC_testing_e2e_poll_reconnect_1_a_timeout_or_refused_connection_is_never_retried(
    exc,
):
    handler, calls = _failing_first(10, exc)
    count = ReconnectCount()
    async with _client(handler) as client:
        with pytest.raises(type(exc)):
            await get_with_reconnect(client, URL, count, pause=0)

    assert count.value == 0
    assert calls["n"] == 1


async def test_AC_testing_e2e_poll_reconnect_1_an_error_status_is_returned_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(502, text="bad gateway")

    count = ReconnectCount()
    async with _client(handler) as client:
        response = await get_with_reconnect(client, URL, count, pause=0)

    assert response.status_code == 502
    assert count.value == 0
    assert calls["n"] == 1


def test_AC_testing_e2e_poll_reconnect_1_the_pause_default_is_positive():
    assert transport_retry.RECONNECT_PAUSE_SECONDS > 0
