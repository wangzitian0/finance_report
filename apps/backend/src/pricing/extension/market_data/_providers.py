"""Provider HTTP fetch + parsing + validated fetch + sync specs."""

from __future__ import annotations

import csv
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from typing import Any, TypeVar
from urllib.parse import quote

import httpx

import src.config
from src.pricing.extension.market_data._base import (
    _STOOQ_DAILY_URL,
    _YAHOO_FX_CHART_URL,
    _YAHOO_STOCK_CHART_URL,
    logger,
)
from src.pricing.extension.market_data._store import (
    _latest_fx_rate_date_for_scope,
    _latest_stock_price_date,
    _persist_fx_rate,
    _persist_stock_price,
    _stored_fx_rate_dates_for_scope,
    _stored_stock_price_dates,
)
from src.pricing.extension.market_data._types import (
    FxRateObservation,
    StockPriceObservation,
    ValidatedMarketObservation,
    ValidatedMarketObservationSeries,
    _MarketSyncSpec,
)
from src.pricing.extension.market_data._util import (
    _date_to_epoch,
    _fx_scope,
    _looks_like_ticker,
    _normalize_currency,
    _normalize_symbol,
    _observation_date,
    _parse_sync_fx_scope,
    _quantize_price,
    _quantize_rate,
    _select_validated_observation,
    _select_validated_observation_series,
    _stock_scope,
    _stooq_fx_symbol,
    _stooq_stock_symbol,
    _yahoo_stock_symbol,
)

settings = src.config.settings


_ObsT = TypeVar("_ObsT")


async def _latest_in_window(  # noqa: UP047
    fetcher: Callable[[date, date], Awaitable[Sequence[_ObsT] | None]],
    requested_date: date,
    date_attr: str,
) -> _ObsT | None:
    items = await fetcher(requested_date - timedelta(days=7), requested_date)
    return max(items, key=lambda item: getattr(item, date_attr), default=None) if items is not None else None


async def _fetch_validated_fx_rate_series_for_scope(
    scope: tuple[str, str], start_date: date, end_date: date
) -> ValidatedMarketObservationSeries:
    return await _fetch_validated_fx_rate_series(scope[0], scope[1], start_date, end_date)


async def _fetch_validated_fx_rate_series(
    base_currency: str, quote_currency: str, start_date: date, end_date: date
) -> ValidatedMarketObservationSeries:
    primary = await _fetch_yahoo_or_derived_fx_rate_series(base_currency, quote_currency, start_date, end_date)
    secondary = await _fetch_stooq_fx_rate_series(base_currency, quote_currency, start_date, end_date)
    return _select_validated_observation_series(
        asset=f"{base_currency}/{quote_currency}",
        start_date=start_date,
        end_date=end_date,
        primary=primary,
        secondary=secondary,
        provider_success=primary is not None or secondary is not None,
    )


async def _fetch_validated_stock_price_series(
    symbol: str, start_date: date, end_date: date
) -> ValidatedMarketObservationSeries:
    normalized = _normalize_symbol(symbol)
    primary = await _fetch_yahoo_stock_price_series(normalized, start_date, end_date)
    secondary = await _fetch_stooq_stock_price_series(normalized, start_date, end_date)
    return _select_validated_observation_series(
        asset=normalized,
        start_date=start_date,
        end_date=end_date,
        primary=primary,
        secondary=secondary,
        provider_success=primary is not None or secondary is not None,
    )


_FX_SYNC_SPEC = _MarketSyncSpec(
    kind="fx",
    parse_scope=_parse_sync_fx_scope,
    scope_name=lambda scope: _fx_scope(scope[0], scope[1]),
    latest_date=_latest_fx_rate_date_for_scope,
    stored_dates=_stored_fx_rate_dates_for_scope,
    fetch_series=lambda scope, start_date, end_date: _fetch_validated_fx_rate_series_for_scope(
        scope, start_date, end_date
    ),
    persist_observation=_persist_fx_rate,  # type: ignore[arg-type]
    observation_date=_observation_date,
    observation_matches_scope=lambda obs, scope: (
        isinstance(obs, FxRateObservation)
        and _normalize_currency(obs.base_currency) == scope[0]
        and _normalize_currency(obs.quote_currency) == scope[1]
    ),
)

_STOCK_SYNC_SPEC = _MarketSyncSpec(
    kind="stock",
    parse_scope=lambda symbol: _normalize_symbol(symbol) or None,
    scope_name=_stock_scope,
    latest_date=_latest_stock_price_date,
    stored_dates=_stored_stock_price_dates,
    fetch_series=lambda symbol, start_date, end_date: _fetch_validated_stock_price_series(
        symbol, start_date, end_date
    ),
    persist_observation=_persist_stock_price,  # type: ignore[arg-type]
    observation_date=_observation_date,
    observation_matches_scope=lambda obs, scope: (
        isinstance(obs, StockPriceObservation) and _normalize_symbol(obs.symbol) == scope
    ),
)


async def _fetch_validated_fx_rate(
    base_currency: str, quote_currency: str, requested_date: date
) -> ValidatedMarketObservation:
    return _select_validated_observation(
        asset=f"{base_currency}/{quote_currency}",
        observed_date=requested_date,
        primary=await _fetch_yahoo_or_derived_fx_rate(base_currency, quote_currency, requested_date),
        secondary=await _fetch_stooq_fx_rate(base_currency, quote_currency, requested_date),
    )


async def _fetch_validated_stock_price(symbol: str, requested_date: date) -> ValidatedMarketObservation:
    normalized = _normalize_symbol(symbol)
    return _select_validated_observation(
        asset=normalized,
        observed_date=requested_date,
        primary=await _fetch_yahoo_stock_price(normalized, requested_date),
        secondary=await _fetch_stooq_stock_price(normalized, requested_date),
    )


async def _fetch_yahoo_or_derived_fx_rate(
    base_currency: str, quote_currency: str, requested_date: date
) -> FxRateObservation | None:
    if (direct := await _fetch_yahoo_fx_rate(base_currency, quote_currency, requested_date)) is not None:
        return direct
    if (inverse := await _fetch_yahoo_fx_rate(quote_currency, base_currency, requested_date)) is not None:
        return FxRateObservation(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=_quantize_rate(Decimal("1") / inverse.rate),
            rate_date=inverse.rate_date,
            source="yahoo_finance:inverse",
        )
    bridge = _normalize_currency(settings.market_data_fx_bridge_currency)
    if bridge in {base_currency, quote_currency}:
        return None
    b2br = await _fetch_yahoo_fx_rate(base_currency, bridge, requested_date)
    br2q = await _fetch_yahoo_fx_rate(bridge, quote_currency, requested_date)
    if b2br is None or br2q is None:
        return None
    return FxRateObservation(
        base_currency=base_currency,
        quote_currency=quote_currency,
        rate=_quantize_rate(b2br.rate * br2q.rate),
        rate_date=max(b2br.rate_date, br2q.rate_date),
        source=f"yahoo_finance:bridge:{bridge}",
    )


async def _fetch_yahoo_or_derived_fx_rate_series(
    base_currency: str, quote_currency: str, start_date: date, end_date: date
) -> list[FxRateObservation] | None:
    direct = await _fetch_yahoo_fx_rate_series(base_currency, quote_currency, start_date, end_date)
    if direct:
        return direct
    direct_failed = direct is None
    inverse = await _fetch_yahoo_fx_rate_series(quote_currency, base_currency, start_date, end_date)
    if inverse:
        return [
            FxRateObservation(
                base_currency=base_currency,
                quote_currency=quote_currency,
                rate=_quantize_rate(Decimal("1") / obs.rate),
                rate_date=obs.rate_date,
                source="yahoo_finance:inverse",
            )
            for obs in inverse
            if obs.rate != Decimal("0")
        ]
    bridge = _normalize_currency(settings.market_data_fx_bridge_currency)
    if bridge in {base_currency, quote_currency}:
        return None if direct_failed and inverse is None else []
    b2br = await _fetch_yahoo_fx_rate_series(base_currency, bridge, start_date, end_date)
    br2q = await _fetch_yahoo_fx_rate_series(bridge, quote_currency, start_date, end_date)
    if b2br is None and br2q is None and direct_failed and inverse is None:
        return None
    if not b2br or not br2q:
        return []
    by_date = {obs.rate_date: obs for obs in br2q}
    return [
        FxRateObservation(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=_quantize_rate(b_obs.rate * q_obs.rate),
            rate_date=b_obs.rate_date,
            source=f"yahoo_finance:bridge:{bridge}",
        )
        for b_obs in b2br
        if (q_obs := by_date.get(b_obs.rate_date)) is not None
    ]


async def _fetch_provider_response(
    url: str, params: dict[str, str], *, failure_message: str, log_context: dict[str, str]
) -> httpx.Response | None:
    try:
        async with httpx.AsyncClient(
            timeout=settings.market_data_yahoo_timeout_seconds,
            headers={"User-Agent": "finance-report-audit/1.0"},
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response
    except httpx.HTTPError as exc:
        logger.warning(failure_message, **log_context, error=str(exc))
        return None


def _yahoo_chart_params(start_date: date, end_date: date) -> dict[str, str]:
    return {
        "period1": str(_date_to_epoch(start_date)),
        "period2": str(_date_to_epoch(end_date + timedelta(days=1))),
        "interval": "1d",
    }


def _stooq_daily_params(symbol: str, start_date: date, end_date: date) -> dict[str, str]:
    return {"s": symbol, "d1": start_date.strftime("%Y%m%d"), "d2": end_date.strftime("%Y%m%d"), "i": "d"}


def _parse_yahoo_close_rows(
    payload: dict[str, Any], *, start_date: date, end_date: date
) -> tuple[str, list[tuple[date, Decimal]]]:
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return "USD", []
    result = results[0]
    currency = _normalize_currency((result.get("meta") or {}).get("currency") or "USD")
    timestamps = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    rows = [
        (obs_date, Decimal(str(close)))
        for ts, close in zip(timestamps, closes, strict=False)
        if close is not None and start_date <= (obs_date := datetime.fromtimestamp(int(ts), UTC).date()) <= end_date
    ]
    return currency, rows


def _parse_yahoo_fx_response_series(
    payload: dict[str, Any], base_currency: str, quote_currency: str, start_date: date, end_date: date
) -> list[FxRateObservation]:
    _, rows = _parse_yahoo_close_rows(payload, start_date=start_date, end_date=end_date)
    return [
        FxRateObservation(base_currency, quote_currency, _quantize_rate(r), d, "yahoo_finance") for d, r in rows
    ]


def _parse_yahoo_stock_response_series(
    payload: dict[str, Any], symbol: str, start_date: date, end_date: date
) -> list[StockPriceObservation]:
    currency, rows = _parse_yahoo_close_rows(payload, start_date=start_date, end_date=end_date)
    return [StockPriceObservation(symbol, _quantize_price(p), currency, d, "yahoo_finance") for d, p in rows]


def _parse_stooq_close_rows(payload: str, *, start_date: date, end_date: date) -> list[tuple[date, Decimal]]:
    return [
        (obs_date, Decimal(close))
        for row in csv.DictReader(StringIO(payload))
        if (close := row.get("Close"))
        and close != "N/D"
        and (row_date := row.get("Date"))
        and start_date <= (obs_date := date.fromisoformat(row_date)) <= end_date
    ]


def _parse_stooq_fx_csv_series(
    payload: str, base_currency: str, quote_currency: str, start_date: date, end_date: date
) -> list[FxRateObservation]:
    return [
        FxRateObservation(base_currency, quote_currency, _quantize_rate(r), d, "stooq")
        for d, r in _parse_stooq_close_rows(payload, start_date=start_date, end_date=end_date)
    ]


def _parse_stooq_stock_csv_series(
    payload: str, symbol: str, start_date: date, end_date: date
) -> list[StockPriceObservation]:
    return [
        StockPriceObservation(symbol, _quantize_price(p), "USD", d, "stooq")
        for d, p in _parse_stooq_close_rows(payload, start_date=start_date, end_date=end_date)
    ]


async def _fetch_yahoo_fx_rate(base_currency: str, quote_currency: str, requested_date: date) -> FxRateObservation | None:
    return await _latest_in_window(
        lambda s, e: _fetch_yahoo_fx_rate_series(base_currency, quote_currency, s, e), requested_date, "rate_date"
    )


async def _fetch_yahoo_fx_rate_series(
    base_currency: str, quote_currency: str, start_date: date, end_date: date
) -> list[FxRateObservation] | None:
    url = _YAHOO_FX_CHART_URL.format(symbol=quote(f"{base_currency}{quote_currency}", safe=""))
    response = await _fetch_provider_response(
        url,
        _yahoo_chart_params(start_date, end_date),
        failure_message="Yahoo Finance FX range fetch failed",
        log_context={
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    return (
        None
        if response is None
        else _parse_yahoo_fx_response_series(response.json(), base_currency, quote_currency, start_date, end_date)
    )


async def _fetch_yahoo_stock_price(symbol: str, requested_date: date) -> StockPriceObservation | None:
    normalized = _normalize_symbol(symbol)
    return await _latest_in_window(
        lambda s, e: _fetch_yahoo_stock_price_series(normalized, s, e), requested_date, "price_date"
    )


async def _fetch_yahoo_stock_price_series(
    symbol: str, start_date: date, end_date: date
) -> list[StockPriceObservation] | None:
    normalized = _normalize_symbol(symbol)
    if not _looks_like_ticker(normalized):
        logger.debug(
            "Skipping Yahoo stock fetch for non-ticker identifier",
            symbol=normalized,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        return None
    url = _YAHOO_STOCK_CHART_URL.format(symbol=quote(_yahoo_stock_symbol(normalized), safe=".-"))
    response = await _fetch_provider_response(
        url,
        _yahoo_chart_params(start_date, end_date),
        failure_message="Yahoo Finance stock range fetch failed",
        log_context={"symbol": normalized, "start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
    )
    return None if response is None else _parse_yahoo_stock_response_series(response.json(), normalized, start_date, end_date)


async def _fetch_stooq_fx_rate(base_currency: str, quote_currency: str, requested_date: date) -> FxRateObservation | None:
    return await _latest_in_window(
        lambda s, e: _fetch_stooq_fx_rate_series(base_currency, quote_currency, s, e), requested_date, "rate_date"
    )


async def _fetch_stooq_fx_rate_series(
    base_currency: str, quote_currency: str, start_date: date, end_date: date
) -> list[FxRateObservation] | None:
    response = await _fetch_provider_response(
        _STOOQ_DAILY_URL,
        _stooq_daily_params(_stooq_fx_symbol(base_currency, quote_currency), start_date, end_date),
        failure_message="Stooq FX range fetch failed",
        log_context={
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    return None if response is None else _parse_stooq_fx_csv_series(response.text, base_currency, quote_currency, start_date, end_date)


async def _fetch_stooq_stock_price(symbol: str, requested_date: date) -> StockPriceObservation | None:
    normalized = _normalize_symbol(symbol)
    return await _latest_in_window(
        lambda s, e: _fetch_stooq_stock_price_series(normalized, s, e), requested_date, "price_date"
    )


async def _fetch_stooq_stock_price_series(
    symbol: str, start_date: date, end_date: date
) -> list[StockPriceObservation] | None:
    normalized = _normalize_symbol(symbol)
    response = await _fetch_provider_response(
        _STOOQ_DAILY_URL,
        _stooq_daily_params(_stooq_stock_symbol(normalized), start_date, end_date),
        failure_message="Stooq stock range fetch failed",
        log_context={"symbol": normalized, "start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
    )
    return None if response is None else _parse_stooq_stock_csv_series(response.text, normalized, start_date, end_date)
