"""POST and GET /statements/{id}/runs: run again with hints, and the audit list of attempts (#2994, slice S2)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from src.extraction import (
    BankStatementStatus,
    ParseJob,
    RunActorKind,
    RunHints,
    RunKind,
    RunTrigger,
    StatementSummary,
    create_run,
    fail_run,
    list_runs,
)
from src.extraction.extension import statement_pipeline
from src.extraction.extension.prompts.statement import PARSING_PROMPT_TEMPLATE_VERSION, parsing_prompt_digest
from src.extraction.orm.statement_run import StatementRun
from src.identity import User
from tests.api._statement_router_fixtures import _compose_mock_ingestion, build_statement, seed_uploaded_document

RUN_FIELDS = {
    "id",
    "seq",
    "kind",
    "state",
    "actor_kind",
    "trigger",
    "parent_run_id",
    "hints",
    "model",
    "prompt_template_version",
    "prompt_digest",
    "error_code",
    "error_message",
    "requested_at",
    "started_at",
    "finished_at",
}


def _capture_dispatch(monkeypatch) -> list[ParseJob]:
    jobs: list[ParseJob] = []

    async def capture(*, job, content):
        jobs.append(job)

    monkeypatch.setattr(statement_pipeline, "compose_statement_ingestion_use_case", _compose_mock_ingestion(capture))
    return jobs


async def _statement(db, user, *, status=BankStatementStatus.PARSED, name="run.pdf") -> StatementSummary:
    statement = build_statement(user.id, f"hash-{uuid4()}", 70)
    statement.status = status
    db.add(statement)
    await db.flush()
    await seed_uploaded_document(db, statement, file_path=f"statements/{statement.file_hash}", original_filename=name)
    await db.commit()
    return statement


async def _runs(db, statement_id) -> list[StatementRun]:
    rows = await db.execute(
        select(StatementRun)
        .where(StatementRun.statement_id == statement_id)
        .order_by(StatementRun.seq)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


async def _failed_first_run(db, user, statement_id):
    first = await create_run(
        db,
        statement_id=statement_id,
        user_id=user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(),
    )
    await fail_run(db, first.id, error_code="extraction_error", error_message="The parse failed.")
    await db.commit()
    return first.id


async def test_AC_extraction_2994_50_post_runs_starts_a_rerun_with_the_hints_as_typed(
    client, db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-extraction.2994.50: POST runs writes a user rerun run with the typed hints and dispatches it."""
    statement = await _statement(db, test_user)
    statement_id = statement.id
    first_id = await _failed_first_run(db, test_user, statement_id)
    jobs = _capture_dispatch(monkeypatch)
    hints = {"keywords": ["interest", "FX fee"], "note": 'Credits carry a "CR" suffix.\nYear is 2026.'}

    response = await client.post(
        f"/statements/{statement_id}/runs", json={"kind": "extract", "hints": hints, "model": "vendor/vision-x"}
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert set(body) == RUN_FIELDS
    assert (body["seq"], body["kind"], body["actor_kind"], body["trigger"]) == (2, "extract", "user", "rerun")
    assert body["state"] in ("requested", "running")
    assert body["parent_run_id"] == str(first_id)
    assert body["hints"] == hints
    assert body["model"] == "vendor/vision-x"
    runs = await _runs(db, statement_id)
    assert [run.seq for run in runs] == [1, 2]
    assert str(runs[1].id) == body["id"]
    assert runs[1].hints == hints
    assert [job.run_id for job in jobs] == [runs[1].id]
    assert jobs[0].model == "vendor/vision-x"
    fresh = await db.scalar(
        select(StatementSummary).where(StatementSummary.id == statement_id).execution_options(populate_existing=True)
    )
    assert fresh.status is BankStatementStatus.PARSING


async def test_AC_extraction_2994_50_the_body_may_omit_kind_hints_and_model(
    client, db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-extraction.2994.50: An empty body runs the extraction again with no hints, like the old retry."""
    statement = await _statement(db, test_user, status=BankStatementStatus.REJECTED)
    jobs = _capture_dispatch(monkeypatch)

    response = await client.post(f"/statements/{statement.id}/runs", json={})

    assert response.status_code == 202, response.text
    assert response.json()["hints"] == {"keywords": [], "note": None}
    assert response.json()["model"] is None
    assert len(jobs) == 1


async def test_AC_extraction_2994_50_the_run_stores_the_digest_of_its_model_and_hints(
    client, db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-extraction.2994.50: The new run carries the template version and a digest that its columns reproduce."""
    statement = await _statement(db, test_user)
    _capture_dispatch(monkeypatch)
    hints = {"keywords": ["salary"], "note": None}

    body = (await client.post(f"/statements/{statement.id}/runs", json={"hints": hints, "model": "vendor/vision-x"})).json()

    assert body["prompt_template_version"] == PARSING_PROMPT_TEMPLATE_VERSION
    assert body["prompt_digest"] == parsing_prompt_digest("vendor/vision-x", RunHints(**hints))


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "classify"},
        {"kind": "extract", "actor_kind": "system"},
        {"hints": {"keywords": [f"k{n}" for n in range(21)]}},
        {"hints": {"keywords": ["k" * 65]}},
        {"hints": {"keywords": [""]}},
        {"hints": {"note": "n" * 501}},
        {"hints": {"note": "bell\x07"}},
        {"hints": {"keywords": ["a"], "unknown": 1}},
    ],
    ids=["classify", "actor_in_body", "21_keywords", "65_chars", "empty_keyword", "501_note", "control", "extra_hint_field"],
)
async def test_AC_extraction_2994_51_post_runs_rejects_a_body_outside_the_limits(
    body, client, db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-extraction.2994.51: A classify kind, an actor in the body or a hint over its limit gives 422 and no run."""
    statement = await _statement(db, test_user)
    statement_id = statement.id
    jobs = _capture_dispatch(monkeypatch)

    response = await client.post(f"/statements/{statement_id}/runs", json=body)

    assert response.status_code == 422, response.text
    assert await _runs(db, statement_id) == []
    assert jobs == []


async def test_AC_extraction_2994_51_post_runs_accepts_the_hint_limits(
    client, db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-extraction.2994.51: 20 keywords of 64 characters and a 500-character note are valid."""
    statement = await _statement(db, test_user)
    _capture_dispatch(monkeypatch)
    hints = {"keywords": [f"{n:02d}" + "k" * 62 for n in range(20)], "note": "n" * 500}

    response = await client.post(f"/statements/{statement.id}/runs", json={"hints": hints})

    assert response.status_code == 202, response.text
    assert response.json()["hints"] == hints


async def test_AC_extraction_2994_52_post_runs_of_another_users_statement_gives_404(
    client, db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-extraction.2994.52: A statement of another user gives 404, and no run starts."""
    other = User(id=uuid4(), email=f"other-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other)
    await db.commit()
    foreign = await _statement(db, other)
    foreign_id = foreign.id
    jobs = _capture_dispatch(monkeypatch)

    response = await client.post(f"/statements/{foreign_id}/runs", json={"hints": {"keywords": ["x"]}})

    assert response.status_code == 404, response.text
    assert await _runs(db, foreign_id) == []
    assert jobs == []


async def test_AC_extraction_2994_52_post_runs_of_an_unknown_statement_gives_404(client, test_user):
    """AC-extraction.2994.52: An unknown statement id gives 404."""
    response = await client.post(f"/statements/{uuid4()}/runs", json={})

    assert response.status_code == 404, response.text


async def test_AC_extraction_2994_53_post_runs_of_a_csv_statement_with_hints_gives_400(
    client, db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-extraction.2994.53: A CSV parse sends no prompt, so hints on a CSV statement give 400 and no run."""
    statement = await _statement(db, test_user, name="bank.csv")
    statement_id = statement.id
    jobs = _capture_dispatch(monkeypatch)

    rejected = await client.post(f"/statements/{statement_id}/runs", json={"hints": {"keywords": ["x"]}})
    accepted = await client.post(f"/statements/{statement_id}/runs", json={})

    assert rejected.status_code == 400, rejected.text
    assert "PDF and image" in rejected.json()["detail"]
    assert accepted.status_code == 202, accepted.text
    assert len(jobs) == 1


async def test_AC_extraction_2994_54_get_runs_lists_the_attempts_in_order_with_their_hints(
    client, db, test_user
):
    """AC-extraction.2994.54: GET runs returns each attempt by seq with its hints, actor, state and error."""
    statement = await _statement(db, test_user)
    statement_id = statement.id
    first_id = await _failed_first_run(db, test_user, statement_id)
    second = await create_run(
        db,
        statement_id=statement_id,
        user_id=test_user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.RERUN,
        hints=RunHints(keywords=["interest"], note="Credits."),
        model="vendor/vision-x",
        parent_run_id=first_id,
    )
    await db.commit()

    response = await client.get(f"/statements/{statement_id}/runs")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    first, latest = body["items"]
    assert set(first) == RUN_FIELDS and set(latest) == RUN_FIELDS
    assert [first["seq"], latest["seq"]] == [1, 2]
    assert (first["state"], first["error_code"], first["error_message"]) == ("failed", "extraction_error", "The parse failed.")
    assert first["finished_at"] is not None and first["hints"] == {"keywords": [], "note": None}
    assert (latest["id"], latest["state"], latest["actor_kind"], latest["trigger"]) == (
        str(second.id),
        "requested",
        "user",
        "rerun",
    )
    assert latest["parent_run_id"] == str(first_id)
    assert latest["hints"] == {"keywords": ["interest"], "note": "Credits."}
    assert latest["model"] == "vendor/vision-x"
    assert latest["error_code"] is None and latest["finished_at"] is None


async def test_AC_extraction_2994_54_get_runs_shows_two_runs_with_identical_results_as_two_rows(
    client, db, monkeypatch, storage_stub, model_catalog_stub, test_user
):
    """AC-extraction.2994.54: Two runs with different hints leave two rows, whatever their results."""
    statement = await _statement(db, test_user)
    statement_id = statement.id
    _capture_dispatch(monkeypatch)
    first = await client.post(f"/statements/{statement_id}/runs", json={"hints": {"keywords": ["one"]}})
    assert first.status_code == 202, first.text
    await fail_run(db, (await _runs(db, statement_id))[0].id, error_code="done", error_message="Ended for the test.")
    await db.commit()
    second = await client.post(f"/statements/{statement_id}/runs", json={"hints": {"keywords": ["two"]}})
    assert second.status_code == 202, second.text

    items = (await client.get(f"/statements/{statement_id}/runs")).json()["items"]

    assert [item["hints"]["keywords"] for item in items] == [["one"], ["two"]]
    assert [item["seq"] for item in items] == [1, 2]


async def test_AC_extraction_2994_54_get_runs_is_scoped_to_the_owner(client, db, test_user):
    """AC-extraction.2994.54: A statement of another user gives 404, never an empty or a foreign list."""
    other = User(id=uuid4(), email=f"owner-{uuid4()}@example.com", hashed_password="hashed")
    db.add(other)
    await db.commit()
    foreign = await _statement(db, other)
    foreign_id = foreign.id
    await create_run(
        db,
        statement_id=foreign_id,
        user_id=other.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(keywords=["secret"]),
    )
    await db.commit()

    response = await client.get(f"/statements/{foreign_id}/runs")

    assert response.status_code == 404, response.text
    assert "secret" not in response.text


async def test_AC_extraction_2994_54_get_runs_of_a_statement_without_runs_is_an_empty_list(client, db, test_user):
    """AC-extraction.2994.54: An older statement with no run row gives an empty list, not an error."""
    statement = await _statement(db, test_user)

    response = await client.get(f"/statements/{statement.id}/runs")

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "total": 0}


async def test_AC_extraction_2994_55_the_retry_route_and_its_request_schema_are_gone(client, db, test_user):
    """AC-extraction.2994.55: POST /retry no longer exists, and neither does RetryParsingRequest."""
    from src import schemas
    from src.main import app

    statement = await _statement(db, test_user)

    response = await client.post(f"/statements/{statement.id}/retry", json={})

    assert response.status_code in (404, 405), response.text
    paths = app.openapi()["paths"]
    assert not [path for path in paths if path.endswith("/retry")]
    assert "/statements/{statement_id}/runs" in paths
    assert set(paths["/statements/{statement_id}/runs"]) == {"get", "post"}
    assert not hasattr(schemas, "RetryParsingRequest")
    assert "RetryParsingRequest" not in app.openapi()["components"]["schemas"]


async def test_AC_extraction_2994_54_list_runs_returns_only_the_runs_of_the_given_user(db, test_user):
    """AC-extraction.2994.54: list_runs filters by user, so it never returns the runs of another user."""
    statement = await _statement(db, test_user)
    statement_id = statement.id
    await _failed_first_run(db, test_user, statement_id)

    own = await list_runs(db, statement_id, test_user.id)
    foreign = await list_runs(db, statement_id, uuid4())

    assert [record.seq for record in own] == [1]
    assert foreign == []
