"""The envelope confirmation refuses a statement that a rerun parses again (#2994, slice S2 review)."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest
from sqlalchemy import select, update

from src.database import create_session_maker_from_db
from src.extraction import (
    ActiveRunExists,
    BankStatementStatus,
    RunActorKind,
    RunHints,
    RunKind,
    RunState,
    RunTrigger,
    StatementSummary,
    claim_run,
    create_run,
    finish_run,
)
from src.extraction.extension.reviewed_statement_envelope import current_reviewed_statement_envelope
from src.extraction.orm.statement_run import StatementRun
from tests.extraction.test_reviewed_statement_envelope import _command, _confirm, _seed_statement_source_and_account

pytestmark = pytest.mark.asyncio


async def _commit_active_run(db, user_id, statement_id, kind: RunKind, *, running: bool = False, parsing: bool = False):
    async with create_session_maker_from_db(db)() as other_tab:
        run = await create_run(
            other_tab,
            statement_id=statement_id,
            user_id=user_id,
            kind=kind,
            actor_kind=RunActorKind.USER if kind is RunKind.EXTRACT else RunActorKind.SYSTEM,
            trigger=RunTrigger.RERUN if kind is RunKind.EXTRACT and parsing else (RunTrigger.AUTO_CLASSIFY if kind is RunKind.CLASSIFY else RunTrigger.AUTO_RETRY),
            hints=RunHints(),
        )
        if parsing:
            await other_tab.execute(update(StatementSummary).where(StatementSummary.id == statement_id).values(status=BankStatementStatus.PARSING))
        if running:
            await claim_run(other_tab, run.id)
        await other_tab.commit()
    return run.id


async def _status(db, statement_id) -> BankStatementStatus:
    return (await db.scalar(select(StatementSummary).where(StatementSummary.id == statement_id).execution_options(populate_existing=True))).status


@pytest.mark.parametrize(("replay", "parsing", "digest"), [(False, True, "b"), (True, True, "c"), (False, False, "e")])
async def test_AC_extraction_2994_86_active_extract_blocks_confirm(db, test_user, replay, parsing, digest):
    statement, account, result, _ = await _seed_statement_source_and_account(db, test_user, source_digest=digest * 64)
    statement_id, user_id = statement.id, test_user.id
    command = _command(account_id=account.id, source_result_digest=result.content_digest)
    if replay:
        await _confirm(db, user_id=user_id, statement_id=statement_id, command=command)
        await db.commit()
    run_id = await _commit_active_run(db, user_id, statement_id, RunKind.EXTRACT, running=not parsing, parsing=parsing)
    with pytest.raises(ActiveRunExists) as caught:
        await _confirm(db, user_id=user_id, statement_id=statement_id, command=command)
    await db.rollback()
    assert caught.value.active_run_id == run_id
    if parsing:
        assert await _status(db, statement_id) is BankStatementStatus.PARSING
    if not replay:
        assert await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement_id) is None


async def test_AC_extraction_2994_86_a_confirmation_still_works_after_a_finished_run(db, test_user):
    statement, account, result, _ = await _seed_statement_source_and_account(db, test_user, source_digest="d" * 64)
    statement_id, user_id = statement.id, test_user.id
    run = await create_run(db, statement_id=statement_id, user_id=user_id, kind=RunKind.EXTRACT, actor_kind=RunActorKind.USER, trigger=RunTrigger.UPLOAD, hints=RunHints())
    await claim_run(db, run.id)
    await finish_run(db, run.id)
    await db.commit()
    envelope = await _confirm(db, user_id=user_id, statement_id=statement_id, command=_command(account_id=account.id, source_result_digest=result.content_digest))
    await db.commit()
    assert envelope is not None and await _status(db, statement_id) is BankStatementStatus.PARSED


@pytest.mark.parametrize("running", [False, True])
async def test_AC_extraction_2994_110_a_confirmation_passes_while_a_classify_run_is_active(db, test_user, running):
    statement, account, result, _ = await _seed_statement_source_and_account(db, test_user, source_digest=("1" if running else "2") * 64)
    statement_id, user_id = statement.id, test_user.id
    command = _command(account_id=account.id, source_result_digest=result.content_digest)
    run_id = await _commit_active_run(db, user_id, statement_id, RunKind.CLASSIFY, running=running)
    envelope = await _confirm(db, user_id=user_id, statement_id=statement_id, command=command)
    await db.commit()
    run = await db.scalar(select(StatementRun).where(StatementRun.id == run_id).execution_options(populate_existing=True))
    assert (envelope is not None, await _status(db, statement_id), (await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement_id)) is not None, run.state) == (
        True, BankStatementStatus.PARSED, True, RunState.RUNNING if running else RunState.REQUESTED
    )


async def test_AC_extraction_2994_110_the_replay_of_a_confirmed_envelope_passes_while_a_classify_run_is_active(db, test_user):
    statement, account, result, _ = await _seed_statement_source_and_account(db, test_user, source_digest="3" * 64)
    statement_id, user_id = statement.id, test_user.id
    command = _command(account_id=account.id, source_result_digest=result.content_digest)
    first_id = (await _confirm(db, user_id=user_id, statement_id=statement_id, command=command)).id
    await db.commit()
    await _commit_active_run(db, user_id, statement_id, RunKind.CLASSIFY)
    replay = await _confirm(db, user_id=user_id, statement_id=statement_id, command=command)
    await db.commit()
    assert replay.id == first_id


async def test_AC_extraction_2994_110_the_route_answers_200_during_a_classify_run_and_409_during_an_extract_run(client, db, test_user):
    c_stmt, c_acct, c_res, _ = await _seed_statement_source_and_account(db, test_user, source_digest="5" * 64)
    e_stmt, e_acct, e_res, _ = await _seed_statement_source_and_account(db, test_user, source_digest="6" * 64)
    await _commit_active_run(db, test_user.id, c_stmt.id, RunKind.CLASSIFY)
    extract_run_id = await _commit_active_run(db, test_user.id, e_stmt.id, RunKind.EXTRACT)
    passed = await client.post(f"/statements/{c_stmt.id}/review-envelopes", json=json.loads(json.dumps(asdict(_command(account_id=c_acct.id, source_result_digest=c_res.content_digest)), default=str)))
    refused = await client.post(f"/statements/{e_stmt.id}/review-envelopes", json=json.loads(json.dumps(asdict(_command(account_id=e_acct.id, source_result_digest=e_res.content_digest)), default=str)))
    assert (passed.status_code, refused.status_code, refused.json()["active_run_id"]) == (200, 409, str(extract_run_id))
