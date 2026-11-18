from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.audit import JournalEntrySourceType
from src.extraction import TransactionDirection
from src.extraction.orm.layer2 import AtomicTransaction
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine, TransferPair, create_transfer_in_entry, create_transfer_out_entry
from src.reconciliation import DEFAULT_CONFIG, entry_bank_side_amount, entry_total_amount
from src.reconciliation.extension.matching import MatchingContext, execute_matching
from src.reconciliation.extension.phases.normal_matching import run_normal_matching_phase
from src.reconciliation.extension.phases.transfer_detection import run_transfer_detection_phase
from src.reconciliation.extension.repository import SqlReconciliationRepository
from src.reconciliation.extension.transfer_pairs import InvalidTransferPairError, list_unpaired_transfer_dispositions, persist_transfer_pairs
from src.reconciliation.orm.reconciliation import DispositionKind, ReconciliationMatch, ReconciliationMatchJournalEntry, ReconciliationStatus, ReconciliationTransferPair, ReconciliationTransferPairLeg, TransferPairDecision, TransferPairLegRole, TransferPairReviewState
from tests.factories import AccountFactory, AtomicTransactionFactory, UserFactory


def _atomic(uid, *, desc: str = "payment", direction: TransactionDirection = TransactionDirection.OUT, ccy: str = "SGD") -> AtomicTransaction:
    return AtomicTransaction(user_id=uid, txn_date=date(2026, 7, 20), amount=Decimal("100.00"), direction=direction, description=desc, currency=ccy, dedup_hash=uuid4().hex + uuid4().hex, source_documents=[])


def _match(txn_id, *, kind: DispositionKind = DispositionKind.JOURNAL_MATCH, eids: list[str] | None = None) -> ReconciliationMatch:
    return ReconciliationMatch(atomic_txn_id=txn_id, journal_entry_ids=eids or [], match_score=90, score_breakdown={}, status=ReconciliationStatus.PENDING_REVIEW, disposition_kind=kind)


def _journal(uid, memo: str) -> JournalEntry:
    return JournalEntry(user_id=uid, entry_date=date(2026, 7, 20), memo=memo, source_type=JournalEntrySourceType.SYSTEM, status=JournalEntryStatus.DRAFT)


async def _add_leg(db: AsyncSession, txn: AtomicTransaction, entry: JournalEntry) -> ReconciliationMatch:
    m = _match(txn.id, kind=DispositionKind.TRANSFER_LEG, eids=[str(entry.id)])
    db.add(m)
    await db.flush()
    db.add(ReconciliationMatchJournalEntry(match_id=m.id, journal_entry_id=entry.id))
    await db.flush()
    return m


async def test_AC_reconciliation_economic_disposition_1_normal_precedes_transfer(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    txn = await AtomicTransactionFactory.create_async(db, user_id=uid, txn_date=date(2026, 7, 20), amount=Decimal("100.00"), direction=TransactionDirection.OUT, description="internal transfer rent", currency="SGD")
    cash, expense = await AccountFactory.create_async(db, user_id=uid, name="Cash"), await AccountFactory.create_async(db, user_id=uid, name="Rent", type=AccountType.EXPENSE)
    entry = JournalEntry(user_id=uid, entry_date=txn.txn_date, memo=txn.description, source_type=JournalEntrySourceType.MANUAL, status=JournalEntryStatus.POSTED, lines=[JournalLine(account=expense, direction=Direction.DEBIT, amount=txn.amount, currency="SGD"), JournalLine(account=cash, direction=Direction.CREDIT, amount=txn.amount, currency="SGD")])
    db.add(entry)
    await db.flush()
    matches = await execute_matching(db, user_id=uid, currency="SGD")
    assert len(matches) == 1 and (matches[0].disposition_kind, matches[0].journal_entry_ids) == (DispositionKind.JOURNAL_MATCH, [str(entry.id)])
    assert await db.scalar(select(func.count()).select_from(JournalLine).join(Account, Account.id == JournalLine.account_id).where(Account.user_id == uid, Account.code == "1199")) == 0


@pytest.mark.integration
async def test_AC_reconciliation_economic_disposition_2_and_3_uniqueness_and_concurrency(db: AsyncSession, db_engine, test_user) -> None:
    uid = test_user.id
    txn = await AtomicTransactionFactory.create_async(db, user_id=uid, txn_date=date(2026, 7, 20), amount=Decimal("100.00"), description="payment", currency="SGD")
    db.add_all([_match(txn.id), _match(txn.id)])
    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()

    txn2 = await AtomicTransactionFactory.create_async(db, user_id=uid, txn_date=date(2026, 7, 20), amount=Decimal("100.00"), description="race", currency="SGD")
    cash = Account(user_id=uid, name="Race cash", code="1098", type=AccountType.ASSET, currency="SGD")
    db.add(cash)
    await db.flush()
    txn2_id, txn2_amt, txn2_date, cash_id = txn2.id, txn2.amount, txn2.txn_date, cash.id
    await db.commit()
    maker, start, ready, lock = async_sessionmaker(db_engine, expire_on_commit=False), asyncio.Event(), 0, asyncio.Lock()

    async def worker() -> tuple[UUID, bool, UUID | None]:
        nonlocal ready
        async with maker() as s:
            async with lock:
                ready += 1
                if ready == 2:
                    start.set()
            await start.wait()
            repo = SqlReconciliationRepository(s)
            winner = await repo.claim_transaction(txn2_id)
            created, eid = winner is None, None
            if winner is None:
                eff = await create_transfer_out_entry(s, user_id=uid, source_account_id=cash_id, amount=txn2_amt, txn_date=txn2_date, description="concurrent disposition effect", currency="SGD")
                winner = _match(txn2_id, eids=[str(eff.id)])
                await repo.add_match(winner)
                await s.flush()
                eid = eff.id
            await s.commit()
            return winner.id, created, eid

    a, b = await asyncio.wait_for(asyncio.gather(worker(), worker()), timeout=10)
    assert a[0] == b[0] and sorted((a[1], b[1])) == [False, True] and len([e for e in (a[2], b[2]) if e]) == 1
    async with maker() as v:
        assert (await v.scalar(select(func.count()).select_from(ReconciliationMatch).where(ReconciliationMatch.atomic_txn_id == txn2_id)), await v.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.memo == "Transfer OUT: concurrent disposition effect"))) == (1, 1)


@pytest.mark.integration
async def test_AC_reconciliation_economic_disposition_4_and_5_transfer_pair_round_trip(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    out_t, in_t, extra_t = _atomic(uid, desc="transfer out"), _atomic(uid, desc="transfer in", direction=TransactionDirection.IN), _atomic(uid, desc="unpaired")
    out_e, in_e = _journal(uid, "transfer out"), _journal(uid, "transfer in")
    db.add_all([out_t, in_t, extra_t, out_e, in_e])
    await db.flush()
    out_m, in_m = await _add_leg(db, out_t, out_e), await _add_leg(db, in_t, in_e)
    extra_m = _match(extra_t.id, kind=DispositionKind.TRANSFER_LEG)
    db.add(extra_m)
    await db.flush()
    cand = TransferPair(out_entry=out_e, in_entry=in_e, confidence=96, score_breakdown={"amount": 100.0})

    for attr, bad in (("direction", TransactionDirection.OUT), ("currency", "USD"), ("currency", "XYZ")):
        setattr(in_t, attr, bad)
        await db.flush()
        with pytest.raises(InvalidTransferPairError):
            await persist_transfer_pairs(db, [cand])
        setattr(in_t, attr, TransactionDirection.IN if attr == "direction" else "SGD")
    out_t.currency = "sgd"

    other_uid = (await UserFactory.create_async(db)).id
    f_txn, f_ent = _atomic(other_uid, desc="foreign", direction=TransactionDirection.IN), _journal(other_uid, "foreign")
    db.add_all([f_txn, f_ent])
    await db.flush()
    await _add_leg(db, f_txn, f_ent)
    with pytest.raises(InvalidTransferPairError):
        await persist_transfer_pairs(db, [TransferPair(out_entry=out_e, in_entry=f_ent, confidence=96, score_breakdown={"amount": 100.0})])

    persisted = await persist_transfer_pairs(db, [cand])
    assert len(persisted) == 1 and await persist_transfer_pairs(db, [cand]) == [] and ReconciliationTransferPair.__table__.c.score_breakdown.nullable is False
    pid, out_mid, in_mid, extra_mid = persisted[0].id, out_m.id, in_m.id, extra_m.id
    with pytest.raises(InvalidTransferPairError):
        await persist_transfer_pairs(db, [TransferPair(out_entry=in_e, in_entry=out_e, confidence=95, score_breakdown={"amount": 100.0})])

    db.expire_all()
    stored = await db.get(ReconciliationTransferPair, pid)
    assert (stored.decision, stored.review_state, stored.version) == (TransferPairDecision.AUTO_PAIRED, TransferPairReviewState.PAIRED, 1)
    legs = (await db.scalars(select(ReconciliationTransferPairLeg).where(ReconciliationTransferPairLeg.pair_id == pid))).all()
    assert {(item.role, item.disposition_id) for item in legs} == {(TransferPairLegRole.OUT, out_mid), (TransferPairLegRole.IN, in_mid)}
    assert [i.id for i in await list_unpaired_transfer_dispositions(db, user_id=uid)] == [extra_mid]

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            cp = ReconciliationTransferPair(decision=TransferPairDecision.AUTO_PAIRED, review_state=TransferPairReviewState.PAIRED, confidence=96, score_breakdown={})
            db.add(cp)
            await db.flush()
            db.add(ReconciliationTransferPairLeg(pair_id=cp.id, role=TransferPairLegRole.OUT, disposition_id=out_mid))
            await db.flush()
    assert await db.scalar(select(func.count()).select_from(ReconciliationTransferPair)) == 1

    sgd, usd = Account(user_id=uid, name="SGD cash", code="1001", type=AccountType.ASSET, currency="SGD"), Account(user_id=uid, name="USD cash", code="1002", type=AccountType.ASSET, currency="USD")
    mixed = _journal(uid, "mixed")
    mixed.lines = [JournalLine(account=sgd, direction=Direction.CREDIT, amount=Decimal("100"), currency="SGD"), JournalLine(account=usd, direction=Direction.CREDIT, amount=Decimal("900"), currency="USD"), JournalLine(account=sgd, direction=Direction.DEBIT, amount=Decimal("100"), currency="SGD"), JournalLine(account=usd, direction=Direction.DEBIT, amount=Decimal("900"), currency="USD")]
    assert entry_bank_side_amount(mixed, "OUT", currency="SGD") == Decimal("100") and entry_total_amount(mixed, currency="USD") == Decimal("900")
    with pytest.raises(TypeError):
        entry_total_amount(mixed)


@pytest.mark.integration
async def test_AC_reconciliation_economic_disposition_6_retry_and_phase_permutation_are_idempotent(db: AsyncSession, db_engine, test_user) -> None:
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, txn_date=date(2026, 7, 20), amount=Decimal("100.00"), description="internal transfer", currency="SGD")
    cash, checking = Account(user_id=test_user.id, name="Retry cash", code="1096", type=AccountType.ASSET, currency="SGD"), Account(user_id=test_user.id, name="Retry chk", code="1097", type=AccountType.ASSET, currency="SGD")
    db.add_all([cash, checking])
    await db.commit()
    maker = async_sessionmaker(db_engine, expire_on_commit=False)

    for commit in (False, True):
        async with maker() as s:
            assert await SqlReconciliationRepository(s).claim_transaction(txn.id) is None
            out_eff = await create_transfer_out_entry(s, user_id=test_user.id, source_account_id=cash.id, amount=txn.amount, txn_date=txn.txn_date, description="idempotent disposition OUT", currency="SGD")
            await _add_leg(s, txn, out_eff)
            await s.commit() if commit else await s.rollback()

    in_t = _atomic(test_user.id, desc="idempotent disposition IN", direction=TransactionDirection.IN)
    async with maker() as pairing:
        pairing.add(in_t)
        await pairing.flush()
        in_eff = await create_transfer_in_entry(pairing, user_id=test_user.id, dest_account_id=checking.id, amount=in_t.amount, txn_date=in_t.txn_date, description="idempotent disposition IN", currency="SGD")
        await _add_leg(pairing, in_t, in_eff)
        cand = TransferPair(out_entry=out_eff, in_entry=in_eff, confidence=96, score_breakdown={"amount": 100.0})
        assert len(await persist_transfer_pairs(pairing, [cand])) == 1 and await persist_transfer_pairs(pairing, [cand]) == []
        await pairing.commit()

    for order in ((run_normal_matching_phase, run_transfer_detection_phase), (run_transfer_detection_phase, run_normal_matching_phase)):
        async with maker() as rep:
            repo = SqlReconciliationRepository(rep)
            entries = [e for e in await repo.list_journal_candidates(user_id=test_user.id, start_date=txn.txn_date, end_date=txn.txn_date) if e.id == out_eff.id]
            ctx = MatchingContext(DEFAULT_CONFIG, "SGD", {str(e.id): e for e in entries}, lambda _: entries, AsyncMock(return_value=0.0))
            for phase in order:
                kw = {"context": ctx} if phase is run_normal_matching_phase else {"base_currency": "SGD"}
                assert await phase(rep, transactions=[txn], matched_txn_ids=set(), repository=repo, user_id=test_user.id, **kw) == []
                assert (await repo.get_active_match(txn.id)).disposition_kind == DispositionKind.TRANSFER_LEG
            await rep.commit()

    async with maker() as v:
        assert (await v.scalar(select(func.count()).select_from(ReconciliationMatch).where(ReconciliationMatch.atomic_txn_id == txn.id)), await v.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.memo.in_(["Transfer OUT: idempotent disposition OUT", "Transfer IN: idempotent disposition IN"]))), await v.scalar(select(func.count()).select_from(ReconciliationTransferPair)), await v.scalar(select(func.count()).select_from(ReconciliationTransferPairLeg))) == (1, 2, 1, 2)


async def test_AC_reconciliation_economic_disposition_7_processing_uses_typed_ledger_boundary(monkeypatch) -> None:
    from src.reconciliation.extension.phases import transfer_detection

    events: list[str] = []
    repo = SimpleNamespace(claim_transaction=AsyncMock(side_effect=lambda _i: events.append("claim")), add_match=AsyncMock(side_effect=lambda _m: events.append("disposition")))
    monkeypatch.setattr(transfer_detection, "detect_transfer_pattern", lambda _d: True)
    monkeypatch.setattr(transfer_detection, "resolve_custody_account_id", AsyncMock(return_value=uuid4()))

    async def _cmd(tag, **_kw):
        events.append(tag)
        return SimpleNamespace(id=uuid4(), status=JournalEntryStatus.POSTED)

    async def _out_cmd(**kw):
        return await _cmd("ledger-out-command", **kw)

    async def _in_cmd(**kw):
        return await _cmd("ledger-in-command", **kw)

    out_spy, in_spy = AsyncMock(side_effect=_out_cmd), AsyncMock(side_effect=_in_cmd)
    monkeypatch.setattr(transfer_detection, "create_transfer_out_entry", out_spy)
    monkeypatch.setattr(transfer_detection, "create_transfer_in_entry", in_spy)
    uid = uuid4()
    out_t, in_t = _atomic(uid, desc="internal transfer out"), _atomic(uid, desc="internal transfer in", direction=TransactionDirection.IN)
    out_t.id, in_t.id = uuid4(), uuid4()
    created = await transfer_detection.run_transfer_detection_phase(AsyncMock(spec=AsyncSession), transactions=[out_t, in_t], matched_txn_ids=set(), repository=repo, user_id=uid, base_currency="SGD")
    assert len(created) == 2 and events == ["claim", "ledger-out-command", "disposition", "claim", "ledger-in-command", "disposition"]
    assert out_spy.await_args.kwargs["currency"] == out_t.currency and in_spy.await_args.kwargs["currency"] == in_t.currency
