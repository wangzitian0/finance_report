from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import TransactionDirection
from src.extraction.base.types import RetireStatementCommand
from src.extraction.extension.source_lifecycle import retire_statement
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType, JournalEntry, JournalEntryStatus
from src.reconciliation import (
    ReconciliationMatch,
    ReconciliationStatus,
    accepted_transfer_txn_ids,
    execute_matching,
    paired_transfer_entry_ids,
    release_transaction_dispositions,
)
from tests.factories import UserFactory
from tests.reconciliation.test_transfer_integration import _seed_statement, _seed_txn
from tests.statement_ingestion import posting_dependencies


async def _seed_matched_transfer(db: AsyncSession, user_id: UUID):
    cash = Account(user_id=user_id, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD")
    checking = Account(user_id=user_id, name="Checking", code="1002", type=AccountType.ASSET, currency="SGD")
    db.add_all([cash, checking])
    await db.flush()
    desc = "TRANSFER BETWEEN OWN ACCOUNTS REF 2888"
    cash_doc = await _seed_statement(db, user_id, account_id=cash.id, file_hash=f"ac2888_cash_{uuid4().hex}")
    chk_doc = await _seed_statement(db, user_id, account_id=checking.id, file_hash=f"ac2888_checking_{uuid4().hex}")
    out_txn = await _seed_txn(
        db, user_id, cash_doc, description=desc, amount=Decimal("500.00"), direction="OUT", txn_date=date(2025, 1, 10)
    )
    in_txn = await _seed_txn(
        db, user_id, chk_doc, description=desc, amount=Decimal("500.00"), direction="IN", txn_date=date(2025, 1, 11)
    )
    by_txn = {m.atomic_txn_id: m for m in await execute_matching(db, user_id=user_id, currency="SGD")}
    assert set(by_txn) == {out_txn.id, in_txn.id} and {m.status for m in by_txn.values()} == {
        ReconciliationStatus.AUTO_ACCEPTED
    }
    out_stmt_id = (
        await db.execute(select(StatementSummary.id).where(StatementSummary.uploaded_document_id == cash_doc.id))
    ).scalar_one()
    return out_stmt_id, out_txn.id, in_txn.id, by_txn[out_txn.id], by_txn[in_txn.id]


async def test_AC_extraction_2888_2_and_AC_reconciliation_2888_1_retire_releases_leg_and_breaks_pair(
    db: AsyncSession, test_user
):
    out_stmt_id, out_txn_id, in_txn_id, out_m, in_m = await _seed_matched_transfer(db, test_user.id)
    out_eid, in_eid = UUID(out_m.journal_entry_ids[0]), UUID(in_m.journal_entry_ids[0])
    assert await accepted_transfer_txn_ids(db, [out_txn_id, in_txn_id]) == {out_txn_id, in_txn_id}
    assert await paired_transfer_entry_ids(db, user_id=test_user.id) == {out_eid, in_eid}

    await retire_statement(
        db, RetireStatementCommand(statement_id=out_stmt_id, user_id=test_user.id), dependencies=posting_dependencies()
    )
    await db.flush()
    assert (
        await db.execute(select(JournalEntry.status).where(JournalEntry.id == out_eid))
    ).scalar_one() is JournalEntryStatus.VOID
    assert (
        await db.execute(select(JournalEntry.status).where(JournalEntry.id == in_eid))
    ).scalar_one() is not JournalEntryStatus.VOID
    assert (
        await db.execute(select(ReconciliationMatch.status).where(ReconciliationMatch.id == out_m.id))
    ).scalar_one() is ReconciliationStatus.SUPERSEDED
    assert (
        await db.execute(select(ReconciliationMatch.status).where(ReconciliationMatch.id == in_m.id))
    ).scalar_one() is ReconciliationStatus.AUTO_ACCEPTED
    assert await accepted_transfer_txn_ids(db, [out_txn_id, in_txn_id]) == {in_txn_id}
    assert await paired_transfer_entry_ids(db, user_id=test_user.id) == set()


async def test_release_transaction_dispositions_ignores_rows_of_other_users(db: AsyncSession, test_user):
    other_user = await UserFactory.create_async(db)
    rows = {
        u.id: AtomicTransaction(
            user_id=u.id,
            txn_date=date(2025, 1, 12),
            description="Salary",
            amount=Decimal("20.00"),
            direction=TransactionDirection.IN,
            currency="SGD",
            dedup_hash=uuid4().hex + uuid4().hex,
            source_documents=[{"doc_id": str(uuid4()), "doc_type": "bank_statement"}],
        )
        for u in (test_user, other_user)
    }
    db.add_all(rows.values())
    await db.flush()
    matches = {
        uid: ReconciliationMatch(
            atomic_txn_id=r.id,
            journal_entry_ids=[],
            match_score=95,
            score_breakdown={"amount": 100.0},
            status=ReconciliationStatus.AUTO_ACCEPTED,
        )
        for uid, r in rows.items()
    }
    db.add_all(matches.values())
    await db.flush()
    assert (
        await release_transaction_dispositions(
            db, user_id=test_user.id, transaction_ids=[rows[other_user.id].id], reason="Statement retired"
        )
        == 0
    )
    assert (
        await db.execute(
            select(ReconciliationMatch.status, ReconciliationMatch.version).where(
                ReconciliationMatch.id == matches[other_user.id].id
            )
        )
    ).one() == (ReconciliationStatus.AUTO_ACCEPTED, 1)
    assert (
        await release_transaction_dispositions(
            db, user_id=test_user.id, transaction_ids=[rows[test_user.id].id], reason="Statement retired"
        )
        == 1
    )
    assert (
        await db.execute(
            select(ReconciliationMatch.status, ReconciliationMatch.version).where(
                ReconciliationMatch.id == matches[test_user.id].id
            )
        )
    ).one() == (ReconciliationStatus.SUPERSEDED, 2)
