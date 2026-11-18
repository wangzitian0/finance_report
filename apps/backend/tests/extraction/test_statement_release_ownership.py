from __future__ import annotations

import asyncio
import contextlib
import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.extraction import BankStatementStatus, UploadedDocument
from src.extraction.base.types import RetireStatementCommand
from src.extraction.extension.source_lifecycle import retire_statement
from src.extraction.extension.statement_posting import release_statement_ledger_effects, try_auto_approve_high_confidence_statement
from src.extraction.extension.statement_workflow import reject_statement_workflow
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType, JournalEntry, JournalEntryStatus
from src.reconciliation import ReconciliationMatch, ReconciliationStatus, execute_matching
from tests.api._statement_router_fixtures import add_reviewed_disposition_rule, add_txn, build_statement, create_statement_account, seed_uploaded_document
from tests.factories import UserFactory
from tests.reconciliation.test_transfer_integration import _seed_statement, _seed_txn
from tests.statement_ingestion import posting_dependencies


@dataclass(frozen=True)
class SharedRow:
    original_id: UUID
    duplicate_id: UUID
    txn_id: UUID
    entry_id: UUID


async def _col(db: AsyncSession, column, predicate):
    return (await db.execute(select(column).where(predicate))).scalar_one()


async def _reversal_ids(db: AsyncSession, entry_id: UUID) -> list[UUID]:
    return list((await db.execute(select(JournalEntry.id).where(JournalEntry.source_id == entry_id))).scalars().all())


async def _share_row(db: AsyncSession, txn: AtomicTransaction, other_document: UploadedDocument) -> None:
    txn.source_documents = [*txn.source_documents, {"doc_id": str(other_document.id), "doc_type": "bank_statement"}]
    await db.flush()


async def _seed_shared_pair(db: AsyncSession, user_id: UUID, *, duplicate_status: BankStatementStatus) -> SharedRow:
    bank = await create_statement_account(db, user_id, "DBS Release Ownership")
    original = build_statement(user_id, f"release-original-{uuid4().hex}", 90)
    original.status, original.account_id, original.closing_balance = BankStatementStatus.APPROVED, bank.id, Decimal("120.00")
    db.add(original)
    await db.flush()
    txn = await add_txn(db, original, txn_date=date(2025, 1, 8), description="Salary", amount=Decimal("20.00"), direction="IN")
    await add_reviewed_disposition_rule(db, user_id=user_id, keyword="salary", account_type=AccountType.INCOME, category="SALARY")
    await db.commit()
    assert await try_auto_approve_high_confidence_statement(db, original.id, user_id, dependencies=posting_dependencies()) == 1
    entry_id = (await db.execute(select(JournalEntry.id).where(JournalEntry.user_id == user_id, JournalEntry.source_id == txn.id, JournalEntry.status != JournalEntryStatus.VOID))).scalar_one()

    duplicate = build_statement(user_id, f"release-duplicate-{uuid4().hex}", 90)
    duplicate.status, duplicate.account_id, duplicate.closing_balance = duplicate_status, bank.id, Decimal("120.00")
    db.add(duplicate)
    await db.flush()
    await _share_row(db, txn, await seed_uploaded_document(db, duplicate))
    await db.commit()
    return SharedRow(original_id=original.id, duplicate_id=duplicate.id, txn_id=txn.id, entry_id=entry_id)


@pytest.mark.parametrize(
    ("action", "target", "duplicate_status", "expect_void"),
    [("reject", "duplicate", BankStatementStatus.PARSED, False), ("retire", "original", BankStatementStatus.PARSED, True), ("reject", "original", BankStatementStatus.PARSED, True), ("retire", "both", BankStatementStatus.APPROVED, True)],
)
async def test_AC_extraction_2888_1_release_ownership_matrix(db: AsyncSession, test_user, action, target, duplicate_status, expect_void):
    shared, deps = await _seed_shared_pair(db, test_user.id, duplicate_status=duplicate_status), posting_dependencies()
    assert await _col(db, JournalEntry.status, JournalEntry.id == shared.entry_id) is JournalEntryStatus.POSTED
    if target == "duplicate":
        assert (await reject_statement_workflow(db, shared.duplicate_id, test_user.id, dependencies=deps)).status is BankStatementStatus.REJECTED
        assert (await _col(db, JournalEntry.status, JournalEntry.id == shared.entry_id), await _reversal_ids(db, shared.entry_id), await _col(db, StatementSummary.status, StatementSummary.id == shared.original_id)) == (JournalEntryStatus.POSTED, [], BankStatementStatus.APPROVED)
    elif target == "original" and action == "retire":
        await retire_statement(db, RetireStatementCommand(statement_id=shared.original_id, user_id=test_user.id), dependencies=deps)
        assert (await _col(db, StatementSummary.status, StatementSummary.id == shared.original_id), await _col(db, JournalEntry.status, JournalEntry.id == shared.entry_id), len(await _reversal_ids(db, shared.entry_id))) == (BankStatementStatus.RETIRED, JournalEntryStatus.VOID, 1)
    elif target == "original" and action == "reject":
        assert (await reject_statement_workflow(db, shared.original_id, test_user.id, dependencies=deps)).status is BankStatementStatus.REJECTED
        assert (await _col(db, JournalEntry.status, JournalEntry.id == shared.entry_id), await _col(db, StatementSummary.status, StatementSummary.id == shared.duplicate_id)) == (JournalEntryStatus.VOID, BankStatementStatus.PARSED)
    else:
        await retire_statement(db, RetireStatementCommand(statement_id=shared.original_id, user_id=test_user.id), dependencies=deps)
        assert (await _col(db, JournalEntry.status, JournalEntry.id == shared.entry_id), await _reversal_ids(db, shared.entry_id)) == (JournalEntryStatus.POSTED, [])
        await retire_statement(db, RetireStatementCommand(statement_id=shared.duplicate_id, user_id=test_user.id), dependencies=deps)
        assert (await _col(db, JournalEntry.status, JournalEntry.id == shared.entry_id), len(await _reversal_ids(db, shared.entry_id))) == (JournalEntryStatus.VOID, int(expect_void))


async def test_reject_pending_duplicate_and_unreadable_result(db: AsyncSession, test_user):
    uid, deps = test_user.id, posting_dependencies()
    cash, checking = Account(user_id=uid, name="Cash", code="1001", type=AccountType.ASSET, currency="SGD"), Account(user_id=uid, name="Checking", code="1002", type=AccountType.ASSET, currency="SGD")
    db.add_all([cash, checking])
    await db.flush()
    d1, d2, d_chk = await _seed_statement(db, uid, account_id=cash.id, file_hash="release_first_stmt"), await _seed_statement(db, uid, account_id=cash.id, file_hash="release_second_stmt"), await _seed_statement(db, uid, account_id=checking.id, file_hash="release_checking_stmt")
    out_txn = await _seed_txn(db, uid, d1, description="FAST PAYMENT TO BANK B", amount=Decimal("500.00"), direction="OUT", txn_date=date(2025, 1, 10))
    await _share_row(db, out_txn, d2)
    in_txn = await _seed_txn(db, uid, d_chk, description="FAST PAYMENT FROM BANK A", amount=Decimal("500.00"), direction="IN", txn_date=date(2025, 1, 11))
    s1, s2 = await _col(db, StatementSummary.id, StatementSummary.uploaded_document_id == d1.id), await _col(db, StatementSummary.id, StatementSummary.uploaded_document_id == d2.id)
    matches = await execute_matching(db, user_id=uid, currency="SGD")
    out_entry_id = UUID(next(m for m in matches if m.atomic_txn_id == out_txn.id).journal_entry_ids[0])
    assert {m.atomic_txn_id for m in matches} == {out_txn.id, in_txn.id} and (await db.get(JournalEntry, out_entry_id)).source_id == out_txn.id
    await db.commit()

    await reject_statement_workflow(db, s2, uid, dependencies=deps)
    assert (await _col(db, JournalEntry.status, JournalEntry.id == out_entry_id), await _col(db, ReconciliationMatch.status, ReconciliationMatch.atomic_txn_id == out_txn.id)) == (JournalEntryStatus.RECONCILED, ReconciliationStatus.AUTO_ACCEPTED)
    await reject_statement_workflow(db, s1, uid, dependencies=deps)
    assert (await _col(db, JournalEntry.status, JournalEntry.id == out_entry_id), await _col(db, ReconciliationMatch.status, ReconciliationMatch.atomic_txn_id == out_txn.id)) == (JournalEntryStatus.VOID, ReconciliationStatus.SUPERSEDED)

    for status in (BankStatementStatus.PARSED, BankStatementStatus.APPROVED):
        bank = await create_statement_account(db, uid, "DBS Unreadable Result")
        stmt = build_statement(uid, f"release-unreadable-{uuid4().hex}", 90)
        stmt.status, stmt.account_id = status, bank.id
        db.add(stmt)
        await db.flush()
        await seed_uploaded_document(db, stmt)
        rid = uuid4()
        db.add(StatementExtractionResultRecord(id=rid, user_id=uid, statement_id=stmt.id, content_digest=hashlib.sha256(rid.bytes).hexdigest(), source_content_digest=stmt.file_hash.ljust(64, "0")[:64], schema_version="999", producer_version="test-v1", payload={"schema_version": "999"}, source_trace_record_id=uuid4(), created_at=datetime.now(UTC)))
        await db.flush()
        stmt.current_extraction_result_id = rid
        await db.commit()
        cmd = RetireStatementCommand(statement_id=stmt.id, user_id=uid)
        if status is BankStatementStatus.PARSED:
            assert (await retire_statement(db, cmd, dependencies=deps)).status is BankStatementStatus.RETIRED and await _col(db, StatementSummary.status, StatementSummary.id == stmt.id) is BankStatementStatus.RETIRED
        else:
            with pytest.raises(ValueError, match="unsupported statement extraction schema version: 999"):
                await retire_statement(db, cmd, dependencies=deps)


async def test_concurrent_retires_and_advisory_lock(db: AsyncSession, db_engine, test_user):
    shared, maker, deps = await _seed_shared_pair(db, test_user.id, duplicate_status=BankStatementStatus.APPROVED), async_sessionmaker(db_engine, expire_on_commit=False), posting_dependencies()
    async with maker() as first, maker() as second:
        await retire_statement(first, RetireStatementCommand(statement_id=shared.original_id, user_id=test_user.id), dependencies=deps)
        second_retire = asyncio.create_task(retire_statement(second, RetireStatementCommand(statement_id=shared.duplicate_id, user_id=test_user.id), dependencies=deps))
        try:
            finished, _ = await asyncio.wait({second_retire}, timeout=1.0)
            assert not finished, "release 2 must wait for the advisory lock of release 1"
            await first.commit()
            await asyncio.wait_for(second_retire, timeout=10)
            await second.commit()
        finally:
            if not second_retire.done():
                second_retire.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await second_retire
    async with maker() as v:
        assert (await _col(v, StatementSummary.status, StatementSummary.id == shared.original_id), await _col(v, StatementSummary.status, StatementSummary.id == shared.duplicate_id), await _col(v, JournalEntry.status, JournalEntry.id == shared.entry_id)) == (
            BankStatementStatus.RETIRED, BankStatementStatus.RETIRED, JournalEntryStatus.VOID
        )

    lock_sql = text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND ((classid::bigint << 32) | objid::bigint) = hashtextextended(:key, 0)")
    other = await UserFactory.create_async(db)
    key, shared2 = {"key": f"statement-release:{other.id}"}, await _seed_shared_pair(db, other.id, duplicate_status=BankStatementStatus.PARSED)
    before = (await db.execute(lock_sql, key)).scalar_one()
    voided = await release_statement_ledger_effects(db, await db.get(StatementSummary, shared2.original_id), other.id, was_approved=True, reason="Statement retired", dependencies=deps)
    after = (await db.execute(lock_sql, key)).scalar_one()
    assert voided == 1 and after >= before + 1
