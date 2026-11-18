from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4
import pytest
from src.audit import JournalEntrySourceType
from src.reconciliation.extension.fx_transfer import (
    REVALUATION_SOURCE_TYPE,
    FxTransferError,
    TransferLeg,
    build_fx_conversion,
    classify_internal_transfer,
    pair_fx_legs,
    round_trip_realized_pnl,
)

_OUT_AMOUNT = Decimal("1360.00")
_IN_AMOUNT = Decimal("1000.00")
_MARKET_RATE = Decimal("1.360000")


def _legs(*, user_id=None, out_account=None, in_account=None, when=None):
    user_id = user_id or uuid4()
    when = when or datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    out_leg = TransferLeg(
        user_id=user_id,
        account_id=out_account or uuid4(),
        direction="OUT",
        amount=_OUT_AMOUNT,
        currency="sgd",
        occurred_at=when,
    )
    in_leg = TransferLeg(
        user_id=user_id,
        account_id=in_account or uuid4(),
        direction="IN",
        amount=_IN_AMOUNT,
        currency="usd",
        occurred_at=when,
    )
    return (out_leg, in_leg)


def test_AC2_pairs_out_ccyA_with_in_ccyB_within_rate_tolerance():
    out_leg, in_leg = _legs()
    pair = pair_fx_legs(out_leg, in_leg, _MARKET_RATE)
    assert pair is not None
    assert pair.out_leg.currency == "SGD"
    assert pair.in_leg.currency == "USD"
    assert pair.implied_rate == _OUT_AMOUNT / _IN_AMOUNT
    assert pair.rate_deviation <= Decimal("0.005")
    swapped = pair_fx_legs(in_leg, out_leg, _MARKET_RATE)
    assert swapped is not None
    assert swapped.out_leg.account_id == out_leg.account_id


def test_AC2_implied_rate_outside_tolerance_does_not_pair():
    out_leg, in_leg = _legs()
    assert pair_fx_legs(out_leg, in_leg, Decimal("1.500000")) is None
    assert pair_fx_legs(out_leg, in_leg, Decimal("1.364000")) is not None


def test_AC2_non_candidate_legs_do_not_pair():
    out_leg, in_leg = _legs()
    far_in = TransferLeg(
        user_id=out_leg.user_id,
        account_id=in_leg.account_id,
        direction="IN",
        amount=_IN_AMOUNT,
        currency="USD",
        occurred_at=datetime(2025, 6, 6, 12, 0, tzinfo=UTC),
    )
    assert pair_fx_legs(out_leg, far_in, _MARKET_RATE) is None
    out_leg2, _ = _legs(user_id=out_leg.user_id)
    assert pair_fx_legs(out_leg, out_leg2, _MARKET_RATE) is None
    _, other_in = _legs()
    assert pair_fx_legs(out_leg, other_in, _MARKET_RATE) is None
    acct = uuid4()
    same_out, same_in = _legs(user_id=out_leg.user_id, out_account=acct, in_account=acct)
    assert pair_fx_legs(same_out, same_in, _MARKET_RATE) is None


def test_AC3_internal_transfer_classified_net_zero():
    out_leg, in_leg = _legs()
    pair = pair_fx_legs(out_leg, in_leg, _MARKET_RATE)
    classification = classify_internal_transfer(pair, fee=Decimal("2.50"))
    assert classification.is_internal_transfer is True
    assert classification.income_amount == Decimal("0.00")
    assert classification.expense_amount == Decimal("0.00")
    unpaired = classify_internal_transfer(None)
    assert unpaired.is_internal_transfer is False


def test_AC3_net_worth_unchanged_by_internal_transfer_minus_fee():
    out_leg, in_leg = _legs()
    pair = pair_fx_legs(out_leg, in_leg, _MARKET_RATE)
    no_fee = classify_internal_transfer(pair)
    assert no_fee.net_worth_delta == Decimal("0.00")
    with_fee = classify_internal_transfer(pair, fee=Decimal("3.75"))
    assert with_fee.net_worth_delta == Decimal("-3.75")


def test_AC4_same_day_round_trip_nets_zero_pnl_minus_fee():
    pnl = round_trip_realized_pnl(Decimal("1360.00"), rate_out=_MARKET_RATE, rate_back=_MARKET_RATE, fee=Decimal("0"))
    assert pnl == Decimal("0.00")
    pnl_with_fee = round_trip_realized_pnl(
        Decimal("1360.00"), rate_out=_MARKET_RATE, rate_back=_MARKET_RATE, fee=Decimal("1.20")
    )
    assert pnl_with_fee == Decimal("-1.20")


def test_AC4_revaluation_pnl_routed_through_fx_revaluation_source_type():
    assert round_trip_realized_pnl(Decimal("1000.00"), rate_out=_MARKET_RATE, rate_back=_MARKET_RATE) == Decimal("0.00")
    assert REVALUATION_SOURCE_TYPE is JournalEntrySourceType.FX_REVALUATION
    assert REVALUATION_SOURCE_TYPE.value == "fx_revaluation"


def test_AC2_fx_conversion_model_round_trips_decimals():
    out_leg, in_leg = _legs()
    pair = pair_fx_legs(out_leg, in_leg, _MARKET_RATE)
    assert pair is not None
    conversion = build_fx_conversion(pair, fee=Decimal("2.50"), fee_currency="sgd")
    assert conversion.amount_from == Decimal("1360.00")
    assert conversion.amount_to == Decimal("1000.00")
    assert isinstance(conversion.amount_from, Decimal)
    assert isinstance(conversion.amount_to, Decimal)
    assert conversion.rate == _MARKET_RATE
    assert conversion.currency_from == "SGD"
    assert conversion.currency_to == "USD"
    assert conversion.fee == Decimal("2.50")
    assert conversion.fee_currency == "SGD"
    assert conversion.from_account_id == out_leg.account_id
    assert conversion.to_account_id == in_leg.account_id
    assert conversion.conversion_date == out_leg.occurred_at.date()


def test_invalid_transfer_leg_rejected():
    when = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    with pytest.raises(FxTransferError):
        TransferLeg(
            user_id=uuid4(),
            account_id=uuid4(),
            direction="SIDEWAYS",
            amount=Decimal("1.00"),
            currency="SGD",
            occurred_at=when,
        )
    with pytest.raises(FxTransferError):
        TransferLeg(
            user_id=uuid4(), account_id=uuid4(), direction="OUT", amount=Decimal("0"), currency="SGD", occurred_at=when
        )
    _m1_naive = datetime(2025, 6, 1, 12, 0)
    assert _m1_naive.tzinfo is None
    with pytest.raises(FxTransferError, match="timezone-aware"):
        TransferLeg(
            user_id=uuid4(),
            account_id=uuid4(),
            direction="OUT",
            amount=Decimal("100.00"),
            currency="SGD",
            occurred_at=_m1_naive,
        )
    _m2_user_id = uuid4()
    _m2_when = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    _m2_out_leg = TransferLeg(
        user_id=_m2_user_id,
        account_id=uuid4(),
        direction="OUT",
        amount=Decimal("500.00"),
        currency="SGD",
        occurred_at=_m2_when,
    )
    _m2_in_leg = TransferLeg(
        user_id=_m2_user_id,
        account_id=uuid4(),
        direction="IN",
        amount=Decimal("500.00"),
        currency="SGD",
        occurred_at=_m2_when,
    )
    assert pair_fx_legs(_m2_out_leg, _m2_in_leg, Decimal("1.000000")) is None
    assert pair_fx_legs(_m2_in_leg, _m2_out_leg, Decimal("1.000000")) is None
    _m3_classification = classify_internal_transfer(None, income=Decimal("120.00"), expense=Decimal("45.00"))
    assert _m3_classification.is_internal_transfer is False
    assert _m3_classification.income_amount == Decimal("120.00")
    assert _m3_classification.expense_amount == Decimal("45.00")
    assert _m3_classification.net_worth_delta == Decimal("75.00")
    assert classify_internal_transfer(None).net_worth_delta == Decimal("0.00")
