"""AC-ledger.anchored-batch.*: the anchored command port accepts a set of commands (#2612).

``submit_anchored_journal_entries_v2`` must persist the entries that one ``submit_anchored_journal_entry_v2``
call per command persists, with a number of SQL statements that does not grow with the set.
"""

from __future__ import annotations

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
    AnchoredJournalCommandV2,
    DecisionAnchor,
    DecisionAnchorError,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    submit_anchored_journal_entries_v2,
    submit_anchored_journal_entry_v2,
)
from src.ledger.base.decision_anchor import journal_command_target
from src.ledger.base.validators import ValidationError
from src.ledger.extension import anchored_posting
from src.ledger.extension.repository import post_journal_entries
from tests.ledger.test_decision_anchor import _decision_records, _Policy, _TraceRepository

pytestmark = pytest.mark.asyncio

ENTRY_DATE = date(2026, 7, 18)


class _Statements:
    def __init__(self, db: AsyncSession) -> None:
        self._engine = db.bind.sync_engine
        self.texts: list[str] = []

    def _capture(self, _conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        self.texts.append(statement)

    def __enter__(self) -> _Statements:
        event.listen(self._engine, "before_cursor_execute", self._capture)
        return self

    def __exit__(self, *_exc) -> None:
        event.remove(self._engine, "before_cursor_execute", self._capture)


async def _accounts(db: AsyncSession, user_id: UUID, *, debit_code: str | None = None) -> tuple[Account, Account]:
    debit = Account(
        user_id=user_id, name=f"batch cash {uuid4()}", type=AccountType.ASSET, currency="SGD", code=debit_code
    )
    credit = Account(user_id=user_id, name=f"batch income {uuid4()}", type=AccountType.INCOME, currency="SGD")
    db.add_all((debit, credit))
    await db.flush()
    return debit, credit


async def _commands(
    db: AsyncSession,
    user_id: UUID,
    count: int,
    *,
    accounts: tuple[Account, Account] | None = None,
    source_type: JournalEntrySourceType = JournalEntrySourceType.AUTO_PARSED,
    post_immediately: bool = True,
    source_ids: list[UUID] | None = None,
    repository: SqlTraceRecordRepository | None = None,
) -> tuple[list[AnchoredJournalCommandV2], SqlTraceRecordRepository]:
    """Persist the decisions of ``count`` commands and return the commands that they authorize."""
    debit, credit = accounts or await _accounts(db, user_id)
    repository = repository or SqlTraceRecordRepository(db, TraceDecisionPolicyRegistry((_Policy(),)))
    commands: list[AnchoredJournalCommandV2] = []
    for index in range(count):
        source_id = source_ids[index] if source_ids else uuid4()
        lines_data = [
            {
                "account_id": debit.id,
                "direction": Direction.DEBIT,
                "amount": Decimal("10.00") + index,
                "currency": "SGD",
            },
            {
                "account_id": credit.id,
                "direction": Direction.CREDIT,
                "amount": Decimal("10.00") + index,
                "currency": "SGD",
            },
        ]
        memo = f"Batch command {index}"
        source_identity = f"statement-transaction:{source_id}"
        target = journal_command_target(
            entry_date=ENTRY_DATE,
            memo=memo,
            lines_data=lines_data,
            base_currency="SGD",
            source_identity=source_identity,
        )
        observation, decision = _decision_records(user_id=user_id, target=target)
        await TraceEmitter(repository).emit_many((observation, decision))
        commands.append(
            AnchoredJournalCommandV2.from_mappings(
                entry_date=ENTRY_DATE,
                memo=memo,
                lines_data=lines_data,
                base_currency="SGD",
                source_type=source_type,
                source_id=source_id,
                source_identity=source_identity,
                decision_anchor=DecisionAnchor.from_record(decision),
                post_immediately=post_immediately,
            )
        )
    return commands, repository


async def _described(db: AsyncSession, entries: list[JournalEntry]) -> list[dict]:
    """The persisted facts of entries, without generated identifiers."""
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
                "lines": sorted(
                    (line.line_no, line.account_id, line.direction, line.amount, line.currency, line.fx_rate)
                    for line in lines
                ),
            }
        )
    return described


async def test_AC_ledger_anchored_batch_1_batch_persists_the_entries_of_one_submit_per_command(db, test_user):
    """AC-ledger.anchored-batch.1."""
    source_ids = [uuid4() for _ in range(5)]
    commands, repository = await _commands(db, test_user.id, 5, source_ids=source_ids)
    nested = await db.begin_nested()
    batch = await submit_anchored_journal_entries_v2(
        db, user_id=test_user.id, commands=commands, base_currency="SGD", trace_repository=repository
    )
    batch_facts = await _described(db, batch)
    await nested.rollback()
    assert await db.scalar(select(func.count()).select_from(JournalEntry)) == 0

    sequential = [
        await submit_anchored_journal_entry_v2(
            db, user_id=test_user.id, command=command, base_currency="SGD", trace_repository=repository
        )
        for command in commands
    ]

    assert [entry.memo for entry in batch] == [command.memo for command in commands]
    assert [entry.memo for entry in sequential] == [command.memo for command in commands]
    assert len(batch_facts) == 5 and all(fact["status"] is JournalEntryStatus.POSTED for fact in batch_facts)
    assert batch_facts == await _described(db, sequential)


async def test_AC_ledger_anchored_batch_2_batch_statement_count_does_not_grow_with_the_set(db, test_user):
    """AC-ledger.anchored-batch.2."""
    accounts = await _accounts(db, test_user.id)
    small, repository = await _commands(db, test_user.id, 2, accounts=accounts)
    large, _ = await _commands(db, test_user.id, 30, accounts=accounts, repository=repository)

    with _Statements(db) as small_run:
        await submit_anchored_journal_entries_v2(
            db, user_id=test_user.id, commands=small, base_currency="SGD", trace_repository=repository
        )
    with _Statements(db) as large_run:
        await submit_anchored_journal_entries_v2(
            db, user_id=test_user.id, commands=large, base_currency="SGD", trace_repository=repository
        )

    assert len(large_run.texts) == len(small_run.texts) <= 10, (len(small_run.texts), len(large_run.texts))


async def test_AC_ledger_anchored_batch_3_batch_is_idempotent_and_refuses_a_different_owner_of_a_target(db, test_user):
    """AC-ledger.anchored-batch.3."""
    commands, repository = await _commands(db, test_user.id, 3)
    first = await submit_anchored_journal_entries_v2(
        db, user_id=test_user.id, commands=commands, base_currency="SGD", trace_repository=repository
    )
    again = await submit_anchored_journal_entries_v2(
        db, user_id=test_user.id, commands=commands, base_currency="SGD", trace_repository=repository
    )
    assert [entry.id for entry in again] == [entry.id for entry in first]
    assert await db.scalar(select(func.count()).select_from(JournalEntry)) == 3

    # The same source target under another decision is a second owner of an immutable command.
    command = commands[0]
    target = journal_command_target(
        entry_date=ENTRY_DATE,
        memo=command.memo,
        lines_data=command.lines_data,
        base_currency="SGD",
        source_identity=command.source_identity,
    )
    replacement = _decision_records(user_id=test_user.id, target=target, execution_id="replacement-decision")[-1]
    with pytest.raises(DecisionAnchorError, match="different decision already owns"):
        await submit_anchored_journal_entries_v2(
            db,
            user_id=test_user.id,
            commands=[
                AnchoredJournalCommandV2(
                    entry_date=command.entry_date,
                    memo=command.memo,
                    lines=command.lines,
                    source_type=command.source_type,
                    source_id=command.source_id,
                    source_identity=command.source_identity,
                    decision_anchor=DecisionAnchor.from_record(replacement),
                    post_immediately=True,
                )
            ],
            base_currency="SGD",
            trace_repository=_TraceRepository((replacement,), current=replacement),
        )
    assert await db.scalar(select(func.count()).select_from(JournalEntry)) == 3


async def test_AC_ledger_anchored_batch_4_one_invalid_command_persists_none_of_the_set(db, test_user):
    """AC-ledger.anchored-batch.4."""
    commands, repository = await _commands(db, test_user.id, 3)
    mismatched = AnchoredJournalCommandV2(
        entry_date=commands[1].entry_date,
        memo=commands[1].memo,
        lines=commands[1].lines,
        source_type=commands[1].source_type,
        source_id=commands[1].source_id,
        source_identity=commands[1].source_identity,
        decision_anchor=commands[0].decision_anchor,  # the anchor of another command
        post_immediately=True,
    )

    with pytest.raises(DecisionAnchorError, match="target"):
        await submit_anchored_journal_entries_v2(
            db,
            user_id=test_user.id,
            commands=[commands[0], mismatched, commands[2]],
            base_currency="SGD",
            trace_repository=repository,
        )

    assert await db.scalar(select(func.count()).select_from(JournalEntry)) == 0


async def test_AC_ledger_anchored_batch_5_post_immediately_decides_for_each_command(db, test_user):
    """AC-ledger.anchored-batch.5."""
    posted, repository = await _commands(db, test_user.id, 2)
    drafts, _ = await _commands(db, test_user.id, 2, post_immediately=False, repository=repository)
    mixed = [posted[0], drafts[0], posted[1], drafts[1]]

    entries = await submit_anchored_journal_entries_v2(
        db, user_id=test_user.id, commands=mixed, base_currency="SGD", trace_repository=repository
    )

    assert [entry.status for entry in entries] == [
        JournalEntryStatus.POSTED,
        JournalEntryStatus.DRAFT,
        JournalEntryStatus.POSTED,
        JournalEntryStatus.DRAFT,
    ]
    assert (
        await submit_anchored_journal_entries_v2(
            db, user_id=test_user.id, commands=[], base_currency="SGD", trace_repository=repository
        )
        == []
    )


async def test_AC_ledger_anchored_batch_6_commands_that_share_a_target_keep_the_single_path(db, test_user):
    """AC-ledger.anchored-batch.6."""
    commands, repository = await _commands(db, test_user.id, 1)

    entries = await submit_anchored_journal_entries_v2(
        db, user_id=test_user.id, commands=[commands[0], commands[0]], base_currency="SGD", trace_repository=repository
    )

    assert entries[0].id == entries[1].id
    assert await db.scalar(select(func.count()).select_from(JournalEntry)) == 1


async def test_AC_ledger_anchored_batch_7_the_processing_account_rule_applies_to_the_accounts_of_each_command(
    db, test_user
):
    """AC-ledger.anchored-batch.7: a system command may use the Processing account. A source command in the same set may not,
    and the accounts of one command must not decide for another."""
    processing_cash = await _accounts(db, test_user.id, debit_code=PROCESSING_ACCOUNT_CODE)
    ordinary = await _accounts(db, test_user.id)
    system_commands, repository = await _commands(
        db, test_user.id, 1, accounts=processing_cash, source_type=JournalEntrySourceType.SYSTEM
    )
    ordinary_commands, _ = await _commands(db, test_user.id, 1, accounts=ordinary, repository=repository)

    entries = await submit_anchored_journal_entries_v2(
        db,
        user_id=test_user.id,
        commands=[system_commands[0], ordinary_commands[0]],
        base_currency="SGD",
        trace_repository=repository,
    )
    assert [entry.status for entry in entries] == [JournalEntryStatus.POSTED] * 2

    forbidden, _ = await _commands(db, test_user.id, 1, accounts=processing_cash, repository=repository)
    with pytest.raises(ValidationError, match="Processing account"):
        await submit_anchored_journal_entries_v2(
            db, user_id=test_user.id, commands=forbidden, base_currency="SGD", trace_repository=repository
        )


async def test_AC_ledger_anchored_batch_8_post_journal_entries_checks_each_entry_like_post_journal_entry(db, test_user):
    """AC-ledger.anchored-batch.8."""
    commands, repository = await _commands(db, test_user.id, 3, post_immediately=False)
    drafts = await submit_anchored_journal_entries_v2(
        db, user_id=test_user.id, commands=commands, base_currency="SGD", trace_repository=repository
    )

    with pytest.raises(ValidationError, match="does not belong"):
        await post_journal_entries(db, drafts, uuid4(), base_currency="SGD")

    posted = await post_journal_entries(db, drafts, test_user.id, base_currency="SGD")
    assert [entry.status for entry in posted] == [JournalEntryStatus.POSTED] * 3

    with pytest.raises(ValidationError, match="Can only post draft"):
        await post_journal_entries(db, drafts, test_user.id, base_currency="SGD")

    # An entry with an empty line list is read again with its lines, as the single post does. The entry
    # still has no line, so the posting invariants refuse it.
    empty = JournalEntry(id=uuid4(), user_id=test_user.id, entry_date=ENTRY_DATE, memo="no lines", base_currency="SGD")
    empty.lines = []
    db.add(empty)
    await db.flush()
    with pytest.raises(ValidationError):
        await post_journal_entries(db, [empty], test_user.id, base_currency="SGD")

    stranger = JournalEntry(id=uuid4(), user_id=test_user.id, entry_date=ENTRY_DATE, memo="not stored")
    stranger.lines = []
    with pytest.raises(ValidationError, match="not found"):
        await post_journal_entries(db, [stranger], test_user.id, base_currency="SGD")


async def test_AC_ledger_anchored_batch_9_target_read_is_chunked_and_refuses_two_owners(db, test_user):
    """AC-ledger.anchored-batch.9."""
    commands, repository = await _commands(db, test_user.id, 5)
    entries = await submit_anchored_journal_entries_v2(
        db, user_id=test_user.id, commands=commands, base_currency="SGD", trace_repository=repository
    )
    targets = [
        journal_command_target(
            entry_date=command.entry_date,
            memo=command.memo,
            lines_data=command.lines_data,
            base_currency="SGD",
            source_identity=command.source_identity,
        )
        for command in commands
    ]

    with patch.object(anchored_posting, "_TARGET_READ_CHUNK_SIZE", 2), _Statements(db) as statements:
        owners = await anchored_posting._existing_for_targets(db, user_id=test_user.id, targets=targets)

    assert {owner.id for owner in owners.values()} == {entry.id for entry in entries}
    assert len(statements.texts) == 1 + 3  # one lock statement and three reads of two targets

    duplicate = MagicMock()
    duplicate.all.return_value = [(entries[0], "journal_command", "t"), (entries[1], "journal_command", "t")]
    fake_db = AsyncMock()
    fake_db.execute.return_value = duplicate
    with pytest.raises(MultipleResultsFound):
        await anchored_posting._existing_for_targets(fake_db, user_id=test_user.id, targets=targets[:1])
