"""Shared E2E statement polling helper that waits for active async classification runs (#1600)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

_ACTIVE_RUN_STATES = frozenset({"requested", "running"})


async def has_active_classify_run(
    client: httpx.AsyncClient,
    api_url: Callable[[str], str],
    statement_id: str,
) -> tuple[bool, dict[str, Any] | None]:
    """Return whether ``statement_id`` has a queued or running classify run plus the newest classify run."""
    response = await client.get(api_url(f"/statements/{statement_id}/runs"))
    assert response.status_code == 200, (
        f"GET /statements/{statement_id}/runs failed: {response.status_code} {response.text}"
    )
    runs = response.json().get("items") or []
    classify_runs = [run for run in runs if run.get("kind") == "classify"]
    active = any(run.get("state") in _ACTIVE_RUN_STATES for run in classify_runs)
    return active, (classify_runs[-1] if classify_runs else None)


async def wait_for_auto_approved_statement(
    client: httpx.AsyncClient,
    *,
    api_url: Callable[[str], str],
    statement_id: str,
    timeout_ms: int,
    poll_seconds: float,
    fetch_entries: Callable[
        [dict[str, Any]], Awaitable[tuple[bool, list[dict[str, Any]]]]
    ],
    terminal_fail_statuses: frozenset[str] = frozenset({"rejected"}),
    failure_prefix: str = "the statement did not post by itself",
    timeout_message: Callable[[dict[str, Any], list[dict[str, Any]]], str]
    | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Poll until an auto-approve candidate reaches ``approved`` with expected entries, waiting through active classify runs."""
    deadline = time.monotonic() + timeout_ms / 1000
    statement: dict[str, Any] = {}
    entries: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        response = await client.get(api_url(f"/statements/{statement_id}"))
        assert response.status_code == 200, (
            f"GET /statements/{statement_id} failed: {response.status_code} {response.text}"
        )
        statement = response.json()
        status = statement["status"]
        if status in terminal_fail_statuses:
            pytest.fail(
                f"{failure_prefix}: status={status} confidence_score={statement.get('confidence_score')} "
                f"balance_validated={statement.get('balance_validated')} validation_error={statement.get('validation_error')!r}"
            )
        if status == "parsed":
            active, latest_classify = await has_active_classify_run(
                client, api_url, statement_id
            )
            if not active:
                pytest.fail(
                    f"{failure_prefix}: status={status} confidence_score={statement.get('confidence_score')} "
                    f"balance_validated={statement.get('balance_validated')} validation_error={statement.get('validation_error')!r} "
                    f"classify_run={latest_classify!r}"
                )
        elif status == "approved":
            ready, entries = await fetch_entries(statement)
            if ready:
                return statement, entries
        await asyncio.sleep(poll_seconds)
    if timeout_message is not None:
        pytest.fail(timeout_message(statement, entries))
    pytest.fail(
        f"statement {statement_id} did not post every row within {timeout_ms}ms: "
        f"status={statement.get('status')} entries={len(entries)}"
    )
