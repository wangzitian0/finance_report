"""FX / cross-currency transfer pairing and net-worth classification (#1123 AC2-AC4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from src.audit import JournalEntrySourceType
from src.audit.money import Currency, Money, to_money
from src.pricing import FxConversion
from src.schemas.base import normalize_currency_code

DEFAULT_RATE_TOLERANCE = Decimal("0.005")
DEFAULT_TIME_WINDOW = timedelta(days=2)
REVALUATION_SOURCE_TYPE = JournalEntrySourceType.FX_REVALUATION


class FxTransferError(Exception):
    """Raised when FX transfer pairing inputs are invalid."""


@dataclass(frozen=True)
class TransferLeg:
    """One directional leg (`IN` or `OUT`) of a transfer."""

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
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise FxTransferError("transfer leg occurred_at must be timezone-aware")

    @property
    def money(self) -> Money:
        return Money(self.amount, Currency.of(self.currency))


@dataclass(frozen=True)
class FxLegPair:
    """Matched out-leg/in-leg pair forming one cross-currency transfer event."""

    out_leg: TransferLeg
    in_leg: TransferLeg
    market_rate: Decimal
    implied_rate: Decimal
    rate_deviation: Decimal


@dataclass
class TransferClassification:
    """Net-worth classification of a matched internal transfer (#1123 AC3)."""

    is_internal_transfer: bool
    income_amount: Decimal = field(default_factory=lambda: Decimal("0.00"))
    expense_amount: Decimal = field(default_factory=lambda: Decimal("0.00"))
    fee_amount: Decimal = field(default_factory=lambda: Decimal("0.00"))

    @property
    def net_worth_delta(self) -> Decimal:
        return to_money(-self.fee_amount if self.is_internal_transfer else self.income_amount - self.expense_amount)


def implied_rate(out_leg: TransferLeg, in_leg: TransferLeg) -> Decimal:
    if in_leg.amount == 0:
        raise FxTransferError("cannot derive implied rate from a zero in-leg amount")
    return out_leg.amount / in_leg.amount


def _within_tolerance(implied: Decimal, market: Decimal, tolerance: Decimal) -> tuple[bool, Decimal]:
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
    """Pair opposite-direction cross-currency legs of the same owner within tolerance."""
    if out_leg.direction == "IN" and in_leg.direction == "OUT":
        out_leg, in_leg = in_leg, out_leg
    if (
        out_leg.direction != "OUT"
        or in_leg.direction != "IN"
        or out_leg.user_id != in_leg.user_id
        or out_leg.account_id == in_leg.account_id
        or out_leg.currency == in_leg.currency
        or abs(out_leg.occurred_at - in_leg.occurred_at) > time_window
    ):
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
    if pair is None:
        return TransferClassification(
            is_internal_transfer=False,
            income_amount=to_money(income),
            expense_amount=to_money(expense),
        )
    return TransferClassification(is_internal_transfer=True, fee_amount=to_money(fee))


def round_trip_realized_pnl(
    initial_amount: Decimal,
    rate_out: Decimal,
    rate_back: Decimal,
    *,
    fee: Decimal = Decimal("0"),
) -> Decimal:
    if rate_out <= 0 or rate_back <= 0:
        raise FxTransferError("conversion rates must be positive")
    return to_money((initial_amount / rate_out) * rate_back - initial_amount - fee)


def build_fx_conversion(
    pair: FxLegPair,
    *,
    fee: Decimal = Decimal("0"),
    fee_currency: str | None = None,
) -> FxConversion:
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
