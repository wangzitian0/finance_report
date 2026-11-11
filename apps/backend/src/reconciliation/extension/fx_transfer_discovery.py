"""Ledger-based discovery of unambiguous cross-currency internal-transfer leg pairs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.pricing import FxConversion
from src.reconciliation.extension.fx_transfer import (
    DEFAULT_RATE_TOLERANCE,
    DEFAULT_TIME_WINDOW,
    FxLegPair,
    FxTransferError,
    TransferLeg,
    build_fx_conversion,
    pair_fx_legs,
)

_DISCOVERY_STATUSES = (JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED)
MarketRateResolver = Callable[[str, str, date], Awaitable[Decimal | None]]


@dataclass(frozen=True)
class _CandidateLeg:
    leg: TransferLeg
    journal_entry_id: UUID


@dataclass(frozen=True)
class DiscoveredConversion:
    """In-memory discovered conversion anchored to its two journal entries."""

    conversion: FxConversion
    pair: FxLegPair


async def _load_asset_legs(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date,
    start_date: date | None,
) -> list[_CandidateLeg]:
    stmt = (
        select(
            JournalLine.id,
            JournalLine.account_id,
            JournalLine.direction,
            JournalLine.amount,
            JournalLine.currency,
            JournalEntry.entry_date,
            JournalEntry.id,
        )
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(
            Account.user_id == user_id,
            Account.type == AccountType.ASSET,
            JournalEntry.user_id == user_id,
            JournalEntry.status.in_(_DISCOVERY_STATUSES),
            JournalEntry.entry_date <= as_of_date,
        )
    )
    if start_date is not None:
        stmt = stmt.where(JournalEntry.entry_date >= start_date)

    candidates: list[_CandidateLeg] = []
    for line_id, account_id, line_dir, amount, currency, entry_date, entry_id in (await db.execute(stmt)).all():
        try:
            leg = TransferLeg(
                user_id=user_id,
                account_id=account_id,
                direction="IN" if line_dir == Direction.DEBIT else "OUT",
                amount=amount,
                currency=currency,
                occurred_at=datetime.combine(entry_date, time.min, tzinfo=UTC),
                leg_id=line_id,
            )
        except FxTransferError:
            continue
        candidates.append(_CandidateLeg(leg=leg, journal_entry_id=entry_id))
    return candidates


async def discover_fx_conversions(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date,
    market_rate_resolver: MarketRateResolver,
    *,
    start_date: date | None = None,
    tolerance: Decimal = DEFAULT_RATE_TOLERANCE,
    time_window: timedelta = DEFAULT_TIME_WINDOW,
) -> list[DiscoveredConversion]:
    """Auto-discover unambiguous cross-currency transfer pairs from ASSET journal lines."""
    candidates = await _load_asset_legs(db, user_id, as_of_date, start_date)
    out_legs = [c for c in candidates if c.leg.direction == "OUT"]
    in_legs = [c for c in candidates if c.leg.direction == "IN"]

    matches_for_out: dict[int, list[tuple[int, FxLegPair]]] = defaultdict(list)
    matches_for_in: dict[int, list[int]] = defaultdict(list)

    for oi, out_c in enumerate(out_legs):
        for ii, in_c in enumerate(in_legs):
            out_leg, in_leg = out_c.leg, in_c.leg
            if (
                out_leg.account_id == in_leg.account_id
                or out_leg.currency == in_leg.currency
                or abs(out_leg.occurred_at - in_leg.occurred_at) > time_window
            ):
                continue
            market_rate = await market_rate_resolver(in_leg.currency, out_leg.currency, out_leg.occurred_at.date())
            if market_rate is None or market_rate <= 0:
                continue
            pair = pair_fx_legs(out_leg, in_leg, market_rate, tolerance=tolerance, time_window=time_window)
            if pair is not None:
                matches_for_out[oi].append((ii, pair))
                matches_for_in[ii].append(oi)

    discovered: list[DiscoveredConversion] = []
    for oi, matches in matches_for_out.items():
        if len(matches) != 1:
            continue
        ii, pair = matches[0]
        if len(matches_for_in[ii]) != 1:
            continue
        conv = build_fx_conversion(pair)
        conv.user_id = user_id
        conv.from_journal_entry_id = out_legs[oi].journal_entry_id
        conv.to_journal_entry_id = in_legs[ii].journal_entry_id
        discovered.append(DiscoveredConversion(conversion=conv, pair=pair))

    discovered.sort(key=lambda d: (d.conversion.conversion_date, str(d.conversion.from_account_id)))
    return discovered
