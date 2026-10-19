"""AC-testing.benchmarks.9: Bench V2 runner pins the explicit review path (#2473).

Since #2405 a high-confidence PDF statement posts by itself and stays "approved".
The runner must (1) turn AI classification and auto-accept off for its user,
(2) accept "approved" as a settled status, and (3) not re-approve an approved statement.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from common.testing.benchmarks import run_financial_scenario_benchmark as runner_module
from common.testing.benchmarks.run_financial_scenario_benchmark import (
    ScenarioBenchmarkRunner,
)

BASE_URL = "http://api.test"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))


def _runner() -> ScenarioBenchmarkRunner:
    return ScenarioBenchmarkRunner(BASE_URL)


def test_AC_testing_benchmarks_9_ephemeral_user_pins_explicit_review_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        seen.append((request.method, request.url.path, body))
        if request.url.path == "/api/auth/register":
            return httpx.Response(201, json={"access_token": "tok", "id": "1"})
        assert request.headers["Authorization"] == "Bearer tok"
        return httpx.Response(
            200,
            json={
                "enable_ai_classification": False,
                "auto_accept_ai_suggestions": False,
                "auto_accept_ai_suggestions_active": False,
            },
        )

    real_client = httpx.Client
    monkeypatch.setattr(
        runner_module.httpx,
        "Client",
        lambda **kwargs: real_client(
            base_url=kwargs["base_url"], transport=httpx.MockTransport(handler)
        ),
    )

    _runner().create_ephemeral_client()

    assert seen[1] == (
        "PATCH",
        "/api/users/me/settings",
        {"enable_ai_classification": False, "auto_accept_ai_suggestions": False},
    )


def test_AC_testing_benchmarks_9_pin_fails_when_setting_is_not_in_effect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "enable_ai_classification": False,
                "auto_accept_ai_suggestions": False,
                "auto_accept_ai_suggestions_active": True,
            },
        )

    with pytest.raises(RuntimeError, match="not in effect"):
        _runner().pin_explicit_review_path(_client(handler))


def test_AC_testing_benchmarks_9_pin_fails_on_http_error() -> None:
    client = _client(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(RuntimeError, match="500"):
        _runner().pin_explicit_review_path(client)


@pytest.mark.parametrize("status", ["parsed", "approved"])
def test_AC_testing_benchmarks_9_waiter_accepts_parsed_and_approved(
    status: str,
) -> None:
    client = _client(
        lambda request: httpx.Response(200, json={"id": "s1", "status": status})
    )
    data = _runner().wait_for_statement_parsed(
        client, "s1", max_wait_seconds=1, poll_interval=0
    )
    assert data["status"] == status


def test_AC_testing_benchmarks_9_waiter_still_times_out_on_unsettled_status() -> None:
    client = _client(
        lambda request: httpx.Response(200, json={"id": "s1", "status": "uploaded"})
    )
    with pytest.raises(TimeoutError):
        _runner().wait_for_statement_parsed(
            client, "s1", max_wait_seconds=0.05, poll_interval=0.01
        )


def test_AC_testing_benchmarks_9_waiter_raises_on_rejected() -> None:
    client = _client(
        lambda request: httpx.Response(
            200, json={"id": "s1", "status": "rejected", "validation_error": "bad"}
        )
    )
    with pytest.raises(RuntimeError, match="rejected"):
        _runner().wait_for_statement_parsed(client, "s1", poll_interval=0)


def test_AC_testing_benchmarks_9_approve_is_idempotent_for_approved_statement() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json={"id": "s1", "status": "approved"})

    result = _runner().approve_statement(_client(handler), "s1")

    assert result["status"] == "approved"
    assert ("POST", "/api/statements/s1/review/approve") not in calls


def test_AC_testing_benchmarks_9_approve_posts_for_parsed_statement() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"id": "s1", "status": "parsed"})
        return httpx.Response(200, json={"id": "s1", "status": "approved"})

    result = _runner().approve_statement(_client(handler), "s1")

    assert result["status"] == "approved"
    assert ("POST", "/api/statements/s1/review/approve") in calls
