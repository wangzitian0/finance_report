"""Reconciliation rounding adjustment domain workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import (
    Account,
    AccountType,
    JournalEntry,
    account_service,
    calculate_reconciliation_adjustment,
    submit_system_journal_entry,
)
from src.reconciliation.base.errors import AdjustmentValidationError


@dataclass(frozen=True, slots=True)
class ReconciliationAdjustmentResult:
    """Outcome of applying a penny-rounding reconciliation adjustment."""

    account_id: UUID
    bank_balance: Decimal
    book_balance: Decimal
    difference: Decimal
    is_gain: bool
    journal_entry_id: UUID | None
    entry: JournalEntry | None


async def apply_reconciliation_adjustment(
    db: AsyncSession,
    *,
    account: Account,
    base_currency: str,
    bank_balance: Decimal,
    book_balance: Decimal,
    threshold: Decimal,
    fx_rate: Decimal | None = None,
    entry_date: date | None = None,
) -> ReconciliationAdjustmentResult:
    """Validate threshold/FX, ensure BankRoundingDifference account, and post entry."""
    user_id = account.user_id
    diff = abs(bank_balance - book_balance)
    if diff > threshold:
        raise AdjustmentValidationError(f"difference {diff} exceeds immaterial threshold {threshold}")

    adj = calculate_reconciliation_adjustment(
        bank_balance=bank_balance,
        book_balance=book_balance,
        threshold=threshold,
    )
    if adj.difference == Decimal("0"):
        return ReconciliationAdjustmentResult(
            account_id=account.id,
            bank_balance=adj.bank_balance,
            book_balance=adj.book_balance,
            difference=adj.difference,
            is_gain=adj.is_gain,
            journal_entry_id=None,
            entry=None,
        )

    preferred_type = AccountType.INCOME if adj.is_gain else AccountType.EXPENSE

    async def _find_rounding_account(session: AsyncSession) -> Account | None:
        base_where = (
            Account.user_id == user_id,
            Account.name == "BankRoundingDifference",
            Account.currency == account.currency,
        )
        for type_clause in (
            Account.type == preferred_type,
            Account.type.in_([AccountType.INCOME, AccountType.EXPENSE]),
        ):
            found = (
                (
                    await session.execute(
                        select(Account)
                        .where(*base_where, type_clause)
                        .order_by(Account.created_at, Account.id)
                        .limit(1)
                    )
                )
                .scalars()
                .first()
            )
            if found is not None:
                return found
        return None

    rounding_account = await account_service.find_or_create_account(
        db,
        user_id=user_id,
        find=_find_rounding_account,
        build=lambda: Account(
            user_id=user_id,
            name="BankRoundingDifference",
            type=preferred_type,
            currency=account.currency,
            is_active=True,
        ),
    )

    if account.currency != base_currency and fx_rate is None:
        raise AdjustmentValidationError(
            f"fx_rate is required for non-base currency account {account.currency} (base currency {base_currency})"
        )

    lines_data = [
        {
            "account_id": account.id if sl.role == "bank_adjustment" else rounding_account.id,
            "direction": sl.direction,
            "amount": sl.amount,
            "currency": account.currency,
            "fx_rate": fx_rate if account.currency != base_currency else None,
        }
        for sl in adj.lines
    ]
    entry = await submit_system_journal_entry(
        db,
        user_id=user_id,
        entry_date=entry_date or date.today(),
        memo=f"Reconciliation rounding adjustment for {account.name}",
        lines_data=lines_data,
        base_currency=base_currency,
        operation="reconciliation_adjustment",
        source_id=uuid4(),
        post_immediately=True,
    )
    await db.refresh(entry, ["lines"])
    return ReconciliationAdjustmentResult(
        account_id=account.id,
        bank_balance=adj.bank_balance,
        book_balance=adj.book_balance,
        difference=adj.difference,
        is_gain=adj.is_gain,
        journal_entry_id=entry.id,
        entry=entry,
    )
