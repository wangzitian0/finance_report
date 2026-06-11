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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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
