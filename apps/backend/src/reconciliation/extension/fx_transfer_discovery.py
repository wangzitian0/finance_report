"""Ledger-based discovery of cross-currency internal-transfer leg pairs.

#1123 AC2 (live consumption). The :mod:`src.reconciliation.extension.fx_transfer` primitives can
*pair* two already-known :class:`TransferLeg` objects, and
:func:`src.reporting.extension.internal_transfer._internal_transfer_adjustment` can *consume* a
pre-recorded ``fx_conversions`` row. This module closes the gap between them: it
**auto-discovers** candidate cross-currency transfer leg pairs directly from a
user's RAW journal ledger, so a real internal transfer booked only as journal
lines (no pre-seeded ``fx_conversions`` row) is still recognised and netted out.

The discovery is deliberately **deterministic and conservative**:

- It scans only ``ASSET`` accounts (the cash/bank/brokerage accounts money moves
  between). On an asset, a ``CREDIT`` line is money leaving (an ``OUT`` leg) and a
  ``DEBIT`` line is money arriving (an ``IN`` leg).
- An OUT leg in currency A pairs with an IN leg in currency B only when the
  deterministic :func:`pair_fx_legs` accepts them: same owner, opposite
  direction, distinct accounts, **distinct currencies**, within the time window,
  and ``amount_from / amount_to`` within tolerance of the observed market rate.
- Only **unambiguous** matches are materialised. If an OUT leg could pair with
  more than one IN leg (or vice versa), the leg is left alone — the system never
  *guesses* which booking is the counterpart. This biases strongly toward
  *under*-netting: skipping ambiguous matches sharply reduces the risk of
  false-positive netting (which would corrupt net worth), though absent an
  explicit linkage signal it cannot eliminate it entirely.

A discovered pair is materialised as an **in-memory** :class:`FxConversion`
(never persisted by this module) anchoring both legs to their journal entries, so
it slots straight into the existing ``_internal_transfer_adjustment`` consumer
alongside any recorded rows.

All money is :class:`~decimal.Decimal` (never ``float`` — see the decimal rule in
``common/ledger/readme.md``).
"""

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

# Statuses whose lines are eligible to participate in a discovered transfer. Must
# match the reporting layer's ``_REPORT_STATUSES`` so discovery and aggregation
# see the same ledger.
_DISCOVERY_STATUSES = (JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED)

# Market-rate resolver signature: given (base, quote, on_date) return ``get_exchange_rate``'s
# value, i.e. **units of quote per unit of base** (``convert_amount`` multiplies by
# it: ``amount_in_quote = amount_in_base * rate``). Returning ``None`` means "no rate
# available" — the candidate is skipped rather than paired on a guess. This matches
# ``src.pricing.get_exchange_rate``; discovery converts the orientation it needs
# (``currency_from`` per ``currency_to``, see :func:`pair_fx_legs`) by calling the
# resolver with ``base=in_currency, quote=out_currency``.
MarketRateResolver = Callable[[str, str, date], Awaitable[Decimal | None]]


@dataclass(frozen=True)
class _CandidateLeg:
    """A raw asset-account journal line reinterpreted as a transfer leg."""

    leg: TransferLeg
    journal_entry_id: UUID


@dataclass(frozen=True)
class DiscoveredConversion:
    """A ledger-discovered conversion plus the pairing detail that produced it.

    ``conversion`` is an in-memory :class:`FxConversion` (not persisted) carrying
    both leg journal-entry anchors. ``pair`` is the :class:`FxLegPair` the
    deterministic primitive produced, surfaced so callers can report exactly what
    was matched (rate, implied rate, deviation).
    """

    conversion: FxConversion
    pair: FxLegPair


async def _load_asset_legs(
    db: AsyncSession,
    user_id: UUID,
    as_of_date: date,
    start_date: date | None,
) -> list[_CandidateLeg]:
    """Load asset-account journal lines in window as directional transfer legs.

    On an ASSET account a ``DEBIT`` increases the balance (money ``IN``) and a
    ``CREDIT`` decreases it (money ``OUT``). Each line's ``occurred_at`` is the
    owning entry's ``entry_date`` at tz-aware midnight (the exact instant is
    immaterial to same-day/within-window pairing).
    """
    stmt = (
        select(JournalLine, JournalEntry.entry_date, JournalEntry.id)
        .join(Account, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalLine.journal_entry_id == JournalEntry.id)
        .where(Account.user_id == user_id)
        .where(Account.type == AccountType.ASSET)
        .where(JournalEntry.status.in_(_DISCOVERY_STATUSES))
        .where(JournalEntry.entry_date <= as_of_date)
    )
    if start_date is not None:
        stmt = stmt.where(JournalEntry.entry_date >= start_date)

    result = await db.execute(stmt)

    candidates: list[_CandidateLeg] = []
    for line, entry_date, entry_id in result.all():
        direction = "IN" if line.direction == Direction.DEBIT else "OUT"
        when = datetime.combine(entry_date, time.min, tzinfo=UTC)
        try:
            leg = TransferLeg(
                user_id=user_id,
                account_id=line.account_id,
                direction=direction,
                amount=line.amount,
                currency=line.currency,
                occurred_at=when,
                leg_id=line.id,
            )
        except FxTransferError:
            # Defensive: a malformed line (non-positive amount, etc.) cannot form a
            # transfer leg. The DB constraint forbids it, so this is belt-and-braces.
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
    """Auto-discover unambiguous cross-currency transfer pairs from the ledger.

    #1123 AC2 (live). Scans the user's ASSET-account journal lines in
    ``[start_date, as_of_date]``, reinterprets each as a directional
    :class:`TransferLeg`, and pairs OUT legs with IN legs via the deterministic
    :func:`pair_fx_legs` (which already enforces same-owner, opposite-direction,
    distinct accounts, **distinct currencies**, time-window, and implied-rate
    tolerance). The market rate for each candidate OUT→IN pair is fetched via
    ``market_rate_resolver``; a candidate with no available rate is skipped.

    **Only unambiguous pairs are returned.** A pairing is kept iff the OUT leg
    pairs with exactly one IN leg *and* that IN leg pairs with exactly one OUT
    leg. Any leg involved in more than one acceptable pairing is dropped entirely
    (the algorithm refuses to guess), so discovery biases toward *under*-netting
    rather than risk pairing unrelated legs. Without an explicit linkage signal,
    coincidental matches remain possible, so this reduces — not eliminates —
    false positives.

    Returns the discovered conversions as in-memory :class:`FxConversion` rows
    (not persisted) wrapped with their :class:`FxLegPair` for reporting.
    """
    candidates = await _load_asset_legs(db, user_id, as_of_date, start_date)
    out_legs = [c for c in candidates if c.leg.direction == "OUT"]
    in_legs = [c for c in candidates if c.leg.direction == "IN"]

    # Build every acceptable OUT->IN pairing first, then keep only the ones that
    # are unambiguous from BOTH sides. We index acceptable matches per leg.
    matches_for_out: dict[int, list[tuple[int, FxLegPair]]] = defaultdict(list)
    matches_for_in: dict[int, list[int]] = defaultdict(list)

    for oi, out_c in enumerate(out_legs):
        for ii, in_c in enumerate(in_legs):
            out_leg = out_c.leg
            in_leg = in_c.leg
            # Cheap pre-checks mirror pair_fx_legs so we only resolve a market
            # rate for genuinely plausible candidates (distinct accounts/currencies,
            # within window). pair_fx_legs re-validates all of these.
            if out_leg.account_id == in_leg.account_id:
                continue
            if out_leg.currency == in_leg.currency:
                continue
            if abs(out_leg.occurred_at - in_leg.occurred_at) > time_window:
                continue

            # pair_fx_legs wants market_rate quoted as currency_from / currency_to
            # (out per in). get_exchange_rate(base, quote) returns quote-per-base, so
            # base=in_currency, quote=out_currency yields out-per-in.
            market_rate = await market_rate_resolver(in_leg.currency, out_leg.currency, out_leg.occurred_at.date())
            if market_rate is None or market_rate <= 0:
                continue

            pair = pair_fx_legs(
                out_leg,
                in_leg,
                market_rate,
                tolerance=tolerance,
                time_window=time_window,
            )
            if pair is None:
                continue
            matches_for_out[oi].append((ii, pair))
            matches_for_in[ii].append(oi)

    discovered: list[DiscoveredConversion] = []
    for oi, matches in matches_for_out.items():
        if len(matches) != 1:
            # OUT leg pairs with multiple IN legs -> ambiguous; do not guess.
            continue
        ii, pair = matches[0]
        if len(matches_for_in[ii]) != 1:
            # The IN leg is also wanted by another OUT leg -> ambiguous; skip.
            continue

        out_c = out_legs[oi]
        in_c = in_legs[ii]
        conversion = build_fx_conversion(pair)
        # Anchor both legs to their journal entries so the conversion slots into
        # the existing _internal_transfer_adjustment consumer unchanged.
        conversion.user_id = user_id
        conversion.from_journal_entry_id = out_c.journal_entry_id
        conversion.to_journal_entry_id = in_c.journal_entry_id
        discovered.append(DiscoveredConversion(conversion=conversion, pair=pair))

    # Deterministic ordering: by conversion_date then from-account for stable output.
    discovered.sort(key=lambda d: (d.conversion.conversion_date, str(d.conversion.from_account_id)))
    return discovered
