"""FX / cross-currency transfer pairing and net-worth classification.

#1123 AC2/AC3/AC4. A cross-currency transfer (e.g. SGD leaves one account, USD
enters another, at a conversion rate) is **one economic event spanning two
legs**, not two independent income/expense transactions. This module provides
the deterministic, Decimal-only accounting-layer primitives for that model:

- :func:`pair_fx_legs` — match an out-leg in currency A with an in-leg in
  currency B for the **same owner**, **opposite direction**, within a **time
  window**, where ``amount_from ≈ amount_to × market_rate`` within a Decimal
  tolerance (**AC2**).
- :func:`classify_internal_transfer` — classify a matched internal transfer as
  net-zero so the transfer-in is not income and the transfer-out is not expense;
  net worth changes only by the fee (**AC3**).
- :func:`round_trip_realized_pnl` — a same-day round-trip conversion nets ~zero
  realized P&L (minus fee/spread); the rate move belongs to revaluation over the
  holding period (routed through the ``fx_revaluation`` journal source type),
  not to the conversion event (**AC4**).

Generalized invariant: **net worth changes only via external in/out + market
moves + FX revaluation; internal transfers cancel (minus fees).**

All money is :class:`~decimal.Decimal` (never ``float`` — see the decimal rule in
``common/ledger/readme.md``). FX rates carry 6 dp; currency amounts quantize to
2 dp via :func:`src.audit.money.to_money`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from src.audit.money import Money, to_money
from src.models.fx_conversion import FxConversion
from src.models.journal import JournalEntrySourceType
from src.schemas.base import normalize_currency_code

# Default implied-rate tolerance: the implied rate (amount_from / amount_to) may
# differ from the observed market rate by up to this fraction and still pair.
# 0.5% absorbs ordinary bid/ask spread and rounding without matching unrelated
# legs. Callers may override per reconciliation policy.
DEFAULT_RATE_TOLERANCE = Decimal("0.005")

# Default pairing time window. Cross-currency conversions settle close together;
# legs more than this far apart are not treated as one event.
DEFAULT_TIME_WINDOW = timedelta(days=2)


class FxTransferError(Exception):
    """Raised when FX transfer pairing inputs are invalid."""


@dataclass(frozen=True)
class TransferLeg:
    """One side of a (possibly cross-currency) transfer.

    ``direction`` is ``"OUT"`` (money leaving an account) or ``"IN"`` (money
    arriving). ``amount`` is always positive and Decimal.
    """

    user_id: UUID
    account_id: UUID
    direction: str
    amount: Decimal
    currency: str
    occurred_at: datetime
    leg_id: UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", normalize_currency_code(self.currency))
        if self.direction not in ("IN", "OUT"):
            raise FxTransferError(f"direction must be 'IN' or 'OUT', got {self.direction!r}")
        if self.amount <= 0:
            raise FxTransferError("transfer leg amount must be positive")
        # Enforce timezone-aware timestamps at construction (#1161 CR3). Pairing
        # subtracts two legs' ``occurred_at``; a mix of naive and aware datetimes
        # raises ``TypeError`` mid-pairing. Reject naive datetimes up front so the
        # failure is a clear, local FxTransferError instead.
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise FxTransferError("transfer leg occurred_at must be timezone-aware")

    @property
    def money(self) -> Money:
        """This leg's amount as a typed :class:`Money` (#1167 / #1171 AC2.22.4).

        The single typed representation of a leg's value — so callers compare and
        combine legs through the money value type (same-currency-only) instead of
        passing a bare ``(Decimal, str)`` pair. Pairing/rate math is unchanged.
        """
        return Money(self.amount, self.currency)


@dataclass(frozen=True)
class FxLegPair:
    """A matched out-leg/in-leg pair forming one cross-currency transfer event."""

    out_leg: TransferLeg
    in_leg: TransferLeg
    market_rate: Decimal
    implied_rate: Decimal
    rate_deviation: Decimal


@dataclass
class TransferClassification:
    """Net-worth classification of a matched internal transfer (#1123 AC3).

    A matched internal transfer is net-zero across its legs: the in-leg is *not*
    income and the out-leg is *not* expense. Net worth moves only by ``fee``.
    """

    is_internal_transfer: bool
    income_amount: Decimal = field(default_factory=lambda: Decimal("0.00"))
    expense_amount: Decimal = field(default_factory=lambda: Decimal("0.00"))
    fee_amount: Decimal = field(default_factory=lambda: Decimal("0.00"))

    @property
    def net_worth_delta(self) -> Decimal:
        """Net-worth change attributable to this transfer (fee only when internal)."""
        if self.is_internal_transfer:
            return to_money(-self.fee_amount)
        return to_money(self.income_amount - self.expense_amount)


def implied_rate(out_leg: TransferLeg, in_leg: TransferLeg) -> Decimal:
    """Implied conversion rate ``amount_from / amount_to`` (ccyA per ccyB).

    Mirrors :func:`src.services.fx.get_exchange_rate` orientation: the rate is
    quoted as ``base/quote`` where base is the out (from) currency.
    """
    if in_leg.amount == 0:
        raise FxTransferError("cannot derive implied rate from a zero in-leg amount")
    return out_leg.amount / in_leg.amount


def _within_tolerance(implied: Decimal, market: Decimal, tolerance: Decimal) -> tuple[bool, Decimal]:
    """Return (within, relative_deviation) of ``implied`` vs ``market`` rate."""
    if market <= 0:
        raise FxTransferError("market rate must be positive")
    deviation = abs(implied - market) / market
    return deviation <= tolerance, deviation


def pair_fx_legs(
    out_leg: TransferLeg,
    in_leg: TransferLeg,
    market_rate: Decimal,
    *,
    tolerance: Decimal = DEFAULT_RATE_TOLERANCE,
    time_window: timedelta = DEFAULT_TIME_WINDOW,
) -> FxLegPair | None:
    """Pair an out-leg with an in-leg into one cross-currency transfer event.

    #1123 AC2. Two legs pair iff ALL hold:

    1. **Same owner** — identical ``user_id``.
    2. **Opposite direction** — one ``OUT`` and one ``IN``.
    3. **Time window** — ``|out.occurred_at - in.occurred_at| <= time_window``.
    4. **Implied-rate match** — ``amount_from / amount_to`` is within
       ``tolerance`` (relative) of the observed ``market_rate``.

    ``market_rate`` is quoted as ``currency_from / currency_to`` (ccyA per ccyB),
    matching :func:`src.services.fx.get_exchange_rate`'s base/quote orientation.

    Returns the :class:`FxLegPair` when the legs pair, else ``None``. Argument
    order is not assumed: the leg with ``direction == "OUT"`` is treated as the
    from-leg regardless of position.
    """
    # Normalize argument order so callers may pass legs in either position.
    if out_leg.direction == "IN" and in_leg.direction == "OUT":
        out_leg, in_leg = in_leg, out_leg

    if out_leg.direction != "OUT" or in_leg.direction != "IN":
        return None
    if out_leg.user_id != in_leg.user_id:
        return None
    if out_leg.account_id == in_leg.account_id:
        # Same account cannot be both source and destination of a transfer.
        return None
    if out_leg.currency == in_leg.currency:
        # A cross-currency conversion requires distinct currencies (#1161 CR2).
        # A same-currency internal transfer with rate≈1 and matching amounts would
        # otherwise be misclassified here as an FX conversion. Same-currency
        # own-account transfers are handled by the (non-FX) internal-transfer path,
        # not by FX-leg pairing.
        return None
    if abs(out_leg.occurred_at - in_leg.occurred_at) > time_window:
        return None

    implied = implied_rate(out_leg, in_leg)
    within, deviation = _within_tolerance(implied, market_rate, tolerance)
    if not within:
        return None

    return FxLegPair(
        out_leg=out_leg,
        in_leg=in_leg,
        market_rate=market_rate,
        implied_rate=implied,
        rate_deviation=deviation,
    )


def classify_internal_transfer(
    pair: FxLegPair | None,
    *,
    fee: Decimal = Decimal("0"),
    income: Decimal = Decimal("0"),
    expense: Decimal = Decimal("0"),
) -> TransferClassification:
    """Classify a matched transfer for net-worth aggregation (#1123 AC3).

    When ``pair`` is a matched :class:`FxLegPair`, the event is an internal
    (own-account) transfer: the in-leg must NOT register as income and the
    out-leg must NOT register as expense. Net worth changes only by ``fee``, so
    income/expense are forced to zero and ``net_worth_delta == -fee``.

    When ``pair`` is ``None`` (legs did not pair), no internal-transfer netting is
    asserted: the caller's already-classified ``income`` / ``expense`` are carried
    through unchanged so ``net_worth_delta == income − expense`` matches the
    documented formula (#1161 CR4). Defaulting both to zero preserves the previous
    "no-op" behavior for callers that do not pass them.
    """
    if pair is None:
        return TransferClassification(
            is_internal_transfer=False,
            income_amount=to_money(income),
            expense_amount=to_money(expense),
        )
    return TransferClassification(
        is_internal_transfer=True,
        income_amount=Decimal("0.00"),
        expense_amount=Decimal("0.00"),
        fee_amount=to_money(fee),
    )


def round_trip_realized_pnl(
    initial_amount: Decimal,
    rate_out: Decimal,
    rate_back: Decimal,
    *,
    fee: Decimal = Decimal("0"),
) -> Decimal:
    """Realized P&L of a same-day round-trip conversion A→B→A (#1123 AC4).

    Convert ``initial_amount`` of currency A into B at ``rate_out`` (A per B),
    then back into A at ``rate_back``. The realized P&L is the net change in the
    base-currency-A holding, minus ``fee``.

    For a **same-day** round trip the market rate has not moved
    (``rate_out == rate_back``), so the realized P&L is ``-fee``: the conversion
    event itself produces no gain/loss. Any later divergence between the entry and
    a subsequent valuation is a holding-period **revaluation**, attributed over
    time through the ``fx_revaluation`` journal source type
    (:data:`REVALUATION_SOURCE_TYPE`) — never booked as a conversion-event gain.
    """
    if rate_out <= 0 or rate_back <= 0:
        raise FxTransferError("conversion rates must be positive")
    intermediate = initial_amount / rate_out  # amount of currency B acquired
    returned = intermediate * rate_back  # amount of currency A on the way back
    realized = returned - initial_amount - fee
    return to_money(realized)


def build_fx_conversion(
    pair: FxLegPair,
    *,
    fee: Decimal = Decimal("0"),
    fee_currency: str | None = None,
) -> FxConversion:
    """Materialize a matched :class:`FxLegPair` as an :class:`FxConversion` row.

    #1123 AC2. The linking record carries the multi-leg event additively. Money
    amounts are quantized to 2 dp; the rate keeps full Decimal precision; ISO
    currency codes are normalized.
    """
    return FxConversion(
        user_id=pair.out_leg.user_id,
        from_account_id=pair.out_leg.account_id,
        to_account_id=pair.in_leg.account_id,
        amount_from=to_money(pair.out_leg.amount),
        currency_from=normalize_currency_code(pair.out_leg.currency),
        amount_to=to_money(pair.in_leg.amount),
        currency_to=normalize_currency_code(pair.in_leg.currency),
        rate=pair.market_rate,
        fee=to_money(fee),
        fee_currency=normalize_currency_code(fee_currency) if fee_currency else None,
        conversion_date=pair.out_leg.occurred_at.date(),
    )


# The journal source type that carries FX gain/loss as a holding-period
# revaluation (#1123 AC4). Re-exported so the accounting layer routes FX P&L
# here rather than through a conversion-event income/expense line.
REVALUATION_SOURCE_TYPE = JournalEntrySourceType.FX_REVALUATION
