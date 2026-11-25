from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.reconciliation.extension.fx_transfer import (
    REVALUATION_SOURCE_TYPE,
    FxTransferError,
    TransferLeg,
    build_fx_conversion,
    classify_internal_transfer,
    pair_fx_legs,
    round_trip_realized_pnl,
)
from src.reconciliation.extension.fx_transfer_discovery import discover_fx_conversions

_OUT_AMOUNT = Decimal("1360.00")
_IN_AMOUNT = Decimal("1000.00")
_MARKET_RATE = Decimal("1.360000")
_WHEN = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)


def _legs(*, user_id=None, out_account=None, in_account=None, when=_WHEN, in_currency="usd"):
    user_id = user_id or uuid4()
    return (
        TransferLeg(
            user_id=user_id,
            account_id=out_account or uuid4(),
            direction="OUT",
            amount=_OUT_AMOUNT,
            currency="sgd",
            occurred_at=when,
        ),
        TransferLeg(
            user_id=user_id,
            account_id=in_account or uuid4(),
            direction="IN",
            amount=_IN_AMOUNT,
            currency=in_currency,
            occurred_at=when,
        ),
    )


def test_fx_pair_classify_round_trip_and_conversion() -> None:
    out_leg, in_leg = _legs()
    pair = pair_fx_legs(out_leg, in_leg, _MARKET_RATE)
    swapped = pair_fx_legs(in_leg, out_leg, _MARKET_RATE)
    assert pair is not None and swapped is not None and swapped.out_leg.account_id == out_leg.account_id
    assert (pair.out_leg.currency, pair.in_leg.currency, pair.implied_rate) == ("SGD", "USD", _OUT_AMOUNT / _IN_AMOUNT)
    assert pair.rate_deviation <= Decimal("0.005")
    assert (
        pair_fx_legs(out_leg, in_leg, Decimal("1.364000")) is not None
        and pair_fx_legs(out_leg, in_leg, Decimal("1.500000")) is None
    )

    classified = classify_internal_transfer(pair, fee=Decimal("2.50"))
    assert classified.is_internal_transfer is True and classified.income_amount == Decimal("0.00")
    assert classify_internal_transfer(pair).net_worth_delta == Decimal("0.00")
    assert classify_internal_transfer(pair, fee=Decimal("3.75")).net_worth_delta == Decimal("-3.75")
    assert classify_internal_transfer(
        None, income=Decimal("120.00"), expense=Decimal("45.00")
    ).net_worth_delta == Decimal("75.00")
    assert classify_internal_transfer(None).net_worth_delta == Decimal("0.00")

    assert round_trip_realized_pnl(Decimal("1360.00"), rate_out=_MARKET_RATE, rate_back=_MARKET_RATE) == Decimal("0.00")
    assert round_trip_realized_pnl(
        Decimal("1360.00"), rate_out=_MARKET_RATE, rate_back=_MARKET_RATE, fee=Decimal("1.20")
    ) == Decimal("-1.20")
    assert (
        REVALUATION_SOURCE_TYPE is JournalEntrySourceType.FX_REVALUATION
        and REVALUATION_SOURCE_TYPE.value == "fx_revaluation"
    )

    conv = build_fx_conversion(pair, fee=Decimal("2.50"), fee_currency="sgd")
    assert (
        conv.amount_from,
        conv.amount_to,
        conv.rate,
        conv.currency_from,
        conv.currency_to,
        conv.fee,
        conv.fee_currency,
        conv.from_account_id,
        conv.to_account_id,
        conv.conversion_date,
    ) == (
        Decimal("1360.00"),
        Decimal("1000.00"),
        _MARKET_RATE,
        "SGD",
        "USD",
        Decimal("2.50"),
        "SGD",
        out_leg.account_id,
        in_leg.account_id,
        out_leg.occurred_at.date(),
    )


def test_non_candidate_and_invalid_transfer_legs() -> None:
    out_leg, in_leg = _legs()
    acct = uuid4()
    same_out, same_in = _legs(user_id=out_leg.user_id, out_account=acct, in_account=acct)
    same_ccy_out, same_ccy_in = _legs(user_id=out_leg.user_id, in_currency="SGD")
    other_out, _ = _legs(user_id=out_leg.user_id)
    _, other_user_in = _legs()
    far_in = TransferLeg(
        user_id=out_leg.user_id,
        account_id=in_leg.account_id,
        direction="IN",
        amount=_IN_AMOUNT,
        currency="USD",
        occurred_at=datetime(2025, 6, 6, 12, 0, tzinfo=UTC),
    )
    for left, right in (
        (out_leg, far_in),
        (out_leg, other_out),
        (out_leg, other_user_in),
        (same_out, same_in),
        (same_ccy_out, same_ccy_in),
        (same_ccy_in, same_ccy_out),
    ):
        assert pair_fx_legs(left, right, _MARKET_RATE) is None

    for direction, amount, occurred_at in (
        ("SIDEWAYS", Decimal("1.00"), _WHEN),
        ("OUT", Decimal("0"), _WHEN),
        ("OUT", Decimal("100.00"), datetime(2025, 6, 1, 12, 0)),
    ):
        with pytest.raises(FxTransferError):
            TransferLeg(
                user_id=uuid4(),
                account_id=uuid4(),
                direction=direction,
                amount=amount,
                currency="SGD",
                occurred_at=occurred_at,
            )


async def _rate_resolver(base: str, quote: str, _on_date: date) -> Decimal | None:
    b, q = base.upper(), quote.upper()
    if b == q:
        return Decimal("1")
    return (
        _MARKET_RATE if (b, q) == ("USD", "SGD") else Decimal("1") / _MARKET_RATE if (b, q) == ("SGD", "USD") else None
    )


async def _seed_leg(
    db: AsyncSession, user_id, debit_acc: Account, credit_acc: Account, amount: Decimal, currency: str
) -> JournalEntry:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2025, 6, 15),
        memo="seed",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    fx = None if currency == "SGD" else _MARKET_RATE
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=debit_acc.id,
                direction=Direction.DEBIT,
                amount=amount,
                currency=currency,
                fx_rate=fx,
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=credit_acc.id,
                direction=Direction.CREDIT,
                amount=amount,
                currency=currency,
                fx_rate=fx,
            ),
        ]
    )
    await db.flush()
    return entry


@pytest.mark.parametrize("ambiguous", [False, True])
async def test_discover_fx_conversions(db: AsyncSession, test_user, ambiguous: bool) -> None:
    uid = test_user.id
    sgd_bank = Account(user_id=uid, name="SGD Bank", type=AccountType.ASSET, currency="SGD")
    usd_a = Account(user_id=uid, name="USD Bank A", type=AccountType.ASSET, currency="USD")
    usd_b = Account(user_id=uid, name="USD Bank B", type=AccountType.ASSET, currency="USD")
    t_out = Account(user_id=uid, name="Out", type=AccountType.EXPENSE, currency="SGD")
    t_in = Account(user_id=uid, name="In", type=AccountType.INCOME, currency="USD")
    db.add_all([sgd_bank, usd_a, usd_b, t_out, t_in])
    await db.flush()
    out_entry = await _seed_leg(db, uid, t_out, sgd_bank, _OUT_AMOUNT, "SGD")
    in_entry = await _seed_leg(db, uid, usd_a, t_in, _IN_AMOUNT, "USD")
    if ambiguous:
        await _seed_leg(db, uid, usd_b, t_in, _IN_AMOUNT, "USD")
    await db.commit()

    discovered = await discover_fx_conversions(db, uid, date(2025, 6, 30), _rate_resolver, start_date=date(2025, 6, 1))
    if ambiguous:
        assert discovered == []
    else:
        assert len(discovered) == 1
        conv = discovered[0].conversion
        assert (conv.from_account_id, conv.to_account_id, conv.from_journal_entry_id, conv.to_journal_entry_id) == (
            sgd_bank.id,
            usd_a.id,
            out_entry.id,
            in_entry.id,
        )
        assert discovered[0].pair.implied_rate == Decimal("1.36")
