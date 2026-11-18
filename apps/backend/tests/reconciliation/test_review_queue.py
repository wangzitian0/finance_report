from __future__ import annotations

import inspect
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, TraceScope
from src.config import settings
from src.extraction import ClassificationStatus, EconomicIntent, RuleType, TransactionDirection
from src.extraction.extension.review_queue import create_entry_from_txn, get_or_create_account
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.ledger import AccountType, JournalEntry, JournalEntryStatus, ValidationError, journal_command_target
from src.pricing import PricingError
from src.reconciliation import AmountMismatchError, EntryCreationError, MatchNotFoundError, ReconciliationStatus
from src.reconciliation.extension.review_queue import accept_match, accept_pending_matches, batch_decide_matches, get_pending_items, reject_match
from tests.factories import AccountFactory, AtomicTransactionFactory, JournalEntryFactory, ReconciliationMatchFactory, StatementSummaryFactory, UploadedDocumentFactory, UserFactory
from tests.ledger._ledger_helpers import create_valid_void_entry
from tests.statement_ingestion import anchored_reviewed_posting_inputs


async def _seed_txn(db: AsyncSession, uid, *, amount: Decimal = Decimal("50.00"), direction: TransactionDirection = TransactionDirection.OUT, txn_date: date | None = None, description: str = "Transaction", currency: str = "SGD", account_id=None, create_account: bool = False, commit: bool = True):
    if create_account:
        account_id = (await AccountFactory.create_async(db, user_id=uid, name="Test custody account", currency=currency)).id
    doc = await UploadedDocumentFactory.create_async(db, user_id=uid)
    stmt = await StatementSummaryFactory.create_async(db, user_id=uid, account_id=account_id, uploaded_document_id=doc.id, file_hash=doc.file_hash, currency=currency)
    txn = await AtomicTransactionFactory.create_async(db, user_id=uid, source_doc_id=doc.id, amount=amount, direction=direction, txn_date=txn_date or date.today(), description=description, currency=currency)
    if commit:
        await db.commit()
    return stmt, txn


async def _reviewed_entry(db: AsyncSession, txn, *, user_id, counter_account=None, **kw):
    intent = EconomicIntent.INCOME if txn.direction is TransactionDirection.IN else EconomicIntent.EXPENSE
    dec, d_cnt, s_dec, em = await anchored_reviewed_posting_inputs(db, user_id=user_id, transaction=txn, intent=intent)
    return await create_entry_from_txn(db, txn, user_id=user_id, disposition=dec, counter_account=counter_account or d_cnt, source_decision=s_dec, trace_emitter=em, base_currency=kw.pop("base_currency", "SGD"), **kw)


async def _seed_match(db: AsyncSession, uid, *, reviewed: bool = False, status: ReconciliationStatus = ReconciliationStatus.PENDING_REVIEW, score: int | None = None, doc_id=None):
    if doc_id is None:
        stmt, txn = await _seed_txn(db, uid, amount=Decimal("100.00") if reviewed else Decimal("50.00"), create_account=reviewed, commit=False)
        doc_id = stmt.uploaded_document_id
    else:
        txn = await AtomicTransactionFactory.create_async(db, user_id=uid, source_doc_id=doc_id, amount=Decimal("100.00") if reviewed else Decimal("50.00"), direction=TransactionDirection.OUT, txn_date=date.today(), description="Txn", currency="SGD")
    entry = await _reviewed_entry(db, txn, user_id=uid, auto_post=True) if reviewed else (await JournalEntryFactory.create_balanced_async(db, user_id=uid))[0]
    m = await ReconciliationMatchFactory.create_async(db, atomic_txn_id=txn.id, journal_entry_ids=[str(entry.id)], status=status, **({"match_score": score} if score is not None else {}))
    await db.commit()
    return doc_id, txn, entry, m


async def test_pending_items_accept_reject_and_guards(db, test_user):
    uid = test_user.id
    assert "skip_amount_validation" not in inspect.signature(accept_match).parameters
    await _seed_match(db, uid, status=ReconciliationStatus.ACCEPTED)
    assert await get_pending_items(db, user_id=uid) == []
    _, _, _, pending = await _seed_match(db, uid, status=ReconciliationStatus.PENDING_REVIEW)
    assert [m.status for m in await get_pending_items(db, user_id=uid)] == [ReconciliationStatus.PENDING_REVIEW]

    _, _, _, acc_done = await _seed_match(db, uid, status=ReconciliationStatus.ACCEPTED)
    _, _, _, rej_done = await _seed_match(db, uid, status=ReconciliationStatus.REJECTED)
    assert (await accept_match(db, acc_done.id, user_id=uid)).version == 1 and (await reject_match(db, str(rej_done.id), user_id=uid)).version == 1
    for fn in (accept_match, reject_match):
        with pytest.raises(MatchNotFoundError, match="Match not found"):
            await fn(db, str(uuid4()), user_id=uid)

    _, txn, entry, rev = await _seed_match(db, uid, reviewed=True)
    res_acc = await accept_match(db, rev.id, user_id=uid)
    await db.refresh(entry)
    assert (res_acc.status, res_acc.version, entry.status, entry.source_type) == (ReconciliationStatus.ACCEPTED, 2, JournalEntryStatus.RECONCILED, JournalEntrySourceType.AUTO_PARSED)
    res_rej = await reject_match(db, str(pending.id), user_id=uid)
    assert (res_rej.status, res_rej.version) == (ReconciliationStatus.REJECTED, 2)

    _, bad_txn, _, bad_rev = await _seed_match(db, uid, reviewed=True)
    bad_txn.amount = Decimal("500.00")
    await db.commit()
    with pytest.raises(AmountMismatchError, match="Amount mismatch"):
        await accept_match(db, bad_rev.id, user_id=uid)

    acc = await AccountFactory.create_async(db, user_id=uid, name="Mapped")
    _, txn_empty = await _seed_txn(db, uid, account_id=acc.id, amount=Decimal("42.00"), commit=False)
    m_empty = await ReconciliationMatchFactory.create_async(db, atomic_txn_id=txn_empty.id, journal_entry_ids=[], status=ReconciliationStatus.PENDING_REVIEW)
    await db.commit()
    with pytest.raises(EntryCreationError, match="pre-existing journal entry"):
        await accept_match(db, m_empty.id, user_id=uid)
    await db.refresh(m_empty)
    assert m_empty.status == ReconciliationStatus.PENDING_REVIEW and m_empty.journal_entry_ids == []

    _, txn_void = await _seed_txn(db, uid, amount=Decimal("100.00"), commit=False)
    void_entry = await create_valid_void_entry(db, uid, memo="Void match candidate")
    m_void = await ReconciliationMatchFactory.create_async(db, atomic_txn_id=txn_void.id, journal_entry_ids=[str(void_entry.id)], status=ReconciliationStatus.PENDING_REVIEW, match_score=95)
    await db.commit()
    with pytest.raises(EntryCreationError, match="current decision authority"):
        await accept_match(db, m_void.id, user_id=uid)
    await db.refresh(void_entry)
    assert void_entry.status == JournalEntryStatus.VOID


async def test_accept_pending_and_batch_decide_matches(db, test_user):
    uid = test_user.id
    assert await accept_pending_matches(db, [], user_id=uid) == 0 and (await batch_decide_matches(db, user_id=uid, action="accept", match_ids=[])).approved_count == 0
    doc_id, _, e1, m1 = await _seed_match(db, uid, reviewed=True, score=90)
    _, _, _, m2 = await _seed_match(db, uid, reviewed=True, score=90, doc_id=doc_id)
    await accept_pending_matches(db, [m1, m2], user_id=uid)
    await db.refresh(e1)
    assert all(m.status == ReconciliationStatus.ACCEPTED for m in (m1, m2)) and e1.status == JournalEntryStatus.RECONCILED

    _, _, e3, m3 = await _seed_match(db, uid, reviewed=True, score=90, doc_id=doc_id)
    _, _, _, m4 = await _seed_match(db, uid, reviewed=True, score=90, doc_id=doc_id)
    _, _, _, m_low = await _seed_match(db, uid, score=50)
    assert (await batch_decide_matches(db, user_id=uid, action="accept", match_ids=[m_low.id], min_score=80)).approved_count == 0
    res = await batch_decide_matches(db, user_id=uid, action="accept", match_ids=[m3.id, m4.id], min_score=80)
    await db.refresh(e3)
    assert res.approved_count == 2 and all(m.status == ReconciliationStatus.ACCEPTED for m in (m3, m4)) and e3.status == JournalEntryStatus.RECONCILED


@pytest.mark.parametrize("case", ["no_mapping", "bad_stmt", "unowned_bank", "mismatched_bank", "wrong_user", "out_no_disp", "in_no_disp", "unbalanced"])
async def test_create_entry_error_branches(db, test_user, case: str):
    uid = test_user.id
    if case == "no_mapping":
        _, txn = await _seed_txn(db, uid, direction=TransactionDirection.IN, amount=Decimal("75.00"))
        with pytest.raises(ValueError, match="Account mapping required before statement posting"):
            await create_entry_from_txn(db, txn, user_id=uid, auto_post=True, base_currency="SGD")
    elif case == "bad_stmt":
        stmt, txn = await _seed_txn(db, uid)
        other, _ = await _seed_txn(db, uid)
        other.user_id = uuid4()
        with pytest.raises(ValueError, match="Preloaded statement does not match"):
            await create_entry_from_txn(db, txn, user_id=uid, preloaded_statement=other, base_currency="SGD")
    elif case in ("unowned_bank", "mismatched_bank"):
        acc = await AccountFactory.create_async(db, user_id=uid)
        other_acc = await AccountFactory.create_async(db, user_id=(await UserFactory.create_async(db)).id if case == "unowned_bank" else uid, name="Other Bank")
        stmt, txn = await _seed_txn(db, uid, account_id=acc.id)
        with pytest.raises(ValueError, match="Bank account does not belong to user" if case == "unowned_bank" else "Preloaded bank account does not match statement"):
            await create_entry_from_txn(db, txn, user_id=uid, preloaded_statement=stmt, preloaded_bank_account=other_acc, base_currency="SGD")
    elif case == "wrong_user":
        _, txn = await _seed_txn(db, uid)
        with pytest.raises(ValueError, match="Transaction does not belong to user"):
            await create_entry_from_txn(db, txn, user_id=uuid4(), base_currency="SGD")
    elif case in ("out_no_disp", "in_no_disp"):
        _, txn = await _seed_txn(db, uid, create_account=True, direction=TransactionDirection.OUT if case == "out_no_disp" else TransactionDirection.IN)
        with pytest.raises(ValueError, match="Authoritative economic disposition"):
            await create_entry_from_txn(db, txn, user_id=uid, base_currency="SGD")
    else:
        _, txn = await _seed_txn(db, uid, create_account=True, direction=TransactionDirection.IN, amount=Decimal("10.00"))
        with patch("src.extraction.extension.review_queue.submit_anchored_journal_entry", side_effect=ValidationError("not balanced")), pytest.raises(ValueError, match="Generated entry does not balance"):
            await _reviewed_entry(db, txn, user_id=uid)


async def test_create_entry_paths_ownership_classification_and_fx_rate(db, test_user):
    uid = test_user.id
    a1 = await get_or_create_account(db, name="Same", account_type=AccountType.ASSET, currency="SGD", user_id=uid)
    a2 = await get_or_create_account(db, name="Same", account_type=AccountType.ASSET, currency="SGD", user_id=uid)
    assert (a1.id, a1.name, a1.type, a1.currency) == (a2.id, "Same", AccountType.ASSET, "SGD")

    for direction, amt in ((TransactionDirection.IN, Decimal("200.00")), (TransactionDirection.OUT, Decimal("50.00"))):
        _, txn = await _seed_txn(db, uid, create_account=True, direction=direction, amount=amt)
        assert (e := await _reviewed_entry(db, txn, user_id=uid)).status == JournalEntryStatus.DRAFT and len(e.lines) == 2

    linked = await AccountFactory.create_async(db, user_id=uid, name="DBS Savings")
    _, t_lnk = await _seed_txn(db, uid, account_id=linked.id, direction=TransactionDirection.IN, amount=Decimal("300.00"))
    posted = await _reviewed_entry(db, t_lnk, user_id=uid, auto_post=True)
    assert posted.status == JournalEntryStatus.POSTED and linked.id in {item.account_id for item in posted.lines}

    other_acc = await AccountFactory.create_async(db, user_id=(await UserFactory.create_async(db)).id, name="Other")
    with pytest.raises(IntegrityError):
        await _seed_txn(db, uid, account_id=other_acc.id)
    await db.rollback()

    cls_acc = await AccountFactory.create_async(db, user_id=uid, name="Expense Dining", type=AccountType.EXPENSE)
    _, t_cls = await _seed_txn(db, uid, create_account=True, direction=TransactionDirection.OUT, amount=Decimal("80.00"), description="Dinner", commit=False)
    rule = ClassificationRule(user_id=uid, version_number=1, effective_date=t_cls.txn_date, rule_name="Food", rule_type=RuleType.KEYWORD_MATCH, rule_config={"keywords": ["dinner"]}, default_account_id=cls_acc.id, created_by=uid)
    db.add(rule)
    await db.flush()
    db.add(TransactionClassification(atomic_txn_id=t_cls.id, rule_version_id=rule.id, account_id=cls_acc.id, confidence_score=100, status=ClassificationStatus.APPLIED))
    await ReconciliationMatchFactory.create_async(db, atomic_txn_id=t_cls.id, journal_entry_ids=[], status=ReconciliationStatus.PENDING_REVIEW)
    await db.commit()
    assert next(i for i in (await _reviewed_entry(db, t_cls, user_id=uid, counter_account=cls_acc)).lines if i.direction.value == "DEBIT").account_id == cls_acc.id

    _, cny_txn = await _seed_txn(db, uid, currency="CNY", create_account=True, direction=TransactionDirection.OUT, amount=Decimal("100.00"), txn_date=date(2025, 1, 15))
    with patch("src.extraction.extension.review_queue.get_exchange_rate", return_value=Decimal("0.19")) as mock_fx:
        assert (await _reviewed_entry(db, cny_txn, user_id=uid)).status == JournalEntryStatus.DRAFT
    mock_fx.assert_awaited_once_with(db, "CNY", "SGD", date(2025, 1, 15), lazy_load=True)

    _, cny_fail = await _seed_txn(db, uid, currency="CNY", direction=TransactionDirection.OUT, amount=Decimal("100.00"), txn_date=date(2025, 1, 15))
    with patch("src.extraction.extension.review_queue.get_exchange_rate", side_effect=PricingError("No FX")), pytest.raises(ValueError, match="FX rate required to create CNY journal entry"):
        await create_entry_from_txn(db, cny_fail, user_id=uid, base_currency="SGD")


@pytest.mark.parametrize("auto_post", [True, False])
@pytest.mark.parametrize(("description", "expected_length"), [("x" * 499, 499), ("x" * 500, 500), ("x" * 501, 500), ("PAYNOW " + "y" * 593, 500), ("转账" * 300, 500), ("a" * 499 + " " + "b" * 100, 500), (" " + "c" * 100 + " ", 102)], ids=["499", "500", "501", "600-ascii", "600-chinese", "space-at-the-cut", "edge-spaces"])
async def test_AC_extraction_statement_memo_1_a_long_description_posts_one_entry_with_a_cut_memo(db, test_user, description, expected_length, auto_post):
    linked = await AccountFactory.create_async(db, user_id=test_user.id, name="Mapped Bank")
    _, txn = await _seed_txn(db, test_user.id, account_id=linked.id, direction=TransactionDirection.OUT, amount=Decimal("12.00"), description=description)
    entry = await _reviewed_entry(db, txn, user_id=test_user.id, auto_post=auto_post)
    assert len(entry.memo) == expected_length and entry.memo == description[:500]


async def test_AC_extraction_statement_memo_1_the_anchor_covers_the_stored_memo_and_a_retry_finds_the_entry(db, test_user):
    linked = await AccountFactory.create_async(db, user_id=test_user.id, name="Mapped Bank")
    _, txn = await _seed_txn(db, test_user.id, account_id=linked.id, direction=TransactionDirection.OUT, amount=Decimal("12.00"), description="PAYNOW " + "y" * 593)
    dec, c_acc, s_dec, emitter = await anchored_reviewed_posting_inputs(db, user_id=test_user.id, transaction=txn, intent=EconomicIntent.EXPENSE)
    kw = {"user_id": test_user.id, "base_currency": "SGD", "disposition": dec, "counter_account": c_acc, "source_decision": s_dec, "trace_emitter": emitter, "auto_post": True}
    first = await create_entry_from_txn(db, txn, **kw)
    await db.commit()
    second = await create_entry_from_txn(db, txn, **kw)
    await db.commit()
    assert second.id == first.id and (await db.execute(select(func.count(JournalEntry.id)).where(JournalEntry.source_id == txn.id))).scalar_one() == 1
    record = await emitter.repository.get(TraceScope.tenant(test_user.id), first.decision_anchor_id)
    lines = sorted(first.lines, key=lambda item: item.direction.value != "DEBIT")
    assert record.target == journal_command_target(entry_date=first.entry_date, memo=first.memo, lines_data=[{"account_id": i.account_id, "direction": i.direction, "amount": i.amount, "currency": i.currency, "fx_rate": i.fx_rate, "event_type": i.event_type, "tags": i.tags} for i in lines], base_currency=settings.base_currency.upper(), source_identity=f"statement-transaction:{txn.id}")
