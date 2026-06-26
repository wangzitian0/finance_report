"""Accounting service - Core double-entry bookkeeping logic."""

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings

# The journal write pipeline (create/post/void + validators) and its error types
# now live in the ledger store; re-exported here so existing callers and
# `except ValidationError` sites are unchanged. This removes the
# `ledger.ops → services.accounting → ledger` import cycle.
from src.ledger.store.posting import (  # noqa: E402
    AccountingError,
    ValidationError,
    create_journal_entry,
    post_journal_entry,
    validate_fx_rates,
    validate_journal_balance,
    validate_journal_posting_invariants,
    validate_line_account_ownership,
    void_journal_entry,
)
from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine

__all__ = [
    "AccountingError",
    "ValidationError",
    "calculate_account_balance",
    "calculate_account_balances",
    "create_journal_entry",
    "get_opening_balance_readiness",
    "post_journal_entry",
    "post_opening_balance_entry",
    "validate_fx_rates",
    "validate_journal_balance",
    "validate_journal_posting_invariants",
    "validate_line_account_ownership",
    "verify_accounting_equation",
    "void_journal_entry",
]


async def calculate_account_balance(db: AsyncSession, account_id: UUID, user_id: UUID) -> Decimal:
    """
    Calculate the current balance of an account.

    Only includes posted and reconciled journal entries.
    Balance calculation follows account type rules:
    - Asset/Expense: debit increases, credit decreases
    - Liability/Equity/Income: credit increases, debit decreases

    Args:
        db: Database session
        account_id: Account UUID
        user_id: User UUID for security check

    Returns:
        Current account balance
    """
    # Get account
    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise ValidationError(f"Account {account_id} not found")
    if account.user_id != user_id:
        raise ValidationError("Account does not belong to user")

    # Sum journal lines for posted/reconciled entries
    # Use separate queries for debit and credit sums
    debit_query = (
        select(func.coalesce(func.sum(JournalLine.amount), Decimal("0")))
        .select_from(JournalLine)
        .join(JournalEntry)
        .where(JournalLine.account_id == account_id)
        .where(JournalLine.direction == Direction.DEBIT)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )

    credit_query = (
        select(func.coalesce(func.sum(JournalLine.amount), Decimal("0")))
        .select_from(JournalLine)
        .join(JournalEntry)
        .where(JournalLine.account_id == account_id)
        .where(JournalLine.direction == Direction.CREDIT)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
    )

    debit_result = await db.execute(debit_query)
    credit_result = await db.execute(credit_query)

    total_debit = debit_result.scalar() or Decimal("0")
    total_credit = credit_result.scalar() or Decimal("0")

    # Net balance = debit - credit
    net_balance = total_debit - total_credit

    # Adjust based on account type
    # Asset/Expense: DEBIT increases (positive), CREDIT decreases (negative)
    # Liability/Equity/Income: CREDIT increases (positive), DEBIT decreases (negative)
    if account.type in (AccountType.ASSET, AccountType.EXPENSE):
        return net_balance
    else:
        return -net_balance


async def calculate_account_balances(
    db: AsyncSession,
    accounts: list[Account],
    user_id: UUID,
    *,
    use_base_currency: bool = False,
) -> dict[UUID, Decimal]:
    """
    Calculate balances for multiple accounts in a single query.

    Returns a mapping of account_id -> balance, with account type adjustments applied.
    """
    if not accounts:
        return {}

    account_ids = [account.id for account in accounts]
    if use_base_currency:
        base_currency = settings.base_currency.upper()
        amount_expr: Any = case(
            (func.coalesce(func.upper(JournalLine.currency), base_currency) == base_currency, JournalLine.amount),
            else_=JournalLine.amount * func.coalesce(JournalLine.fx_rate, Decimal("1")),
        )
    else:
        amount_expr = JournalLine.amount

    net_query = (
        select(
            JournalLine.account_id,
            func.coalesce(
                func.sum(
                    case(
                        (JournalLine.direction == Direction.DEBIT, amount_expr),
                        else_=-amount_expr,
                    )
                ),
                Decimal("0"),
            ).label("net_balance"),
        )
        .select_from(JournalLine)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .where(Account.user_id == user_id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalLine.account_id.in_(account_ids))
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .group_by(JournalLine.account_id)
    )
    result = await db.execute(net_query)
    net_by_account = {row.account_id: row.net_balance for row in result.all()}

    balances: dict[UUID, Decimal] = {}
    for account in accounts:
        net = net_by_account.get(account.id, Decimal("0"))
        if account.type in (AccountType.ASSET, AccountType.EXPENSE):
            balances[account.id] = net
        else:
            balances[account.id] = -net

    return balances


async def verify_accounting_equation(db: AsyncSession, user_id: UUID) -> bool:
    """
    Verify that the accounting equation holds for a user.

    Assets = Liabilities + Equity + (Income - Expenses)

    Args:
        db: Database session
        user_id: User UUID

    Returns:
        True if equation holds (within tolerance)
    """
    # Get all accounts for user
    result = await db.execute(select(Account).where(Account.user_id == user_id))
    accounts = list(result.scalars().all())

    balances = await calculate_account_balances(db, accounts, user_id, use_base_currency=True)

    totals = {
        AccountType.ASSET: Decimal("0"),
        AccountType.LIABILITY: Decimal("0"),
        AccountType.EQUITY: Decimal("0"),
        AccountType.INCOME: Decimal("0"),
        AccountType.EXPENSE: Decimal("0"),
    }

    for account in accounts:
        totals[account.type] += balances.get(account.id, Decimal("0"))

    left_side = totals[AccountType.ASSET]
    right_side = (
        totals[AccountType.LIABILITY]
        + totals[AccountType.EQUITY]
        + totals[AccountType.INCOME]
        - totals[AccountType.EXPENSE]
    )

    # Allow small tolerance for rounding errors (must match AGENTS.md: < 0.01)
    return abs(left_side - right_side) < Decimal("0.01")


async def post_opening_balance_entry(
    db: AsyncSession,
    user_id: UUID,
    *,
    entry_date: date,
    balances: dict[UUID, Decimal],
    currency: str,
    memo: str = "Opening balances",
) -> JournalEntry:
    """Post a balanced opening-balance entry establishing year-start positions (#949).

    Each supplied account is increased to its opening balance per its normal
    side (assets/expenses debited, liabilities/equity/income credited); the net
    is offset into the system Opening Balance Equity account so the entry
    balances and the accounting equation holds. All amounts are ``Decimal``.
    """
    # Imported lazily so importing this module stays free of the FastAPI/util
    # dependency graph (tooling tests import accounting without those installed).
    from src.ledger import Entry, Leg
    from src.money import Money, to_money
    from src.money.currency import normalize_currency_code
    from src.services.account_service import get_or_create_opening_balance_equity_account

    if not balances:
        raise ValidationError("At least one opening balance is required")

    normalized_currency = normalize_currency_code(currency)
    account_ids = list(balances.keys())
    result = await db.execute(select(Account).where(Account.id.in_(account_ids), Account.user_id == user_id))
    accounts = {account.id: account for account in result.scalars().all()}
    missing = [str(account_id) for account_id in account_ids if account_id not in accounts]
    if missing:
        raise ValidationError(f"Unknown or non-owned account(s): {sorted(missing)}")

    # The posted entry is SYSTEM-typed (it offsets into the system equity account),
    # which would otherwise let a caller target any system account (e.g. Processing).
    # Opening balances may only target user-managed accounts.
    system_targets = sorted(str(account.id) for account in accounts.values() if account.is_system)
    if system_targets:
        raise ValidationError(f"Opening balances cannot target system accounts: {system_targets}")

    base_currency = normalize_currency_code(settings.base_currency)
    if normalized_currency != base_currency:
        raise ValidationError(
            f"Opening balances are supported only in the base currency ({base_currency}); got {normalized_currency}."
        )

    # An opening balance establishes a starting position, not a delta: reject when
    # any affected account already has posted/reconciled activity before entry_date,
    # otherwise the posted amount would stack on top of an existing balance.
    prior = await db.execute(
        select(JournalLine.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id.in_(account_ids))
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]))
        .where(JournalEntry.entry_date < entry_date)
        .limit(1)
    )
    if prior.first() is not None:
        raise ValidationError(
            "Opening balances must precede all activity for the affected accounts; "
            "one or more already have posted entries before the opening date."
        )

    lines_data: list[dict] = []
    total_debit = Decimal("0")
    total_credit = Decimal("0")
    for account_id, raw_amount in balances.items():
        amount = to_money(raw_amount)
        if amount <= Decimal("0"):
            raise ValidationError("Opening balance amounts must be positive")
        account = accounts[account_id]
        if normalize_currency_code(account.currency or "") != normalized_currency:
            raise ValidationError(
                f"Opening balance currency {normalized_currency} does not match the currency "
                f"of account {account_id} ({account.currency}); lines must not be mis-stamped."
            )
        if account.type in (AccountType.ASSET, AccountType.EXPENSE):
            direction = Direction.DEBIT
            total_debit += amount
        else:
            direction = Direction.CREDIT
            total_credit += amount
        lines_data.append(
            {"account_id": account_id, "direction": direction, "amount": amount, "currency": normalized_currency}
        )

    net = total_debit - total_credit
    if net != Decimal("0"):
        equity_account = await get_or_create_opening_balance_equity_account(db, user_id, normalized_currency)
        lines_data.append(
            {
                "account_id": equity_account.id,
                "direction": Direction.CREDIT if net > 0 else Direction.DEBIT,
                "amount": abs(net),
                "currency": normalized_currency,
            }
        )

    # Guarantee the double-entry balance as a TYPE before persistence: if the
    # equity-plug logic above is wrong, Entry construction raises here rather than
    # producing an unbalanced opening entry (Axiom D / double-entry integrity).
    Entry.of(
        *(Leg(line["account_id"], line["direction"], Money(line["amount"], line["currency"])) for line in lines_data)
    )

    # SYSTEM-typed: the guided flow orchestrates this entry and it offsets into
    # the system Opening Balance Equity account, which manual entries may not touch.
    entry = await create_journal_entry(
        db,
        user_id,
        entry_date=entry_date,
        memo=memo,
        lines_data=lines_data,
        source_type=JournalEntrySourceType.SYSTEM,
    )
    return await post_journal_entry(db, entry.id, user_id)


async def get_opening_balance_readiness(db: AsyncSession, user_id: UUID) -> dict:
    """Detect whether a user's balance sheet may be silently incomplete (#949 / AC2.16.1).

    The everyday-user persona who already owns assets/liabilities on day one will,
    without recording opening balances, get a balance sheet that looks right but
    omits the starting position. This returns ``needs_opening_balance=True`` when
    the user has posted activity but no opening-balance entry on or before the
    earliest such activity, so the UI can nudge them before they ship incomplete
    numbers.
    """
    posted = (JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED)

    # Opening-balance entries are exactly the journal entries with a line on the
    # user's system-managed Opening Balance Equity account (code 3199).
    opening_entry_ids = (
        select(JournalLine.journal_entry_id)
        .join(Account, Account.id == JournalLine.account_id)
        .where(
            Account.user_id == user_id,
            Account.is_system.is_(True),
            Account.code == "3199",
        )
    )

    # Earliest "real" activity = earliest posted/reconciled entry that is not an
    # opening-balance entry (statements, manual entries, FX, processing, ...).
    earliest_activity = await db.scalar(
        select(func.min(JournalEntry.entry_date)).where(
            JournalEntry.user_id == user_id,
            JournalEntry.status.in_(posted),
            JournalEntry.id.notin_(opening_entry_ids),
        )
    )
    earliest_opening = await db.scalar(
        select(func.min(JournalEntry.entry_date)).where(
            JournalEntry.user_id == user_id,
            JournalEntry.status.in_(posted),
            JournalEntry.id.in_(opening_entry_ids),
        )
    )

    has_activity = earliest_activity is not None
    has_opening_before = earliest_opening is not None and (
        earliest_activity is None or earliest_opening <= earliest_activity
    )
    return {
        "needs_opening_balance": has_activity and not has_opening_before,
        "has_activity": has_activity,
        "has_opening_entry": earliest_opening is not None,
        "earliest_activity_date": earliest_activity,
    }
