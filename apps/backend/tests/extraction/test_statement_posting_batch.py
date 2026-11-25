from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, TraceEmitter
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
from src.extraction.extension.review_queue import StatementEntryRequest, create_entries_from_txns, create_entry_from_txn
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import Account, Direction, JournalEntry, JournalEntryStatus, JournalLine, ValidationError
from tests.extraction._statement_run_helpers import make_account
from tests.factories import AtomicTransactionFactory, seed_parsed_statement
from tests.statement_ingestion import posting_dependencies, reviewed_posting_inputs

pytestmark = pytest.mark.asyncio
OCCURRED_AT = datetime(2026, 7, 1, tzinfo=UTC)


class _Statements:
    def __init__(self, db: AsyncSession) -> None:
        self._engine, self.texts = db.bind.sync_engine, []

    def _capture(self, _conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        self.texts.append(statement)

    def __enter__(self) -> _Statements:
        event.listen(self._engine, "before_cursor_execute", self._capture)
        return self

    def __exit__(self, *_exc) -> None:
        event.remove(self._engine, "before_cursor_execute", self._capture)


class _SingleRepository:
    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def _st_txn(txn):
    return StatementTransaction(
        transaction_id=txn.id,
        transaction_date=txn.txn_date,
        amount=txn.amount,
        currency=txn.currency,
        direction=txn.direction,
        description=txn.description,
    )


def _intent(txn):
    return EconomicIntent.INCOME if txn.direction == TransactionDirection.IN else EconomicIntent.EXPENSE


def _proposal(txn):
    return IntentProposal(
        schema_version="1",
        policy_version="reviewed-test-v1",
        origin=IntentProposalOrigin.REVIEWED_RULE,
        intent=_intent(txn),
        category="TEST",
        confidence=Decimal("1"),
        evidence=("reviewed-test",),
    )


async def _transactions(
    db: AsyncSession, user_id: UUID, count: int, prefix: str = "Posting batch"
) -> list[AtomicTransaction]:
    rows = [
        {
            "description": f"{prefix} {i}",
            "amount": Decimal("5.00") + i,
            "direction": TransactionDirection.OUT if i % 2 else TransactionDirection.IN,
            "date": date(2026, 7, 1) + timedelta(days=i),
        }
        for i in range(count)
    ]
    return list((await seed_parsed_statement(db, user_id, transactions=rows)).transactions)


async def _inputs(
    db: AsyncSession, user_id: UUID, transactions: list[AtomicTransaction]
) -> list[tuple[DispositionTraceInput, DispositionDecision, Account]]:
    inputs = []
    for txn in transactions:
        decision, counter = await reviewed_posting_inputs(db, user_id=user_id, transaction=txn, intent=_intent(txn))
        inputs.append(
            (
                DispositionTraceInput(transaction=_st_txn(txn), proposal=_proposal(txn), decision=decision),
                decision,
                counter,
            )
        )
    return inputs


def _emitter(db: AsyncSession):
    return posting_dependencies().trace_emitter_factory(db)


async def _emit_each(db: AsyncSession, user_id: UUID, items: list[DispositionTraceInput], emitter=None) -> list:
    em = emitter or _emitter(db)
    return [
        await emit_disposition_trace_records(
            emitter=em,
            user_id=user_id,
            execution_id="batch-test-execution",
            occurred_at=OCCURRED_AT,
            transaction=i.transaction,
            proposal=i.proposal,
            decision=i.decision,
        )
        for i in items
    ]


async def _rollback_run(db: AsyncSession, coro, *, capture_sql: bool = False):
    nested = await db.begin_nested()
    if not capture_sql:
        res = await coro
        await nested.rollback()
        return res
    with _Statements(db) as sql_run:
        res = await coro
    await nested.rollback()
    return res, sql_run.texts


async def test_AC_extraction_statement_approve_4_batch_disposition_records_and_lineage(db, test_user):
    items = [item for item, _, _ in await _inputs(db, test_user.id, await _transactions(db, test_user.id, 4))]
    batch, batch_sql = await _rollback_run(
        db,
        emit_disposition_trace_records_many(
            emitter=_emitter(db),
            user_id=test_user.id,
            execution_id="batch-test-execution",
            occurred_at=OCCURRED_AT,
            inputs=items,
        ),
        capture_sql=True,
    )
    with _Statements(db) as single_run:
        single = await _emit_each(db, test_user.id, items)
    assert (
        len(batch) == 4
        and all(len(r) == 4 for r in batch)
        and batch == single
        and len(batch_sql) <= 8
        and 3 * len(batch_sql) < len(single_run.texts)
    )

    txns, txns2 = (
        await _transactions(db, test_user.id, 3, prefix="Posting lin1"),
        await _transactions(db, test_user.id, 2, prefix="Posting lin2"),
    )
    await _emit_each(db, test_user.id, [item for item, _, _ in await _inputs(db, test_user.id, txns)][:2])
    second_round = [item for item, _, _ in await _inputs(db, test_user.id, txns)]
    b1 = await _rollback_run(
        db,
        emit_disposition_trace_records_many(
            emitter=_emitter(db),
            user_id=test_user.id,
            execution_id="batch-test-execution",
            occurred_at=OCCURRED_AT,
            inputs=second_round,
        ),
    )
    assert b1 == await _emit_each(db, test_user.id, second_round)
    assert (
        b1[0][2].supersedes_id is not None,
        b1[1][3].supersedes_id is not None,
        b1[2][2].supersedes_id,
        b1[2][3].supersedes_id,
    ) == (True, True, None, None)

    d1, d2 = (
        [item for item, _, _ in await _inputs(db, test_user.id, txns2)],
        [item for item, _, _ in await _inputs(db, test_user.id, txns2)],
    )
    b2 = await _rollback_run(
        db,
        emit_disposition_trace_records_many(
            emitter=_emitter(db),
            user_id=test_user.id,
            execution_id="batch-test-execution",
            occurred_at=OCCURRED_AT,
            inputs=[d1[0], d1[1], d2[0]],
        ),
    )
    assert (
        b2 == await _emit_each(db, test_user.id, [d1[0], d1[1], d2[0]]) and b2[2][3].supersedes_id == b2[0][3].record_id
    )
    b_leg = await _rollback_run(
        db,
        emit_disposition_trace_records_many(
            emitter=TraceEmitter(_SingleRepository(_emitter(db).repository)),
            user_id=test_user.id,
            execution_id="batch-test-execution",
            occurred_at=OCCURRED_AT,
            inputs=d1,
        ),
    )
    assert b_leg == await _emit_each(db, test_user.id, d1)


async def _requests(
    db: AsyncSession, user_id: UUID, transactions: list[AtomicTransaction]
) -> tuple[list[FinancialCommandRequest], TraceEmitter]:
    emitter, debit, credit, requests = _emitter(db), uuid4(), uuid4(), []
    for (item, _, _), txn in zip(await _inputs(db, user_id, transactions), transactions, strict=True):
        records = (await _emit_each(db, user_id, [item], emitter=emitter))[0]
        lines = [
            {"account_id": debit, "direction": Direction.DEBIT, "amount": txn.amount, "currency": "SGD"},
            {"account_id": credit, "direction": Direction.CREDIT, "amount": txn.amount, "currency": "SGD"},
        ]
        requests.append(
            FinancialCommandRequest(
                upstream_decision=records[-1],
                entry_date=txn.txn_date,
                memo=txn.description,
                lines_data=lines,
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
            upstream_decision=r.upstream_decision,
            entry_date=r.entry_date,
            memo=r.memo,
            lines_data=r.lines_data,
            base_currency=r.base_currency,
            source_id=r.source_id,
        )
        for r in requests
    ]


async def test_AC_extraction_statement_approve_5_batch_command_anchors_and_edge_cases(db, test_user):
    requests, emitter = await _requests(db, test_user.id, await _transactions(db, test_user.id, 4))
    batch, batch_sql = await _rollback_run(
        db,
        authorize_financial_commands_many(emitter=emitter, user_id=test_user.id, requests=requests),
        capture_sql=True,
    )
    with _Statements(db) as single_run:
        single = await _authorize_each(emitter, test_user.id, requests)
    assert (
        len(batch) == 4
        and len({a.decision_id for a in batch}) == 4
        and batch == single
        and len(batch_sql) <= 8
        and 3 * len(batch_sql) < len(single_run.texts)
    )

    req3, em3 = await _requests(db, test_user.id, await _transactions(db, test_user.id, 3))
    first = await _authorize_each(em3, test_user.id, req3[:1])
    b3 = await _rollback_run(db, authorize_financial_commands_many(emitter=em3, user_id=test_user.id, requests=req3))
    leg3 = await _rollback_run(
        db,
        authorize_financial_commands_many(
            emitter=TraceEmitter(_SingleRepository(em3.repository)), user_id=test_user.id, requests=req3
        ),
    )
    s3 = [*first, *await _authorize_each(em3, test_user.id, req3[1:])]
    assert len({a.decision_id for a in s3}) == 3 and b3 == s3 and leg3 == s3

    tx2 = await _transactions(db, test_user.id, 2)
    req2, em2 = await _requests(db, test_user.id, tx2)
    new_src = (
        await _emit_each(
            db, test_user.id, [item for item, _, _ in await _inputs(db, test_user.id, tx2[:1])], emitter=em2
        )
    )[0][-1]
    doubled = [replace(req2[0], upstream_decision=new_src), req2[0]]
    bd = await _rollback_run(db, authorize_financial_commands_many(emitter=em2, user_id=test_user.id, requests=doubled))
    assert (
        new_src.record_id != req2[0].upstream_decision.record_id
        and bd == await _authorize_each(em2, test_user.id, doubled)
        and bd[0] == bd[1]
    )

    foreign = replace(req2[1], upstream_decision=req2[0].upstream_decision)
    with pytest.raises(ValueError, match="current authoritative source decision"):
        await authorize_financial_commands_many(emitter=em2, user_id=test_user.id, requests=[req2[0], foreign])
    assert await authorize_financial_commands_many(emitter=em2, user_id=test_user.id, requests=[]) == []


async def _posting_context(db: AsyncSession, user_id: UUID, count: int):
    seeded = await seed_parsed_statement(
        db,
        user_id,
        transactions=[
            {
                "description": f"Entry batch {i}",
                "amount": Decimal("7.00") + i,
                "direction": TransactionDirection.OUT if i % 2 else TransactionDirection.IN,
                "date": date(2026, 7, 1) + timedelta(days=i),
            }
            for i in range(count)
        ],
    )
    bank = await make_account(db, user_id, f"Bank {seeded.id}")
    seeded.statement.account_id = bank.id
    await db.flush()
    emitter, deps = _emitter(db), posting_dependencies()
    reqs = [
        StatementEntryRequest(
            txn=txn,
            disposition=dec,
            counter_account=cnt,
            source_decision=(
                await emit_disposition_trace_records(
                    emitter=emitter,
                    user_id=user_id,
                    execution_id=f"entry-batch:{txn.id}",
                    occurred_at=OCCURRED_AT,
                    transaction=_st_txn(txn),
                    proposal=_proposal(txn),
                    decision=dec,
                )
            )[-1],
            source_type=JournalEntrySourceType.AUTO_PARSED,
        )
        for txn in seeded.transactions
        for dec, cnt in [await reviewed_posting_inputs(db, user_id=user_id, transaction=txn, intent=_intent(txn))]
    ]
    common = {
        "user_id": user_id,
        "base_currency": "SGD",
        "auto_post": True,
        "preloaded_statement": seeded.statement,
        "preloaded_bank_account": bank,
        "fx_rate_provider": deps.fx_rate_provider,
        "fx_rate_error": deps.fx_rate_error,
        "trace_emitter": emitter,
    }
    return bank, reqs, common


async def _facts(db: AsyncSession, entries: list[JournalEntry], bank: Account) -> list[dict]:
    return [
        {
            "memo": e.memo,
            "date": e.entry_date,
            "status": e.status,
            "source_type": e.source_type,
            "authority": e.decision_authority_state,
            "anchor": (a.record_type, a.assertion_kind, a.assertion_id, a.result),
            "lines": sorted(
                (ln.line_no, "bank" if ln.account_id == bank.id else "counter", ln.direction, ln.amount, ln.currency)
                for ln in (await db.execute(select(JournalLine).where(JournalLine.journal_entry_id == e.id))).scalars()
            ),
            "loaded_lines": len(e.lines),
        }
        for e in sorted(entries, key=lambda item: item.memo)
        for a in [await db.get(TraceRecordRow, e.decision_anchor_id)]
    ]


async def test_AC_extraction_statement_approve_6_batch_entries_and_checks(db, test_user):
    b_bank, b_reqs, b_common = await _posting_context(db, test_user.id, 4)
    s_bank, s_reqs, s_common = await _posting_context(db, test_user.id, 4)
    batch = await create_entries_from_txns(db, b_reqs, **b_common)
    single = [
        await create_entry_from_txn(
            db,
            r.txn,
            disposition=r.disposition,
            counter_account=r.counter_account,
            source_decision=r.source_decision,
            source_type=r.source_type,
            record_evidence=False,
            **s_common,
        )
        for r in s_reqs
    ]
    batch_facts = await _facts(db, batch, b_bank)
    assert [e.source_id for e in batch] == [r.txn.id for r in b_reqs] and all(
        e.status is JournalEntryStatus.POSTED for e in batch
    )
    assert (
        len(batch_facts) == 4
        and batch_facts == await _facts(db, single, s_bank)
        and all(
            f["loaded_lines"] == 2 and f["anchor"][1:3] == ("financial_command", "source-disposition")
            for f in batch_facts
        )
    )

    _, reqs, common = await _posting_context(db, test_user.id, 2)
    assert await create_entries_from_txns(db, [], **common) == []
    foreign_req = replace(reqs[0], txn=AtomicTransactionFactory.build(user_id=UUID(int=1)))
    with pytest.raises(ValueError, match="does not belong to user"):
        await create_entries_from_txns(db, [reqs[0], foreign_req], **{**common, "auto_post": False})
    assert (
        await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id)) == 8
    )

    async def refuse(*_args, **_kwargs):
        raise ValidationError("unbalanced")

    with patch.object(review_queue, "submit_anchored_journal_entries", refuse):
        for auto_post, msg in (
            (False, "Generated entry does not balance: unbalanced"),
            (True, "Generated entry violates accounting invariants: unbalanced"),
        ):
            with pytest.raises(ValueError, match=msg):
                await create_entries_from_txns(db, reqs, **{**common, "auto_post": auto_post})
