from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.advisor.orm.chat import ChatMessageRole, ChatSessionStatus
from src.audit import JournalEntrySourceType
from src.ledger import AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from tests.ledger._ledger_helpers import make_account, make_entry


async def _valid_posted_entry(db: AsyncSession, user_id, *, memo: str = "posted") -> tuple[JournalEntry, JournalLine]:
    debit_acc = await make_account(db, user_id, f"{memo} cash", AccountType.ASSET, is_active=True)
    credit_acc = await make_account(db, user_id, f"{memo} income", AccountType.INCOME, is_active=True)
    entry = await make_entry(
        db,
        user_id,
        [(debit_acc.id, Direction.DEBIT, "100.00"), (credit_acc.id, Direction.CREDIT, "100.00")],
        memo=memo,
        commit=True,
    )
    await db.refresh(entry, ["lines"])
    return entry, next(ln for ln in entry.lines if ln.direction == Direction.DEBIT)


async def _reject_commit(db: AsyncSession, action) -> None:
    with pytest.raises(IntegrityError):
        await action()
        await db.commit()
    await db.rollback()


async def test_posted_entry_db_constraints_and_immutability(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    for spec in (
        [(Direction.DEBIT, "10.00", "SGD", None)],
        [(Direction.DEBIT, "100.00", "SGD", None), (Direction.CREDIT, "99.98", "SGD", None)],
        [(Direction.DEBIT, "100.00", "HKD", Decimal("0")), (Direction.CREDIT, "100.00", "SGD", None)],
    ):
        c = await make_account(db, uid, "c", AccountType.ASSET, is_active=True)
        i = await make_account(db, uid, "i", AccountType.INCOME, is_active=True)
        lines = [(c.id if d == Direction.DEBIT else i.id, d, amt, ccy, fx) for d, amt, ccy, fx in spec]
        await _reject_commit(db, lambda lines=lines: make_entry(db, uid, lines, memo="bad"))

    entry, debit = await _valid_posted_entry(db, uid)
    entry_id, debit_id = entry.id, debit.id
    rec, _ = await _valid_posted_entry(db, uid, memo="rec guard")
    rec_id = rec.id
    extra_c = await make_account(db, uid, "extra c", AccountType.ASSET, is_active=True)
    extra_i = await make_account(db, uid, "extra i", AccountType.INCOME, is_active=True)
    await db.commit()
    extra_cid, extra_iid = extra_c.id, extra_i.id

    async def mut_memo():
        (await db.get(JournalEntry, entry_id)).memo = "mutated"

    async def mut_amt():
        (await db.get(JournalLine, debit_id)).amount = Decimal("101.00")

    async def del_line():
        await db.delete(await db.get(JournalLine, debit_id))

    async def add_line():
        db.add_all(
            [
                JournalLine(
                    journal_entry_id=entry_id,
                    account_id=extra_cid,
                    direction=Direction.DEBIT,
                    amount=Decimal("1"),
                    currency="SGD",
                ),
                JournalLine(
                    journal_entry_id=entry_id,
                    account_id=extra_iid,
                    direction=Direction.CREDIT,
                    amount=Decimal("1"),
                    currency="SGD",
                ),
            ]
        )

    async def mut_rec():
        r = await db.get(JournalEntry, rec_id)
        r.status, r.source_type = JournalEntryStatus.RECONCILED, JournalEntrySourceType.AUTO_PARSED

    for action in (mut_memo, mut_amt, del_line, add_line, mut_rec):
        await _reject_commit(db, action)

    draft_acc = await make_account(db, uid, "draft cash", AccountType.ASSET, is_active=True)
    draft = await make_entry(
        db, uid, [(draft_acc.id, Direction.DEBIT, "1.00")], status=JournalEntryStatus.DRAFT, commit=True
    )
    await db.refresh(draft, ["lines"])
    draft.memo, draft.lines[0].amount = "edited draft", Decimal("2.00")
    await db.commit()
    await db.delete(draft.lines[0])
    await db.delete(draft)
    await db.commit()


async def test_void_transition_and_base_currency_immutability(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    entry, _ = await _valid_posted_entry(db, uid, memo="original")
    rev, _ = await _valid_posted_entry(db, uid, memo="reversal")
    rec, _ = await _valid_posted_entry(db, uid, memo="rec orig")
    rec_rev, _ = await _valid_posted_entry(db, uid, memo="rec rev")
    posted, _ = await _valid_posted_entry(db, uid, memo="base guard")
    entry_id, rev_id, rec_id, rec_rev_id, posted_id = entry.id, rev.id, rec.id, rec_rev.id, posted.id

    async def _set_entry(eid, **attrs):
        row = await db.get(JournalEntry, eid)
        for k, v in attrs.items():
            setattr(row, k, v)

    await _reject_commit(db, lambda: _set_entry(entry_id, status=JournalEntryStatus.VOID, void_reason="missing"))
    await _set_entry(entry_id, status=JournalEntryStatus.VOID, void_reason="valid", void_reversal_entry_id=rev_id)
    await db.commit()
    await _reject_commit(db, lambda: _set_entry(entry_id, void_reversal_entry_id=None))
    await _reject_commit(
        db, lambda: db.delete(db.get_one(JournalEntry, entry_id)) if False else _delete_entry(db, entry_id)
    )

    await _set_entry(rec_id, status=JournalEntryStatus.RECONCILED)
    await db.commit()
    await _reject_commit(
        db,
        lambda: _set_entry(
            rec_id, status=JournalEntryStatus.VOID, memo="mutated", void_reason="x", void_reversal_entry_id=rev_id
        ),
    )
    await _reject_commit(db, lambda: _set_entry(rec_id, status=JournalEntryStatus.VOID, void_reason="missing"))
    await _set_entry(rec_id, status=JournalEntryStatus.VOID, void_reason="valid rec", void_reversal_entry_id=rec_rev_id)
    await db.commit()
    assert (await db.get(JournalEntry, rec_id)).status == JournalEntryStatus.VOID

    await _reject_commit(db, lambda: _set_entry(posted_id, status=JournalEntryStatus.RECONCILED, base_currency="USD"))
    await _reject_commit(
        db,
        lambda: _set_entry(
            posted_id,
            status=JournalEntryStatus.VOID,
            void_reason="v",
            void_reversal_entry_id=rec_rev_id,
            base_currency="USD",
        ),
    )


async def _delete_entry(db: AsyncSession, entry_id) -> None:
    await db.delete(await db.get(JournalEntry, entry_id))


async def test_reconcile_posted_usd_entry_and_enum_deserialization(db: AsyncSession, test_user) -> None:
    test_user.base_currency = "USD"
    await db.flush()
    cash = await make_account(db, test_user.id, "USD Cash", AccountType.ASSET, "USD", is_active=True)
    rev = await make_account(db, test_user.id, "USD Rev", AccountType.INCOME, "USD", is_active=True)
    entry = await make_entry(
        db,
        test_user.id,
        [(cash.id, Direction.DEBIT, "250.00", "USD"), (rev.id, Direction.CREDIT, "250.00", "USD")],
        memo="USD inv",
        base_currency="USD",
        commit=True,
    )
    entry.status = JournalEntryStatus.RECONCILED
    await db.commit()
    await db.refresh(entry)
    assert entry.status == JournalEntryStatus.RECONCILED

    for enum_cls, raw, member in (
        (JournalEntryStatus, "POSTED", JournalEntryStatus.POSTED),
        (JournalEntryStatus, "posted", JournalEntryStatus.POSTED),
        (ChatSessionStatus, "ACTIVE", ChatSessionStatus.ACTIVE),
        (ChatSessionStatus, "active", ChatSessionStatus.ACTIVE),
        (ChatMessageRole, "USER", ChatMessageRole.USER),
        (ChatMessageRole, "user", ChatMessageRole.USER),
    ):
        assert enum_cls(raw) == member and enum_cls._missing_("UNKNOWN_INVALID") is None
