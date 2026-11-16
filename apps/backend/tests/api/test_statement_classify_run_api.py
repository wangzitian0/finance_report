"""POST /statements/{id}/runs with kind classify: classify again with hints (#2994, slice S4b-1).

A user classify run is a run row with the hints of the user. The API process runs it as a background task. The
hints are allowed for every file type, because the model classifies the rows of a CSV too.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

import pytest
from sqlalchemy import select

from src.extraction import (
    BankStatementStatus,
    RunActorKind,
    RunHints,
    RunKind,
    RunState,
    RunTrigger,
    StatementStatusChanged,
    StatementSummary,
    claim_run,
    create_run,
    fail_run,
)
from src.extraction.extension import statement_pipeline
from src.extraction.extension.prompts.classification import CLASSIFICATION_PROMPT_TEMPLATE_VERSION
from src.extraction.extension.prompts.hints import run_prompt_digest
from src.extraction.orm.statement_run import StatementRun
from src.routers import statements as statements_router
from tests.extraction.test_statement_classify_hints import HintsModel
from tests.extraction.test_statement_classify_run import _install, _model_on, _rows, _seed  # noqa: F401
from tests.statement_ingestion import classify_statement

HINTS = {"keywords": ["rent", "FX fee"], "note": 'Credits carry a "CR" suffix.'}


async def _runs(db, statement_id) -> list[StatementRun]:
    rows = await db.execute(
        select(StatementRun)
        .where(StatementRun.statement_id == statement_id)
        .order_by(StatementRun.seq)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


async def _parsed(db, user, *, name="classify.pdf", rows=None):
    return await _seed_named(db, user, name, rows)


async def _seed_named(db, user, name, rows):
    from tests.factories import seed_parsed_statement

    rows = rows or _rows(4)
    seeded = await seed_parsed_statement(db, user.id, original_filename=name, transactions=rows)
    return seeded


def _spy_dispatch(monkeypatch) -> list:
    """Replace the dispatch: record the run id and start nothing."""
    ids: list = []

    def submit(run_id, *, db):
        ids.append(run_id)
        return asyncio.ensure_future(asyncio.sleep(0))

    monkeypatch.setattr(statements_router, "submit_classify_run", submit)
    return ids


async def _wait_for_tasks() -> None:
    pending = list(statements_router._PENDING_PARSE_TASKS)
    if pending:
        await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=20)


@pytest.mark.parametrize("name", ["classify.pdf", "classify.csv"])
async def test_AC_extraction_2994_130_post_runs_starts_a_classify_run_with_the_hints_as_typed(
    client, db, monkeypatch, test_user, name
):
    """AC-extraction.2994.130: Kind classify gives a user rerun run with the hints and the digest, for a PDF and a CSV."""
    seeded = await _parsed(db, test_user, name=name)
    statement_id = seeded.id
    ids = _spy_dispatch(monkeypatch)

    response = await client.post(f"/statements/{statement_id}/runs", json={"kind": "classify", "hints": HINTS})

    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["seq"], body["kind"], body["actor_kind"], body["trigger"], body["model"]) == (
        1,
        "classify",
        "user",
        "rerun",
        None,
    )
    assert body["hints"] == HINTS and body["state"] == "requested"
    assert body["prompt_template_version"] == CLASSIFICATION_PROMPT_TEMPLATE_VERSION
    assert body["prompt_digest"] == run_prompt_digest(CLASSIFICATION_PROMPT_TEMPLATE_VERSION, None, RunHints(**HINTS))
    runs = await _runs(db, statement_id)
    assert [str(run.id) for run in runs] == [body["id"]] and ids == [runs[0].id]
    fresh = await db.scalar(
        select(StatementSummary).where(StatementSummary.id == statement_id).execution_options(populate_existing=True)
    )
    assert fresh.status is BankStatementStatus.PARSED, "a classify run sets no statement status"


async def test_AC_extraction_2994_130_the_run_is_committed_before_the_task_starts(client, db, monkeypatch, test_user):
    """AC-extraction.2994.130: When the dispatch runs, the session of the request has committed, and another session sees the run."""
    seeded = await _parsed(db, test_user)
    statement_id = seeded.id
    seen: list[list[RunState]] = []
    open_when_dispatched: list[bool] = []

    def submit(run_id, *, db):
        open_when_dispatched.append(db.in_transaction())  # deterministic: a commit after the dispatch shows here

        async def peek():
            from src.database import create_session_maker_from_db

            async with create_session_maker_from_db(db)() as other:
                seen.append([run.state for run in await _runs(other, statement_id)])

        return asyncio.ensure_future(peek())

    monkeypatch.setattr(statements_router, "submit_classify_run", submit)

    response = await client.post(f"/statements/{statement_id}/runs", json={"kind": "classify", "hints": HINTS})
    await _wait_for_tasks()

    assert response.status_code == 202, response.text
    assert open_when_dispatched == [False], "the dispatch ran inside the transaction of the run insert"
    assert seen == [[RunState.REQUESTED]]


async def test_AC_extraction_2994_131_the_background_task_runs_the_run_with_the_hints(
    client, db, monkeypatch, test_user
):
    """AC-extraction.2994.131: The API process classifies the rows. The model call gets the hints of the run."""
    seeded = await _parsed(db, test_user)
    statement_id = seeded.id
    model = _install(monkeypatch, HintsModel())

    response = await client.post(f"/statements/{statement_id}/runs", json={"kind": "classify", "hints": HINTS})
    await _wait_for_tasks()

    assert response.status_code == 202, response.text
    (run,) = await _runs(db, statement_id)
    assert (run.state, run.result_summary["outcome"]) == (RunState.SUCCEEDED, "classified")
    assert model.hints == [RunHints(**HINTS)] and len(model.calls) == 1


async def test_AC_extraction_2994_131_a_dispatch_failure_fails_the_run_and_leaves_no_active_run(
    client, db, monkeypatch, test_user
):
    """AC-extraction.2994.131: The run fails with a fixed code and message. A later request starts a new run."""
    seeded = await _parsed(db, test_user)
    statement_id = seeded.id

    def broken(run_id, *, db):
        raise RuntimeError("secret dispatch detail Salary 000")

    monkeypatch.setattr(statements_router, "submit_classify_run", broken)

    refused = await client.post(f"/statements/{statement_id}/runs", json={"kind": "classify", "hints": HINTS})

    assert refused.status_code == 503, refused.text
    assert "secret" not in refused.text
    (run,) = await _runs(db, statement_id)
    assert (run.state, run.error_code) == (RunState.FAILED, "dispatch_failed")
    assert "secret" not in (run.error_message or "")
    ids = _spy_dispatch(monkeypatch)
    again = await client.post(f"/statements/{statement_id}/runs", json={"kind": "classify", "hints": HINTS})
    assert again.status_code == 202, again.text
    assert len(ids) == 1


async def test_AC_extraction_2994_131_the_dispatch_uses_the_tracked_background_task(db, monkeypatch, test_user):
    """AC-extraction.2994.131: submit_classify_run starts execute_classify_run as a task of the API process."""
    seeded = await _parsed(db, test_user)
    called: list = []

    async def fake_execute(session_maker, *, run_id, posting_dependencies, **_options):
        called.append(run_id)
        return 0

    monkeypatch.setattr(statement_pipeline, "execute_classify_run", fake_execute)

    task = statement_pipeline.submit_classify_run(seeded.id, db=db)  # any id: the executor is a fake
    await asyncio.wait_for(task, timeout=10)

    assert called == [seeded.id]


@pytest.mark.parametrize(
    "status", [BankStatementStatus.APPROVED, BankStatementStatus.REJECTED, BankStatementStatus.PARSING]
)
async def test_AC_extraction_2994_132_only_a_parsed_statement_accepts_a_classify_run(
    client, db, monkeypatch, test_user, status
):
    """AC-extraction.2994.132: A statement that is approved, rejected or parsing gives 400 and no run."""
    seeded = await _parsed(db, test_user)
    if status is BankStatementStatus.APPROVED:
        from tests.api._statement_router_fixtures import create_statement_account

        seeded.statement.account_id = (await create_statement_account(db, test_user.id)).id
    seeded.statement.status = status
    await db.commit()
    statement_id = seeded.id
    ids = _spy_dispatch(monkeypatch)

    response = await client.post(f"/statements/{statement_id}/runs", json={"kind": "classify", "hints": HINTS})

    assert response.status_code == 400, response.text
    assert await _runs(db, statement_id) == [] and ids == []


async def test_AC_extraction_2994_132_an_active_run_gives_409_with_its_id_and_starts_nothing(
    client, db, monkeypatch, test_user
):
    """AC-extraction.2994.132: A requested or running run blocks a classify run with active_run_id."""
    seeded = await _parsed(db, test_user)
    statement_id = seeded.id
    active = await create_run(
        db,
        statement_id=statement_id,
        user_id=test_user.id,
        kind=RunKind.CLASSIFY,
        actor_kind=RunActorKind.SYSTEM,
        trigger=RunTrigger.AUTO_CLASSIFY,
        hints=RunHints(),
    )
    await claim_run(db, active.id)
    await db.commit()
    active_id = active.id
    ids = _spy_dispatch(monkeypatch)

    response = await client.post(f"/statements/{statement_id}/runs", json={"kind": "classify", "hints": HINTS})

    assert response.status_code == 409, response.text
    assert response.json()["active_run_id"] == str(active_id)
    assert len(await _runs(db, statement_id)) == 1 and ids == []


async def test_AC_extraction_2994_132_a_status_that_changed_after_the_check_gives_409_and_no_run(
    client, db, monkeypatch, test_user
):
    """AC-extraction.2994.132: The row lock re-checks the status. A change in between gives 409 and writes nothing."""
    seeded = await _parsed(db, test_user)
    statement_id = seeded.id
    ids = _spy_dispatch(monkeypatch)

    async def changed(*_args, **_kwargs):
        raise StatementStatusChanged("The statement changed while the run started.")

    monkeypatch.setattr(statements_router, "start_user_classify_run", changed)

    response = await client.post(f"/statements/{statement_id}/runs", json={"kind": "classify", "hints": HINTS})

    assert response.status_code == 409, response.text
    assert "active_run_id" not in response.json()
    assert await _runs(db, statement_id) == [] and ids == []


async def test_AC_extraction_2994_132_a_classify_run_takes_no_model_and_no_actor_from_the_body(
    client, db, monkeypatch, test_user
):
    """AC-extraction.2994.132: A model, an actor or an extra field gives 422 and no run."""
    seeded = await _parsed(db, test_user)
    statement_id = seeded.id
    ids = _spy_dispatch(monkeypatch)

    for body in (
        {"kind": "classify", "model": "vendor/vision-x"},
        {"kind": "classify", "actor_kind": "ai"},
        {"kind": "classify", "hints": {"keywords": ["x"] * 21}},
        {"kind": "other"},
    ):
        response = await client.post(f"/statements/{statement_id}/runs", json=body)
        assert response.status_code == 422, (body, response.text)

    assert await _runs(db, statement_id) == [] and ids == []


async def test_AC_extraction_2994_132_extraction_hints_still_need_a_prompt_file_type(
    client, db, monkeypatch, test_user
):
    """AC-extraction.2994.132: The CSV rule stays an extraction rule: extract with hints on a CSV is 400, classify is 202."""
    seeded = await _parsed(db, test_user, name="classify.csv")
    statement_id = seeded.id
    _spy_dispatch(monkeypatch)

    extract = await client.post(f"/statements/{statement_id}/runs", json={"kind": "extract", "hints": HINTS})
    classify = await client.post(f"/statements/{statement_id}/runs", json={"kind": "classify", "hints": HINTS})

    assert extract.status_code == 400, extract.text
    assert classify.status_code == 202, classify.text


async def test_AC_extraction_2994_133_a_user_run_after_an_automatic_run_asks_the_answered_rows_again(
    client, db, monkeypatch, test_user
):
    """AC-extraction.2994.133: With the hints of the user, the model sees the rows that already have a model answer."""
    seeded = await _parsed(db, test_user, rows=_rows(3, first_day=date(2026, 3, 1)))
    statement_id = seeded.id
    model = _install(monkeypatch, HintsModel())
    await classify_statement(db, statement_id)
    asked = len(model.calls)

    response = await client.post(f"/statements/{statement_id}/runs", json={"kind": "classify", "hints": HINTS})
    await _wait_for_tasks()

    assert response.status_code == 202, response.text
    runs = await _runs(db, statement_id)
    assert (runs[-1].state, runs[-1].result_summary["outcome"]) == (RunState.SUCCEEDED, "classified")
    assert len(model.calls) == 2 * asked and model.hints[-1] == RunHints(**HINTS)
    assert runs[-1].parent_run_id == runs[0].id


async def test_AC_extraction_2994_133_a_failed_run_does_not_block_the_next_one(
    client, db, monkeypatch, test_user, caplog
):
    """AC-extraction.2994.133: After a failed classify run the user can start another. No hint text reaches a log."""
    caplog.set_level(logging.DEBUG)
    seeded = await _parsed(db, test_user)
    statement_id = seeded.id
    failed = await create_run(
        db,
        statement_id=statement_id,
        user_id=test_user.id,
        kind=RunKind.CLASSIFY,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.RERUN,
        hints=RunHints(),
    )
    await fail_run(db, failed.id, error_code="classification_failed", error_message="The classification failed.")
    await db.commit()
    ids = _spy_dispatch(monkeypatch)
    hints = {"keywords": ["UNIQUE-KEYWORD-SECRET"], "note": "UNIQUE-NOTE-SECRET"}

    response = await client.post(f"/statements/{statement_id}/runs", json={"kind": "classify", "hints": hints})

    assert response.status_code == 202, response.text
    assert len(ids) == 1
    everything = "\n".join(f"{r.getMessage()} {r.msg!r}" for r in caplog.records)
    assert "UNIQUE-KEYWORD-SECRET" not in everything and "UNIQUE-NOTE-SECRET" not in everything


async def test_AC_extraction_2994_142_a_422_body_keeps_only_loc_msg_and_type(client, db, monkeypatch, test_user):
    """AC-extraction.2994.142: Each entry of a 422 keeps loc, msg and type. The input and ctx fields are dropped.

    A msg can hold validator text. For these three bodies, the secret text is not in the response.
    """
    seeded = await _parsed(db, test_user)
    statement_id = seeded.id
    _spy_dispatch(monkeypatch)
    secret = "SECRET-NOTE-TEXT"

    for body in (
        {"kind": "classify", "model": "x", "hints": {"note": secret}},  # a model validator
        {"kind": "classify", "hints": {"note": secret + "n" * 500}},  # a field limit
        {"kind": "classify", "hints": {"keywords": [secret + "k" * 64]}},
    ):
        response = await client.post(f"/statements/{statement_id}/runs", json=body)

        assert response.status_code == 422, response.text
        assert secret not in response.text, body
        assert all(set(entry) == {"loc", "msg", "type"} for entry in response.json()["detail"]), response.text
