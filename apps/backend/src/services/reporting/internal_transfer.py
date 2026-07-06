"""Internal cross-currency transfer adjustment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit.money import to_money
from src.models.fx_conversion import FxConversion
from src.observability import ErrorIds, get_logger
from src.services.fx import (
    FxRateError,
    get_exchange_rate,
)
from src.services.fx_transfer import (
    DEFAULT_RATE_TOLERANCE,
    DEFAULT_TIME_WINDOW,
    FxTransferError,
    TransferLeg,
    classify_internal_transfer,
    pair_fx_legs,
)
from src.services.fx_transfer_discovery import discover_fx_conversions

logger = get_logger(__name__)


@dataclass(frozen=True)
class _InternalTransferAdjustment:
    """Net-income correction for matched internal (own-account) transfers (#1123 AC3).

    A matched internal transfer is one economic event spanning two legs, not two
    independent income/expense transactions. Its legs must not double-count as
    income (in-leg) and expense (out-leg); net income changes only by the fee.

    - ``excluded_entry_ids``: journal entries that are the legs of a matched
      internal transfer; their INCOME/EXPENSE lines are skipped during net-income
      aggregation.
    - ``fee_total``: total fee across matched internal transfers, in the report's
      target currency. The fee is the only net-income impact of the transfer
      (it lowers net income, like an expense).
    - ``fee_by_account``: the converted fee total attributed to the account it was
      effectively paid from (the conversion's ``from_account_id``), in the target
      currency. Used to materialise the fee as a real expense LINE so the income
      statement's lines, totals and trend buckets stay coherent — rather than
      bumping ``total_expenses`` out of band (#1162 CR2).
    - ``fee_trend_date``: the earliest conversion date contributing a fee, used to
      bucket the fee into the correct monthly trend period. ``None`` when there is
      no fee.
    """

    excluded_entry_ids: frozenset[UUID]
    fee_total: Decimal
    fee_by_account: dict[UUID, Decimal]
    fee_trend_date: date | None


async def _internal_transfer_adjustment(
    db: AsyncSession,
    user_id: UUID,
    target_currency: str,
    as_of_date: date,
    *,
    start_date: date | None = None,
) -> _InternalTransferAdjustment:
    """Resolve matched internal transfers into a net-income correction (#1123 AC3).

    Loads the recorded :class:`FxConversion` rows for ``user_id`` whose
    ``conversion_date`` falls in ``[start_date, as_of_date]`` and that anchor BOTH
    legs to journal entries (``from_journal_entry_id`` / ``to_journal_entry_id``).
    Each candidate is re-validated through the deterministic accounting primitives
    :func:`pair_fx_legs` + :func:`classify_internal_transfer`: only a pair that the
    primitives still classify as an internal transfer contributes an exclusion, so
    the reporting layer never invents netting the accounting layer would reject.

    Returns the entry IDs to exclude from income/expense and the converted fee to
    subtract from net income. This is the live wiring that makes a matched
    internal transfer net-worth-neutral (minus fees) end to end.
    """
    stmt = (
        select(FxConversion)
        .where(FxConversion.user_id == user_id)
        .where(FxConversion.conversion_date <= as_of_date)
        .where(FxConversion.from_journal_entry_id.is_not(None))
        .where(FxConversion.to_journal_entry_id.is_not(None))
    )
    if start_date:
        stmt = stmt.where(FxConversion.conversion_date >= start_date)

    result = await db.execute(stmt)
    conversions = list(result.scalars().all())

    # AC2 live (#1123): also auto-discover internal-transfer leg pairs straight
    # from the RAW ledger, so a real cross-currency transfer booked only as journal
    # lines (no pre-seeded ``fx_conversions`` row) is netted out too. Discovered
    # conversions are in-memory only and deduplicated against recorded rows by the
    # unordered pair of anchored journal entries, so a transfer that is BOTH
    # recorded and discoverable is never counted twice.
    async def _resolve_market_rate(base: str, quote: str, on_date: date) -> Decimal | None:
        try:
            return await get_exchange_rate(db, base, quote, on_date, lazy_load=True)
        except FxRateError:
            return None

    recorded_anchor_pairs = {
        frozenset((c.from_journal_entry_id, c.to_journal_entry_id))
        for c in conversions
        if c.from_journal_entry_id is not None and c.to_journal_entry_id is not None
    }
    discovered = await discover_fx_conversions(
        db,
        user_id,
        as_of_date,
        _resolve_market_rate,
        start_date=start_date,
    )
    for found in discovered:
        anchor = frozenset((found.conversion.from_journal_entry_id, found.conversion.to_journal_entry_id))
        if anchor in recorded_anchor_pairs:
            continue
        conversions.append(found.conversion)

    excluded: set[UUID] = set()
    fee_total = Decimal("0")
    fee_by_account: dict[UUID, Decimal] = {}
    fee_trend_date: date | None = None
    for conversion in conversions:
        # Re-derive the legs and confirm the accounting layer still classifies
        # this as an internal transfer before excluding anything. occurred_at is
        # tz-aware midnight on the conversion date (legs share the day; the exact
        # instant is immaterial to same-day pairing and net-worth netting).
        when = datetime.combine(conversion.conversion_date, time.min, tzinfo=UTC)
        try:
            out_leg = TransferLeg(
                user_id=conversion.user_id,
                account_id=conversion.from_account_id,
                direction="OUT",
                amount=conversion.amount_from,
                currency=conversion.currency_from,
                occurred_at=when,
            )
            in_leg = TransferLeg(
                user_id=conversion.user_id,
                account_id=conversion.to_account_id,
                direction="IN",
                amount=conversion.amount_to,
                currency=conversion.currency_to,
                occurred_at=when,
            )
            pair = pair_fx_legs(
                out_leg,
                in_leg,
                conversion.rate,
                tolerance=DEFAULT_RATE_TOLERANCE,
                time_window=DEFAULT_TIME_WINDOW,
            )
        except FxTransferError:
            # A malformed/ non-conforming conversion row is not trusted to net;
            # leave its legs to the normal income/expense classification.
            continue

        classification = classify_internal_transfer(pair, fee=conversion.fee)
        if not classification.is_internal_transfer:
            continue

        excluded.add(conversion.from_journal_entry_id)
        excluded.add(conversion.to_journal_entry_id)

        if conversion.fee and conversion.fee > 0:
            fee_currency = conversion.fee_currency or conversion.currency_from
            try:
                fee_rate = await get_exchange_rate(
                    db,
                    fee_currency,
                    target_currency,
                    as_of_date,
                    lazy_load=True,
                )
            except FxRateError:
                # The transfer legs are still a matched internal transfer and MUST
                # stay excluded (otherwise the double-counted income/expense legs
                # are re-introduced). Only the fee adjustment is omitted when its
                # currency cannot be converted; keep the exclusions intact.
                logger.warning(
                    "Internal-transfer fee FX conversion failed; omitting fee adjustment but keeping leg exclusions",
                    error_id=ErrorIds.REPORT_FX_FALLBACK,
                    fee_currency=fee_currency,
                    target_currency=target_currency,
                    conversion_date=conversion.conversion_date,
                )
                continue
            converted_fee = to_money(Decimal(str(classification.fee_amount)) * fee_rate)
            fee_total += converted_fee
            # Attribute the fee to the account it was effectively paid from so it can
            # be materialised as a real expense line (#1162 CR2).
            fee_by_account[conversion.from_account_id] = (
                fee_by_account.get(conversion.from_account_id, Decimal("0")) + converted_fee
            )
            if fee_trend_date is None or conversion.conversion_date < fee_trend_date:
                fee_trend_date = conversion.conversion_date

    return _InternalTransferAdjustment(
        excluded_entry_ids=frozenset(excluded),
        fee_total=to_money(fee_total),
        fee_by_account=fee_by_account,
        fee_trend_date=fee_trend_date,
    )
