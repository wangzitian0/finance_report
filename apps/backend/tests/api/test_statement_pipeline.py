"""AC19.13: config-gated dispatch for the upload→report pipeline (EPIC-019).

These are the safety-critical seam tests: with Prefect unconfigured the dispatch
MUST fall back to the in-process task (so CI/local/preview run with no Prefect),
and with Prefect configured it MUST submit only serializable params.
"""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.services import statement_pipeline

pytestmark = pytest.mark.no_db


def _dispatch_kwargs() -> dict:
    return {
        "statement_id": uuid4(),
        "filename": "stmt.pdf",
        "institution": None,
        "user_id": uuid4(),
        "account_id": None,
        "file_hash": "hash",
        "storage_key": "uploads/stmt.pdf",
        "content": b"file-bytes",
        "model": None,
        "db": object(),
        "request_id": "req-1",
    }


async def test_AC19_13_1_dispatch_falls_back_to_asyncio_when_prefect_unset(monkeypatch):
    """AC19.13.1: PREFECT_API_URL unset → in-process asyncio fallback, no Prefect."""
    monkeypatch.setattr(statement_pipeline.settings, "prefect_api_url", None)
    seen: dict = {}

    async def fake_background(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(statement_pipeline, "parse_statement_background", fake_background)
    monkeypatch.setattr(statement_pipeline, "create_session_maker_from_db", lambda db: "session-maker")

    task = await statement_pipeline.submit_parse_pipeline(**_dispatch_kwargs())

    assert isinstance(task, asyncio.Task)
    await task
    # In-process path keeps the raw content + a session maker.
    assert seen["filename"] == "stmt.pdf"
    assert seen["content"] == b"file-bytes"
    assert seen["session_maker"] == "session-maker"


async def test_AC19_13_1_dispatch_registers_exception_consumer_on_fallback(monkeypatch):
    """AC19.13.1: fallback tasks retrieve failures after structured telemetry logs them."""
    monkeypatch.setattr(statement_pipeline.settings, "prefect_api_url", None)

    class FakeTask:
        def __init__(self) -> None:
            self.callbacks: list[object] = []

        def add_done_callback(self, callback) -> None:  # noqa: ANN001
            self.callbacks.append(callback)

    task = FakeTask()

    async def fake_background(**_kwargs):
        return None

    def fake_tracking(awaitable, **_kwargs):
        awaitable.close()

        async def noop() -> None:
            return None

        return noop()

    def fake_create_task(coro):
        coro.close()
        return task

    monkeypatch.setattr(statement_pipeline, "parse_statement_background", fake_background)
    monkeypatch.setattr(statement_pipeline, "run_with_async_parse_tracking", fake_tracking)
    monkeypatch.setattr(statement_pipeline, "create_session_maker_from_db", lambda db: "session-maker")
    monkeypatch.setattr(statement_pipeline.asyncio, "create_task", fake_create_task)

    result = await statement_pipeline.submit_parse_pipeline(**_dispatch_kwargs())

    assert result is task
    assert task.callbacks == [statement_pipeline._consume_background_task_exception]


async def test_AC19_13_2_dispatch_submits_serializable_params_to_prefect(monkeypatch):
    """AC19.13.2: PREFECT_API_URL set → submit flow run with serializable params only."""
    monkeypatch.setattr(statement_pipeline.settings, "prefect_api_url", "http://prefect:4200/api")

    run_deployment = AsyncMock(return_value=None)
    fake_deployments = types.ModuleType("prefect.deployments")
    fake_deployments.run_deployment = run_deployment
    monkeypatch.setitem(sys.modules, "prefect", types.ModuleType("prefect"))
    monkeypatch.setitem(sys.modules, "prefect.deployments", fake_deployments)

    kwargs = _dispatch_kwargs()
    task = await statement_pipeline.submit_parse_pipeline(**kwargs)

    assert task is None  # submitted to Prefect, nothing to track in-process
    run_deployment.assert_awaited_once()
    params = run_deployment.await_args.kwargs["parameters"]
    # Serializable only — never the raw bytes or the DB session.
    assert "content" not in params
    assert "db" not in params
    assert "session_maker" not in params
    assert params["statement_id"] == str(kwargs["statement_id"])
    assert params["storage_key"] == "uploads/stmt.pdf"


async def test_AC19_13_1_dispatch_falls_back_when_prefect_client_absent(monkeypatch):
    """AC19.13.1 (fail-soft): PREFECT_API_URL set but the prefect client isn't installed
    (base image) → degrade to in-process. An upload must NEVER 500 on Prefect absence."""
    monkeypatch.setattr(statement_pipeline.settings, "prefect_api_url", "http://prefect:4200/api")
    # Force `from prefect.deployments import run_deployment` to raise ImportError.
    monkeypatch.setitem(sys.modules, "prefect.deployments", None)
    seen: dict = {}

    async def fake_background(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(statement_pipeline, "parse_statement_background", fake_background)
    monkeypatch.setattr(statement_pipeline, "create_session_maker_from_db", lambda db: "session-maker")

    task = await statement_pipeline.submit_parse_pipeline(**_dispatch_kwargs())

    assert isinstance(task, asyncio.Task)  # degraded to in-process, no raise
    await task
    assert seen["content"] == b"file-bytes"  # in-process keeps the raw content
    assert seen["session_maker"] == "session-maker"


async def test_AC19_13_1_dispatch_falls_back_when_prefect_submit_fails(monkeypatch):
    """AC19.13.1 (fail-soft): Prefect installed but the submit fails (server unreachable)
    → degrade to in-process rather than failing the upload."""
    monkeypatch.setattr(statement_pipeline.settings, "prefect_api_url", "http://prefect:4200/api")
    run_deployment = AsyncMock(side_effect=ConnectionError("prefect server unreachable"))
    fake_deployments = types.ModuleType("prefect.deployments")
    fake_deployments.run_deployment = run_deployment
    monkeypatch.setitem(sys.modules, "prefect", types.ModuleType("prefect"))
    monkeypatch.setitem(sys.modules, "prefect.deployments", fake_deployments)
    seen: dict = {}

    async def fake_background(**kwargs):
        seen.update(kwargs)

    monkeypatch.setattr(statement_pipeline, "parse_statement_background", fake_background)
    monkeypatch.setattr(statement_pipeline, "create_session_maker_from_db", lambda db: "session-maker")

    task = await statement_pipeline.submit_parse_pipeline(**_dispatch_kwargs())

    assert isinstance(task, asyncio.Task)  # degraded after the submit raised
    await task
    run_deployment.assert_awaited_once()  # it tried Prefect first, then fell back
    assert seen["content"] == b"file-bytes"
