from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from src.audit import JournalEntrySourceType
from src.ledger import PROCESSING_ACCOUNT_CODE, Account, AccountType, Direction, JournalEntry, JournalEntryStatus, TransferAccountCurrencyMismatchError, create_transfer_out_entry, find_transfer_pairs, get_or_create_processing_account
from src.reconciliation import NamedTransfer, post_named_transfer_legs, score_description
from src.reconciliation.extension import named_transfers
from src.reconciliation.extension.phases.transfer_detection import run_transfer_detection_phase
from src.reconciliation.extension.repository import SqlReconciliationRepository
from src.reconciliation.extension.transfer_pairs import persist_transfer_pairs
from src.reconciliation.orm.reconciliation import DispositionKind, ReconciliationMatch, ReconciliationStatus, ReconciliationTransferPair
from tests.api._statement_router_fixtures import add_txn, build_statement, create_statement_account
from tests.db_lock_probe import backend_pid, backend_waits_for_a_lock

pytestmark = pytest.mark.asyncio


async def _stmt(db, uid, file_hash: str, *, account_name: str = "Bank A", linked: bool = True, currency: str = "SGD"):
    bank = await create_statement_account(db, uid, account_name)
    bank.currency = currency
    s = build_statement(uid, file_hash, 90)
    s.account_id, s.currency = (bank.id if linked else None), currency
    db.add(s)
    await db.flush()
    return s, bank


async def _entry(db, entry_id: str) -> JournalEntry:
    return (await db.execute(select(JournalEntry).where(JournalEntry.id == UUID(entry_id)).options(selectinload(JournalEntry.lines)))).scalar_one()


async def _count(db, col, *cond) -> int:
    return (await db.execute(select(func.count(col)).where(*cond))).scalar_one()


def _fail_ledger(monkeypatch) -> None:
    async def _fail(*_a, **_kw):
        raise AssertionError("ledger must not run")

    monkeypatch.setattr(named_transfers, "post_transfer_leg", _fail)


@pytest.mark.parametrize(("direction", "desc", "amt", "cat", "score"), [("OUT", "Credit Card Repayment", "1200.00", "CARD_REPAYMENT", 92), ("IN", "Wallet refund", "5000.00", "TRANSFER", 70)])
async def test_AC_reconciliation_named_transfer_legs_1_direction_posts_leg(db, test_user, direction, desc, amt, cat, score):
    s, bank = await _stmt(db, test_user.id, f"named_leg_{direction}")
    txn = await add_txn(db, s, txn_date=date(2025, 1, 11), description=desc, amount=Decimal(amt), direction=direction)
    matches = await post_named_transfer_legs(db, user_id=test_user.id, named=[NamedTransfer(transaction=txn, category=cat, score=score)], base_currency="SGD")
    m = matches[0]
    assert len(matches) == 1 and (m.atomic_txn_id, m.disposition_kind, m.status, m.match_score, m.score_breakdown["ai_category"], m.score_breakdown["ai_score"]) == (txn.id, DispositionKind.TRANSFER_LEG, ReconciliationStatus.ACCEPTED, score, cat, float(score))
    proc, entry = await get_or_create_processing_account(db, test_user.id, currency="SGD"), await _entry(db, m.journal_entry_ids[0])
    assert (entry.source_type, entry.source_id, entry.status) == (JournalEntrySourceType.SYSTEM, txn.id, JournalEntryStatus.RECONCILED)
    expected_lines = {(proc.id, Direction.DEBIT, Decimal(amt)), (bank.id, Direction.CREDIT, Decimal(amt))} if direction == "OUT" else {(bank.id, Direction.DEBIT, Decimal(amt)), (proc.id, Direction.CREDIT, Decimal(amt))}
    assert {(item.account_id, item.direction, item.amount) for item in entry.lines} == expected_lines


async def test_AC_reconciliation_named_transfer_legs_2_idempotency_unlinked_and_refusals(db, test_user, monkeypatch):
    uid = test_user.id
    s, _ = await _stmt(db, uid, "named_leg_twice")
    txn = await add_txn(db, s, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT")
    named = [NamedTransfer(transaction=txn, category="TRANSFER", score=88)]
    assert len(await post_named_transfer_legs(db, user_id=uid, named=named, base_currency="SGD")) == 1
    assert await post_named_transfer_legs(db, user_id=uid, named=named, base_currency="SGD") == []
    assert (await _count(db, ReconciliationMatch.id), await _count(db, JournalEntry.id)) == (1, 1)

    s_unl, _ = await _stmt(db, uid, "named_leg_unlinked", linked=False)
    t_unl = await add_txn(db, s_unl, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT")
    assert await post_named_transfer_legs(db, user_id=uid, named=[NamedTransfer(transaction=t_unl, category="TRANSFER", score=88)], base_currency="SGD") == [] and await _count(db, JournalEntry.id) == 1

    first = await add_txn(db, s, txn_date=date(2025, 1, 5), description="Wallet A", amount=Decimal("10.00"), direction="OUT")
    second = await add_txn(db, s, txn_date=date(2025, 1, 6), description="Wallet B", amount=Decimal("20.00"), direction="OUT")
    real = named_transfers.post_transfer_leg

    async def _refuse_first(db_, **kw):
        if kw["txn"].id == first.id:
            await get_or_create_processing_account(db_, kw["user_id"], currency="SGD")
            raise TransferAccountCurrencyMismatchError("refused")
        return await real(db_, **kw)

    monkeypatch.setattr(named_transfers, "post_transfer_leg", _refuse_first)
    m_iso = await post_named_transfer_legs(db, user_id=uid, named=[NamedTransfer(transaction=first, category="TRANSFER", score=90), NamedTransfer(transaction=second, category="TRANSFER", score=90)], base_currency="SGD")
    assert [m.atomic_txn_id for m in m_iso] == [second.id] and await _count(db, JournalEntry.id) == 2

    solo = await add_txn(db, s, txn_date=date(2025, 1, 7), description="Wallet C", amount=Decimal("10.00"), direction="OUT")

    async def _post_then_refuse(db_, **kw):
        await real(db_, **kw)
        raise TransferAccountCurrencyMismatchError("refused after")

    monkeypatch.setattr(named_transfers, "post_transfer_leg", _post_then_refuse)
    assert await post_named_transfer_legs(db, user_id=uid, named=[NamedTransfer(transaction=solo, category="TRANSFER", score=90)], base_currency="SGD") == []
    assert (await _count(db, JournalEntry.id), await _count(db, ReconciliationMatch.id)) == (2, 2)


@pytest.mark.parametrize("currency", ["CNY", "XXX", ""])
async def test_AC_reconciliation_named_transfer_legs_2_currency_guards(db, test_user, currency, monkeypatch):
    _fail_ledger(monkeypatch)
    s, _ = await _stmt(db, test_user.id, f"foreign_{currency or 'blank'}")
    s.currency = currency or "SGD"
    t = await add_txn(db, s, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT")
    t.currency = currency
    assert await post_named_transfer_legs(db, user_id=test_user.id, named=[NamedTransfer(transaction=t, category="TRANSFER", score=88)], base_currency="SGD") == []
    assert (await _count(db, Account.id, Account.code == PROCESSING_ACCOUNT_CODE), await _count(db, JournalEntry.id)) == (0, 0)

    if currency == "CNY":
        cny = await get_or_create_processing_account(db, test_user.id, currency="CNY")
        s_p, _ = await _stmt(db, test_user.id, "proc_cny")
        t_p = await add_txn(db, s_p, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT")
        assert await post_named_transfer_legs(db, user_id=test_user.id, named=[NamedTransfer(transaction=t_p, category="TRANSFER", score=88)], base_currency="SGD") == []
        assert (await db.get(Account, cny.id)).currency == "CNY" and await _count(db, JournalEntry.id) == 0


@pytest.mark.parametrize(("direction", "bank_dir"), [("OUT", Direction.CREDIT), ("IN", Direction.DEBIT)])
async def test_AC_reconciliation_named_transfer_legs_3_two_identical_rows(db, test_user, direction, bank_dir):
    s, bank = await _stmt(db, test_user.id, f"identical_{direction}")
    rows = [await add_txn(db, s, txn_date=date(2025, 1, 5), description="Wallet transfer", amount=Decimal("50.00"), direction=direction) for _ in range(2)]
    matches = await post_named_transfer_legs(db, user_id=test_user.id, named=[NamedTransfer(transaction=r, category="TRANSFER", score=90) for r in rows], base_currency="SGD")
    assert len(matches) == 2 and matches[0].journal_entry_ids != matches[1].journal_entry_ids
    entries = [await _entry(db, m.journal_entry_ids[0]) for m in matches]
    assert {e.source_id for e in entries} == {r.id for r in rows} and sum(item.amount for e in entries for item in e.lines if item.account_id == bank.id and item.direction is bank_dir) == Decimal("100.00")


async def test_AC_reconciliation_named_transfer_legs_4_to_6_pairing_memo_and_keywords(db, test_user):
    uid = test_user.id
    s_usd, _ = await _stmt(db, uid, "kw_usd", account_name="Bank USD", currency="USD")
    t_usd = await add_txn(db, s_usd, txn_date=date(2025, 1, 11), description="Transfer to savings", amount=Decimal("80.00"), direction="OUT")
    assert await run_transfer_detection_phase(db, transactions=[t_usd], matched_txn_ids=set(), repository=SqlReconciliationRepository(db), user_id=uid, base_currency="SGD") == []
    assert await _count(db, Account.id, Account.code == PROCESSING_ACCOUNT_CODE) == 0

    s_a, bank_a = await _stmt(db, uid, "pair_a", account_name="Bank A")
    s_b, _ = await _stmt(db, uid, "pair_b", account_name="Bank B")
    desc = "Funds moved between own accounts, reference NAMED20250110001"
    out_t, in_t = await add_txn(db, s_a, txn_date=date(2025, 1, 10), description=desc, amount=Decimal("500.00"), direction="OUT"), await add_txn(db, s_b, txn_date=date(2025, 1, 11), description=desc, amount=Decimal("500.00"), direction="IN")
    matches = await post_named_transfer_legs(db, user_id=uid, named=[NamedTransfer(transaction=out_t, category="TRANSFER", score=90), NamedTransfer(transaction=in_t, category="TRANSFER", score=90)], base_currency="SGD")
    before = await _count(db, ReconciliationTransferPair.id)
    await persist_transfer_pairs(db, await find_transfer_pairs(db, uid, currency="SGD", description_scorer=score_description, threshold=85))
    assert len(matches) == 2 and (before, await _count(db, ReconciliationTransferPair.id)) == (0, 1)
    assert (await db.scalar(select(Account).where(Account.user_id == uid, Account.is_system.is_(True)))).type is AccountType.ASSET

    long_t = await add_txn(db, s_a, txn_date=date(2025, 1, 12), description="W" * 495, amount=Decimal("80.00"), direction="OUT")
    long_m = await post_named_transfer_legs(db, user_id=uid, named=[NamedTransfer(transaction=long_t, category="TRANSFER", score=88)], base_currency="SGD")
    entry = await _entry(db, long_m[0].journal_entry_ids[0])
    assert len(entry.memo) == 500 and entry.memo.startswith("Transfer OUT: WWW")
    assert (await create_transfer_out_entry(db, user_id=uid, source_account_id=bank_a.id, amount=long_t.amount, txn_date=long_t.txn_date, description=long_t.description, currency=long_t.currency, source_id=long_t.id)).id == entry.id

    kw_rows = [await add_txn(db, s_a, txn_date=date(2025, 1, 13), description="Transfer to savings", amount=Decimal("80.00"), direction=d) for d in ("OUT", "OUT", "IN", "IN")]
    created = await run_transfer_detection_phase(db, transactions=kw_rows, matched_txn_ids=set(), repository=SqlReconciliationRepository(db), user_id=uid, base_currency="SGD")
    await db.commit()
    assert len(created) == 4 and (await db.execute(select(Account).where(Account.code == PROCESSING_ACCOUNT_CODE))).scalar_one().currency == "SGD"
    assert {r.id for r in kw_rows} <= set((await db.execute(select(JournalEntry.source_id))).scalars().all())


@pytest.mark.parametrize(("status", "owned"), [(ReconciliationStatus.REJECTED, False), (ReconciliationStatus.SUPERSEDED, False), (ReconciliationStatus.PENDING_REVIEW, True), (ReconciliationStatus.ACCEPTED, True), (ReconciliationStatus.AUTO_ACCEPTED, True)])
async def test_AC_reconciliation_named_transfer_legs_2_existing_match_ownership(db, test_user, status, owned):
    s, _ = await _stmt(db, test_user.id, f"own_{status.value}")
    t = await add_txn(db, s, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT")
    db.add(ReconciliationMatch(atomic_txn_id=t.id, journal_entry_ids=[], match_score=70, score_breakdown={}, status=status, disposition_kind=DispositionKind.REVIEWED_UNMATCHED))
    await db.flush()
    matches = await post_named_transfer_legs(db, user_id=test_user.id, named=[NamedTransfer(transaction=t, category="TRANSFER", score=88)], base_currency="SGD")
    assert (matches == [] and await _count(db, JournalEntry.id) == 0) if owned else (len(matches) == 1 and matches[0].disposition_kind is DispositionKind.TRANSFER_LEG)


async def test_AC_reconciliation_named_transfer_legs_2_claim_locks_row(db, test_user, db_engine):
    s, _ = await _stmt(db, test_user.id, "lock")
    t = await add_txn(db, s, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT")
    await db.commit()
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    first, second = sessions(), sessions()
    try:
        assert await SqlReconciliationRepository(first).claim_transaction_for_decision(t.id) is None
        waiting = asyncio.create_task(SqlReconciliationRepository(second).claim_transaction_for_decision(t.id))
        assert await backend_waits_for_a_lock(db_engine, await backend_pid(second))
        await first.commit()
        assert await asyncio.wait_for(waiting, timeout=15) is None
    finally:
        await first.close()
        await second.close()


@pytest.mark.parametrize(("accepted_by", "decided_by_user", "expected"), [("user", False, ReconciliationStatus.ACCEPTED), ("user", True, ReconciliationStatus.ACCEPTED), ("system", False, ReconciliationStatus.AUTO_ACCEPTED), ("system", True, ReconciliationStatus.ACCEPTED)])
async def test_AC_reconciliation_named_transfer_legs_1_the_status_names_who_decided(db, test_user, accepted_by, decided_by_user, expected):
    s, _ = await _stmt(db, test_user.id, f"status_{accepted_by}_{decided_by_user}")
    t = await add_txn(db, s, txn_date=date(2025, 1, 11), description="Wallet", amount=Decimal("80.00"), direction="OUT")
    assert [m.status for m in await post_named_transfer_legs(db, user_id=test_user.id, named=[NamedTransfer(transaction=t, category="TRANSFER", score=80, decided_by_user=decided_by_user)], accepted_by=accepted_by, base_currency="SGD")] == [expected]
