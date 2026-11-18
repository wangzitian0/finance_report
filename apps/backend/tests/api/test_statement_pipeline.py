from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.extraction import ParseJob
from src.extraction.extension import statement_flow, statement_pipeline

pytestmark = pytest.mark.no_db


def _dispatch_kwargs():
    return {
        "job": ParseJob(
            statement_id=uuid4(),
            run_id=uuid4(),
            filename="stmt.pdf",
            institution=None,
            user_id=uuid4(),
            account_id=None,
            file_hash="hash",
            storage_key="uploads/stmt.pdf",
            model=None,
            request_id="req-1",
        ),
        "content": b"file-bytes",
        "db": object(),
    }


def _compose_fake_use_case(seen: dict):
    def compose(*, session_maker):
        seen["session_maker"] = session_maker

        class FakeUseCase:
            async def execute(self, job, *, content=None):
                seen["job"], seen["content"] = job, content

        return FakeUseCase()

    return compose


@pytest.mark.parametrize("prefect_mode", ["unset", "absent", "submit_fails"])
async def test_AC19_13_1_dispatch_falls_back_to_asyncio(monkeypatch, prefect_mode):
    seen: dict = {}
    monkeypatch.setattr(statement_pipeline, "compose_statement_ingestion_use_case", _compose_fake_use_case(seen))
    monkeypatch.setattr(statement_pipeline, "create_session_maker_from_db", lambda db: "session-maker")
    run_dep = None
    if prefect_mode == "unset":
        monkeypatch.setattr(statement_pipeline.settings, "prefect_api_url", None)
    else:
        monkeypatch.setattr(statement_pipeline.settings, "prefect_api_url", "http://prefect:4200/api")
        if prefect_mode == "absent":
            monkeypatch.setitem(sys.modules, "prefect.deployments", None)
        else:
            run_dep = AsyncMock(side_effect=ConnectionError("unreachable"))
            fake = types.ModuleType("prefect.deployments")
            fake.run_deployment = run_dep
            monkeypatch.setitem(sys.modules, "prefect", types.ModuleType("prefect"))
            monkeypatch.setitem(sys.modules, "prefect.deployments", fake)
    task = await statement_pipeline.submit_parse_pipeline(**_dispatch_kwargs())
    assert isinstance(task, asyncio.Task)
    await task
    assert (seen["job"].filename, seen["content"], seen["session_maker"]) == (
        "stmt.pdf",
        b"file-bytes",
        "session-maker",
    )
    if run_dep is not None:
        run_dep.assert_awaited_once()


async def test_AC19_13_1_dispatch_registers_exception_consumer_on_fallback(monkeypatch):
    monkeypatch.setattr(statement_pipeline.settings, "prefect_api_url", None)

    class FakeTask:
        callbacks: list[object] = []

        def add_done_callback(self, cb) -> None:
            self.callbacks.append(cb)

    task = FakeTask()
    monkeypatch.setattr(statement_pipeline, "compose_statement_ingestion_use_case", _compose_fake_use_case({}))
    monkeypatch.setattr(
        statement_pipeline, "run_with_async_parse_tracking", lambda aw, **_kw: (aw.close(), asyncio.sleep(0))[1]
    )
    monkeypatch.setattr(statement_pipeline, "create_session_maker_from_db", lambda db: "session-maker")
    monkeypatch.setattr(statement_pipeline.asyncio, "create_task", lambda coro: (coro.close(), task)[1])
    assert await statement_pipeline.submit_parse_pipeline(**_dispatch_kwargs()) is task
    assert task.callbacks == [statement_pipeline._consume_background_task_exception]


async def test_AC19_13_2_dispatch_submits_serializable_params_and_worker_rehydrates(monkeypatch):
    monkeypatch.setattr(statement_pipeline.settings, "prefect_api_url", "http://prefect:4200/api")
    run_dep = AsyncMock(return_value=None)
    fake = types.ModuleType("prefect.deployments")
    fake.run_deployment = run_dep
    monkeypatch.setitem(sys.modules, "prefect", types.ModuleType("prefect"))
    monkeypatch.setitem(sys.modules, "prefect.deployments", fake)
    kwargs = _dispatch_kwargs()
    assert await statement_pipeline.submit_parse_pipeline(**kwargs) is None
    params = run_dep.await_args.kwargs["parameters"]
    assert (
        not ({"content", "db", "session_maker"} & params.keys()) and params["job"] == kwargs["job"].to_prefect_params()
    )

    seen: dict = {}
    monkeypatch.setattr(statement_flow, "compose_statement_ingestion_use_case", _compose_fake_use_case(seen))
    monkeypatch.setattr(statement_flow, "run_with_async_parse_tracking", lambda aw, **_kw: aw)
    await statement_flow.parse_statement_flow.fn(job=kwargs["job"].to_prefect_params())
    assert (seen["job"], seen["content"], seen["session_maker"]) == (
        kwargs["job"],
        None,
        statement_flow.async_session_maker,
    )
