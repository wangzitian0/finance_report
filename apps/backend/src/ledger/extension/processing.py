"""Persistence, transfer-leg posting, pairing, and balance projections for the Processing account."""

from __future__ import annotations

from collections.abc import Callable, Collection
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.audit import JournalEntrySourceType
from src.audit.money import Currency, Money
from src.ledger.base.memo import fit_journal_memo
from src.ledger.base.processing import (
    AUTO_PAIR_THRESHOLD,
    MAX_DATE_DIFF_DAYS,
    PROCESSING_ACCOUNT_CODE,
    PROCESSING_ACCOUNT_DESCRIPTION,
    PROCESSING_ACCOUNT_NAME,
    PROCESSING_ACCOUNT_TYPE,
    ProcessingCurrencyConflictError,
    TransferAccountCurrencyMismatchError,
    TransferPair,
    _calculate_pair_confidence,
    _validate_transfer_params,
)
from src.ledger.base.types.entry import Entry
from src.ledger.base.validators import ValidationError
from src.ledger.extension import account_service
from src.ledger.extension.post import post_entry
from src.ledger.orm.account import Account
from src.ledger.orm.journal import Direction, JournalEntry, JournalLine, active_journal_entry_filter
from src.observability import get_logger

logger = get_logger(__name__)


async def get_or_create_processing_account(
    db: AsyncSession,
    user_id: UUID,
    *,
    currency: str,
) -> Account:
    """Get or create the per-user Processing virtual account."""
    return await account_service.find_or_create_account(
        db,
        user_id=user_id,
        find=lambda session: find_processing_account(session, user_id),
        build=lambda: Account(
            user_id=user_id,
            name=PROCESSING_ACCOUNT_NAME,
            code=PROCESSING_ACCOUNT_CODE,
            type=PROCESSING_ACCOUNT_TYPE,
            currency=currency,
            is_system=True,
            description=PROCESSING_ACCOUNT_DESCRIPTION,
        ),
    )


async def find_processing_account(db: AsyncSession, user_id: UUID) -> Account | None:
    """Look up the Processing account of a user without creating one."""
    accounts = list(
        (
            await db.execute(
                select(Account)
                .where(Account.user_id == user_id, Account.is_system == True, Account.code == PROCESSING_ACCOUNT_CODE)  # noqa: E712
                .order_by(Account.created_at, Account.id)
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    if len(accounts) > 1:
        logger.error(
            "A user holds more than one Processing account; the oldest is used",
            user_id=str(user_id),
            account_ids=[str(a.id) for a in accounts],
        )
    return accounts[0] if accounts else None


async def find_transfer_pairs(
    db: AsyncSession,
    user_id: UUID,
    *,
    currency: str,
    description_scorer: Callable[[str | None, str | None], float],
    threshold: int = AUTO_PAIR_THRESHOLD,
    max_entries: int = 500,
    exclude_entry_ids: Collection[UUID] | None = None,
) -> list[TransferPair[JournalEntry]]:
    """Find matching transfer pairs with confidence >= threshold."""
    _ = currency
    processing = await find_processing_account(db, user_id)
    if processing is None:
        return []

    stmt = (
        select(JournalEntry)
        .options(selectinload(JournalEntry.lines))
        .join(JournalLine, JournalEntry.id == JournalLine.journal_entry_id)
        .where(
            JournalEntry.user_id == user_id,
            active_journal_entry_filter(JournalEntry),
            JournalEntry.source_type == JournalEntrySourceType.SYSTEM,
            JournalLine.account_id == processing.id,
        )
    )
    if exclude_entry_ids:
        stmt = stmt.where(JournalEntry.id.notin_(exclude_entry_ids))
    entries = (
        (
            await db.execute(
                stmt.order_by(
                    JournalEntry.entry_date.desc(), JournalEntry.created_at.desc(), JournalEntry.id.desc()
                ).limit(max_entries * 2)
            )
        )
        .scalars()
        .unique()
        .all()
    )

    out_entries: list[JournalEntry] = []
    in_entries: list[JournalEntry] = []
    for entry in entries:
        line = next((ln for ln in entry.lines if ln.account_id == processing.id), None)
        if line is not None:
            (out_entries if line.direction == Direction.DEBIT else in_entries).append(entry)

    pairs: list[TransferPair[JournalEntry]] = []
    matched_in: set[int] = set()
    for out_entry in out_entries[:max_entries]:
        best: TransferPair[JournalEntry] | None = None
        for in_entry in in_entries[:max_entries]:
            if id(in_entry) in matched_in:
                continue
            conf, breakdown = _calculate_pair_confidence(
                out_entry, in_entry, processing.id, description_scorer=description_scorer
            )
            if conf >= threshold and (best is None or conf > best.confidence):
                best = TransferPair(out_entry=out_entry, in_entry=in_entry, confidence=conf, score_breakdown=breakdown)
        if best is not None:
            pairs.append(best)
            matched_in.add(id(best.in_entry))
    return pairs


async def create_transfer_out_entry(
    db: AsyncSession,
    user_id: UUID,
    source_account_id: UUID,
    amount: Decimal,
    txn_date: date,
    description: str,
    *,
    currency: str,
    source_id: UUID | None = None,
) -> JournalEntry:
    """Create a Transfer OUT journal entry in the user's effective base currency."""
    return await _create_transfer_entry(
        db,
        user_id=user_id,
        account_id=source_account_id,
        amount=amount,
        txn_date=txn_date,
        description=description,
        currency=currency,
        direction="OUT",
        source_id=source_id,
    )


async def create_transfer_in_entry(
    db: AsyncSession,
    user_id: UUID,
    dest_account_id: UUID,
    amount: Decimal,
    txn_date: date,
    description: str,
    *,
    currency: str,
    source_id: UUID | None = None,
) -> JournalEntry:
    """Create a Transfer IN journal entry in the user's effective base currency."""
    return await _create_transfer_entry(
        db,
        user_id=user_id,
        account_id=dest_account_id,
        amount=amount,
        txn_date=txn_date,
        description=description,
        currency=currency,
        direction="IN",
        source_id=source_id,
    )


async def _create_transfer_entry(
    db: AsyncSession,
    *,
    user_id: UUID,
    account_id: UUID,
    amount: Decimal,
    txn_date: date,
    description: str,
    currency: str,
    direction: str,
    source_id: UUID | None = None,
) -> JournalEntry:
    _validate_transfer_params(amount, description)
    normalized_ccy = Currency.of(currency).code
    processing = await get_or_create_processing_account(db, user_id, currency=normalized_ccy)
    proc_ccy = Currency.of(processing.currency).code
    if proc_ccy != normalized_ccy:
        raise ProcessingCurrencyConflictError(
            f"Processing account currency is {proc_ccy}; got transfer currency {normalized_ccy}"
        )

    counterparty = (
        await db.execute(select(Account).where(Account.id == account_id, Account.user_id == user_id))
    ).scalar_one_or_none()
    if counterparty is None:
        raise ValidationError(f"Account {account_id} not found")
    cp_ccy = Currency.of(counterparty.currency).code
    if cp_ccy != proc_ccy:
        raise TransferAccountCurrencyMismatchError(
            f"Transfer account currency is {cp_ccy}; Processing account currency is {proc_ccy}"
        )

    debit_id, credit_id = (processing.id, account_id) if direction == "OUT" else (account_id, processing.id)
    return await post_entry(
        db,
        user_id=user_id,
        entry_date=txn_date,
        memo=fit_journal_memo(f"Transfer {direction}: {description}"),
        entry=Entry.transfer(debit=debit_id, credit=credit_id, money=Money(amount, Currency.of(proc_ccy))),
        base_currency=proc_ccy,
        source_id=source_id,
        operation=f"processing-transfer-{direction.lower()}",
    )


async def get_processing_balance(db: AsyncSession, user_id: UUID, *, currency: str) -> Decimal:
    _ = currency
    processing = await find_processing_account(db, user_id)
    if processing is None:
        return Decimal("0")
    lines = (
        (
            await db.execute(
                select(JournalLine)
                .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
                .where(
                    JournalLine.account_id == processing.id,
                    JournalEntry.user_id == user_id,
                    active_journal_entry_filter(JournalEntry),
                )
            )
        )
        .scalars()
        .all()
    )
    monies = [ln.money if ln.direction == Direction.DEBIT else -ln.money for ln in lines]
    return Money.sum(monies).amount if monies else Decimal("0")


async def get_unpaired_transfers(
    db: AsyncSession,
    user_id: UUID,
    *,
    currency: str,
    days_threshold: int = MAX_DATE_DIFF_DAYS,
) -> list[dict]:
    _ = currency, days_threshold
    processing = await find_processing_account(db, user_id)
    if processing is None:
        return []
    rows = (
        await db.execute(
            select(JournalLine, JournalEntry)
            .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
            .where(
                JournalLine.account_id == processing.id,
                JournalEntry.user_id == user_id,
                active_journal_entry_filter(JournalEntry),
                JournalEntry.source_type == JournalEntrySourceType.SYSTEM,
            )
            .order_by(JournalEntry.entry_date.desc())
        )
    ).all()
    return [
        {
            "entry_id": entry.id,
            "direction": "OUT" if line.direction == Direction.DEBIT else "IN",
            "amount": line.amount,
            "date": entry.entry_date,
            "description": entry.memo or "",
        }
        for line, entry in rows
    ]


async def list_processing_transfer_legs(db: AsyncSession, user_id: UUID, *, currency: str) -> list[dict]:
    _ = currency
    processing = await find_processing_account(db, user_id)
    if processing is None:
        return []
    entries = (
        (
            await db.execute(
                select(JournalEntry)
                .join(JournalLine, JournalLine.journal_entry_id == JournalEntry.id)
                .where(
                    JournalLine.account_id == processing.id,
                    JournalEntry.user_id == user_id,
                    active_journal_entry_filter(JournalEntry),
                    JournalEntry.source_type == JournalEntrySourceType.SYSTEM,
                )
                .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
                .order_by(JournalEntry.entry_date.desc())
            )
        )
        .scalars()
        .unique()
        .all()
    )

    today = date.today()
    proc_ccy = Currency.of(processing.currency).code
    legs: list[dict] = []
    for entry in entries:
        proc_line = next((ln for ln in entry.lines if ln.account_id == processing.id), None)
        if proc_line is None:
            continue
        line_ccy = Currency.of(proc_line.currency).code
        if line_ccy != proc_ccy:
            raise ValidationError(f"Processing line currency is {line_ccy}; account currency is {proc_ccy}")
        other = next((ln for ln in entry.lines if ln.account_id != processing.id), None)
        other_name = other.account.name if other and other.account else "(unknown)"
        from_acct, to_acct = (
            (other_name, "(unmatched destination)")
            if proc_line.direction == Direction.DEBIT
            else ("(unmatched source)", other_name)
        )
        legs.append(
            {
                "entry_id": entry.id,
                "from_account": from_acct,
                "to_account": to_acct,
                "amount": proc_line.amount,
                "currency": proc_ccy,
                "initiated_date": entry.entry_date,
                "days_outstanding": (today - entry.entry_date).days,
                "description": entry.memo or "",
            }
        )
    return legs
