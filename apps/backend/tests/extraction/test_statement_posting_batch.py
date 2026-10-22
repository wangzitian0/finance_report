"""AC-extraction.statement-approve.4 to .6: the batch ports of statement posting equal the single ports (#2612).

Each batch function must return what the per-item function returns for the same input, and must keep the
per-item path for an item whose trace lineage already holds a head.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, TraceEmitter
from src.audit.extension.trace_repository import SqlTraceRecordRepository
from src.audit.orm import TraceRecordRow
from src.extraction import (
    DispositionDecision,
    EconomicIntent,
    IntentProposal,
    IntentProposalOrigin,
    StatementTransaction,
    TransactionDirection,
)
from src.extraction.extension import review_queue
from src.extraction.extension.disposition_trace import (
    DispositionTraceInput,
    FinancialCommandRequest,
    authorize_financial_command,
    authorize_financial_commands_many,
    emit_disposition_trace_records,
    emit_disposition_trace_records_many,
)
from src.extraction.extension.review_queue import (
    StatementEntryRequest,
    create_entries_from_txns,
    create_entry_from_txn,
)
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine, ValidationError
from tests.factories import AtomicTransactionFactory, seed_parsed_statement
from tests.statement_ingestion import posting_dependencies, reviewed_posting_inputs

pytestmark = pytest.mark.asyncio

OCCURRED_AT = datetime(2026, 7, 1, tzinfo=UTC)


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


async def _transactions(db: AsyncSession, user_id: UUID, count: int) -> list[AtomicTransaction]:
    rows = [
        {
            "description": f"Posting batch {index}",
            "amount": Decimal("5.00") + index,
            "direction": TransactionDirection.OUT if index % 2 else TransactionDirection.IN,
            "date": date(2026, 7, 1) + timedelta(days=index),
        }
        for index in range(count)
    ]
    seeded = await seed_parsed_statement(db, user_id, transactions=rows)
    return list(seeded.transactions)


def _statement_transaction(txn: AtomicTransaction) -> StatementTransaction:
    return StatementTransaction(
        transaction_id=txn.id,
        transaction_date=txn.txn_date,
        amount=txn.amount,
        currency=txn.currency,
        direction=txn.direction,
        description=txn.description,
    )


def _intent(txn: AtomicTransaction) -> EconomicIntent:
    return EconomicIntent.INCOME if txn.direction == TransactionDirection.IN else EconomicIntent.EXPENSE


def _proposal(txn: AtomicTransaction) -> IntentProposal:
    return IntentProposal(
        schema_version="1",
        policy_version="reviewed-test-v1",
        origin=IntentProposalOrigin.REVIEWED_RULE,
        intent=_intent(txn),
        category="TEST",
        confidence=Decimal("1"),
        evidence=("reviewed-test",),
    )


async def _inputs(
    db: AsyncSession, user_id: UUID, transactions: list[AtomicTransaction]
) -> list[tuple[DispositionTraceInput, DispositionDecision, Account]]:
    inputs = []
    for txn in transactions:
        decision, counter_account = await reviewed_posting_inputs(
            db, user_id=user_id, transaction=txn, intent=_intent(txn)
        )
        inputs.append(
            (
                DispositionTraceInput(
                    transaction=_statement_transaction(txn), proposal=_proposal(txn), decision=decision
                ),
                decision,
                counter_account,
            )
        )
    return inputs


def _emitter(db: AsyncSession) -> TraceEmitter:
    return posting_dependencies().trace_emitter_factory(db)


async def _emit_each(db: AsyncSession, user_id: UUID, items: list[DispositionTraceInput], **extra) -> list:
    emitter = extra.pop("emitter", None) or _emitter(db)
    return [
        await emit_disposition_trace_records(
            emitter=emitter,
            user_id=user_id,
            execution_id="batch-test-execution",
            occurred_at=OCCURRED_AT,
            transaction=item.transaction,
            proposal=item.proposal,
            decision=item.decision,
        )
        for item in items
    ]


async def _emit_batch(db: AsyncSession, user_id: UUID, items: list[DispositionTraceInput], **extra) -> list:
    return await emit_disposition_trace_records_many(
        emitter=extra.pop("emitter", None) or _emitter(db),
        user_id=user_id,
        execution_id="batch-test-execution",
        occurred_at=OCCURRED_AT,
        inputs=items,
    )


async def test_AC_extraction_statement_approve_4_batch_disposition_records_equal_the_single_records(db, test_user):
    """AC-extraction.statement-approve.4: Batch disposition records equal the single records."""
    transactions = await _transactions(db, test_user.id, 4)
    items = [item for item, _decision, _counter in await _inputs(db, test_user.id, transactions)]

    nested = await db.begin_nested()
    with _Statements(db) as batch_run:
        batch = await _emit_batch(db, test_user.id, items)
    await nested.rollback()
    with _Statements(db) as single_run:
        single = await _emit_each(db, test_user.id, items)

    assert len(batch) == 4 and all(len(records) == 4 for records in batch)
    assert batch == single
    assert len(batch_run.texts) <= 8 and 3 * len(batch_run.texts) < len(single_run.texts)


async def test_AC_extraction_statement_approve_4_a_lineage_with_a_head_keeps_the_single_path(db, test_user):
    """AC-extraction.statement-approve.4: A lineage with a head keeps the single path."""
    transactions = await _transactions(db, test_user.id, 3)
    first_round = [item for item, _decision, _counter in await _inputs(db, test_user.id, transactions)]
    await _emit_each(db, test_user.id, first_round[:2])
    # The first two transactions get a new decision: their records supersede the heads. The third is new.
    second_round = [item for item, _decision, _counter in await _inputs(db, test_user.id, transactions)]

    nested = await db.begin_nested()
    batch = await _emit_batch(db, test_user.id, second_round)
    await nested.rollback()
    single = await _emit_each(db, test_user.id, second_round)

    assert batch == single
    assert batch[0][2].supersedes_id is not None and batch[1][3].supersedes_id is not None
    assert batch[2][2].supersedes_id is None and batch[2][3].supersedes_id is None


async def test_AC_extraction_statement_approve_4_a_repository_without_the_batch_read_keeps_the_single_path(
    db, test_user
):
    """AC-extraction.statement-approve.4: A repository without the batch read keeps the single path."""

    class SingleRepository:
        """Only the per-record port: no ``append_many`` and no ``lineages_with_decision_head``."""

        def __init__(self, inner: SqlTraceRecordRepository) -> None:
            self._inner = inner

        async def append(self, record):
            return await self._inner.append(record)

        async def get(self, scope, record_id):
            return await self._inner.get(scope, record_id)

        async def current_decision(self, scope, lineage):
            return await self._inner.current_decision(scope, lineage)

        async def decision_head(self, scope, lineage):
            return await self._inner.decision_head(scope, lineage)

    transactions = await _transactions(db, test_user.id, 2)
    items = [item for item, _decision, _counter in await _inputs(db, test_user.id, transactions)]
    inner = _emitter(db).repository
    legacy = TraceEmitter(SingleRepository(inner))

    nested = await db.begin_nested()
    batch = await _emit_batch(db, test_user.id, items, emitter=legacy)
    await nested.rollback()
    single = await _emit_each(db, test_user.id, items)

    assert batch == single


def _lines(txn: AtomicTransaction, debit: UUID, credit: UUID) -> list[dict]:
    return [
        {"account_id": debit, "direction": Direction.DEBIT, "amount": txn.amount, "currency": "SGD"},
        {"account_id": credit, "direction": Direction.CREDIT, "amount": txn.amount, "currency": "SGD"},
    ]


async def _requests(
    db: AsyncSession, user_id: UUID, transactions: list[AtomicTransaction]
) -> tuple[list[FinancialCommandRequest], TraceEmitter]:
    emitter = _emitter(db)
    debit, credit = uuid4(), uuid4()
    requests = []
    for (item, _decision, _counter), txn in zip(await _inputs(db, user_id, transactions), transactions, strict=True):
        records = (await _emit_each(db, user_id, [item], emitter=emitter))[0]
        requests.append(
            FinancialCommandRequest(
                upstream_decision=records[-1],
                entry_date=txn.txn_date,
                memo=txn.description,
                lines_data=_lines(txn, debit, credit),
                base_currency="SGD",
                source_id=txn.id,
            )
        )
    return requests, emitter


async def _authorize_each(emitter: TraceEmitter, user_id: UUID, requests: list[FinancialCommandRequest]) -> list:
    return [
        await authorize_financial_command(
            emitter=emitter,
            user_id=user_id,
            upstream_decision=request.upstream_decision,
            entry_date=request.entry_date,
            memo=request.memo,
            lines_data=request.lines_data,
            base_currency=request.base_currency,
            source_id=request.source_id,
        )
        for request in requests
    ]


async def test_AC_extraction_statement_approve_5_batch_command_anchors_equal_the_single_anchors(db, test_user):
    """AC-extraction.statement-approve.5: Batch command anchors equal the single anchors."""
    transactions = await _transactions(db, test_user.id, 4)
    requests, emitter = await _requests(db, test_user.id, transactions)

    nested = await db.begin_nested()
    with _Statements(db) as batch_run:
        batch = await authorize_financial_commands_many(emitter=emitter, user_id=test_user.id, requests=requests)
    await nested.rollback()
    with _Statements(db) as single_run:
        single = await _authorize_each(emitter, test_user.id, requests)

    assert len(batch) == 4 and len({anchor.decision_id for anchor in batch}) == 4
    assert batch == single
    assert len(batch_run.texts) <= 8 and 3 * len(batch_run.texts) < len(single_run.texts)


async def test_AC_extraction_statement_approve_5_a_command_with_a_head_keeps_the_single_path(db, test_user):
    """AC-extraction.statement-approve.5: A command with a head keeps the single path."""
    transactions = await _transactions(db, test_user.id, 3)
    requests, emitter = await _requests(db, test_user.id, transactions)
    first = await _authorize_each(emitter, test_user.id, requests[:1])
    # The first command is authorized: the batch must reuse its anchor. The others are new.
    batch = await authorize_financial_commands_many(emitter=emitter, user_id=test_user.id, requests=requests)

    assert batch[0] == first[0]
    assert batch[1:] == await _authorize_each(emitter, test_user.id, requests[1:])

    # A repository without the batch read gives the same anchors through the single path.
    class SingleRepository:
        def __init__(self, inner) -> None:
            self.inner = inner

        async def decision_head(self, scope, lineage):
            return await self.inner.decision_head(scope, lineage)

        async def append(self, record):
            return await self.inner.append(record)

    legacy = TraceEmitter(SingleRepository(emitter.repository))
    assert await authorize_financial_commands_many(emitter=legacy, user_id=test_user.id, requests=requests) == batch


async def test_AC_extraction_statement_approve_5_a_command_needs_an_authoritative_source_decision(db, test_user):
    """AC-extraction.statement-approve.5: A command needs an authoritative source decision."""
    transactions = await _transactions(db, test_user.id, 2)
    requests, emitter = await _requests(db, test_user.id, transactions)
    foreign = FinancialCommandRequest(
        upstream_decision=requests[0].upstream_decision,
        entry_date=requests[1].entry_date,
        memo=requests[1].memo,
        lines_data=requests[1].lines_data,
        base_currency="SGD",
        source_id=requests[1].source_id,  # the decision belongs to the first transaction
    )

    with pytest.raises(ValueError, match="current authoritative source decision"):
        await authorize_financial_commands_many(emitter=emitter, user_id=test_user.id, requests=[requests[0], foreign])
    assert await authorize_financial_commands_many(emitter=emitter, user_id=test_user.id, requests=[]) == []


async def _posting_context(db: AsyncSession, user_id: UUID, count: int):
    seeded = await seed_parsed_statement(
        db,
        user_id,
        transactions=[
            {
                "description": f"Entry batch {index}",
                "amount": Decimal("7.00") + index,
                "direction": TransactionDirection.OUT if index % 2 else TransactionDirection.IN,
                "date": date(2026, 7, 1) + timedelta(days=index),
            }
            for index in range(count)
        ],
    )
    bank = Account(user_id=user_id, name=f"Bank {seeded.id}", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.flush()
    seeded.statement.account_id = bank.id
    await db.flush()
    emitter = _emitter(db)
    requests = []
    for txn in seeded.transactions:
        decision, counter = await reviewed_posting_inputs(db, user_id=user_id, transaction=txn, intent=_intent(txn))
        records = await emit_disposition_trace_records(
            emitter=emitter,
            user_id=user_id,
            execution_id=f"entry-batch:{txn.id}",
            occurred_at=OCCURRED_AT,
            transaction=_statement_transaction(txn),
            proposal=_proposal(txn),
            decision=decision,
        )
        requests.append(
            StatementEntryRequest(
                txn=txn,
                disposition=decision,
                counter_account=counter,
                source_decision=records[-1],
                source_type=JournalEntrySourceType.AUTO_PARSED,
            )
        )
    return seeded.statement, bank, emitter, requests


async def _facts(db: AsyncSession, entries: list[JournalEntry], bank: Account) -> list[dict]:
    """The persisted facts of entries. Identifiers are replaced by what they name, so two runs compare equal."""
    facts = []
    for entry in sorted(entries, key=lambda item: item.memo):
        lines = (await db.execute(select(JournalLine).where(JournalLine.journal_entry_id == entry.id))).scalars().all()
        anchor = await db.get(TraceRecordRow, entry.decision_anchor_id)
        facts.append(
            {
                "memo": entry.memo,
                "date": entry.entry_date,
                "status": entry.status,
                "source_type": entry.source_type,
                "authority": entry.decision_authority_state,
                "anchor": (anchor.record_type, anchor.assertion_kind, anchor.assertion_id, anchor.result),
                "lines": sorted(
                    (
                        line.line_no,
                        "bank" if line.account_id == bank.id else "counter",
                        line.direction,
                        line.amount,
                        line.currency,
                    )
                    for line in lines
                ),
                "loaded_lines": len(entry.lines),
            }
        )
    return facts


def _common(test_user, statement, bank) -> dict:
    dependencies = posting_dependencies()
    return {
        "user_id": test_user.id,
        "base_currency": "SGD",
        "auto_post": True,
        "preloaded_statement": statement,
        "preloaded_bank_account": bank,
        "fx_rate_provider": dependencies.fx_rate_provider,
        "fx_rate_error": dependencies.fx_rate_error,
    }


async def test_AC_extraction_statement_approve_6_batch_entries_equal_the_single_entries(db, test_user):
    """AC-extraction.statement-approve.6: Batch entries equal the single entries."""
    batch_statement, batch_bank, batch_emitter, batch_requests = await _posting_context(db, test_user.id, 4)
    single_statement, single_bank, single_emitter, single_requests = await _posting_context(db, test_user.id, 4)

    batch = await create_entries_from_txns(
        db, batch_requests, trace_emitter=batch_emitter, **_common(test_user, batch_statement, batch_bank)
    )
    single = [
        await create_entry_from_txn(
            db,
            request.txn,
            disposition=request.disposition,
            counter_account=request.counter_account,
            source_decision=request.source_decision,
            source_type=request.source_type,
            trace_emitter=single_emitter,
            record_evidence=False,
            **_common(test_user, single_statement, single_bank),
        )
        for request in single_requests
    ]

    assert [entry.source_id for entry in batch] == [request.txn.id for request in batch_requests]
    assert all(entry.status is JournalEntryStatus.POSTED for entry in batch)
    batch_facts = await _facts(db, batch, batch_bank)
    assert len(batch_facts) == 4
    assert batch_facts == await _facts(db, single, single_bank)
    assert all(fact["loaded_lines"] == 2 for fact in batch_facts)
    assert all(fact["anchor"][1:3] == ("financial_command", "source-disposition") for fact in batch_facts)


async def test_AC_extraction_statement_approve_6_batch_entries_keep_the_checks_and_errors_of_the_single_path(
    db, test_user
):
    """AC-extraction.statement-approve.6: Batch entries keep the checks and errors of the single path."""
    statement, bank, emitter, requests = await _posting_context(db, test_user.id, 2)
    common = {**_common(test_user, statement, bank), "trace_emitter": emitter}
    assert await create_entries_from_txns(db, [], **common) == []

    # A transaction of another user is refused before any entry exists. The transaction is not stored.
    foreign = AtomicTransactionFactory.build(user_id=UUID(int=1))
    foreign_request = StatementEntryRequest(
        txn=foreign,
        disposition=requests[0].disposition,
        counter_account=requests[0].counter_account,
        source_decision=requests[0].source_decision,
        source_type=requests[0].source_type,
    )
    with pytest.raises(ValueError, match="does not belong to user"):
        await create_entries_from_txns(db, [requests[0], foreign_request], **{**common, "auto_post": False})
    assert await db.scalar(select(func.count()).select_from(JournalEntry)) == 0

    # A ledger rule that refuses a generated entry surfaces as the same ValueError as the single path.
    async def refuse(*_args, **_kwargs):
        raise ValidationError("unbalanced")

    with patch.object(review_queue, "submit_anchored_journal_entries_v2", refuse):
        with pytest.raises(ValueError, match="Generated entry does not balance: unbalanced"):
            await create_entries_from_txns(db, requests, **{**common, "auto_post": False})
        # The savepoint of the posting batch rolls back with the error.
        with pytest.raises(ValueError, match="Generated entry violates accounting invariants: unbalanced"):
            await create_entries_from_txns(db, requests, **common)
