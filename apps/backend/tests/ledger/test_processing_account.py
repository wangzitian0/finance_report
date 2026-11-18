from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.extraction import TransactionDirection
from src.ledger import (
    AccountType,
    Direction,
    JournalEntryStatus,
    ValidationError,
    calculate_account_balance,
    create_transfer_in_entry,
    create_transfer_out_entry,
    detect_transfer_pattern,
    find_transfer_pairs,
    fit_journal_memo,
    get_or_create_processing_account,
    get_processing_balance,
    get_unpaired_transfers,
    post_journal_entry,
)
from src.ledger.base.memo import JOURNAL_MEMO_MAX_LENGTH
from src.ledger.base.processing import _calculate_pair_confidence, _score_amount_match, _score_date_proximity
from src.ledger.extension.account_service import list_accounts
from src.ledger.orm.journal import JournalEntry
from src.reconciliation import score_description
from tests.factories import AtomicTransactionFactory, UploadedDocumentFactory, UserFactory
from tests.ledger._ledger_helpers import make_account, make_entry


async def test_processing_account_creation_and_isolation(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    p1 = await get_or_create_processing_account(db, uid, currency="SGD")
    p2 = await get_or_create_processing_account(db, uid, currency="SGD")
    assert (p1.id, p1.name, p1.code, p1.type, p1.is_system, p1.currency) == (
        p2.id,
        "Processing",
        "1199",
        AccountType.ASSET,
        True,
        "SGD",
    )
    await make_account(db, uid, "Cash", AccountType.ASSET, code="1001", is_system=False)
    accounts, total = await list_accounts(db, uid)
    assert total == 1 and accounts[0].name == "Cash" and all(not a.is_system for a in accounts)

    other_id = (await UserFactory.create_async(db)).id
    p_other = await get_or_create_processing_account(db, other_id, currency="SGD")
    assert p_other.user_id == other_id and p_other.id != p1.id


async def test_processing_account_transfers_and_equation(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    cash = await make_account(db, uid, "Cash", AccountType.ASSET, code="1001")
    checking = await make_account(db, uid, "Checking", AccountType.ASSET, code="1002")
    equity = await make_account(db, uid, "Equity", AccountType.EQUITY, code="3001")
    processing = await get_or_create_processing_account(db, uid, currency="SGD")

    await make_entry(db, uid, [(cash.id, Direction.DEBIT, "500.00"), (equity.id, Direction.CREDIT, "500.00")])
    await make_entry(db, uid, [(processing.id, Direction.DEBIT, "200.00"), (cash.id, Direction.CREDIT, "200.00")])
    assert await calculate_account_balance(db, processing.id, uid) == Decimal("200.00")

    await make_entry(db, uid, [(checking.id, Direction.DEBIT, "200.00"), (processing.id, Direction.CREDIT, "200.00")])
    cash_b, proc_b, chk_b, eq_b = [
        await calculate_account_balance(db, acc.id, uid) for acc in (cash, processing, checking, equity)
    ]
    assert (proc_b, cash_b, chk_b, cash_b + proc_b + chk_b, eq_b) == (
        Decimal("0.00"),
        Decimal("300.00"),
        Decimal("200.00"),
        Decimal("500.00"),
        Decimal("500.00"),
    )


@pytest.mark.parametrize(
    ("source_type", "should_fail"),
    [(JournalEntrySourceType.MANUAL, True), (JournalEntrySourceType.SYSTEM, False)],
)
async def test_processing_account_posting_authority(db: AsyncSession, test_user, source_type, should_fail: bool) -> None:
    uid = test_user.id
    processing = await get_or_create_processing_account(db, uid, currency="SGD")
    cash = await make_account(db, uid, "Cash", AccountType.ASSET, code="1001")
    entry = await make_entry(
        db,
        uid,
        [(processing.id, Direction.DEBIT, "100.00"), (cash.id, Direction.CREDIT, "100.00")],
        status=JournalEntryStatus.DRAFT,
        source_type=source_type,
    )
    if should_fail:
        with pytest.raises(ValidationError, match="System accounts.*system-generated"):
            await post_journal_entry(db, entry.id, uid)
    else:
        assert (await post_journal_entry(db, entry.id, uid)).status == JournalEntryStatus.POSTED


async def test_transfer_detection_pairing_and_unpaired_queries(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    doc = await UploadedDocumentFactory.create_async(db, user_id=uid)
    for desc, expected in (
        ("TRANSFER TO JOHN DOE", True),
        ("Fast Payment to Bank B", True),
        ("PAYNOW TRANSFER", True),
        ("STARBUCKS COFFEE #1234", False),
        ("", False),
    ):
        txn = await AtomicTransactionFactory.create_async(
            db, user_id=uid, source_doc_id=doc.id, txn_date=date.today(), description=desc, amount=Decimal("10.00"), direction=TransactionDirection.OUT
        )
        assert detect_transfer_pattern(txn.description) is expected

    assert await get_unpaired_transfers(db, uid, currency="SGD") == []
    assert await get_processing_balance(db, uid, currency="SGD") == Decimal("0")

    cash = await make_account(db, uid, "Cash", AccountType.ASSET, code="1001")
    checking = await make_account(db, uid, "Checking", AccountType.ASSET, code="1002")
    await create_transfer_out_entry(db, user_id=uid, source_account_id=cash.id, amount=Decimal("100.00"), txn_date=date.today(), description="Transfer to Bank B", currency="SGD")
    assert len(await get_unpaired_transfers(db, uid, currency="SGD")) == 1
    assert await get_processing_balance(db, uid, currency="SGD") == Decimal("100.00")

    await create_transfer_in_entry(db, user_id=uid, dest_account_id=checking.id, amount=Decimal("100.00"), txn_date=date.today(), description="Transfer to Bank B", currency="SGD")
    pairs = await find_transfer_pairs(db, uid, currency="SGD", description_scorer=score_description, threshold=85)
    assert len(pairs) == 1 and pairs[0].confidence >= 85 and pairs[0].score_breakdown["amount"] == 100.0


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [("100.00", "100.01", 100.0), ("100.00", "100.10", 95.0), ("100.00", "101.00", 85.0), ("100.00", "105.00", 70.0), ("0", "100.00", 0.0), ("100.00", "110.00", 90.0)],
)
def test_score_amount_match(a, b, expected) -> None:
    assert _score_amount_match(Decimal(a), Decimal(b)) == expected


def test_scoring_and_pair_confidence_edge_cases() -> None:
    assert score_description("TRANSFER TO BANK B", "transfer to bank b") == 100.0
    assert 50 < score_description("Transfer to Bank B", "Transfer to Bank A") < 100
    for left, right in ((None, "Transfer"), ("Transfer", None), (None, None), ("   ", "Transfer"), ("Transfer", "   ")):
        assert score_description(left, right) == 0.0

    for d1, d2, expected in (
        (date(2025, 1, 15), date(2025, 1, 15), 100.0),
        (date(2025, 1, 15), date(2025, 1, 16), 95.0),
        (date(2025, 1, 15), date(2025, 1, 18), 85.0),
        (date(2025, 1, 15), date(2025, 1, 22), 70.0),
        (date(2025, 1, 15), date(2025, 1, 30), 0.0),
    ):
        assert _score_date_proximity(d1, d2) == expected

    def _mock_entry(lines_data):
        return SimpleNamespace(
            memo="test",
            entry_date=date.today(),
            lines=[SimpleNamespace(account_id=aid, direction=d, amount=Decimal(amt)) for aid, d, amt in lines_data],
        )

    a, b = uuid4(), uuid4()
    s1, bd1 = _calculate_pair_confidence(
        _mock_entry([(a, Direction.DEBIT, "100"), (b, Direction.CREDIT, "100")]),
        _mock_entry([(b, Direction.DEBIT, "100"), (a, Direction.CREDIT, "100")]),
        processing_account_id=None,
        description_scorer=score_description,
    )
    _, bd2 = _calculate_pair_confidence(
        _mock_entry([(a, Direction.CREDIT, "100")]),
        _mock_entry([(b, Direction.CREDIT, "100")]),
        processing_account_id=None,
        description_scorer=score_description,
    )
    _, bd3 = _calculate_pair_confidence(
        _mock_entry([(a, Direction.DEBIT, "100"), (b, Direction.CREDIT, "100")]),
        _mock_entry([(b, Direction.DEBIT, "50")]),
        processing_account_id=None,
        description_scorer=score_description,
    )
    assert s1 > 0 and bd1["amount"] == 100.0 and bd2["amount"] == 100.0 and bd3["amount"] == 0.0

    assert JOURNAL_MEMO_MAX_LENGTH == JournalEntry.__table__.c.memo.type.length == 500
    assert fit_journal_memo("x" * 600) == "x" * 500 and fit_journal_memo("x" * 499) == "x" * 499


@pytest.mark.parametrize(
    ("fn", "amount", "desc", "match"),
    [
        (create_transfer_out_entry, "0", "Test", "Transfer amount must be positive"),
        (create_transfer_out_entry, "-50", "Test", "Transfer amount must be positive"),
        (create_transfer_out_entry, "100", "", "Transfer description must not be empty"),
        (create_transfer_out_entry, "100", "   ", "Transfer description must not be empty"),
        (create_transfer_in_entry, "0", "Test", "Transfer amount must be positive"),
        (create_transfer_in_entry, "100", "", "Transfer description must not be empty"),
    ],
)
async def test_transfer_entry_validation(db: AsyncSession, test_user, fn, amount, desc, match) -> None:
    acct = await make_account(db, test_user.id, "Cash", AccountType.ASSET, code="1001")
    with pytest.raises(ValueError, match=match):
        await fn(db, test_user.id, acct.id, Decimal(amount), date.today(), desc, currency="SGD")


async def test_find_transfer_pairs_orders_and_excludes_paired_before_limit(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    bank_a = await make_account(db, uid, "Bank A", AccountType.ASSET, code="1001")
    bank_b = await make_account(db, uid, "Bank B", AccountType.ASSET, code="1002")
    unpaired_out = await create_transfer_out_entry(db, user_id=uid, source_account_id=bank_a.id, amount=Decimal("400.00"), txn_date=date(2025, 3, 1), description="Older transfer to Bank B", currency="SGD")
    unpaired_in = await create_transfer_in_entry(db, user_id=uid, dest_account_id=bank_b.id, amount=Decimal("400.00"), txn_date=date(2025, 3, 1), description="Older transfer to Bank B", currency="SGD")
    paired_out = await create_transfer_out_entry(db, user_id=uid, source_account_id=bank_a.id, amount=Decimal("250.00"), txn_date=date(2025, 3, 5), description="Already paired A", currency="SGD")
    paired_in = await create_transfer_in_entry(db, user_id=uid, dest_account_id=bank_b.id, amount=Decimal("999.00"), txn_date=date(2025, 3, 5), description="Already paired B", currency="SGD")

    assert await find_transfer_pairs(db, uid, currency="SGD", description_scorer=score_description, threshold=85, max_entries=1) == []
    captured: list = []
    real_execute = db.execute

    async def spy_execute(statement, *args, **kwargs):
        captured.append(statement)
        return await real_execute(statement, *args, **kwargs)

    db.execute = AsyncMock(side_effect=spy_execute)
    try:
        pairs = await find_transfer_pairs(db, uid, currency="SGD", description_scorer=score_description, threshold=85, max_entries=1, exclude_entry_ids={paired_out.id, paired_in.id})
    finally:
        db.execute = real_execute

    assert len(pairs) == 1 and (pairs[0].out_entry.id, pairs[0].in_entry.id) == (unpaired_out.id, unpaired_in.id)
    compiled_sql = str(captured[-1].compile(compile_kwargs={"literal_binds": False}))
    assert "ORDER BY journal_entries.entry_date DESC, journal_entries.created_at DESC, journal_entries.id DESC" in compiled_sql
    assert "journal_entries.id NOT IN" in compiled_sql and "LIMIT" in compiled_sql
