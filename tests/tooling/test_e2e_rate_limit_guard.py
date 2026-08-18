"""AC-testing.journeys.6 — E2E rate-limit failures are attributable."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from common.testing.e2e_rate_limit import (
    RateLimitHit,
    fail_report_for_rate_limits,
    record_rate_limit_response,
)

@dataclass
class _Request:
    method: str = "GET"


@dataclass
class _Response:
    status: int
    url: str
    request: _Request


@dataclass
class _Report:
    outcome: str = "passed"
    longrepr: object | None = None
    when: str = "call"
    skipped: bool = False


@dataclass
class _Outcome:
    report: _Report

    def get_result(self) -> _Report:
        return self.report


class _Item:
    nodeid = "tests/e2e/test_example.py::test_journey"

    def get_closest_marker(self, _name: str) -> None:
        return None


class _BrowserContext:
    def __init__(self) -> None:
        self.handlers = {}
        self.closed = False

    def on(self, event: str, handler) -> None:
        self.handlers[event] = handler

    async def close(self) -> None:
        self.closed = True


class _Browser:
    def __init__(self) -> None:
        self.context = _BrowserContext()

    async def new_context(self, **_kwargs) -> _BrowserContext:
        return self.context


@dataclass
class _FixtureRequest:
    node: _Item


def test_AC_testing_journeys_6_rate_limit_hits_fail_the_test_report() -> None:
    hits: list[RateLimitHit] = []
    record_rate_limit_response(
        _Response(
            status=429,
            url=(
                "https://report-staging.example/api/reports/income-statement"
                "?access_token=must-not-appear"
            ),
            request=_Request(),
        ),
        hits,
    )
    report = _Report()

    assert fail_report_for_rate_limits(report, hits) is True
    assert report.outcome == "failed"
    message = str(report.longrepr)
    assert message.startswith("E2E_RATE_LIMIT_EXHAUSTED:")
    assert message.endswith("HTTP 429 GET /api/reports/income-statement")
    assert message.find("access_token") == -1


def test_non_429_responses_do_not_change_a_passing_report() -> None:
    hits: list[RateLimitHit] = []
    record_rate_limit_response(
        _Response(
            status=200,
            url="https://report-staging.example/api/health",
            request=_Request(),
        ),
        hits,
    )
    report = _Report()

    assert fail_report_for_rate_limits(report, hits) is False
    assert report.outcome == "passed"
    assert report.longrepr is None


def test_rate_limit_diagnostic_preserves_an_existing_failure_and_is_bounded() -> None:
    report = _Report(outcome="failed", longrepr="locator was not visible")
    hits = [RateLimitHit(method="POST", path=f"/api/items/{index}") for index in range(9)]

    assert fail_report_for_rate_limits(report, hits) is True
    message = str(report.longrepr)
    assert message.startswith("locator was not visible")
    assert message.find("POST /api/items/0") >= 0
    assert message.find("POST /api/items/4") >= 0
    assert message.find("POST /api/items/5") == -1
    assert message.endswith("4 additional HTTP 429 response(s)")


def test_global_browser_context_wires_the_guard_into_call_and_teardown_reports() -> None:
    from tests.e2e.conftest import context

    async def exercise_context() -> None:
        browser = _Browser()
        request = _FixtureRequest(node=_Item())
        fixture = context.__wrapped__(browser, request)

        assert await anext(fixture) is browser.context
        browser.context.handlers["response"](
            _Response(
                status=429,
                url="https://report-staging.example/api/accounts?token=redacted",
                request=_Request(),
            )
        )

        with pytest.raises(StopAsyncIteration):
            await anext(fixture)
        assert browser.context.closed is True
        assert request.node._e2e_rate_limit_hits == [
            RateLimitHit(method="GET", path="/api/accounts")
        ]

    asyncio.run(exercise_context())


@pytest.mark.parametrize("when", ["call", "teardown"])
def test_rate_limit_guard_fails_call_and_teardown_reports(when: str) -> None:
    from tests.e2e.conftest import pytest_runtest_makereport

    item = _Item()
    item._e2e_rate_limit_hits = [RateLimitHit(method="GET", path="/api/accounts")]
    report = _Report(when=when)
    hook = pytest_runtest_makereport(item, None)

    next(hook)
    with pytest.raises(StopIteration):
        hook.send(_Outcome(report))

    assert report.outcome == "failed"
    assert str(report.longrepr).startswith("E2E_RATE_LIMIT_EXHAUSTED:")
