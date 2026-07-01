"""Opening-balance domain services (#949).

The double-entry core — the journal write pipeline, the posting validators, and the
account-balance projection — now lives in the ``ledger`` package
(``common/ledger`` / ``apps/backend/src/ledger``). This module keeps only the
opening-balance domain services, which orchestrate the guided year-start flow on
top of the published ledger interface.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.ledger import ValidationError, create_journal_entry, post_journal_entry
from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine

__all__ = [
    "get_opening_balance_readiness",
    "post_opening_balance_entry",
]


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
    from src.audit.money import Money, to_money
    from src.audit.money.currency import normalize_currency_code
    from src.ledger import Entry, Leg
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
    """Detect whether a user's balance sheet may be silently incomplete (#949 / AC-ledger.16.1).

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
