from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, TraceDecisionPolicyRegistry, TraceEmitter
from src.audit.extension.trace_repository import SqlTraceRecordRepository
from src.ledger import (
    PROCESSING_ACCOUNT_CODE,
    Account,
    AccountType,
    AnchoredJournalCommand,
    DecisionAnchor,
    DecisionAnchorError,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    submit_anchored_journal_entries,
    submit_anchored_journal_entry,
)
from src.ledger.base.decision_anchor import journal_command_target
from src.ledger.base.validators import ValidationError
from src.ledger.extension import anchored_posting
from src.ledger.extension.repository import post_journal_entries
from tests.ledger._ledger_helpers import lines_pair, make_account
from tests.ledger.test_decision_anchor import _Policy, _TraceRepository, _decision_records

pytestmark = pytest.mark.asyncio
ENTRY_DATE = date(2026, 7, 18)


from contextlib import contextmanager

@contextmanager
def _capture_sql(db: AsyncSession):
    texts: list[str] = []
    capture = lambda _c, _cur, stmt, _p, _ctx, _m: texts.append(stmt)
    event.listen(db.bind.sync_engine, "before_cursor_execute", capture)
    try:
        yield texts
    finally:
        event.remove(db.bind.sync_engine, "before_cursor_execute", capture)


async def _accounts(db: AsyncSession, user_id: UUID, *, debit_code: str | None = None) -> tuple[Account, Account]:
    return (
        await make_account(db, user_id, f"batch cash {uuid4()}", AccountType.ASSET, code=debit_code),
        await make_account(db, user_id, f"batch income {uuid4()}", AccountType.INCOME),
    )


async def _commands(
    db: AsyncSession,
    user_id: UUID,
    count: int,
    *,
    accounts: tuple[Account, Account] | None = None,
    source_type: JournalEntrySourceType = JournalEntrySourceType.AUTO_PARSED,
    post_immediately: bool = True,
    repository: SqlTraceRecordRepository | None = None,
) -> tuple[list[AnchoredJournalCommand], SqlTraceRecordRepository]:
    debit, credit = accounts or await _accounts(db, user_id)
    repository = repository or SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((_Policy(),)))
    commands: list[AnchoredJournalCommand] = []
    for index in range(count):
        source_id = uuid4()
        lines_data = lines_pair(debit.id, credit.id, Decimal("10.00") + index)
        memo = f"Batch command {index}"
        source_identity = f"statement-transaction:{source_id}"
        target = journal_command_target(
            entry_date=ENTRY_DATE, memo=memo, lines_data=lines_data, base_currency="SGD", source_identity=source_identity
        )
        obs, dec = _decision_records(user_id=user_id, target=target)
        await TraceEmitter(repository).emit_many((obs, dec))
        commands.append(
            AnchoredJournalCommand.from_mappings(
                entry_date=ENTRY_DATE,
                memo=memo,
                lines_data=lines_data,
                base_currency="SGD",
                source_type=source_type,
                source_id=source_id,
                source_identity=source_identity,
                decision_anchor=DecisionAnchor.from_record(dec),
                post_immediately=post_immediately,
            )
        )
    return commands, repository


async def _described(db: AsyncSession, entries: list[JournalEntry]) -> list[dict]:
    described = []
    for entry in sorted(entries, key=lambda item: item.memo):
        lines = (await db.execute(select(JournalLine).where(JournalLine.journal_entry_id == entry.id))).scalars().all()
        described.append(
            {
                "entry_date": entry.entry_date,
                "memo": entry.memo,
                "status": entry.status,
                "source_type": entry.source_type,
                "source_id": entry.source_id,
                "base_currency": entry.base_currency,
                "decision_anchor_id": entry.decision_anchor_id,
                "authority": entry.decision_authority_state,
                "lines": sorted((ln.line_no, ln.account_id, ln.direction, ln.amount, ln.currency, ln.fx_rate) for ln in lines),
            }
        )
    return described


async def test_batch_matches_sequential_and_has_constant_statement_count(db, test_user) -> None:
    accounts = await _accounts(db, test_user.id)
    commands, repository = await _commands(db, test_user.id, 5, accounts=accounts)
    nested = await db.begin_nested()
    batch = await submit_anchored_journal_entries(db, user_id=test_user.id, commands=commands, base_currency="SGD", trace_repository=repository)
    batch_facts = await _described(db, batch)
    await nested.rollback()
    assert await db.scalar(select(func.count()).select_from(JournalEntry)) == 0

    sequential = [
        await submit_anchored_journal_entry(db, user_id=test_user.id, command=cmd, base_currency="SGD", trace_repository=repository)
        for cmd in commands
    ]
    assert [e.memo for e in batch] == [c.memo for c in commands] == [e.memo for e in sequential]
    assert len(batch_facts) == 5 and all(f["status"] is JournalEntryStatus.POSTED for f in batch_facts)
    assert batch_facts == await _described(db, sequential)

    small, _ = await _commands(db, test_user.id, 2, accounts=accounts, repository=repository)
    large, _ = await _commands(db, test_user.id, 30, accounts=accounts, repository=repository)
    with _capture_sql(db) as small_run:
        await submit_anchored_journal_entries(db, user_id=test_user.id, commands=small, base_currency="SGD", trace_repository=repository)
    with _capture_sql(db) as large_run:
        await submit_anchored_journal_entries(db, user_id=test_user.id, commands=large, base_currency="SGD", trace_repository=repository)
    assert len(large_run) == len(small_run) <= 10


async def test_batch_idempotency_conflict_and_atomicity(db, test_user) -> None:
    commands, repository = await _commands(db, test_user.id, 3)
    mismatched = replace(commands[1], decision_anchor=commands[0].decision_anchor)
    with pytest.raises(DecisionAnchorError, match="target"):
        await submit_anchored_journal_entries(db, user_id=test_user.id, commands=[commands[0], mismatched, commands[2]], base_currency="SGD", trace_repository=repository)
    assert await db.scalar(select(func.count()).select_from(JournalEntry)) == 0

    first = await submit_anchored_journal_entries(db, user_id=test_user.id, commands=commands, base_currency="SGD", trace_repository=repository)
    again = await submit_anchored_journal_entries(db, user_id=test_user.id, commands=commands, base_currency="SGD", trace_repository=repository)
    assert [e.id for e in again] == [e.id for e in first] and await db.scalar(select(func.count()).select_from(JournalEntry)) == 3

    cmd = commands[0]
    target = journal_command_target(entry_date=ENTRY_DATE, memo=cmd.memo, lines_data=cmd.lines_data, base_currency="SGD", source_identity=cmd.source_identity)
    replacement = _decision_records(user_id=test_user.id, target=target, execution_id="replacement")[-1]
    with pytest.raises(DecisionAnchorError, match="different decision already owns"):
        await submit_anchored_journal_entries(
            db,
            user_id=test_user.id,
            commands=[replace(cmd, decision_anchor=DecisionAnchor.from_record(replacement))],
            base_currency="SGD",
            trace_repository=_TraceRepository((replacement,), current=replacement),
        )
    assert await db.scalar(select(func.count()).select_from(JournalEntry)) == 3


async def test_batch_mixed_statuses_dedup_processing_and_chunked_reads(db, test_user) -> None:
    posted_cmds, repository = await _commands(db, test_user.id, 2)
    draft_cmds, _ = await _commands(db, test_user.id, 2, post_immediately=False, repository=repository)
    entries = await submit_anchored_journal_entries(
        db, user_id=test_user.id, commands=[posted_cmds[0], draft_cmds[0], posted_cmds[1], draft_cmds[1]], base_currency="SGD", trace_repository=repository
    )
    assert [e.status for e in entries] == [JournalEntryStatus.POSTED, JournalEntryStatus.DRAFT, JournalEntryStatus.POSTED, JournalEntryStatus.DRAFT]
    assert await submit_anchored_journal_entries(db, user_id=test_user.id, commands=[], base_currency="SGD", trace_repository=repository) == []

    dup = await submit_anchored_journal_entries(db, user_id=test_user.id, commands=[posted_cmds[0], posted_cmds[0]], base_currency="SGD", trace_repository=repository)
    assert dup[0].id == dup[1].id

    proc_acc = await _accounts(db, test_user.id, debit_code=PROCESSING_ACCOUNT_CODE)
    sys_cmd, _ = await _commands(db, test_user.id, 1, accounts=proc_acc, source_type=JournalEntrySourceType.SYSTEM, repository=repository)
    ok_proc = await submit_anchored_journal_entries(db, user_id=test_user.id, commands=sys_cmd, base_currency="SGD", trace_repository=repository)
    assert ok_proc[0].status == JournalEntryStatus.POSTED
    bad_proc, _ = await _commands(db, test_user.id, 1, accounts=proc_acc, repository=repository)
    with pytest.raises(ValidationError, match="Processing account"):
        await submit_anchored_journal_entries(db, user_id=test_user.id, commands=bad_proc, base_currency="SGD", trace_repository=repository)

    targets = [journal_command_target(entry_date=c.entry_date, memo=c.memo, lines_data=c.lines_data, base_currency="SGD", source_identity=c.source_identity) for c in posted_cmds + draft_cmds + sys_cmd]
    with patch.object(anchored_posting, "_TARGET_READ_CHUNK_SIZE", 2), _capture_sql(db) as statements:
        owners = await anchored_posting._existing_for_targets(db, user_id=test_user.id, targets=targets)
    assert {o.id for o in owners.values()} == {e.id for e in entries + ok_proc} and len(statements) == 4
    duplicate = MagicMock()
    duplicate.all.return_value = [(entries[0], "journal_command", "t"), (entries[1], "journal_command", "t")]
    fake_db = AsyncMock()
    fake_db.execute.return_value = duplicate
    with pytest.raises(MultipleResultsFound):
        await anchored_posting._existing_for_targets(fake_db, user_id=test_user.id, targets=targets[:1])


async def test_post_journal_entries_checks_each_entry(db, test_user) -> None:
    commands, repository = await _commands(db, test_user.id, 3, post_immediately=False)
    drafts = await submit_anchored_journal_entries(db, user_id=test_user.id, commands=commands, base_currency="SGD", trace_repository=repository)
    with pytest.raises(ValidationError, match="does not belong"):
        await post_journal_entries(db, drafts, uuid4(), base_currency="SGD")
    posted = await post_journal_entries(db, drafts, test_user.id, base_currency="SGD")
    assert [e.status for e in posted] == [JournalEntryStatus.POSTED] * 3
    empty = JournalEntry(id=uuid4(), user_id=test_user.id, entry_date=ENTRY_DATE, memo="no lines", base_currency="SGD")
    empty.lines = []
    db.add(empty)
    await db.flush()
    stranger = JournalEntry(id=uuid4(), user_id=test_user.id, entry_date=ENTRY_DATE, memo="not stored")
    stranger.lines = []
    for match, batch in (("Can only post draft", drafts), ("at least 2 lines", [empty]), ("not found", [stranger])):
        with pytest.raises(ValidationError, match=match):
            await post_journal_entries(db, batch, test_user.id, base_currency="SGD")
