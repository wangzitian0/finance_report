from __future__ import annotations

import contextlib
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.audit import JournalEntrySourceType
from src.composition import compose_reviewed_disposition_dependencies
from src.extraction import BankStatementStatus, DocumentType, EconomicIntent, UploadedDocument
from src.extraction.base.source_vocabulary import TransactionDirection
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine, get_processing_balance
from src.ledger.base.processing import PROCESSING_ACCOUNT_CODE
from src.ledger.orm.journal import JournalEntryAuthorityState
from src.pricing.orm.market_data import FxRate
from src.reconciliation import (
    DEFAULT_CONFIG,
    MatchCandidate,
    ReconciliationConfig,
    ReconciliationMatch,
    ReconciliationStatus,
    ReviewedDispositionCommand,
    _candidate_is_better,
    _find_normal_candidates,
    _within_combination_tolerance,
    build_many_to_one_groups,
    execute_matching,
    extract_merchant_tokens,
    normalize_text,
    prune_candidates,
    score_amount,
    score_business_logic,
    score_date,
    score_description,
    score_group,
    score_pattern,
    score_single,
    submit_reviewed_disposition,
    weighted_total,
)
from src.reconciliation.extension.anomaly import detect_anomalies
from src.reconciliation.extension.candidate_policy import _normal_entry_combinations
from src.reconciliation.extension.entry_reads import entry_bank_side_amount, entry_total_amount
from src.reconciliation.extension.matching import sync_reconciliation_matches_journal_entry_links_batch
from src.reconciliation.extension.phases import transfer_detection
from src.reconciliation.extension.repository import SqlReconciliationRepository
from src.reconciliation.orm.reconciliation import ReconciliationMatchJournalEntry
from tests.factories import AccountFactory, StatementSummaryFactory, UploadedDocumentFactory, UserFactory
from tests.ledger._ledger_helpers import create_valid_posted_entry


def _atomic_txn(*, owner_id: UUID, **kw) -> AtomicTransaction:
    kw.setdefault("currency", "SGD")
    kw.setdefault("dedup_hash", uuid4().hex + uuid4().hex)
    kw.setdefault("source_documents", [{"doc_id": str(uuid4()), "doc_type": "bank_statement"}])
    return AtomicTransaction(user_id=owner_id, **kw)


def _cfg(**ov) -> ReconciliationConfig:
    defaults = {
        "weight_amount": Decimal("0.40"),
        "weight_date": Decimal("0.25"),
        "weight_description": Decimal("0.20"),
        "weight_business": Decimal("0.10"),
        "weight_history": Decimal("0.05"),
        "auto_accept": 95,
        "pending_review": 50,
        "amount_percent": Decimal("0.005"),
        "amount_absolute": Decimal("0.10"),
        "date_days": 7,
    }
    defaults.update(ov)
    return ReconciliationConfig(**defaults)


async def _seed_scenario(db: AsyncSession, uid: UUID, *, txn_desc: str = "Test Txn", txn_amount: Decimal | str | list[Decimal | str] = "100.00", direction: str = "OUT", pair_specs: list[tuple[Decimal | str, str]] | None = None, credit_account: Account | None = None, txn_date: date = date(2024, 1, 1)):
    await StatementSummaryFactory.create_async(db, user_id=uid, period_start=date(2024, 1, 1), period_end=date(2024, 1, 1))
    amounts = txn_amount if isinstance(txn_amount, list) else [txn_amount]
    txns = [_atomic_txn(owner_id=uid, txn_date=txn_date, description=txn_desc, amount=Decimal(str(amt)), direction=direction) for amt in amounts]
    db.add_all(txns)
    acc = await AccountFactory.create_async(db, user_id=uid)
    entries = []
    for amt, memo in pair_specs or []:
        e = JournalEntry(user_id=uid, entry_date=txn_date, memo=memo, status=JournalEntryStatus.POSTED, lines=[JournalLine(account_id=acc.id, amount=Decimal(str(amt)), direction=Direction.DEBIT), JournalLine(account_id=(credit_account or acc).id, amount=Decimal(str(amt)), direction=Direction.CREDIT)])
        db.add(e)
        entries.append(e)
    await db.commit()
    return acc, txns, entries


async def _seed_xfer(db: AsyncSession, *, uid: UUID | None = None, desc: str = "TRANSFER TO SAVINGS", direction: str = "OUT", amount: Decimal = Decimal("500.00"), with_doc: bool = True):
    uid = uid or (await UserFactory.create_async(db)).id
    acc = await AccountFactory.create_async(db, user_id=uid)
    doc = await UploadedDocumentFactory.create_async(db, user_id=uid) if with_doc else None
    doc_id = doc.id if doc else None
    await StatementSummaryFactory.create_async(
        db,
        user_id=uid,
        account_id=acc.id,
        uploaded_document_id=doc_id,
        **({"file_hash": doc.file_hash} if doc else {}),
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
        status=BankStatementStatus.APPROVED,
    )
    src = {"source_documents": [{"doc_id": str(doc_id), "doc_type": "bank_statement"}]} if doc_id else {}
    txn = _atomic_txn(owner_id=uid, txn_date=date(2024, 1, 1), description=desc, amount=amount, direction=direction, **src)
    db.add(txn)
    await db.commit()
    return uid, acc, doc_id, txn


@contextlib.contextmanager
def _patch_phases(**overrides):
    defaults = {"src.reconciliation.extension.phases.transfer_detection.detect_transfer_pattern": {"return_value": False}, "src.reconciliation.extension.matching.find_transfer_pairs": {"new_callable": AsyncMock, "return_value": []}, "src.reconciliation.extension.matching.score_pattern": {"new_callable": AsyncMock, "return_value": 0.0}}
    defaults.update(overrides)
    with contextlib.ExitStack() as stack:
        yield {k: stack.enter_context(patch(k, **kw)) for k, kw in defaults.items()}


def test_normalize_scoring_and_unit_helpers() -> None:
    assert (normalize_text(""), normalize_text("!!! @@@ ###"), normalize_text("ABC   123")) == ("", "", "abc 123")
    assert (score_description(None, "t"), score_description("t", None), score_description("", "t"), score_description("!!!", "@@@"), score_description("Exact Match", "Exact Match")) == (0.0, 0.0, 0.0, 0.0, 100.0)
    assert all(score_amount(Decimal(a), Decimal(b), DEFAULT_CONFIG, is_multi=m) == exp for a, b, m, exp in (("100.00", "100.00", False, 100.0), ("100.00", "100.01", False, 100.0), ("1000.00", "1004.00", False, 90.0), ("100.00", "104.00", False, 70.0), ("1000.00", "1009.00", True, 70.0), ("0.00", "10.00", False, 0.0), ("100.00", "150.00", False, 50.0)))
    assert all(score_date(d1, d2, DEFAULT_CONFIG) == exp for d1, d2, exp in ((date(2024, 1, 1), date(2024, 1, 1), 100.0), (date(2024, 1, 1), date(2024, 1, 4), 90.0), (date(2024, 1, 1), date(2024, 1, 7), 70.0), (date(2024, 1, 30), date(2024, 2, 3), 75.0), (date(2024, 1, 1), date(2024, 1, 15), 0.0)))

    mid, pid = uuid4(), uuid4()
    entries = {str(mid): JournalEntry(id=mid, source_type=JournalEntrySourceType.MANUAL), str(pid): JournalEntry(id=pid, source_type=JournalEntrySourceType.AUTO_PARSED)}
    mc, pc = MatchCandidate([str(mid)], 88, {}), MatchCandidate([str(pid)], 88, {})
    assert _candidate_is_better(mc, pc, entries) and not _candidate_is_better(pc, mc, entries) and mc.breakdown["source_type_winner_rank"] > mc.breakdown["source_type_loser_rank"]
    assert (extract_merchant_tokens("VISA POS COFFEE SHOP 123"), extract_merchant_tokens("REF: 123456789"), extract_merchant_tokens("PAYMENT TO VENDOR ABC")) == (["coffee", "shop"], [], ["vendor", "abc"])
    assert weighted_total({"amount": 100.0, "date": 100.0, "description": 100.0, "business": 100.0, "history": 100.0}, DEFAULT_CONFIG) == 100
    cands = [JournalEntry(id=uuid4(), entry_date=d, lines=[JournalLine(amount=Decimal(a), direction=Direction.DEBIT)]) for d, a in [(date(2024, 1, 1), "100.00"), (date(2024, 1, 2), "101.00"), (date(2024, 1, 10), "100.00")]]
    assert [e.id for e in prune_candidates(cands, txn_date=date(2024, 1, 1), target_amount=Decimal("100.00"), currency="SGD", limit=2)] == [cands[0].id, cands[2].id]
    assert build_many_to_one_groups([SimpleNamespace(description="", txn_date=date(2024, 1, 1), amount=Decimal("50.00")) for _ in range(2)]) == []
    e_amt, e_empty = SimpleNamespace(id=uuid4(), amount=Decimal("123.45")), SimpleNamespace(id=uuid4())
    assert (entry_total_amount(e_amt, currency="SGD"), entry_total_amount(e_empty, currency="SGD"), entry_bank_side_amount(e_amt, "IN", currency="SGD"), entry_bank_side_amount(e_empty, "IN", currency="SGD")) == (Decimal("123.45"), Decimal("0.00"), Decimal("123.45"), Decimal("0.00"))

    base_d = date(2026, 1, 15)
    t_norm = AtomicTransaction(id=uuid4(), txn_date=base_d, description="Vendor ABC", amount=Decimal("100.00"), direction="OUT", currency="SGD")
    mk_e = lambda amt, memo, bal=True: JournalEntry(id=uuid4(), entry_date=base_d, memo=memo, source_type=JournalEntrySourceType.MANUAL, lines=[JournalLine(direction=Direction.DEBIT, amount=Decimal(amt), account=Account(type=AccountType.EXPENSE)), JournalLine(direction=Direction.CREDIT, amount=Decimal(amt) if bal else Decimal(amt) - 1, account=Account(type=AccountType.ASSET))])
    res = _find_normal_candidates([t_norm], [mk_e("40.00", "Vendor ABC part 1"), mk_e("60.00", "Vendor ABC part 2"), mk_e("10.00", "Unbalanced", False), mk_e("300.00", "Too large")], pattern_scores={"vendor": 90.0}, config=DEFAULT_CONFIG, base_currency="SGD")
    assert len(res) == 1 and res[0][0] is t_norm and len(res[0][1].journal_entry_ids) == 2 and res[0][1].breakdown["multi_entry"] == 1


@pytest.mark.parametrize(("direction", "account_types", "expected_score"), [("IN", [AccountType.ASSET, AccountType.INCOME], 100.0), ("IN", [AccountType.ASSET, AccountType.LIABILITY], 85.0), ("IN", [AccountType.ASSET, AccountType.EQUITY], 75.0), ("IN", [AccountType.ASSET, AccountType.ASSET], 70.0), ("IN", [AccountType.EXPENSE], 40.0), ("OUT", [AccountType.ASSET, AccountType.EXPENSE], 100.0), ("OUT", [AccountType.ASSET, AccountType.LIABILITY], 90.0), ("OUT", [AccountType.ASSET, AccountType.EQUITY], 40.0), ("OUT", [AccountType.ASSET], 70.0), ("???", [AccountType.ASSET, AccountType.INCOME], 50.0)])
def test_score_business_logic_combinations(direction: str, account_types: list[AccountType], expected_score: float) -> None:
    assert score_business_logic(AtomicTransaction(direction=direction), JournalEntry(lines=[JournalLine(account=Account(type=t)) for t in account_types])) == expected_score


@pytest.mark.parametrize(("txn_amount", "pair_specs", "expected_count", "breakdown_key", "breakdown_val"), [("100.00", None, 0, None, None), ("100.00", [("1.00", "Random")], 0, None, None), ("100.00", [("50.00", "Part 1"), ("50.00", "Part 2")], 1, "multi_entry", 1), ("150.00", [("50.00", "Part 1"), ("50.00", "Part 2"), ("50.00", "Part 3")], 1, "multi_entry", 2), (["50.00", "50.00"], [("100.00", "Batch Payment #1")], 2, "many_to_one_bonus", 10.0), (["50.00", "50.00"], None, 0, None, None)])
async def test_execute_matching_scenarios(db: AsyncSession, test_user, txn_amount, pair_specs, expected_count, breakdown_key, breakdown_val):
    await _seed_scenario(db, test_user.id, txn_desc="Batch Payment #1", txn_amount=txn_amount, pair_specs=pair_specs)
    matches = await execute_matching(db, user_id=test_user.id, currency="SGD")
    assert len(matches) == expected_count and (not breakdown_key or all(m.score_breakdown.get(breakdown_key) == breakdown_val for m in matches))


async def test_execute_matching_filters_transfers_and_patterns(db: AsyncSession, test_user):
    uid = test_user.id
    assert await score_pattern(db, AtomicTransaction(description="!!!"), DEFAULT_CONFIG, uuid4()) == 0.0
    await StatementSummaryFactory.create_async(db, user_id=uid)
    txn_past = _atomic_txn(owner_id=uid, txn_date=date(2024, 1, 1), description="STARBUCKS COFFEE", amount=Decimal("10.00"), direction="OUT")
    db.add(txn_past)
    await db.flush()
    db.add(ReconciliationMatch(atomic_txn_id=txn_past.id, journal_entry_ids=["some-id"], match_score=95, status=ReconciliationStatus.AUTO_ACCEPTED))
    await db.commit()
    assert await score_pattern(db, AtomicTransaction(description="STARBUCKS #123", amount=Decimal("10.00")), DEFAULT_CONFIG, uid) == 80.0
    assert await score_pattern(db, AtomicTransaction(description="STARBUCKS #123", amount=Decimal("50.00")), DEFAULT_CONFIG, uid) == 40.0
    cand = await score_group(db, AtomicTransaction(description="Test", amount=Decimal("100.00"), txn_date=date(2024, 1, 1), currency="SGD"), [JournalEntry(memo="Test", entry_date=date(2024, 1, 1), lines=[JournalLine(amount=Decimal("100.00"), direction=Direction.DEBIT)])], DEFAULT_CONFIG, uuid4(), group_amount=Decimal("100.00"), history_score=90.0)
    assert cand.breakdown["history"] == 90.0 and "many_to_one_bonus" in cand.breakdown

    _, _, entries = await _seed_scenario(db, uid, txn_desc="Entry A", txn_amount="100.00", pair_specs=[("50.00", "Entry A"), ("60.00", "Entry B")])
    with patch("src.reconciliation.extension.candidate_policy.is_entry_balanced", side_effect=lambda e, *, base_currency: e.id != entries[1].id):
        assert all(str(entries[1].id) not in m.journal_entry_ids for m in await execute_matching(db, user_id=uid, currency="SGD"))
    with patch("src.reconciliation.extension.candidate_policy.is_entry_balanced", return_value=False):
        assert await execute_matching(db, user_id=uid, currency="SGD") == []

    uid2 = (await UserFactory.create_async(db)).id
    _, txns2, _ = await _seed_scenario(db, uid2, txn_desc="TXN", txn_amount=["100.00", "200.00"], pair_specs=[("100.00", "E1"), ("200.00", "E2")])
    assert await execute_matching(db, user_id=uid2, limit=0, currency="SGD") == []
    assert {t.id for t in txns2} <= {m.atomic_txn_id for m in await execute_matching(db, user_id=uid2, currency="SGD")} and await execute_matching(db, user_id=uid2, currency="SGD") == []

    # Transfer branches: unlinked, DB error, batch transfer, two-account auto-pair
    uid3 = (await UserFactory.create_async(db)).id
    await StatementSummaryFactory.create_async(db, user_id=uid3)
    db.add(_atomic_txn(owner_id=uid3, txn_date=date(2024, 1, 1), description="TRANSFER TO SAVINGS", amount=Decimal("500.00"), direction="OUT"))
    await db.commit()
    assert await execute_matching(db, user_id=uid3, currency="SGD") == []

    u_err, _, _, _ = await _seed_xfer(db, with_doc=False)
    with patch("src.reconciliation.extension.phases.transfer_detection.create_transfer_out_entry", side_effect=Exception("DB Error")):
        assert not [m for m in await execute_matching(db, user_id=u_err, currency="SGD") if m.score_breakdown.get("transfer_out")]

    u_bat, _, doc_b, _ = await _seed_xfer(db, desc="Batch Transfer TO savings", amount=Decimal("50.00"), direction="OUT")
    db.add(_atomic_txn(owner_id=u_bat, source_documents=[{"doc_id": str(doc_b), "doc_type": "bank_statement"}], txn_date=date(2024, 1, 1), description="Batch Transfer TO savings", amount=Decimal("50.00"), direction="OUT"))
    await db.commit()
    assert len([m for m in await execute_matching(db, user_id=u_bat, currency="SGD") if m.score_breakdown.get("transfer_out")]) == 2

    u_pair = (await UserFactory.create_async(db)).id
    _, src_acc, _, _ = await _seed_xfer(db, uid=u_pair, desc="TRANSFER TO SAVINGS", direction="OUT")
    _, dst_acc, _, _ = await _seed_xfer(db, uid=u_pair, desc="TRANSFER FROM CHECKING", direction="IN")
    pm = await execute_matching(db, user_id=u_pair, currency="SGD")
    out_m, in_m = [m for m in pm if m.score_breakdown.get("transfer_out")][0], [m for m in pm if m.score_breakdown.get("transfer_in")][0]
    proc = (await db.execute(select(Account).where(Account.user_id == u_pair, Account.code == PROCESSING_ACCOUNT_CODE))).scalar_one()
    out_e = (await db.execute(select(JournalEntry).where(JournalEntry.id == UUID(out_m.journal_entry_ids[0])).options(selectinload(JournalEntry.lines)))).scalar_one()
    in_e = (await db.execute(select(JournalEntry).where(JournalEntry.id == UUID(in_m.journal_entry_ids[0])).options(selectinload(JournalEntry.lines)))).scalar_one()
    assert {(i.account_id, i.direction, i.amount) for i in out_e.lines} == {(proc.id, Direction.DEBIT, Decimal("500.00")), (src_acc.id, Direction.CREDIT, Decimal("500.00"))}
    assert {(i.account_id, i.direction, i.amount) for i in in_e.lines} == {(dst_acc.id, Direction.DEBIT, Decimal("500.00")), (proc.id, Direction.CREDIT, Decimal("500.00"))}
    assert await get_processing_balance(db, user_id=u_pair, currency="SGD") == Decimal("0.00")


@pytest.mark.parametrize(("direction", "desc", "key"), [("OUT", "TRANSFER TO SAVINGS", "transfer_out"), ("IN", "TRANSFER FROM CHECKING", "transfer_in")])
async def test_transfer_creates_match(db: AsyncSession, direction, desc, key):
    uid, _, _, _ = await _seed_xfer(db, desc=desc, direction=direction)
    tm = [m for m in await execute_matching(db, user_id=uid, currency="SGD") if m.score_breakdown.get(key)]
    assert len(tm) == 1 and (tm[0].match_score, tm[0].status) == (100, ReconciliationStatus.AUTO_ACCEPTED)


async def test_execute_matching_errors_repo_links_and_phases(db: AsyncSession, test_user, monkeypatch) -> None:
    uid = test_user.id
    await _seed_scenario(db, uid, txn_desc="Flush Fail", txn_amount="100.00")
    with patch.object(db, "flush", side_effect=RuntimeError("Final flush failed")), patch("src.reconciliation.extension.matching.find_transfer_pairs", new_callable=AsyncMock, return_value=[]), pytest.raises(RuntimeError, match="Final flush failed"):
        await execute_matching(db, user_id=uid, currency="SGD")
    await db.rollback()
    with patch("src.reconciliation.extension.matching.find_transfer_pairs", side_effect=Exception("Pair search failed")):
        assert isinstance(await execute_matching(db, user_id=uid, currency="SGD"), list)

    uid2 = (await UserFactory.create_async(db)).id
    await _seed_scenario(db, uid2, txn_desc="Batch Bulk payment", txn_amount=["50.00", "50.00"], pair_specs=[("103.00", "Different XYZ")])
    with patch("src.reconciliation.extension.matching.load_reconciliation_config", return_value=_cfg(enable_ai_reconciliation=False)):
        m2o = [m for m in await execute_matching(db, user_id=uid2, currency="SGD") if m.score_breakdown.get("many_to_one_bonus")]
    assert m2o and all(m.status == ReconciliationStatus.PENDING_REVIEW for m in m2o)

    uid3 = (await UserFactory.create_async(db)).id
    _, txns3, _ = await _seed_scenario(db, uid3, txn_desc="Unrelated", txn_amount="100.00", txn_date=date(2024, 1, 5), pair_specs=[("100.00", "Different memo")])
    with patch("src.reconciliation.load_reconciliation_config", return_value=_cfg(auto_accept=99, pending_review=40)):
        m3 = await execute_matching(db, user_id=uid3, currency="SGD")
    assert len(m3) == 1 and m3[0].status == ReconciliationStatus.PENDING_REVIEW and m3[0].atomic_txn_id == txns3[0].id

    outcomes: list[str] = []
    monkeypatch.setattr("src.reconciliation.extension.matching.record_reconciliation_match_outcome", lambda *, outcome: outcomes.append(outcome))
    uid4 = (await UserFactory.create_async(db)).id
    exp = await AccountFactory.create_async(db, user_id=uid4, type=AccountType.EXPENSE)
    _, txns4, entries4 = await _seed_scenario(db, uid4, txn_desc="Metric", txn_amount="100.00", pair_specs=[("100.00", "Metric")], credit_account=exp)
    m4 = await execute_matching(db, user_id=uid4, currency="SGD")
    assert len(m4) == 1 and (m4[0].status, m4[0].atomic_txn_id, outcomes) == (ReconciliationStatus.AUTO_ACCEPTED, txns4[0].id, ["auto_accepted"])
    await db.commit()
    assert (await db.get(JournalEntry, entries4[0].id)).status == JournalEntryStatus.RECONCILED

    # score_single + repository + batch link sync
    uid5 = (await UserFactory.create_async(db)).id
    _, t5, e5 = await _seed_scenario(db, uid5, txn_desc="Score Pattern Test", txn_amount="100.00", pair_specs=[("100.00", "Score Pattern Test")])
    loaded = (await db.execute(select(JournalEntry).where(JournalEntry.id == e5[0].id).options(selectinload(JournalEntry.lines).selectinload(JournalLine.account)))).scalar_one()
    assert "history" in (await score_single(db, t5[0], [loaded], DEFAULT_CONFIG, user_id=uid5)).breakdown
    repo = SqlReconciliationRepository(db)
    assert [t.id for t in await repo.list_pending_transactions(uid5)] == [t5[0].id] and await repo.list_pending_transactions(uid5, limit=0) == [] and len(await repo.list_pending_transactions(uid5, limit=1)) == 1 and await repo.get_active_match(t5[0].id) is None
    a2 = _atomic_txn(owner_id=uid5, txn_date=date(2026, 1, 2), amount=Decimal("200.00"), direction=TransactionDirection.IN, description="Batch 2")
    db.add(a2)
    await db.flush()
    e2 = await create_valid_posted_entry(db, user_id=uid5, entry_date=date(2024, 3, 1))
    assert {e.id for e in await repo.list_journal_candidates(user_id=uid5, start_date=date(2024, 1, 1), end_date=date(2024, 1, 31))} == {e5[0].id}
    rm1, rm2 = ReconciliationMatch(atomic_txn_id=t5[0].id, journal_entry_ids=[str(e5[0].id)], match_score=95, status=ReconciliationStatus.AUTO_ACCEPTED), ReconciliationMatch(atomic_txn_id=a2.id, journal_entry_ids=[str(e2.id)], match_score=90, status=ReconciliationStatus.AUTO_ACCEPTED)
    await repo.add_match(rm1)
    db.add(rm2)
    await db.flush()
    assert (await repo.get_active_match(t5[0].id)).atomic_txn_id == t5[0].id
    await sync_reconciliation_matches_journal_entry_links_batch(db, [rm1, rm2], user_id=uid5)
    assert {(i.match_id, i.journal_entry_id) for i in (await db.execute(select(ReconciliationMatchJournalEntry).where(ReconciliationMatchJournalEntry.match_id.in_([rm1.id, rm2.id])))).scalars()} == {(rm1.id, e5[0].id), (rm2.id, e2.id)}
    rm1.journal_entry_ids, rm2.journal_entry_ids = [str(e5[0].id), str(e2.id)], []
    await sync_reconciliation_matches_journal_entry_links_batch(db, [rm1, rm2], user_id=uid5)
    assert {(i.match_id, i.journal_entry_id) for i in (await db.execute(select(ReconciliationMatchJournalEntry).where(ReconciliationMatchJournalEntry.match_id.in_([rm1.id, rm2.id])))).scalars()} == {(rm1.id, e5[0].id), (rm1.id, e2.id)}
    rm1.status = ReconciliationStatus.SUPERSEDED
    await db.flush()
    assert await repo.get_active_match(t5[0].id) is None


async def test_phase_mocks_unbalanced_inflow_fx_and_exclusivity(db: AsyncSession) -> None:
    uid = (await UserFactory.create_async(db)).id
    exp = await AccountFactory.create_async(db, user_id=uid, name="Exp Cache", type=AccountType.EXPENSE)
    _, txns, _ = await _seed_scenario(db, uid, txn_desc="ACME lunch", txn_amount=["10.00", "11.00"], txn_date=date(2024, 6, 10), pair_specs=[("1.00", "seed")], credit_account=exp)
    txns[1].description, txns[1].txn_date = "ACME dinner", date(2024, 6, 11)
    await db.commit()
    with _patch_phases() as mocks:
        await execute_matching(db, user_id=uid, currency="SGD")
    assert mocks["src.reconciliation.extension.matching.score_pattern"].await_count == 1

    txn_dup = _atomic_txn(owner_id=uid, txn_date=date(2024, 8, 1), description="Batch settle", amount=Decimal("100.00"), direction=TransactionDirection.OUT)
    db.add(txn_dup)
    await db.flush()
    db.add(ReconciliationMatch(atomic_txn_id=txn_dup.id, journal_entry_ids=["11111111-1111-1111-1111-111111111111"], match_score=95, score_breakdown={"amount": 100.0}, status=ReconciliationStatus.PENDING_REVIEW))
    await db.commit()
    cand = MatchCandidate(journal_entry_ids=["11111111-1111-1111-1111-111111111111"], score=95, breakdown={"amount": 100.0})
    with _patch_phases(**{"src.reconciliation.extension.phases.many_to_one.build_many_to_one_groups": {"return_value": [[txn_dup, txn_dup]]}, "src.reconciliation.extension.phases.many_to_one.prune_candidates": {"return_value": [object()]}, "src.reconciliation.extension.phases.many_to_one.is_entry_balanced": {"return_value": True}, "src.reconciliation.extension.phases.many_to_one.score_group": {"new_callable": AsyncMock, "return_value": cand}, "src.reconciliation.extension.candidate_policy.entry_total_amount": {"return_value": Decimal("100.00")}}):
        assert await execute_matching(db, user_id=uid, currency="SGD") == []

    txn_m2o, entry = _atomic_txn(owner_id=uid, txn_date=date(2024, 8, 10), description="Batch card", amount=Decimal("30.00"), direction=TransactionDirection.OUT), await create_valid_posted_entry(db, uid, entry_date=date(2024, 8, 10), memo="candidate", amount=Decimal("30.00"))
    db.add(txn_m2o)
    cand2 = MatchCandidate(journal_entry_ids=[str(entry.id)], score=95, breakdown={"amount": 100.0})
    with _patch_phases(**{"src.reconciliation.extension.phases.many_to_one.build_many_to_one_groups": {"return_value": [[txn_m2o]]}, "src.reconciliation.extension.phases.many_to_one.prune_candidates": {"return_value": [entry]}, "src.reconciliation.extension.phases.many_to_one.is_entry_balanced": {"return_value": True}, "src.reconciliation.extension.phases.many_to_one.score_group": {"new_callable": AsyncMock, "return_value": cand2}}):
        assert [m.atomic_txn_id for m in await execute_matching(db, user_id=uid, currency="SGD")] == [txn_m2o.id]

    uid_norm = (await UserFactory.create_async(db)).id
    txn_norm = _atomic_txn(owner_id=uid_norm, txn_date=date(2024, 9, 1), description="Office", amount=Decimal("50.00"), direction=TransactionDirection.OUT)
    entry_norm = await create_valid_posted_entry(db, uid_norm, entry_date=date(2024, 9, 1), memo="candidate", amount=Decimal("50.00"))
    db.add(txn_norm)
    await db.flush()
    cand_norm = MatchCandidate(journal_entry_ids=[str(entry_norm.id)], score=95, breakdown={"amount": 100.0})
    with _patch_phases(**{"src.reconciliation.extension.phases.many_to_one.build_many_to_one_groups": {"return_value": []}, "src.reconciliation.extension.phases.normal_matching.score_single": {"new_callable": AsyncMock, "return_value": cand_norm}}):
        assert [m.atomic_txn_id for m in await execute_matching(db, user_id=uid_norm, currency="SGD")] == [txn_norm.id]

    uid2 = (await UserFactory.create_async(db)).id
    await StatementSummaryFactory.create_async(db, user_id=uid2, period_start=date(2024, 9, 12), period_end=date(2024, 9, 12))
    db.add(_atomic_txn(owner_id=uid2, txn_date=date(2024, 9, 12), description="3-part", amount=Decimal("3.00"), direction=TransactionDirection.OUT))
    e3 = [await create_valid_posted_entry(db, uid2, entry_date=date(2024, 9, 12), memo=m, amount=Decimal("1.00")) for m in ("a", "b", "c")]
    with _patch_phases(**{"src.reconciliation.extension.phases.many_to_one.build_many_to_one_groups": {"return_value": []}, "src.reconciliation.extension.phases.normal_matching.prune_candidates": {"return_value": e3}, "src.reconciliation.extension.candidate_policy.is_entry_balanced": {"side_effect": lambda e, *, base_currency: e.id != e3[2].id}, "src.reconciliation.extension.phases.normal_matching.score_single": {"new_callable": AsyncMock, "return_value": MatchCandidate([str(e3[0].id)], 0, {"amount": 0.0})}, "src.reconciliation.extension.candidate_policy.entry_total_amount": {"return_value": Decimal("1.00")}}):
        assert await execute_matching(db, user_id=uid2, currency="SGD") == []

    db.add(FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.350000"), rate_date=date(2024, 4, 10), source="test"))
    bank_u, income_u, doc_u = await AccountFactory.create_async(db, user_id=uid2, name="Bank USD", currency="USD"), await AccountFactory.create_async(db, user_id=uid2, name="Income USD", type=AccountType.INCOME, currency="USD"), await UploadedDocumentFactory.create_async(db, user_id=uid2)
    await StatementSummaryFactory.create_async(
        db,
        user_id=uid2,
        account_id=bank_u.id,
        uploaded_document_id=doc_u.id,
        file_hash=doc_u.file_hash,
        currency="USD",
        period_start=date(2024, 4, 10),
        period_end=date(2024, 4, 10),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
        status=BankStatementStatus.APPROVED,
    )
    txn_u = _atomic_txn(owner_id=uid2, txn_date=date(2024, 4, 10), description="Client deposit", amount=Decimal("250.00"), direction=TransactionDirection.IN, currency="USD", source_documents=[{"doc_id": str(doc_u.id), "doc_type": DocumentType.BANK_STATEMENT.value}])
    db.add(txn_u)
    await db.commit()
    dep_entry = await submit_reviewed_disposition(db, transaction_id=txn_u.id, user_id=uid2, command=ReviewedDispositionCommand(intent=EconomicIntent.INCOME, counter_account_id=income_u.id, category="CLIENT_DEPOSIT", rationale="Reviewed."), dependencies=compose_reviewed_disposition_dependencies(db), base_currency="SGD")
    assert dep_entry.source_type == JournalEntrySourceType.USER_CONFIRMED and all((i.currency, i.fx_rate) == ("USD", Decimal("1.350000")) for i in dep_entry.lines) and income_u.id in {i.account_id for i in dep_entry.lines}

    uid3 = (await UserFactory.create_async(db)).id
    exp3 = await AccountFactory.create_async(db, user_id=uid3, name="Exp Excl", type=AccountType.EXPENSE)
    _, _, entries_x = await _seed_scenario(db, uid3, txn_desc="微信支付-星巴克", txn_amount=["18.50", "18.50"], txn_date=date(2026, 4, 10), pair_specs=[("18.50", "微信支付-星巴克")], credit_account=exp3)
    m1 = await execute_matching(db, user_id=uid3, currency="SGD")
    assert len(m1) == 1 and m1[0].journal_entry_ids == [str(entries_x[0].id)] and m1[0].status == ReconciliationStatus.AUTO_ACCEPTED and await execute_matching(db, user_id=uid3, currency="SGD") == []
    rows = [_atomic_txn(owner_id=uid3, txn_date=date(2026, 5, 1 + i), description="Daily Cafe", amount=Decimal("10.00"), direction=TransactionDirection.OUT) for i in range(5)]
    rows.append(_atomic_txn(owner_id=uid3, txn_date=date(2026, 5, 5), description="Tokyo Hotel", amount=Decimal("50000.00"), direction=TransactionDirection.OUT, currency="JPY"))
    rows.extend([_atomic_txn(owner_id=uid3, txn_date=date(2026, 5, 25), description="Future Cafe", amount=Decimal("5000.00"), direction=TransactionDirection.OUT) for _ in range(3)])
    target = _atomic_txn(owner_id=uid3, txn_date=date(2026, 5, 10), description="Daily Cafe", amount=Decimal("150.00"), direction=TransactionDirection.OUT)
    db.add_all([*rows, target])
    await db.commit()
    scoped_types = {i.anomaly_type for i in await detect_anomalies(db, target, user_id=uid3)}
    assert "LARGE_AMOUNT" in scoped_types and "NEW_MERCHANT" not in scoped_types


def test_normal_entry_combinations_parity_and_precomputation() -> None:
    uid = uuid4()
    txn = AtomicTransaction(id=uuid4(), user_id=uid, txn_date=date(2026, 1, 1), direction=TransactionDirection.OUT, currency="SGD", amount=Decimal("100.00"), description="Test Txn")

    def _e(amt: Decimal, bal: bool = True) -> JournalEntry:
        eid = uuid4()
        lines = [JournalLine(id=uuid4(), journal_entry_id=eid, account_id=uuid4(), direction=Direction.DEBIT, amount=amt, currency="SGD")] + ([JournalLine(id=uuid4(), journal_entry_id=eid, account_id=uuid4(), direction=Direction.CREDIT, amount=amt, currency="SGD")] if bal else [])
        return JournalEntry(id=eid, user_id=uid, source_type=JournalEntrySourceType.MANUAL, status=JournalEntryStatus.POSTED, entry_date=date(2026, 1, 1), memo="E", decision_authority_state=JournalEntryAuthorityState.LEGACY_UNPROVEN, lines=lines)

    e50a, e50b, e30, e20, e_bad = _e(Decimal("50")), _e(Decimal("50")), _e(Decimal("30")), _e(Decimal("20")), _e(Decimal("100"), False)
    combos = list(_normal_entry_combinations(txn, [e50a, e50b, e30, e20, e_bad], DEFAULT_CONFIG, base_currency="SGD"))
    singles = [c for c in combos if len(c) == 1]
    assert len(singles) == 4 and e_bad not in [c[0] for c in singles] and ([e50a, e50b] in [c for c in combos if len(c) == 2] or [e50b, e50a] in [c for c in combos if len(c) == 2])
    triple_ids = [{e.id for e in t} for t in combos if len(t) == 3]
    assert {e50a.id, e30.id, e20.id} in triple_ids and {e50b.id, e30.id, e20.id} in triple_ids


@pytest.mark.parametrize(("combined", "amount", "expected"), [(Decimal("101.00"), Decimal("100.00"), True), (Decimal("101.01"), Decimal("100.00"), False), (Decimal("98.99"), Decimal("100.00"), False), (Decimal("0.30"), Decimal("0.10"), True), (Decimal("0.31"), Decimal("0.10"), False)])
def test_within_combination_tolerance_boundaries(combined: Decimal, amount: Decimal, expected: bool) -> None:
    assert _within_combination_tolerance(combined, SimpleNamespace(amount=amount, currency="USD"), DEFAULT_CONFIG) is expected


@pytest.mark.parametrize(("error_factory", "expected_exc"), [(lambda: __import__("src.ledger", fromlist=["ProcessingCurrencyConflictError"]).ProcessingCurrencyConflictError("conflict"), "ProcessingCurrencyConflictError"), (lambda: RuntimeError("ledger unavailable"), "RuntimeError"), (lambda: __import__("src.ledger", fromlist=["TransferAccountCurrencyMismatchError"]).TransferAccountCurrencyMismatchError("mismatch"), None)])
async def test_transfer_detection_error_handling(monkeypatch, error_factory, expected_exc) -> None:
    txn = SimpleNamespace(id=uuid4(), description="Transfer to savings", direction="OUT", amount=Decimal("25.00"), txn_date=date(2026, 1, 1), currency="SGD")
    repo = SimpleNamespace(claim_transaction=AsyncMock(return_value=None), add_match=AsyncMock())
    monkeypatch.setattr(transfer_detection, "resolve_custody_account_id", AsyncMock(return_value=uuid4()))
    monkeypatch.setattr(transfer_detection, "create_transfer_out_entry", AsyncMock(side_effect=error_factory()))
    monkeypatch.setattr(transfer_detection.logger, "exception", Mock())
    matched_ids: set = set()
    kw = {"transactions": [txn], "matched_txn_ids": matched_ids, "repository": repo, "user_id": uuid4(), "base_currency": "SGD"}
    if expected_exc is None:
        assert await transfer_detection.run_transfer_detection_phase(SimpleNamespace(), **kw) == [] and matched_ids == set()
        repo.add_match.assert_not_awaited()
    else:
        with pytest.raises(Exception) as raised:
            await transfer_detection.run_transfer_detection_phase(SimpleNamespace(), **kw)
        assert type(raised.value).__name__ == expected_exc
