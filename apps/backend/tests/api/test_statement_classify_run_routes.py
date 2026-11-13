"""A classify run against the rerun and the reject routes, with real sessions (#2994, slice S3).

The statement is PARSED while its classify run is active. A rerun or a reject must answer 409 with the id of
that run, and must write nothing: the reject voids ledger effects, so it checks the run before it writes.
"""

from __future__ import annotations

import asyncio

import pytest

from src.config import settings
from src.extraction import BankStatementStatus, ParseJob, RunKind, RunState
from tests.extraction.test_statement_classify_run import (
    WAIT_SECONDS,
    Proposer,
    _active_classify_run,
    _install,
    _run,
    _runs,
    _statement,
)


@pytest.fixture(autouse=True)
def _model_on(monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    monkeypatch.setattr(settings, "auto_accept_ai_suggestions", True)
    monkeypatch.setattr(settings, "ai_api_key", "test-key")


async def test_AC_extraction_2994_102_a_user_rerun_during_a_classify_run_gives_409_without_a_deadlock(
    client, db, test_user, monkeypatch, storage_stub, model_catalog_stub
):
    """AC-extraction.2994.102: The rerun route meets the running classify run: 409 with its id, then it works after the run."""
    from src.extraction.extension import statement_pipeline
    from tests.api._statement_router_fixtures import _compose_mock_ingestion

    jobs: list[ParseJob] = []

    async def capture(*, job, content):
        jobs.append(job)

    monkeypatch.setattr(statement_pipeline, "compose_statement_ingestion_use_case", _compose_mock_ingestion(capture))
    gate = asyncio.Event()
    proposer = _install(monkeypatch, Proposer(gate=gate))
    statement_id, run_id, worker = await _active_classify_run(db, test_user, monkeypatch, proposer)
    try:
        refused = await asyncio.wait_for(client.post(f"/statements/{statement_id}/runs", json={}), timeout=WAIT_SECONDS)
        assert refused.status_code == 409, refused.text
        assert refused.json()["active_run_id"] == str(run_id)
        assert jobs == []
    finally:
        gate.set()
        await asyncio.wait_for(worker, timeout=WAIT_SECONDS)

    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
    accepted = await client.post(f"/statements/{statement_id}/runs", json={})
    assert accepted.status_code in (200, 202), accepted.text
    assert [(run.kind, run.state) for run in await _runs(db, statement_id)][-1] == (RunKind.EXTRACT, RunState.REQUESTED)


async def test_AC_extraction_2994_102_a_reject_during_a_classify_run_gives_409_and_voids_nothing(
    client, db, test_user, monkeypatch, storage_stub, model_catalog_stub
):
    """AC-extraction.2994.102: The reject checks the active run before it writes: the status and the review stay."""
    gate = asyncio.Event()
    proposer = _install(monkeypatch, Proposer(gate=gate))
    statement_id, run_id, worker = await _active_classify_run(db, test_user, monkeypatch, proposer)
    try:
        refused = await asyncio.wait_for(
            client.post(f"/statements/{statement_id}/review/reject", json={"notes": "check the dates"}),
            timeout=WAIT_SECONDS,
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["active_run_id"] == str(run_id)
        untouched = await _statement(db, statement_id)
        assert untouched.status is BankStatementStatus.PARSED
        assert untouched.stage1_reviewed_at is None
        assert [run.kind for run in await _runs(db, statement_id)] == [RunKind.CLASSIFY]
    finally:
        gate.set()
        await asyncio.wait_for(worker, timeout=WAIT_SECONDS)
    assert (await _run(db, run_id)).state is RunState.SUCCEEDED
