"""Tests for Prefect deployment registration and fail-closed statement pipeline dispatch."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.extraction.base.types import ParseJob
from src.extraction.extension import statement_pipeline

pytestmark = pytest.mark.no_db


def _parse_job() -> ParseJob:
    return ParseJob(
        statement_id=uuid4(),
        run_id=uuid4(),
        filename="stmt.pdf",
        institution="DBS",
        user_id=uuid4(),
        account_id=None,
        file_hash="abc",
        storage_key="statements/stmt.pdf",
        request_id="req-1",
    )


async def test_prefect_api_url_fails_closed_for_parse_and_classify(monkeypatch: pytest.MonkeyPatch) -> None:
    """When PREFECT_API_URL is set, Prefect dispatch errors must fail closed instead of falling back in-process."""
    import prefect.deployments as prefect_deployments

    monkeypatch.setattr(statement_pipeline.settings, "prefect_api_url", "http://prefect:4200/api")
    monkeypatch.setattr(prefect_deployments, "run_deployment", AsyncMock(side_effect=RuntimeError("prefect down")))

    factory = MagicMock()
    with pytest.raises(RuntimeError, match="prefect down"):
        await statement_pipeline.submit_parse_pipeline(job=_parse_job(), content=b"pdf", use_case_factory=factory)
    factory.assert_not_called()

    create_task_called = False
    orig_create_task = asyncio.create_task

    def guarded_create_task(coro, *args, **kwargs):
        nonlocal create_task_called
        create_task_called = True
        return orig_create_task(coro, *args, **kwargs)

    monkeypatch.setattr(asyncio, "create_task", guarded_create_task)
    with pytest.raises(RuntimeError, match="prefect down"):
        await statement_pipeline.submit_classify_run(
            uuid4(), session_maker=MagicMock(), posting_dependencies=MagicMock()
        )
    assert create_task_called is False


def test_register_prefect_deployment_registers_all_pool_flows(monkeypatch: pytest.MonkeyPatch) -> None:
    """register_prefect_deployment deploys 5 core flows everywhere and adds staging-db-hygiene in staging."""
    import scripts.register_prefect_deployment as reg

    monkeypatch.setattr(reg, "_ensure_work_pool_exists", AsyncMock())
    registered: list[tuple[str, str, dict[str, object]]] = []

    class _FakeFlow:
        def from_source(self, *, source: str, entrypoint: str):
            def _deploy(**kwargs):
                registered.append((kwargs["name"], kwargs["work_pool_name"], kwargs))

            return type("_Deployable", (), {"deploy": staticmethod(_deploy)})()

    import src.statement_flow as sf

    for attr in (
        "parse_statement_flow",
        "classify_statement_flow",
        "market_data_sync_flow",
        "storage_sweep_flow",
        "parsing_supervisor_reap_flow",
        "staging_db_hygiene_flow",
    ):
        monkeypatch.setattr(sf, attr, _FakeFlow())

    monkeypatch.setenv("ENVIRONMENT", "production")
    assert reg.main() == 0
    assert [name for name, _, _ in registered] == [
        "parse-statement",
        "classify-statement",
        "market-data-sync",
        "storage-sweep",
        "parsing-supervisor-reap",
    ]
    assert all(pool == "finance-report" for _, pool, _ in registered)

    registered.clear()
    monkeypatch.setenv("ENVIRONMENT", "staging")
    assert reg.main() == 0
    assert "staging-db-hygiene" in [name for name, _, _ in registered]
