"""Account lineage report."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logger import get_logger
from src.models import (
    Account,
    JournalEntry,
    JournalLine,
)
from src.services.reporting._core import _REPORT_STATUSES, _get_fx_rates_map
from src.services.reporting_calc import (
    ReportError,
    _normalize_currency,
    _quantize_money,
    _signed_amount,
)

logger = get_logger(__name__)


async def get_account_lineage(
    db: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    *,
    as_of_date: date,
    start_date: date | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    """Return the posted/reconciled journal lines behind one account's balance.

    Mirrors the balance-sheet aggregation filters (status, as_of_date, optional
    start_date) but keeps lines disaggregated so each contributing line exposes
    a ``journal_line`` evidence anchor for drill-down. Amounts are signed using
    the same accounting rules and converted into the report currency.
    """
    account = await db.scalar(select(Account).where(Account.id == account_id).where(Account.user_id == user_id))
    if account is None:
        raise ReportError(f"Account {account_id} not found")

    target_currency = _normalize_currency(currency or account.currency)

    line_stmt = (
        select(JournalLine, JournalEntry)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(JournalLine.account_id == account_id)
        .where(JournalEntry.user_id == user_id)
        .where(JournalEntry.status.in_(_REPORT_STATUSES))
        .where(JournalEntry.entry_date <= as_of_date)
        .order_by(JournalEntry.entry_date.desc(), JournalLine.created_at.desc())
    )
    if start_date:
        line_stmt = line_stmt.where(JournalEntry.entry_date >= start_date)

    rows = (await db.execute(line_stmt)).all()
    currencies = {line.currency.upper() for line, _entry in rows}
    fx_rates = await _get_fx_rates_map(db, currencies, target_currency, as_of_date) if currencies else {}

    lines: list[dict[str, Any]] = []
    total = Decimal("0")
    for line, entry in rows:
        rate = fx_rates.get(line.currency.upper(), Decimal("1"))
        signed = _quantize_money(_signed_amount(account.type, line.direction, line.amount) * rate)
        total += signed
        lines.append(
            {
                "journal_line_id": line.id,
                "journal_entry_id": entry.id,
                "entry_date": entry.entry_date,
                "memo": entry.memo,
                "direction": line.direction,
                "original_amount": line.amount,
                "original_currency": line.currency,
                "amount": signed,
            }
        )

    return {
        "account_id": account.id,
        "account_name": account.name,
        "account_type": account.type,
        "currency": target_currency,
        "as_of_date": as_of_date,
        "start_date": start_date,
        "total": _quantize_money(total),
        "lines": lines,
    }
