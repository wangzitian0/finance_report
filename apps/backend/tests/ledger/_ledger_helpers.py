from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.config import settings
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.ledger.extension.anchored_posting import submit_manual_journal_entry, submit_system_journal_entry


async def create_anchored_test_journal_entry(
    db: AsyncSession,
    user_id: UUID,
    entry_date: date,
    memo: str,
    lines_data: list[dict],
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    source_id: UUID | None = None,
    *,
    base_currency: str | None = None,
) -> JournalEntry:
    effective_base = base_currency or settings.base_currency
    if source_type == JournalEntrySourceType.MANUAL:
        return await submit_manual_journal_entry(
            db,
            user_id=user_id,
            entry_date=entry_date,
            memo=memo,
            rationale="Test manual entry",
            lines_data=lines_data,
            base_currency=effective_base,
        )
    return await submit_system_journal_entry(
        db,
        user_id=user_id,
        entry_date=entry_date,
        memo=memo,
        lines_data=lines_data,
        base_currency=effective_base,
        operation=f"test-{uuid4().hex[:8]}",
        source_id=source_id,
        source_type=source_type,
        post_immediately=False,
    )


async def make_account(
    db: AsyncSession,
    user_id: UUID,
    name: str = "Cash",
    account_type: AccountType = AccountType.ASSET,
    currency: str = "SGD",
    *,
    commit: bool = False,
    **kwargs,
) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency=currency, **kwargs)
    db.add(account)
    await (db.commit() if commit else db.flush())
    if commit:
        await db.refresh(account)
    return account


async def make_entry(
    db: AsyncSession,
    user_id: UUID,
    lines_spec: list[tuple],
    *,
    entry_date: date | None = None,
    memo: str = "Test entry",
    status: JournalEntryStatus = JournalEntryStatus.POSTED,
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    source_id: UUID | None = None,
    commit: bool = False,
    **kwargs,
) -> JournalEntry:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=entry_date or date.today(),
        memo=memo,
        source_type=source_type,
        source_id=source_id,
        status=status,
        **kwargs,
    )
    db.add(entry)
    await db.flush()
    for spec in lines_spec:
        acc_id, direction, amount = spec[:3]
        currency = spec[3] if len(spec) > 3 else "SGD"
        fx_rate = spec[4] if len(spec) > 4 else None
        db.add(
            JournalLine(
                journal_entry_id=entry.id,
                account_id=acc_id,
                direction=direction,
                amount=Decimal(str(amount)),
                currency=currency,
                fx_rate=fx_rate,
            )
        )
    await (db.commit() if commit else db.flush())
    if commit:
        await db.refresh(entry)
    return entry


def make_line(
    direction: Direction = Direction.DEBIT,
    amount: str | Decimal = "100.00",
    currency: str | None = "SGD",
    fx_rate: Decimal | None = None,
) -> JournalLine:
    return JournalLine(
        id=uuid4(),
        journal_entry_id=uuid4(),
        account_id=uuid4(),
        direction=direction,
        amount=Decimal(str(amount)),
        currency=currency,
        fx_rate=fx_rate,
    )


def lines_pair(debit_id: UUID, credit_id: UUID, amount: str | Decimal = "100.00", currency: str = "SGD") -> list[dict]:
    amt = Decimal(str(amount))
    return [
        {"account_id": debit_id, "direction": Direction.DEBIT, "amount": amt, "currency": currency},
        {"account_id": credit_id, "direction": Direction.CREDIT, "amount": amt, "currency": currency},
    ]


async def create_valid_posted_entry(
    db: AsyncSession,
    user_id: UUID,
    *,
    entry_date: date | None = None,
    memo: str = "Posted entry",
    amount: Decimal = Decimal("100.00"),
    source_type: JournalEntrySourceType = JournalEntrySourceType.MANUAL,
    source_id: UUID | None = None,
    debit_account_type: AccountType = AccountType.ASSET,
    credit_account_type: AccountType = AccountType.INCOME,
) -> JournalEntry:
    debit_acc = await make_account(db, user_id, f"{memo} cash", debit_account_type)
    credit_acc = await make_account(db, user_id, f"{memo} income", credit_account_type)
    return await make_entry(
        db,
        user_id,
        [(debit_acc.id, Direction.DEBIT, amount), (credit_acc.id, Direction.CREDIT, amount)],
        entry_date=entry_date,
        memo=memo,
        source_type=source_type,
        source_id=source_id,
        commit=True,
    )


async def create_valid_void_entry(
    db: AsyncSession,
    user_id: UUID,
    *,
    entry_date: date | None = None,
    memo: str = "Voided entry",
) -> JournalEntry:
    entry = await create_valid_posted_entry(db, user_id, entry_date=entry_date, memo=memo)
    entry_id = entry.id
    reversal = await create_valid_posted_entry(db, user_id, entry_date=entry_date, memo=f"{memo} reversal")
    entry = await db.get(JournalEntry, entry_id)
    assert entry is not None
    entry.status = JournalEntryStatus.VOID
    entry.void_reason = "test void"
    entry.void_reversal_entry_id = reversal.id
    await db.commit()
    await db.refresh(entry)
    return entry
