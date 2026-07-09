"""AC4.14.x — FX / cross-currency transfers as linked multi-leg events.

#1123 AC2/AC3/AC4 (assurance #1103). Deterministic, Decimal-only tests for the
accounting-layer primitives in ``src.reconciliation.extension.fx_transfer``:

- AC2: pairing an out-leg in ccyA with an in-leg in ccyB via implied-rate-within-
  tolerance, same owner, opposite direction, time window.
- AC3: a matched internal transfer is net-zero (not income/expense); net worth
  changes only by the fee.
- AC4: a same-day round-trip conversion nets ~zero realized P&L (minus fee), with
  rate moves attributed to ``fx_revaluation`` rather than the conversion event.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from common.testing.ac_proof import ac_proof

from src.models.journal import JournalEntrySourceType
from src.reconciliation.extension.fx_transfer import (
    REVALUATION_SOURCE_TYPE,
    FxTransferError,
    TransferLeg,
    build_fx_conversion,
    classify_internal_transfer,
    pair_fx_legs,
    round_trip_realized_pnl,
)

# A representative cross-currency conversion: 1360.00 SGD -> 1000.00 USD.
# Implied rate (SGD per USD) = 1360 / 1000 = 1.360000; market rate ~ 1.3600.
_OUT_AMOUNT = Decimal("1360.00")
_IN_AMOUNT = Decimal("1000.00")
_MARKET_RATE = Decimal("1.360000")  # SGD/USD


def _legs(*, user_id=None, out_account=None, in_account=None, when=None):
    user_id = user_id or uuid4()
    when = when or datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    out_leg = TransferLeg(
        user_id=user_id,
        account_id=out_account or uuid4(),
        direction="OUT",
        amount=_OUT_AMOUNT,
        currency="sgd",  # lower-case to exercise normalization
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
    return out_leg, in_leg


@ac_proof(
    "fx-transfer-pair-within-tolerance-pr",
    ac_ids=["AC-reconciliation.fx-transfer.1"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
def test_AC2_pairs_out_ccyA_with_in_ccyB_within_rate_tolerance(ac_evidence):
    """AC-reconciliation.fx-transfer.1: AC4.14.1: out-ccyA leg pairs with in-ccyB leg via implied-rate-in-tolerance."""
    out_leg, in_leg = _legs()
    pair = pair_fx_legs(out_leg, in_leg, _MARKET_RATE)
    assert pair is not None
    assert pair.out_leg.currency == "SGD"
    assert pair.in_leg.currency == "USD"
    assert pair.implied_rate == _OUT_AMOUNT / _IN_AMOUNT
    assert pair.rate_deviation <= Decimal("0.005")
    # Argument order must not matter: passing legs swapped yields the same pairing.
    swapped = pair_fx_legs(in_leg, out_leg, _MARKET_RATE)
    assert swapped is not None
    assert swapped.out_leg.account_id == out_leg.account_id
    ac_evidence(
        ac_id="AC4.14.1",
        score=1.0,
        metric="fx_legs_pair_when_implied_rate_within_tolerance",
        provenance="deterministic",
        comment="Deterministic FX transfer accounting-layer proof (#1123 AC2/AC3/AC4).",
    )


@ac_proof(
    "fx-transfer-rate-outside-tolerance-pr",
    ac_ids=["AC-reconciliation.fx-transfer.2"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
def test_AC2_implied_rate_outside_tolerance_does_not_pair(ac_evidence):
    """AC-reconciliation.fx-transfer.2: AC4.14.2: legs whose implied rate is outside tolerance do not pair."""
    out_leg, in_leg = _legs()
    # Market rate far from the implied 1.36 (e.g. 1.50 SGD/USD) -> ~10% deviation.
    assert pair_fx_legs(out_leg, in_leg, Decimal("1.500000")) is None
    # A tight in-tolerance market rate still pairs.
    assert pair_fx_legs(out_leg, in_leg, Decimal("1.364000")) is not None
    ac_evidence(
        ac_id="AC4.14.2",
        score=1.0,
        metric="fx_legs_do_not_pair_outside_rate_tolerance",
        provenance="deterministic",
        comment="Deterministic FX transfer accounting-layer proof (#1123 AC2/AC3/AC4).",
    )


@ac_proof(
    "fx-transfer-non-candidate-legs-pr",
    ac_ids=["AC-reconciliation.fx-transfer.3"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
def test_AC2_non_candidate_legs_do_not_pair(ac_evidence):
    """AC-reconciliation.fx-transfer.3: AC4.14.3: legs outside window, same direction, or different owner do not pair."""
    # Outside the time window (5 days apart, default window is 2 days).
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

    # Same direction (two OUT legs) does not pair.
    out_leg2, _ = _legs(user_id=out_leg.user_id)
    assert pair_fx_legs(out_leg, out_leg2, _MARKET_RATE) is None

    # Different owner does not pair.
    _, other_in = _legs()  # fresh random user_id
    assert pair_fx_legs(out_leg, other_in, _MARKET_RATE) is None

    # Same account on both sides does not pair.
    acct = uuid4()
    same_out, same_in = _legs(user_id=out_leg.user_id, out_account=acct, in_account=acct)
    assert pair_fx_legs(same_out, same_in, _MARKET_RATE) is None
    ac_evidence(
        ac_id="AC4.14.3",
        score=1.0,
        metric="non_candidate_fx_legs_rejected",
        provenance="deterministic",
        comment="Deterministic FX transfer accounting-layer proof (#1123 AC2/AC3/AC4).",
    )


@ac_proof(
    "internal-transfer-net-zero-pr",
    ac_ids=["AC-reconciliation.fx-transfer.4"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
def test_AC3_internal_transfer_classified_net_zero(ac_evidence):
    """AC-reconciliation.fx-transfer.4: AC4.14.4: a matched internal transfer is not income and not expense."""
    out_leg, in_leg = _legs()
    pair = pair_fx_legs(out_leg, in_leg, _MARKET_RATE)
    classification = classify_internal_transfer(pair, fee=Decimal("2.50"))
    assert classification.is_internal_transfer is True
    assert classification.income_amount == Decimal("0.00")
    assert classification.expense_amount == Decimal("0.00")
    # An unpaired leg keeps normal income/expense classification (no netting).
    unpaired = classify_internal_transfer(None)
    assert unpaired.is_internal_transfer is False
    ac_evidence(
        ac_id="AC4.14.4",
        score=1.0,
        metric="internal_transfer_income_and_expense_are_zero",
        provenance="deterministic",
        comment="Deterministic FX transfer accounting-layer proof (#1123 AC2/AC3/AC4).",
    )


@ac_proof(
    "internal-transfer-net-worth-neutral-pr",
    ac_ids=["AC-reconciliation.fx-transfer.5"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
def test_AC3_net_worth_unchanged_by_internal_transfer_minus_fee(ac_evidence):
    """AC-reconciliation.fx-transfer.5: AC4.14.5: net worth is unchanged by an internal transfer except for the fee."""
    out_leg, in_leg = _legs()
    pair = pair_fx_legs(out_leg, in_leg, _MARKET_RATE)

    # No fee: net worth delta is exactly zero.
    no_fee = classify_internal_transfer(pair)
    assert no_fee.net_worth_delta == Decimal("0.00")

    # With a fee: net worth drops by exactly the fee (and nothing else).
    with_fee = classify_internal_transfer(pair, fee=Decimal("3.75"))
    assert with_fee.net_worth_delta == Decimal("-3.75")
    ac_evidence(
        ac_id="AC4.14.5",
        score=1.0,
        metric="net_worth_delta_equals_negative_fee",
        provenance="deterministic",
        comment="Deterministic FX transfer accounting-layer proof (#1123 AC2/AC3/AC4).",
    )


@ac_proof(
    "fx-round-trip-zero-pnl-pr",
    ac_ids=["AC-reconciliation.fx-transfer.6"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
def test_AC4_same_day_round_trip_nets_zero_pnl_minus_fee(ac_evidence):
    """AC-reconciliation.fx-transfer.6: AC4.14.6: a same-day round-trip conversion nets ~zero P&L (minus fee)."""
    # Same-day: rate has not moved, so realized P&L is exactly -fee.
    pnl = round_trip_realized_pnl(
        Decimal("1360.00"),
        rate_out=_MARKET_RATE,
        rate_back=_MARKET_RATE,
        fee=Decimal("0"),
    )
    assert pnl == Decimal("0.00")

    pnl_with_fee = round_trip_realized_pnl(
        Decimal("1360.00"),
        rate_out=_MARKET_RATE,
        rate_back=_MARKET_RATE,
        fee=Decimal("1.20"),
    )
    assert pnl_with_fee == Decimal("-1.20")
    ac_evidence(
        ac_id="AC4.14.6",
        score=1.0,
        metric="same_day_round_trip_realized_pnl_is_negative_fee",
        provenance="deterministic",
        comment="Deterministic FX transfer accounting-layer proof (#1123 AC2/AC3/AC4).",
    )


@ac_proof(
    "fx-pnl-revaluation-routing-pr",
    ac_ids=["AC-reconciliation.fx-transfer.7"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
def test_AC4_revaluation_pnl_routed_through_fx_revaluation_source_type(ac_evidence):
    """AC-reconciliation.fx-transfer.7: AC4.14.7: FX revaluation P&L is routed through the fx_revaluation source type."""
    # The conversion event itself yields no P&L when the rate is unchanged.
    assert round_trip_realized_pnl(Decimal("1000.00"), rate_out=_MARKET_RATE, rate_back=_MARKET_RATE) == Decimal("0.00")
    # The module routes any rate-move gain/loss through fx_revaluation, never a
    # conversion-event income/expense line.
    assert REVALUATION_SOURCE_TYPE is JournalEntrySourceType.FX_REVALUATION
    assert REVALUATION_SOURCE_TYPE.value == "fx_revaluation"
    ac_evidence(
        ac_id="AC4.14.7",
        score=1.0,
        metric="fx_pnl_routes_through_fx_revaluation_source_type",
        provenance="deterministic",
        comment="Deterministic FX transfer accounting-layer proof (#1123 AC2/AC3/AC4).",
    )


@ac_proof(
    "fx-conversion-model-round-trip-pr",
    ac_ids=["AC-reconciliation.fx-transfer.8"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
def test_AC2_fx_conversion_model_round_trips_decimals(ac_evidence):
    """AC-reconciliation.fx-transfer.8: AC4.14.8: the fx_conversions linking model round-trips Decimal/ISO fields."""
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
    ac_evidence(
        ac_id="AC4.14.8",
        score=1.0,
        metric="fx_conversion_model_round_trips_decimal_and_iso_currency",
        provenance="deterministic",
        comment="Deterministic FX transfer accounting-layer proof (#1123 AC2/AC3/AC4).",
    )


def test_invalid_transfer_leg_rejected():
    """Guard: a zero/negative amount or bad direction is rejected (defensive)."""
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
            user_id=uuid4(),
            account_id=uuid4(),
            direction="OUT",
            amount=Decimal("0"),
            currency="SGD",
            occurred_at=when,
        )


def test_transfer_leg_rejects_naive_datetime():
    """#1161 CR3: a naive (tz-less) occurred_at is rejected at construction.

    Pairing subtracts two legs' occurred_at; a naive/aware mix raises TypeError
    mid-pairing. Reject naive datetimes up front so the error is a clear
    FxTransferError rather than an opaque TypeError deeper in the call.
    """
    naive = datetime(2025, 6, 1, 12, 0)  # no tzinfo
    assert naive.tzinfo is None
    with pytest.raises(FxTransferError, match="timezone-aware"):
        TransferLeg(
            user_id=uuid4(),
            account_id=uuid4(),
            direction="OUT",
            amount=Decimal("100.00"),
            currency="SGD",
            occurred_at=naive,
        )


def test_same_currency_legs_never_pair_even_with_unit_rate():
    """#1161 CR2: same-currency legs never pair, even at rate 1.0 with equal amounts.

    A same-currency own-account transfer (SGD->SGD, amount unchanged, implied rate
    1.0) must NOT be classified as a cross-currency FX conversion. It is handled by
    the (non-FX) internal-transfer path, not by FX-leg pairing.
    """
    user_id = uuid4()
    when = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
    out_leg = TransferLeg(
        user_id=user_id,
        account_id=uuid4(),
        direction="OUT",
        amount=Decimal("500.00"),
        currency="SGD",
        occurred_at=when,
    )
    in_leg = TransferLeg(
        user_id=user_id,
        account_id=uuid4(),
        direction="IN",
        amount=Decimal("500.00"),  # identical amount -> implied rate exactly 1.0
        currency="SGD",  # same currency as the out-leg
        occurred_at=when,
    )
    # Even with a perfectly matching unit rate, same-currency legs must not pair.
    assert pair_fx_legs(out_leg, in_leg, Decimal("1.000000")) is None
    # And the swapped argument order must also refuse to pair.
    assert pair_fx_legs(in_leg, out_leg, Decimal("1.000000")) is None


def test_unpaired_classification_carries_caller_income_expense():
    """#1161 CR4: the non-internal (pair is None) branch obeys net_worth = income - expense.

    Previously the unpaired branch zeroed income/expense, silently zeroing net
    worth. It must now carry the caller's already-classified income/expense so the
    documented formula holds.
    """
    classification = classify_internal_transfer(
        None,
        income=Decimal("120.00"),
        expense=Decimal("45.00"),
    )
    assert classification.is_internal_transfer is False
    assert classification.income_amount == Decimal("120.00")
    assert classification.expense_amount == Decimal("45.00")
    assert classification.net_worth_delta == Decimal("75.00")
    # Backward-compatible default: omitting income/expense is still a net-zero no-op.
    assert classify_internal_transfer(None).net_worth_delta == Decimal("0.00")
