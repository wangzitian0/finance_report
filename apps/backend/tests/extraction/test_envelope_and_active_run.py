"""The envelope confirmation refuses a statement that a rerun parses again (#2994, slice S2 review).

A stale tab that loaded the statement as PARSED can confirm its envelope after another tab started a rerun.
The rerun leaves `current_extraction_result_id` unchanged, so the old digest still matches. The confirmation
must still refuse: it would write PARSED while a run is active, and the finalize of the run would then
overwrite the status over posted entries.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    RunActorKind,
    RunHints,
    RunKind,
    RunTrigger,
    StatementSummary,
    claim_run,
    create_run,
    finish_run,
)
from src.extraction.extension.reviewed_statement_envelope import current_reviewed_statement_envelope
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
            update(StatementSummary).where(StatementSummary.id == statement_id).values(status=BankStatementStatus.PARSING)
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
    statement, account, result, _record = await _seed_statement_source_and_account(db, test_user, source_digest="b" * 64)
    statement_id, user_id = statement.id, test_user.id
    command = _command(account_id=account.id, source_result_digest=result.content_digest)
    await _commit_a_rerun_in_another_tab(db, test_user, statement_id)

    with pytest.raises(ValueError, match="parsing"):
        await _confirm(db, user_id=user_id, statement_id=statement_id, command=command)
    await db.rollback()

    assert await _status(db, statement_id) is BankStatementStatus.PARSING, "the confirmation must not write PARSED"
    assert await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement_id) is None


async def test_AC_extraction_2994_86_the_replay_of_a_confirmed_envelope_is_refused_while_a_rerun_parses(db, test_user):
    """AC-extraction.2994.86: The idempotent replay of the same command refuses too, and leaves the status."""
    statement, account, result, _record = await _seed_statement_source_and_account(db, test_user, source_digest="c" * 64)
    statement_id = statement.id
    command = _command(account_id=account.id, source_result_digest=result.content_digest)
    await _confirm(db, user_id=test_user.id, statement_id=statement_id, command=command)
    await db.commit()
    await _commit_a_rerun_in_another_tab(db, test_user, statement_id)

    with pytest.raises(ValueError, match="parsing"):
        await _confirm(db, user_id=test_user.id, statement_id=statement_id, command=command)
    await db.rollback()

    assert await _status(db, statement_id) is BankStatementStatus.PARSING


async def test_AC_extraction_2994_86_a_confirmation_still_works_after_a_finished_run(db, test_user):
    """AC-extraction.2994.86: A finished run is not an active run: the confirmation writes PARSED as before."""
    statement, account, result, _record = await _seed_statement_source_and_account(db, test_user, source_digest="d" * 64)
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
    statement, account, result, _record = await _seed_statement_source_and_account(db, test_user, source_digest="e" * 64)
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

    with pytest.raises(ValueError, match="parsing"):
        await _confirm(db, user_id=user_id, statement_id=statement_id, command=command)
    await db.rollback()

    assert await current_reviewed_statement_envelope(db, user_id=user_id, statement_id=statement_id) is None
