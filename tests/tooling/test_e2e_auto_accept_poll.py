"""Regression tests for async classification polling in E2E auto-accept helpers (#1600)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from _pytest.outcomes import Failed

from tests.e2e.auto_accept_poll import wait_for_auto_approved_statement

ROOT = Path(__file__).resolve().parents[2]


def _make_client(steps: list[tuple[dict, list[dict]]]) -> httpx.AsyncClient:
    """Build a mock AsyncClient returning a sequence of (statement, runs) poll payloads."""
    state = {"idx": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/statements/stmt-1":
            idx = min(state["idx"], len(steps) - 1)
            payload = steps[idx][0]
            if payload["status"] != "parsed":
                state["idx"] += 1
            return httpx.Response(200, json=payload)
        if request.url.path == "/api/statements/stmt-1/runs":
            idx = min(state["idx"], len(steps) - 1)
            runs = steps[idx][1]
            state["idx"] += 1
            return httpx.Response(200, json={"items": runs, "total": len(runs)})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_waits_while_parsed_has_active_classify_run() -> None:
    steps = [
        ({"id": "stmt-1", "status": "parsing"}, []),
        (
            {"id": "stmt-1", "status": "parsed"},
            [{"kind": "classify", "state": "requested"}],
        ),
        (
            {"id": "stmt-1", "status": "parsed"},
            [{"kind": "classify", "state": "running"}],
        ),
        ({"id": "stmt-1", "status": "approved", "transactions": [{"id": "t1"}]}, []),
    ]

    async def _run() -> tuple[dict, list[dict]]:
        async with _make_client(steps) as client:
            return await wait_for_auto_approved_statement(
                client,
                api_url=lambda p: f"http://test.local/api{p}",
                statement_id="stmt-1",
                timeout_ms=5000,
                poll_seconds=0.0,
                fetch_entries=lambda _st: asyncio.sleep(
                    0, result=(True, [{"id": "je-1"}])
                ),
            )

    stmt, entries = asyncio.run(_run())
    assert stmt["status"] == "approved"
    assert entries == [{"id": "je-1"}]


@pytest.mark.parametrize(
    ("runs", "expected_fragment"),
    [
        (
            [{"kind": "classify", "state": "failed", "error_code": "classify_timeout"}],
            "classify_timeout",
        ),
        ([], "classify_run=None"),
    ],
)
def test_fails_immediately_when_parsed_has_no_active_classify_run(
    runs: list[dict], expected_fragment: str
) -> None:
    steps = [({"id": "stmt-1", "status": "parsed", "confidence_score": 95}, runs)]

    async def _run() -> None:
        async with _make_client(steps) as client:
            await wait_for_auto_approved_statement(
                client,
                api_url=lambda p: f"http://test.local/api{p}",
                statement_id="stmt-1",
                timeout_ms=5000,
                poll_seconds=0.0,
                fetch_entries=lambda _st: asyncio.sleep(0, result=(True, [])),
            )

    with pytest.raises(Failed, match=expected_fragment):
        asyncio.run(_run())


def test_fails_immediately_on_terminal_failure_status() -> None:
    steps = [
        ({"id": "stmt-1", "status": "rejected", "validation_error": "bad balance"}, [])
    ]

    async def _run() -> None:
        async with _make_client(steps) as client:
            await wait_for_auto_approved_statement(
                client,
                api_url=lambda p: f"http://test.local/api{p}",
                statement_id="stmt-1",
                timeout_ms=5000,
                poll_seconds=0.0,
                fetch_entries=lambda _st: asyncio.sleep(0, result=(True, [])),
            )

    with pytest.raises(Failed, match="status=rejected"):
        asyncio.run(_run())


def test_auto_accept_e2e_journeys_use_shared_classify_aware_poller() -> None:
    for rel in (
        "tests/e2e/test_zero_click_statement_journey.py",
        "tests/e2e/test_stage1_routing_journey.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "wait_for_auto_approved_statement" in text, (
            f"{rel} must use wait_for_auto_approved_statement"
        )
        assert "status in ('parsed'" not in text, (
            f"{rel} must not fail immediately on status == 'parsed'"
        )
