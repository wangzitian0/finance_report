"""The envelope confirmation refuses a statement that a rerun parses again (#2994, slice S2 review).

A stale tab that loaded the statement as PARSED can confirm its envelope after another tab started a rerun.
The rerun leaves `current_extraction_result_id` unchanged, so the old digest still matches. The confirmation
must still refuse: it would write PARSED while an extract run is active, and the finalize of the run would then
overwrite the status over posted entries. The refusal is a 409 with the id of the run. A classify run writes
answers of rows, not source facts: the confirmation right after an upload passes during it (#2994).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    ActiveRunExists,
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


async def _commit_a_rerun_in_another_tab(db, user, statement_id):
    """Commit the run and the status PARSING of a rerun. The current extraction result stays as it is."""
    maker = create_session_maker_from_db(db)
    async with maker() as other_tab:
        run = await create_run(
            other_tab,
            statement_id=statement_id,
            user_id=user.id,
            kind=RunKind.EXTRACT,
            actor_kind=RunActorKind.USER,
            trigger=RunTrigger.RERUN,
            hints=RunHints(),
        )
        await other_tab.execute(
            update(StatementSummary)
            .where(StatementSummary.id == statement_id)
            .values(status=BankStatementStatus.PARSING)
        )
        await other_tab.commit()
    return run.id


async def _status(db, statement_id) -> BankStatementStatus:
    row = await db.scalar(
        select(StatementSummary).where(StatementSummary.id == statement_id).execution_options(populate_existing=True)
    )
    return row.status


async def test_AC_extraction_2994_86_a_stale_tab_cannot_confirm_an_envelope_while_a_rerun_parses(db, test_user):
    """AC-extraction.2994.86: The confirmation refuses a statement with an active run and leaves its status."""
    statement, account, result, _record = await _seed_statement_source_and_account(
        db, test_user, source_digest="b" * 64
    )
    statement_id, user_id = statement.id, test_user.id
    command = _command(account_id=account.id, source_result_digest=result.content_digest)
    await _commit_a_rerun_in_another_tab(db, test_user, statement_id)

    with pytest.raises(ActiveRunExists):
        await _confirm(db, user_id=user_id, statement_id=statement_id, command=command)
    await db.rollback()

    assert await _status(db, statement_id) is BankStatementStatus.PARSING, "the confirmation must not write PARSED"
    assert await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement_id) is None


async def test_AC_extraction_2994_86_the_replay_of_a_confirmed_envelope_is_refused_while_a_rerun_parses(db, test_user):
    """AC-extraction.2994.86: The idempotent replay of the same command refuses too, and leaves the status."""
    statement, account, result, _record = await _seed_statement_source_and_account(
        db, test_user, source_digest="c" * 64
    )
    statement_id = statement.id
    command = _command(account_id=account.id, source_result_digest=result.content_digest)
    await _confirm(db, user_id=test_user.id, statement_id=statement_id, command=command)
    await db.commit()
    await _commit_a_rerun_in_another_tab(db, test_user, statement_id)

    with pytest.raises(ActiveRunExists):
        await _confirm(db, user_id=test_user.id, statement_id=statement_id, command=command)
    await db.rollback()

    assert await _status(db, statement_id) is BankStatementStatus.PARSING


async def test_AC_extraction_2994_86_a_confirmation_still_works_after_a_finished_run(db, test_user):
    """AC-extraction.2994.86: A finished run is not an active run: the confirmation writes PARSED as before."""
    statement, account, result, _record = await _seed_statement_source_and_account(
        db, test_user, source_digest="d" * 64
    )
    statement_id = statement.id
    run = await create_run(
        db,
        statement_id=statement_id,
        user_id=test_user.id,
        kind=RunKind.EXTRACT,
        actor_kind=RunActorKind.USER,
        trigger=RunTrigger.UPLOAD,
        hints=RunHints(),
    )
    await claim_run(db, run.id)
    await finish_run(db, run.id)
    await db.commit()

    envelope = await _confirm(
        db,
        user_id=test_user.id,
        statement_id=statement_id,
        command=_command(account_id=account.id, source_result_digest=result.content_digest),
    )
    await db.commit()

    assert envelope is not None
    assert await _status(db, statement_id) is BankStatementStatus.PARSED


async def test_AC_extraction_2994_86_an_active_run_blocks_the_confirmation_whatever_the_status_says(db, test_user):
    """AC-extraction.2994.86: The guard looks at the run, not only at the status: PARSED plus an active run refuses."""
    statement, account, result, _record = await _seed_statement_source_and_account(
        db, test_user, source_digest="e" * 64
    )
    statement_id, user_id = statement.id, test_user.id
    command = _command(account_id=account.id, source_result_digest=result.content_digest)
    maker = create_session_maker_from_db(db)
    async with maker() as other_tab:
        await create_run(
            other_tab,
            statement_id=statement_id,
            user_id=user_id,
            kind=RunKind.EXTRACT,
            actor_kind=RunActorKind.SYSTEM,
            trigger=RunTrigger.AUTO_RETRY,
            hints=RunHints(),
        )
        await other_tab.commit()  # The status stays PARSED.

    with pytest.raises(ActiveRunExists):
        await _confirm(db, user_id=user_id, statement_id=statement_id, command=command)
    await db.rollback()

    assert await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement_id) is None


async def _commit_active_run(db, user, statement_id, kind: RunKind, *, running: bool = False):
    """Commit an active run of the given kind from another session, as the worker or a route does."""
    maker = create_session_maker_from_db(db)
    async with maker() as other_tab:
        run = await create_run(
            other_tab,
            statement_id=statement_id,
            user_id=user.id,
            kind=kind,
            actor_kind=RunActorKind.SYSTEM,
            trigger=RunTrigger.AUTO_CLASSIFY if kind is RunKind.CLASSIFY else RunTrigger.AUTO_RETRY,
            hints=RunHints(),
        )
        if running:
            await claim_run(other_tab, run.id)
        await other_tab.commit()
    return run.id


@pytest.mark.parametrize("running", [False, True])
async def test_AC_extraction_2994_110_a_confirmation_passes_while_a_classify_run_is_active(db, test_user, running):
    """AC-extraction.2994.110: The envelope holds source facts: the automatic classify run after an upload does not block it."""
    statement, account, result, _record = await _seed_statement_source_and_account(
        db, test_user, source_digest=("1" if running else "2") * 64
    )
    statement_id, user_id = statement.id, test_user.id
    command = _command(account_id=account.id, source_result_digest=result.content_digest)
    run_id = await _commit_active_run(db, test_user, statement_id, RunKind.CLASSIFY, running=running)

    envelope = await _confirm(db, user_id=user_id, statement_id=statement_id, command=command)
    await db.commit()

    assert envelope is not None
    assert await _status(db, statement_id) is BankStatementStatus.PARSED
    assert (await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement_id)) is not None
    run = await db.scalar(
        select(StatementRun).where(StatementRun.id == run_id).execution_options(populate_existing=True)
    )
    assert run.state is (RunState.RUNNING if running else RunState.REQUESTED), "the confirmation does not touch the run"


async def test_AC_extraction_2994_110_the_replay_of_a_confirmed_envelope_passes_while_a_classify_run_is_active(
    db, test_user
):
    """AC-extraction.2994.110: The replay branch has the same rule: it passes during a classify run."""
    statement, account, result, _record = await _seed_statement_source_and_account(
        db, test_user, source_digest="3" * 64
    )
    statement_id, user_id = statement.id, test_user.id
    command = _command(account_id=account.id, source_result_digest=result.content_digest)
    first = await _confirm(db, user_id=user_id, statement_id=statement_id, command=command)
    first_id = first.id
    await db.commit()
    await _commit_active_run(db, test_user, statement_id, RunKind.CLASSIFY)

    replay = await _confirm(db, user_id=user_id, statement_id=statement_id, command=command)
    await db.commit()

    assert replay.id == first_id


async def test_AC_extraction_2994_110_an_active_extract_run_refuses_with_its_id(db, test_user):
    """AC-extraction.2994.110: An active extract run, requested or running, gives ActiveRunExists with the run id."""
    statement, account, result, _record = await _seed_statement_source_and_account(
        db, test_user, source_digest="4" * 64
    )
    statement_id, user_id = statement.id, test_user.id
    command = _command(account_id=account.id, source_result_digest=result.content_digest)
    run_id = await _commit_active_run(db, test_user, statement_id, RunKind.EXTRACT, running=True)

    with pytest.raises(ActiveRunExists) as caught:
        await _confirm(db, user_id=user_id, statement_id=statement_id, command=command)
    await db.rollback()

    assert caught.value.active_run_id == run_id
    assert await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement_id) is None


async def test_AC_extraction_2994_110_the_route_answers_200_during_a_classify_run_and_409_during_an_extract_run(
    client, db, test_user
):
    """AC-extraction.2994.110: POST review/envelope right after an upload works; during a parse it answers 409 with the run id."""
    import json
    from dataclasses import asdict

    classify_statement, classify_account, classify_result, _ = await _seed_statement_source_and_account(
        db, test_user, source_digest="5" * 64
    )
    extract_statement, extract_account, extract_result, _ = await _seed_statement_source_and_account(
        db, test_user, source_digest="6" * 64
    )
    classify_id, extract_id = classify_statement.id, extract_statement.id
    classify_body = json.loads(
        json.dumps(
            asdict(_command(account_id=classify_account.id, source_result_digest=classify_result.content_digest)),
            default=str,
        )
    )
    extract_body = json.loads(
        json.dumps(
            asdict(_command(account_id=extract_account.id, source_result_digest=extract_result.content_digest)),
            default=str,
        )
    )
    await _commit_active_run(db, test_user, classify_id, RunKind.CLASSIFY)
    extract_run_id = await _commit_active_run(db, test_user, extract_id, RunKind.EXTRACT)

    passed = await client.post(f"/statements/{classify_id}/review/envelope", json=classify_body)
    refused = await client.post(f"/statements/{extract_id}/review/envelope", json=extract_body)

    assert passed.status_code == 200, passed.text
    assert refused.status_code == 409, refused.text
    assert refused.json()["active_run_id"] == str(extract_run_id)
