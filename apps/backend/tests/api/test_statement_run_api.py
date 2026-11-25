"""POST and GET /statements/{id}/runs: run again with hints, and the audit list of attempts."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from src import schemas
from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    ParseJob,
    RunActorKind,
    RunHints,
    RunKind,
    RunTrigger,
    StatementSummary,
    claim_run,
    create_run,
    fail_run,
    finish_run,
    hints_apply_to_file_type,
    list_runs,
)
from src.extraction.extension import statement_pipeline
from src.extraction.extension.prompts.hints import run_prompt_digest
from src.extraction.extension.prompts.statement import PARSING_PROMPT_TEMPLATE_VERSION
from src.extraction.orm.statement_run import StatementRun
from src.main import app
from src.runtime import StorageError
from tests.api._statement_router_fixtures import (
    _compose_mock_ingestion,
    add_statement,
    create_statement_account,
    failing_storage,
    seed_uploaded_document,
)
from tests.factories import UserFactory

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
    "outcome",
}


def _capture_dispatch(monkeypatch) -> list[ParseJob]:
    jobs: list[ParseJob] = []

    async def capture(*, job, content):
        jobs.append(job)

    monkeypatch.setattr("src.composition.compose_statement_ingestion_use_case", _compose_mock_ingestion(capture))
    return jobs


async def _statement(db, user, *, status=BankStatementStatus.PARSED, name="run.pdf") -> StatementSummary:
    statement = await add_statement(db, user.id, f"hash-{uuid4()}", confidence=70, status=status)
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


async def test_post_runs_starts_a_rerun_with_hints_and_digest(client, db, monkeypatch, storage_stub, test_user):
    statement = await _statement(db, test_user)
    first_id = await _failed_first_run(db, test_user, statement.id)
    jobs = _capture_dispatch(monkeypatch)
    hints = {"keywords": ["interest", "FX fee"], "note": 'Credits carry a "CR" suffix.\nYear is 2026.'}

    body = (
        response := await client.post(f"/statements/{statement.id}/runs", json={"kind": "extract", "hints": hints})
    ).json()
    assert response.status_code == 202 and set(body) == RUN_FIELDS and body["state"] in ("requested", "running")
    assert (
        body["seq"],
        body["kind"],
        body["actor_kind"],
        body["trigger"],
        body["parent_run_id"],
        body["hints"],
        body["model"],
        body["prompt_template_version"],
        body["prompt_digest"],
    ) == (
        2,
        "extract",
        "user",
        "rerun",
        str(first_id),
        hints,
        None,
        PARSING_PROMPT_TEMPLATE_VERSION,
        run_prompt_digest(PARSING_PROMPT_TEMPLATE_VERSION, None, RunHints(**hints)),
    )
    runs = await _runs(db, statement.id)
    assert ([r.seq for r in runs], str(runs[1].id), runs[1].hints, [j.run_id for j in jobs]) == (
        [1, 2],
        body["id"],
        hints,
        [runs[1].id],
    )
    assert (
        await db.scalar(
            select(StatementSummary)
            .where(StatementSummary.id == statement.id)
            .execution_options(populate_existing=True)
        )
    ).status is BankStatementStatus.PARSING


async def test_post_runs_may_omit_body_or_accept_hint_limits(client, db, monkeypatch, storage_stub, test_user):
    s_empty, s_limits = (
        await _statement(db, test_user, status=BankStatementStatus.REJECTED),
        await _statement(db, test_user),
    )
    jobs = _capture_dispatch(monkeypatch)
    r_empty = await client.post(f"/statements/{s_empty.id}/runs", json={})
    hints = {"keywords": [f"{n:02d}" + "k" * 62 for n in range(20)], "note": "n" * 500}
    r_limits = await client.post(f"/statements/{s_limits.id}/runs", json={"hints": hints})
    assert r_empty.status_code == 202 and (r_empty.json()["hints"], r_empty.json()["model"], len(jobs)) == (
        {"keywords": [], "note": None},
        None,
        2,
    )
    assert r_limits.status_code == 202 and r_limits.json()["hints"] == hints


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "other"},
        {"kind": "extract", "actor_kind": "system"},
        {"hints": {"keywords": [f"k{n}" for n in range(21)]}},
        {"hints": {"keywords": ["k" * 65]}},
        {"hints": {"keywords": [""]}},
        {"hints": {"note": "n" * 501}},
        {"hints": {"note": "bell\x07"}},
        {"hints": {"keywords": ["a"], "unknown": 1}},
        {"kind": "extract", "model": "vendor/vision-x"},
        {"kind": "classify", "model": "vendor/vision-x"},
    ],
    ids=[
        "unknown_kind",
        "actor_in_body",
        "21_keywords",
        "65_chars",
        "empty_keyword",
        "501_note",
        "control",
        "extra_hint_field",
        "model_on_extract",
        "model_on_classify",
    ],
)
async def test_post_runs_rejects_a_body_outside_the_limits(body, client, db, monkeypatch, storage_stub, test_user):
    statement = await _statement(db, test_user)
    jobs = _capture_dispatch(monkeypatch)
    response = await client.post(f"/statements/{statement.id}/runs", json=body)
    assert response.status_code == 422 and await _runs(db, statement.id) == [] and jobs == []


@pytest.mark.parametrize("foreign", [True, False])
async def test_post_runs_missing_or_foreign_statement_gives_404(
    client, db, monkeypatch, storage_stub, test_user, foreign
):
    jobs = _capture_dispatch(monkeypatch)
    if foreign:
        other = await UserFactory.create_async(db)
        target_id = (await _statement(db, other)).id
    else:
        target_id = uuid4()
    response = await client.post(
        f"/statements/{target_id}/runs", json={"hints": {"keywords": ["x"]}} if foreign else {}
    )
    assert response.status_code == 404 and await _runs(db, target_id) == [] and jobs == []


async def test_post_runs_of_a_csv_statement_with_hints_gives_400(client, db, monkeypatch, storage_stub, test_user):
    statement = await _statement(db, test_user, name="bank.csv")
    jobs = _capture_dispatch(monkeypatch)
    rejected = await client.post(f"/statements/{statement.id}/runs", json={"hints": {"keywords": ["x"]}})
    accepted = await client.post(f"/statements/{statement.id}/runs", json={})
    assert rejected.status_code == 400 and "PDF and image" in rejected.json()["detail"]
    assert accepted.status_code == 202 and len(jobs) == 1


async def test_get_runs_lists_the_attempts_in_order_with_their_hints(client, db, test_user):
    statement = await _statement(db, test_user)
    first_id = await _failed_first_run(db, test_user, statement.id)
    second = await create_run(
        db,
        statement_id=statement.id,
        user_id=test_user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.RERUN,
        hints=RunHints(keywords=["interest"], note="Credits."),
        model="vendor/vision-x",
        parent_run_id=first_id,
    )
    await db.commit()

    body = (response := await client.get(f"/statements/{statement.id}/runs")).json()
    first, latest = body["items"]
    assert (
        response.status_code == 200
        and body["total"] == 2
        and set(first) == RUN_FIELDS
        and set(latest) == RUN_FIELDS
        and [first["seq"], latest["seq"]] == [1, 2]
    )
    assert (first["state"], first["error_code"], first["error_message"], first["hints"]) == (
        "failed",
        "extraction_error",
        "The parse failed.",
        {"keywords": [], "note": None},
    ) and first["finished_at"] is not None
    assert (
        latest["id"],
        latest["state"],
        latest["actor_kind"],
        latest["trigger"],
        latest["parent_run_id"],
        latest["hints"],
        latest["model"],
        latest["error_code"],
        latest["finished_at"],
    ) == (
        str(second.id),
        "requested",
        "user",
        "rerun",
        str(first_id),
        {"keywords": ["interest"], "note": "Credits."},
        "vendor/vision-x",
        None,
        None,
    )


async def test_get_runs_shows_two_runs_with_identical_results_as_two_rows(
    client, db, monkeypatch, storage_stub, test_user
):
    statement = await _statement(db, test_user)
    _capture_dispatch(monkeypatch)
    assert (
        await client.post(f"/statements/{statement.id}/runs", json={"hints": {"keywords": ["one"]}})
    ).status_code == 202
    await fail_run(db, (await _runs(db, statement.id))[0].id, error_code="done", error_message="Ended for the test.")
    await db.commit()
    assert (
        await client.post(f"/statements/{statement.id}/runs", json={"hints": {"keywords": ["two"]}})
    ).status_code == 202
    items = (await client.get(f"/statements/{statement.id}/runs")).json()["items"]
    assert ([item["hints"]["keywords"] for item in items], [item["seq"] for item in items]) == (
        [["one"], ["two"]],
        [1, 2],
    )


async def test_get_runs_empty_and_scoped_to_owner(client, db, test_user):
    own_stmt = await _statement(db, test_user)
    other = await UserFactory.create_async(db)
    foreign_stmt = await _statement(db, other)
    await create_run(
        db,
        statement_id=foreign_stmt.id,
        user_id=other.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(keywords=["secret"]),
    )
    await db.commit()

    own_resp, foreign_resp = (
        await client.get(f"/statements/{own_stmt.id}/runs"),
        await client.get(f"/statements/{foreign_stmt.id}/runs"),
    )
    assert own_resp.status_code == 200 and own_resp.json() == {"items": [], "total": 0}
    assert foreign_resp.status_code == 404 and "secret" not in foreign_resp.text
    assert [r.seq for r in await list_runs(db, foreign_stmt.id, other.id)] == [1] and await list_runs(
        db, foreign_stmt.id, uuid4()
    ) == []


async def test_the_retry_route_and_its_request_schema_are_gone(client, db, test_user):
    statement = await _statement(db, test_user)
    assert (await client.post(f"/statements/{statement.id}/retry", json={})).status_code in (404, 405)
    paths, components = app.openapi()["paths"], app.openapi()["components"]["schemas"]
    assert not [p for p in paths if p.endswith("/retry")] and set(paths["/statements/{statement_id}/runs"]) == {
        "get",
        "post",
    }
    assert (
        not hasattr(schemas, "RetryParsingRequest")
        and "RetryParsingRequest" not in components
        and "StatementRunRecord" in components
        and "StatementRunResponse" not in components
    )


@pytest.mark.parametrize(
    ("action", "payload", "race_status"),
    [
        ("runs", {}, BankStatementStatus.APPROVED),
        ("rejections", {"notes": "check again"}, BankStatementStatus.RETIRED),
    ],
)
async def test_status_change_after_initial_read_gives_409_and_no_write(
    client, db, monkeypatch, storage_stub, test_user, action, payload, race_status
):
    statement = await _statement(db, test_user)
    values = {"status": race_status}
    if race_status is BankStatementStatus.APPROVED:
        values["account_id"] = (await create_statement_account(db, test_user.id)).id
        await db.commit()
    jobs = _capture_dispatch(monkeypatch)
    maker, original = create_session_maker_from_db(db), statement_pipeline.resolve_uploaded_document

    async def resolve_after_race(*args, **kwargs):
        async with maker() as other_tab:
            await other_tab.execute(
                update(StatementSummary).where(StatementSummary.id == statement.id).values(**values)
            )
            await other_tab.commit()
        return await original(*args, **kwargs)

    monkeypatch.setattr("src.routers.statements._resolve_uploaded_document", resolve_after_race)
    assert (await client.post(f"/statements/{statement.id}/{action}", json=payload)).status_code == 409
    row = await db.scalar(
        select(StatementSummary).where(StatementSummary.id == statement.id).execution_options(populate_existing=True)
    )
    assert row.status is race_status and await _runs(db, statement.id) == [] and jobs == []


@pytest.mark.parametrize(("filename", "expected_note"), [("bank.csv", None), ("bank.pdf", "check the dates")])
async def test_reject_records_hints_only_for_prompt_file_types(
    client, db, monkeypatch, storage_stub, test_user, filename, expected_note
):
    statement = await _statement(db, test_user, name=filename)
    _capture_dispatch(monkeypatch)
    assert (
        await client.post(f"/statements/{statement.id}/rejections", json={"notes": "check the dates"})
    ).status_code == 200
    (run,) = await _runs(db, statement.id)
    assert run.hints == {"keywords": [], "note": expected_note}


@pytest.mark.no_db
@pytest.mark.parametrize(
    "file_type,applies", [("pdf", True), ("png", True), ("jpg", True), ("jpeg", True), ("csv", False)]
)
def test_hints_apply_only_to_the_file_types_that_send_a_prompt(file_type, applies):
    assert hints_apply_to_file_type(file_type) is applies


async def test_get_runs_lists_a_run_whose_stored_hints_no_longer_validate(client, db, test_user):
    statement = await _statement(db, test_user)
    run_id = await _failed_first_run(db, test_user, statement.id)
    await db.execute(
        update(StatementRun).where(StatementRun.id == run_id).values(hints={"keywords": ["ok"], "note": "bell\x07"})
    )
    await db.commit()
    assert (resp := await client.get(f"/statements/{statement.id}/runs")).status_code == 200 and resp.json()["items"][
        0
    ]["hints"]["keywords"] == ["ok"]


async def test_hints_on_a_csv_statement_give_400_before_any_storage_read(client, db, monkeypatch, test_user):
    statement = await _statement(db, test_user, name="bank.csv")
    mock_storage = failing_storage(monkeypatch, method="get_object")
    assert (
        await client.post(f"/statements/{statement.id}/runs", json={"hints": {"keywords": ["x"]}})
    ).status_code == 400 and await _runs(db, statement.id) == []
    mock_storage.get_object.assert_not_called()


async def test_a_reject_and_a_rerun_at_once_give_one_winner_and_one_409(
    client, db, monkeypatch, storage_stub, test_user
):
    _capture_dispatch(monkeypatch)
    for round_number in range(6):
        statement = await _statement(db, test_user)
        first, second = await asyncio.gather(
            client.post(f"/statements/{statement.id}/rejections", json={"notes": "again"}),
            client.post(f"/statements/{statement.id}/runs", json={})
            if round_number % 2
            else client.post(f"/statements/{statement.id}/rejections", json={"notes": "twice"}),
        )
        codes = sorted([first.status_code, second.status_code])
        assert codes[1] == 409 and codes[0] in (200, 202) and len(await _runs(db, statement.id)) == 1
        row = await db.scalar(
            select(StatementSummary)
            .where(StatementSummary.id == statement.id)
            .execution_options(populate_existing=True)
        )
        assert row.status is BankStatementStatus.PARSING


async def test_classify_run_dispatch_failure_and_rejections_validation(client, db, monkeypatch, test_user):
    sid = (await _statement(db, test_user)).id
    monkeypatch.setattr(
        "src.routers.statements.submit_classify_run",
        lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("secret dispatch failure")),
    )
    assert (
        await client.post(
            f"/statements/{sid}/runs", json={"kind": "classify", "hints": {"keywords": ["Grab"], "note": "Check"}}
        )
    ).status_code == 503
    assert len(runs := await _runs(db, sid)) == 1 and runs[0].error_code == "dispatch_failed"
    assert (
        bad := await client.post(f"/statements/{sid}/rejections", json={"notes": "bell\x07"})
    ).status_code == 422 and {"loc", "msg", "type"} <= set(bad.json()["detail"][0])


async def test_post_runs_starts_a_rerun_with_no_model(client, db, monkeypatch, storage_stub, test_user):
    """A rerun has no model field: the run records none and the job carries none (#2953)."""
    statement = await _statement(db, test_user, status=BankStatementStatus.REJECTED)
    jobs = _capture_dispatch(monkeypatch)

    response = await client.post(f"/statements/{statement.id}/runs", json={})

    assert response.status_code == 202, response.text
    assert (response.json()["model"], len(jobs)) == (None, 1)


async def _finished_run(db, user, statement_id, kind: RunKind, result_summary: dict):
    run = await create_run(
        db,
        statement_id=statement_id,
        user_id=user.id,
        kind=kind,
        actor_kind=RunActorKind.SYSTEM,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(),
    )
    await claim_run(db, run.id)
    await finish_run(db, run.id, result_summary=result_summary)
    await db.commit()
    return run.id


async def test_get_runs_returns_the_outcome_of_a_classify_run_and_null_for_an_extract_run(client, db, test_user):
    """#3029 item 4: a classify run that ended `partial` has state `succeeded`; the list also returns the outcome."""
    statement = await _statement(db, test_user)
    await _finished_run(db, test_user, statement.id, RunKind.EXTRACT, {"auto_approve_candidate": True})
    await _finished_run(db, test_user, statement.id, RunKind.CLASSIFY, {"outcome": "partial", "asked": 3})
    await _finished_run(db, test_user, statement.id, RunKind.CLASSIFY, {"outcome": 7})

    items = (await client.get(f"/statements/{statement.id}/runs")).json()["items"]

    assert [(item["kind"], item["state"], item["outcome"]) for item in items] == [
        ("extract", "succeeded", None),
        ("classify", "succeeded", "partial"),
        ("classify", "succeeded", None),
    ]


async def test_statement_list_returns_the_kind_of_the_active_run(client, db, test_user):
    """#3029 item 1: a statement stays `parsed` during a classify run; the list item names the active run."""
    active = await _statement(db, test_user, name="active.pdf")
    ended = await _statement(db, test_user, name="ended.pdf")
    idle = await _statement(db, test_user, name="idle.pdf")
    await create_run(
        db,
        statement_id=active.id,
        user_id=test_user.id,
        kind=RunKind.CLASSIFY,
        actor_kind=RunActorKind.SYSTEM,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(),
    )
    await _finished_run(db, test_user, ended.id, RunKind.CLASSIFY, {"outcome": "classified"})

    items = (await client.get("/statements")).json()["items"]

    assert {item["id"]: item["active_run_kind"] for item in items} == {
        str(active.id): "classify",
        str(ended.id): None,
        str(idle.id): None,
    }
    # The detail route returns the same field.
    assert (await client.get(f"/statements/{active.id}")).json()["active_run_kind"] == "classify"
    assert (await client.get(f"/statements/{idle.id}")).json()["active_run_kind"] is None
