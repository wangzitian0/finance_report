from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import ExchangeRate, Money
from src.pricing import FxWarning, PrefetchedFxRates, PricingError
from src.pricing.base.errors import NoObservationError
from src.pricing.extension import fx as fx_module
from src.pricing.extension.fx import convert_amount, convert_money, get_average_rate, get_exchange_rate, get_exchange_rate_series
from src.pricing.orm.market_data import FxRate

pytestmark = pytest.mark.asyncio


async def _add_rates(db: AsyncSession, *rows: tuple[str, str, str, date, str]) -> None:
    db.add_all([FxRate(base_currency=b, quote_currency=q, rate=Decimal(r), rate_date=d, source=s) for b, q, r, d, s in rows])
    await db.commit()


async def test_spot_rate_and_convert_happy_and_error_paths(db: AsyncSession):
    assert (
        await get_exchange_rate(db, "sgd", "SGD", date(2026, 6, 1)),
        await convert_amount(db, Decimal("100"), "SGD", "sgd", date(2026, 6, 1)),
        await get_average_rate(db, "SGD", "sgd", date(2026, 1, 1), date(2026, 6, 1)),
    ) == (Decimal("1"), Decimal("100"), Decimal("1"))
    for call in (
        get_exchange_rate(db, "USD", "SGD", date(2026, 6, 1)),
        get_exchange_rate(db, "HKD", "SGD", date(2026, 6, 30), lazy_load=True),
        convert_amount(db, Decimal("100"), "USD", "SGD", date(2026, 6, 1)),
    ):
        with pytest.raises(NoObservationError):
            await call
    for call in (
        get_average_rate(db, "USD", "SGD", date(2026, 6, 1), date(2026, 1, 1)),
        convert_amount(db, Decimal("10.00"), "USD", "SGD", date(2026, 6, 30), average_start=date(2026, 6, 1), average_end=date(2026, 6, 30)),
    ):
        with pytest.raises(PricingError):
            await call
    await _add_rates(
        db,
        ("USD", "SGD", "1.30", date(2026, 1, 1), "test"),
        ("USD", "SGD", "1.35", date(2026, 6, 1), "test"),
        ("SGD", "HKD", "5.800000", date(2026, 6, 30), "test"),
    )
    lazy_hkd = await get_exchange_rate(db, "HKD", "SGD", date(2026, 6, 30), lazy_load=True)
    derived = (await db.execute(select(FxRate).where(FxRate.base_currency == "HKD", FxRate.quote_currency == "SGD", FxRate.rate_date == date(2026, 6, 30)))).scalar_one()
    assert (
        await get_exchange_rate(db, "USD", "SGD", date(2026, 6, 15)),
        await convert_amount(db, Decimal("100"), "USD", "SGD", date(2026, 6, 15)),
        await convert_money(db, Money(Decimal("100"), "USD"), "SGD", date(2026, 6, 15)),
        (lazy_hkd, derived.rate, derived.source),
        await convert_money(db, Money(Decimal("100"), "HKD"), "SGD", date(2026, 6, 30), lazy_load=True),
    ) == (
        Decimal("1.35"),
        Decimal("135.00"),
        Money(Decimal("135.00"), "SGD"),
        (Decimal("0.172414"), Decimal("0.172414"), "derived:inverse:SGD/HKD"),
        Money(Decimal("17.24"), "SGD"),
    )


async def test_average_rate_warnings_and_convert_windows(db: AsyncSession):
    await _add_rates(
        db,
        ("USD", "SGD", "1.20", date(2026, 6, 1), "test"),
        ("USD", "SGD", "1.40", date(2026, 6, 15), "test"),
        ("USD", "SGD", "0.10", date(2026, 1, 1), "test"),
        ("EUR", "SGD", "1.50", date(2025, 12, 31), "test"),
    )
    in_range_w: list[FxWarning] = []
    fb_w: list[FxWarning] = []
    money_w: list[FxWarning] = []
    avg_usd = await get_average_rate(db, "USD", "SGD", date(2026, 6, 1), date(2026, 6, 30), fx_warnings=in_range_w)
    conv_usd = await convert_amount(db, Decimal("10.00"), "USD", "SGD", date(2026, 6, 15), average_start=date(2026, 6, 1), average_end=date(2026, 6, 30))
    fb_eur = await get_average_rate(db, "EUR", "SGD", date(2026, 1, 1), date(2026, 1, 31), fx_warnings=fb_w)
    await get_average_rate(db, "EUR", "SGD", date(2026, 1, 1), date(2026, 1, 31), fx_warnings=fb_w)
    fb_money = await convert_money(db, Money(Decimal("100"), "EUR"), "SGD", date(2026, 1, 31), average_start=date(2026, 1, 1), average_end=date(2026, 1, 31), fx_warnings=money_w)
    assert (
        (avg_usd, in_range_w, conv_usd),
        (fb_eur, fb_w, len(fb_w)),
        (fb_money, [w["type"] for w in money_w]),
    ) == (
        (Decimal("1.30"), [], Decimal("13.00")),
        (Decimal("1.50"), [{"type": "average_rate_fallback", "base_currency": "EUR", "quote_currency": "SGD", "start_date": "2026-01-01", "end_date": "2026-01-31"}], 1),
        (Money(Decimal("150.00"), "SGD"), ["average_rate_fallback"]),
    )


async def test_AC12_31_2_convert_amount_money_boundary(db: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    await _add_rates(db, ("USD", "SGD", "1.200000", date(2026, 1, 1), "test"))
    calls: list[tuple[Money, ExchangeRate]] = []
    monkeypatch.setattr(fx_module, "_money_convert", lambda m, r: (calls.append((m, r)), Money(Decimal("120.00"), "SGD"))[1])
    res = await convert_amount(db, Decimal("100.00"), "USD", "SGD", date(2026, 1, 1))
    assert (res, calls) == (Decimal("120.00"), [(Money(Decimal("100.00"), "USD"), ExchangeRate("USD", "SGD", Decimal("1.200000")))])

    async def fake_rate(*_a, **_kw) -> Decimal:
        return Decimal("60000.000000")

    monkeypatch.setattr(fx_module, "get_exchange_rate", fake_rate)
    with pytest.raises(PricingError, match="invalid FX conversion boundary"):
        await convert_amount(db, Decimal("0.50"), "BTC", "USD", date(2026, 1, 1))


async def test_AC_pricing_fx_2_prefetch_serves_and_errors(db: AsyncSession):
    prefetched = PrefetchedFxRates()
    await prefetched.prefetch(db, [])
    assert prefetched.get_rate("USD", "SGD", date(2026, 6, 15)) is None
    with pytest.raises(PricingError):
        await prefetched.prefetch(db, [("USD", "SGD", date(2026, 6, 15), None, None)])
    await _add_rates(db, ("USD", "SGD", "1.30", date(2026, 6, 1), "test"), ("USD", "SGD", "1.40", date(2026, 6, 15), "test"))
    await prefetched.prefetch(db, [("USD", "SGD", date(2026, 6, 15), None, None), ("USD", "SGD", date(2026, 6, 30), date(2026, 6, 1), date(2026, 6, 30))])
    assert (
        prefetched.get_rate("USD", "SGD", date(2026, 6, 15)),
        prefetched.get_rate("USD", "SGD", date(2026, 6, 30), date(2026, 6, 1), date(2026, 6, 30)),
        prefetched.get_rate("SGD", "sgd", date(2026, 6, 15)),
        prefetched.get_rate("GBP", "USD", date(2026, 6, 15)),
    ) == (Decimal("1.40"), Decimal("1.35"), Decimal("1"), None)


async def test_AC_pricing_fx_4_6_rate_series_lookup_and_inverse_non_shadowing(db: AsyncSession, monkeypatch):
    await _add_rates(
        db,
        ("SGD", "HKD", "5.800000", date(2026, 6, 1), "test"),
        ("HKD", "SGD", "0.171100", date(2026, 6, 10), "test"),
        ("HKD", "SGD", "0.173300", date(2026, 6, 20), "test"),
        ("CNY", "SGD", "0.200000", date(2025, 1, 10), "manual"),
        ("CNY", "SGD", "0.250000", date(2025, 1, 20), "manual"),
    )
    dates = [date(2026, 6, day) for day in range(1, 31)]
    without_fb = await get_exchange_rate_series(db, "HKD", "SGD", dates)
    reads = []
    orig = fx_module.SqlObservationRepository.candidates

    async def counting_candidates(self, subject, as_of, user_id=None):
        reads.append(as_of)
        return await orig(self, subject, as_of, user_id)

    monkeypatch.setattr(fx_module.SqlObservationRepository, "candidates", counting_candidates)
    covered = await get_exchange_rate_series(db, "HKD", "SGD", dates[9:])
    reads_for_covered = list(reads)
    series = await get_exchange_rate_series(db, "HKD", "SGD", dates, lazy_load=True)
    expected = {d: await get_exchange_rate(db, "HKD", "SGD", d, lazy_load=True) for d in dates}

    early = await get_exchange_rate(db, "SGD", "CNY", date(2025, 1, 15), lazy_load=True)
    later = await get_exchange_rate(db, "SGD", "CNY", date(2025, 1, 25), lazy_load=True)
    await _add_rates(db, ("CNY", "SGD", "0.500000", date(2025, 1, 28), "manual"))
    cny_series = await get_exchange_rate_series(db, "SGD", "CNY", [date(2025, 1, 15), date(2025, 1, 25), date(2025, 1, 30)], lazy_load=True)
    assert (
        sorted(without_fb),
        reads_for_covered,
        covered == without_fb,
        series == expected,
        (series[date(2026, 6, 5)], series[date(2026, 6, 15)]),
        await get_exchange_rate_series(db, "sgd", "SGD", dates[:2]),
        (early, later, cny_series),
    ) == (
        dates[9:],
        [date(2026, 6, 30)],
        True,
        True,
        (Decimal("0.172414"), Decimal("0.171100")),
        dict.fromkeys(dates[:2], Decimal("1")),
        (Decimal("5.000000"), Decimal("4.000000"), {date(2025, 1, 15): Decimal("5.000000"), date(2025, 1, 25): Decimal("4.000000"), date(2025, 1, 30): Decimal("2.000000")}),
    )


async def test_prefetch_batches_spot_series_with_bounded_sql_and_error_semantics(db: AsyncSession, db_engine):
    await _add_rates(
        db,
        ("USD", "SGD", "1.30", date(2026, 6, 1), "test"),
        ("USD", "SGD", "1.35", date(2026, 6, 10), "test"),
    )
    dates = [date(2026, 6, day) for day in range(1, 21)]
    pairs = [("USD", "SGD", d, None, None) for d in dates]

    stmts: list[str] = []

    def _capture(_conn, _cursor, statement, _params, _ctx, _many):
        stmts.append(statement)

    prefetched = PrefetchedFxRates(lazy_load=True)
    event.listen(db_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        await prefetched.prefetch(db, pairs)
    finally:
        event.remove(db_engine.sync_engine, "before_cursor_execute", _capture)

    assert len(stmts) <= 2
    for d in dates:
        expected = Decimal("1.30") if d < date(2026, 6, 10) else Decimal("1.35")
        assert prefetched.get_rate("USD", "SGD", d) == expected

    with pytest.raises(NoObservationError, match="No FX rate available for USD/SGD on 2026-05-31"):
        await prefetched.prefetch(
            db,
            [
                ("USD", "SGD", date(2026, 6, 1), None, None),
                ("USD", "SGD", date(2026, 5, 31), None, None),
            ],
        )
