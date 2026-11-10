"""AC-testing.e2e-poll-reconnect.1 and .2: a journey GET reconnects on a closed connection, bounded and counted (#2610, #2911)."""

import ast
from pathlib import Path
import re

import httpx
import pytest
from tests.e2e import transport_retry
from tests.e2e.transport_retry import (
    MAX_CONSECUTIVE_RECONNECTS,
    ReconnectCount,
    get_with_reconnect,
)

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ENTRYPOINT = ROOT / "apps/backend/scripts/entrypoint.sh"
TWELVE_MONTH_JOURNEY = ROOT / "tests/e2e/test_twelve_month_journey.py"
# The journey has 8 `get_with_reconnect` calls: 2 pinned-deployment probes, the status poll,
# 3 report reads, the statement list and the getter that the fixture review helper uses.
JOURNEY_GET_CALLS = 8
FIXTURE_REVIEW_HELPER = "approve_statement_with_fixture_review"
MIN_KEEPALIVE_SECONDS = 95
_KEEPALIVE_PATTERN = re.compile(r"--timeout-keep-alive(?:=|\s+)(\d+)\b")
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


async def test_AC_testing_e2e_poll_reconnect_1_the_fourth_closed_connection_in_a_row_fails(
    capsys,
):
    handler, calls = _failing_first(10, httpx.ReadError("reset"))
    count = ReconnectCount()
    async with _client(handler) as client:
        with pytest.raises(httpx.ReadError):
            await get_with_reconnect(client, URL, count, pause=0)

    # The AC says three. Compare with the number, not only the constant.
    assert MAX_CONSECUTIVE_RECONNECTS == 3
    assert count.value == 3
    assert calls["n"] == 4
    output = capsys.readouterr().out
    assert "transport_retry: reconnect 3/3 (total=3)" in output


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


def _extract_keepalive_seconds(command_text: str) -> int | None:
    match = _KEEPALIVE_PATTERN.search(command_text)
    if match is None:
        return None
    return int(match.group(1))


def test_AC_testing_e2e_poll_reconnect_1_backend_entrypoint_keepalive_exceeds_proxy_idle_timeout():
    entrypoint_text = BACKEND_ENTRYPOINT.read_text(encoding="utf-8")
    keepalive_seconds = _extract_keepalive_seconds(entrypoint_text)
    assert keepalive_seconds is not None
    assert keepalive_seconds >= MIN_KEEPALIVE_SECONDS
    assert _extract_keepalive_seconds("exec uvicorn src.main:app --port 8000") is None


async def test_AC_testing_e2e_poll_reconnect_2_query_params_reach_the_client_on_every_attempt():
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if len(urls) == 1:
            raise httpx.ReadError("reset")
        return httpx.Response(200, json={"ok": True})

    count = ReconnectCount()
    params = {"as_of_date": "2026-12-31", "currency": "SGD"}
    async with _client(handler) as client:
        response = await get_with_reconnect(client, URL, count, params=params, pause=0)

    assert response.status_code == 200
    assert count.value == 1
    assert urls == [f"{URL}?as_of_date=2026-12-31&currency=SGD"] * 2


def _direct_client_get_lines(source: str) -> list[int]:
    """Return the line of each `client.get(...)` call in the source."""
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "client"
    ]


def _named_calls(source: str, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


def _reconnect_call_count(source: str) -> int:
    return len(_named_calls(source, "get_with_reconnect"))


def _lines_of_calls_without_get_keyword(source: str, name: str) -> list[int]:
    """Return the line of each call to `name` that has no `get=` keyword argument."""
    return [
        call.lineno
        for call in _named_calls(source, name)
        if all(keyword.arg != "get" for keyword in call.keywords)
    ]


def test_AC_testing_e2e_poll_reconnect_2_the_detector_finds_a_direct_get_and_ignores_the_rest():
    source = (
        "async def f(client, reconnects, data):\n"
        "    a = await client.get(url)\n"
        "    b = await client.post(url)\n"
        "    c = await get_with_reconnect(client, url, reconnects)\n"
        "    d = data.get('key')\n"
        "    e = await client.get(url, params={})\n"
        "    g = await approve_statement_with_fixture_review(client, api_url=u)\n"
        "    h = await approve_statement_with_fixture_review(client, get=getter)\n"
    )

    assert _direct_client_get_lines(source) == [2, 6]
    assert _reconnect_call_count(source) == 1
    assert _lines_of_calls_without_get_keyword(source, FIXTURE_REVIEW_HELPER) == [7]


def test_AC_testing_e2e_poll_reconnect_2_the_twelve_month_journey_makes_no_direct_get_call():
    source = TWELVE_MONTH_JOURNEY.read_text(encoding="utf-8")

    assert _direct_client_get_lines(source) == []
    # Guard against an empty pass: the journey must still make all of its GET requests.
    assert _reconnect_call_count(source) == JOURNEY_GET_CALLS
    # The fixture review helper sends 2 GET requests per month. The journey must give it the getter.
    assert len(_named_calls(source, FIXTURE_REVIEW_HELPER)) == 1
    assert _lines_of_calls_without_get_keyword(source, FIXTURE_REVIEW_HELPER) == []
