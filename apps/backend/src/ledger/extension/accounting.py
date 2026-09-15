"""Account starting positions: one immutable stock, independent of approval path."""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.audit import TraceEmitter, TraceScope, current_authoritative_trace_decision_projection
from src.audit.money import to_money
from src.audit.money.currency import normalize_currency_code
from src.ledger.base.validators import ValidationError
from src.ledger.extension.anchored_posting import submit_system_journal_entry
from src.ledger.extension.opening_positions import list_opening_positions, record_opening_position
from src.ledger.orm.account import Account, AccountType
from src.ledger.orm.journal import Direction, JournalEntry, JournalEntryStatus, JournalLine

__all__ = ["get_opening_balance_readiness", "post_opening_balance_entry"]


async def post_opening_balance_entry(
    db: AsyncSession,
    user_id: UUID,
    *,
    entry_date: date,
    balances: dict[UUID, Decimal],
    currency: str | None = None,
    base_currency: str | None = None,
    memo: str = "Opening balances",
    fx_rates: dict[str, Decimal] | None = None,
    source_decision_id: UUID | None = None,
    trace_emitter: TraceEmitter | None = None,
) -> JournalEntry | None:
    """Initialize signed account stock; repeated identical requests are idempotent.

    Zero is recorded as evidence without inventing a monetary journal. FX rates
    are explicit historical inputs supplied by the composition boundary.
    """
    from src.ledger.extension.account_service import get_or_create_opening_balance_equity_account

    if not balances:
        raise ValidationError("At least one opening balance is required")
    # Serializes first initialization and the per-user equity-account creation
    # across independent sessions, not merely tasks sharing one identity map.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"ledger-opening:{user_id}"}
    )
    normalized_base = normalize_currency_code(base_currency or src.config.settings.base_currency)
    expected_currency = normalize_currency_code(currency) if currency else None
    accounts = {
        a.id: a
        for a in (
            await db.execute(
                select(Account)
                .where(Account.id.in_(balances), Account.user_id == user_id)
                .order_by(Account.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    }
    if len(accounts) != len(balances):
        raise ValidationError("Unknown or non-owned account(s)")
    if any(a.is_system for a in accounts.values()):
        raise ValidationError("Opening balances cannot target system accounts")
    if any(not a.is_active for a in accounts.values()):
        raise ValidationError("Opening balances require active accounts")
    if source_decision_id is not None:
        if trace_emitter is None:
            raise ValidationError("Source-backed opening requires a composed trace emitter")
        projection = current_authoritative_trace_decision_projection(TraceScope.tenant(user_id)).subquery()
        if (
            await db.scalar(select(projection.c.decision_id).where(projection.c.decision_id == source_decision_id))
            is None
        ):
            raise ValidationError("Opening source decision is not currently authoritative")
    positions = {p.account_id: p for p in await list_opening_positions(db, user_id=user_id, as_of=date.max)}
    new = {}
    existing_entries = set()
    rates = {}
    for aid, raw in balances.items():
        if not isinstance(raw, Decimal):
            raise ValidationError("Opening balance amounts must be Decimal")
        amount = to_money(raw)
        account = accounts[aid]
        code = normalize_currency_code(account.currency)
        if expected_currency and code != expected_currency:
            raise ValidationError("Opening balance currency does not match the currency of account")
        previous = positions.get(aid)
        if previous:
            if previous.state != "authoritative":
                raise ValidationError("Existing opening evidence needs review before replacement")
            if (previous.effective_date, previous.amount, previous.currency) != (entry_date, amount, code):
                raise ValidationError("Account already has a different opening position; use the correction lifecycle")
            if previous.journal_entry_id:
                existing_entries.add(previous.journal_entry_id)
            continue
        rate = (fx_rates or {}).get(code)
        if code != normalized_base and amount != 0:
            if not isinstance(rate, Decimal) or not rate.is_finite() or rate <= 0:
                raise ValidationError(f"FX rate required for opening balance in {code}")
            rate = rate.quantize(Decimal("0.000001"))
            if rate <= 0:
                raise ValidationError("FX rate is below supported precision")
        else:
            rate = None
        rates[aid] = rate
        new[aid] = amount
    if not new:
        return await db.get(JournalEntry, next(iter(existing_entries))) if existing_entries else None
    # Opening stock must precede activity. Same-date activity is allowed: the
    # opening evidence distinguishes the start of that day from its flows.
    prior = await db.scalar(
        select(JournalLine.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
        .where(
            JournalLine.account_id.in_(new),
            JournalEntry.user_id == user_id,
            JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]),
            JournalEntry.entry_date < entry_date,
        )
        .limit(1)
    )
    if prior is not None:
        raise ValidationError("Opening balances must precede all activity for the affected accounts")
    lines = []
    net = Decimal("0")
    for aid, amount in new.items():
        if amount == 0:
            continue
        account = accounts[aid]
        debit_normal = account.type in (AccountType.ASSET, AccountType.EXPENSE)
        debit = debit_normal if amount > 0 else not debit_normal
        direction = Direction.DEBIT if debit else Direction.CREDIT
        rate = rates[aid]
        lines.append(
            {
                "account_id": aid,
                "direction": direction,
                "amount": abs(amount),
                "currency": account.currency,
                "fx_rate": rate,
            }
        )
        converted = abs(amount) * (rate or Decimal("1"))
        net += converted if debit else -converted
    entry = None
    if lines:
        net = to_money(net)
        if net != 0:
            equity = await get_or_create_opening_balance_equity_account(db, user_id, normalized_base)
            lines.append(
                {
                    "account_id": equity.id,
                    "direction": Direction.CREDIT if net > 0 else Direction.DEBIT,
                    "amount": abs(net),
                    "currency": normalized_base,
                }
            )
        entry = await submit_system_journal_entry(
            db,
            user_id=user_id,
            entry_date=entry_date,
            memo=memo,
            lines_data=lines,
            base_currency=normalized_base,
            operation="opening-balance",
        )
        await db.refresh(entry, ["lines"])
    for aid, amount in new.items():
        await record_opening_position(
            db,
            user_id=user_id,
            account_id=aid,
            effective_date=entry_date,
            amount=amount,
            currency=accounts[aid].currency,
            fx_rate=rates[aid],
            journal_entry_id=entry.id if entry is not None and amount != 0 else None,
            source_decision_id=source_decision_id,
            trace_emitter=trace_emitter,
        )
    return entry


async def get_opening_balance_readiness(db: AsyncSession, user_id: UUID) -> dict:
    """An initialized account never masks another account's missing starting stock."""
    positions = await list_opening_positions(db, user_id=user_id, as_of=date.max)
    initialized = {p.account_id: p for p in positions if p.state == "authoritative"}
    opening_ids = {p.journal_entry_id for p in positions if p.journal_entry_id}
    rows = (
        await db.execute(
            select(Account.id, func.min(JournalEntry.entry_date))
            .join(JournalLine, JournalLine.account_id == Account.id)
            .join(JournalEntry, JournalEntry.id == JournalLine.journal_entry_id)
            .where(
                Account.user_id == user_id,
                JournalEntry.user_id == user_id,
                Account.is_system.is_(False),
                Account.type.in_([AccountType.ASSET, AccountType.LIABILITY]),
                JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED]),
                JournalEntry.id.notin_(opening_ids),
            )
            .group_by(Account.id)
        )
    ).all()
    needs = any(aid not in initialized or initialized[aid].effective_date > first_date for aid, first_date in rows)
    needs = needs or any(p.state != "authoritative" for p in positions)
    return {
        "needs_opening_balance": needs,
        "has_activity": bool(rows),
        "has_opening_entry": bool(initialized),
        "earliest_activity_date": min((row[1] for row in rows), default=None),
    }
