"""Provider HTTP fetch + parsing + validated fetch + sync specs."""

from __future__ import annotations

import csv
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from typing import Any
from urllib.parse import quote

import httpx

from src.config import settings
from src.services.market_data._base import (
    _STOOQ_DAILY_URL,
    _YAHOO_FX_CHART_URL,
    _YAHOO_STOCK_CHART_URL,
    logger,
)
from src.services.market_data._store import (
    _latest_fx_rate_date_for_scope,
    _latest_stock_price_date,
    _persist_fx_rate,
    _persist_stock_price,
    _stored_fx_rate_dates_for_scope,
    _stored_stock_price_dates,
)
from src.services.market_data._types import (
    FxRateObservation,
    StockPriceObservation,
    ValidatedMarketObservation,
    ValidatedMarketObservationSeries,
    _MarketSyncSpec,
)
from src.services.market_data._util import (
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
)


async def _fetch_validated_fx_rate_series_for_scope(
    scope: tuple[str, str],
    start_date: date,
    end_date: date,
) -> ValidatedMarketObservationSeries:
    base, quote_currency = scope
    return await _fetch_validated_fx_rate_series(base, quote_currency, start_date, end_date)


async def _fetch_validated_fx_rate_series(
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
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
    symbol: str,
    start_date: date,
    end_date: date,
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
        scope,
        start_date,
        end_date,
    ),
    persist_observation=_persist_fx_rate,
    observation_date=_observation_date,
    observation_matches_scope=lambda observation, scope: (
        isinstance(observation, FxRateObservation)
        and _normalize_currency(observation.base_currency) == scope[0]
        and _normalize_currency(observation.quote_currency) == scope[1]
    ),
)


_STOCK_SYNC_SPEC = _MarketSyncSpec(
    kind="stock",
    parse_scope=lambda symbol: _normalize_symbol(symbol) or None,
    scope_name=_stock_scope,
    latest_date=_latest_stock_price_date,
    stored_dates=_stored_stock_price_dates,
    fetch_series=lambda scope, start_date, end_date: _fetch_validated_stock_price_series(
        scope,
        start_date,
        end_date,
    ),
    persist_observation=_persist_stock_price,
    observation_date=_observation_date,
    observation_matches_scope=lambda observation, scope: (
        isinstance(observation, StockPriceObservation) and _normalize_symbol(observation.symbol) == scope
    ),
)


async def _fetch_validated_fx_rate(
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> ValidatedMarketObservation:
    primary = await _fetch_yahoo_or_derived_fx_rate(base_currency, quote_currency, requested_date)
    secondary = await _fetch_stooq_fx_rate(base_currency, quote_currency, requested_date)
    return _select_validated_observation(
        asset=f"{base_currency}/{quote_currency}",
        observed_date=requested_date,
        primary=primary,
        secondary=secondary,
    )


async def _fetch_validated_stock_price(symbol: str, requested_date: date) -> ValidatedMarketObservation:
    normalized = _normalize_symbol(symbol)
    primary = await _fetch_yahoo_stock_price(normalized, requested_date)
    secondary = await _fetch_stooq_stock_price(normalized, requested_date)
    return _select_validated_observation(
        asset=normalized,
        observed_date=requested_date,
        primary=primary,
        secondary=secondary,
    )


async def _fetch_yahoo_or_derived_fx_rate(
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> FxRateObservation | None:
    direct = await _fetch_yahoo_fx_rate(base_currency, quote_currency, requested_date)
    if direct is not None:
        return direct

    inverse = await _fetch_yahoo_fx_rate(quote_currency, base_currency, requested_date)
    if inverse is not None:
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
    base_to_bridge = await _fetch_yahoo_fx_rate(base_currency, bridge, requested_date)
    bridge_to_quote = await _fetch_yahoo_fx_rate(bridge, quote_currency, requested_date)
    if base_to_bridge is None or bridge_to_quote is None:
        return None

    return FxRateObservation(
        base_currency=base_currency,
        quote_currency=quote_currency,
        rate=_quantize_rate(base_to_bridge.rate * bridge_to_quote.rate),
        rate_date=max(base_to_bridge.rate_date, bridge_to_quote.rate_date),
        source=f"yahoo_finance:bridge:{bridge}",
    )


async def _fetch_yahoo_or_derived_fx_rate_series(
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
) -> list[FxRateObservation] | None:
    direct = await _fetch_yahoo_fx_rate_series(base_currency, quote_currency, start_date, end_date)
    if direct:
        return direct
    if direct is None:
        direct_failed = True
    else:
        direct_failed = False

    inverse = await _fetch_yahoo_fx_rate_series(quote_currency, base_currency, start_date, end_date)
    if inverse:
        return [
            FxRateObservation(
                base_currency=base_currency,
                quote_currency=quote_currency,
                rate=_quantize_rate(Decimal("1") / observation.rate),
                rate_date=observation.rate_date,
                source="yahoo_finance:inverse",
            )
            for observation in inverse
            if observation.rate != Decimal("0")
        ]

    bridge = _normalize_currency(settings.market_data_fx_bridge_currency)
    if bridge in {base_currency, quote_currency}:
        return None if direct_failed and inverse is None else []

    base_to_bridge = await _fetch_yahoo_fx_rate_series(base_currency, bridge, start_date, end_date)
    bridge_to_quote = await _fetch_yahoo_fx_rate_series(bridge, quote_currency, start_date, end_date)
    if base_to_bridge is None and bridge_to_quote is None and direct_failed and inverse is None:
        return None
    if not base_to_bridge or not bridge_to_quote:
        return []

    bridge_to_quote_by_date = {observation.rate_date: observation for observation in bridge_to_quote}
    observations: list[FxRateObservation] = []
    for base_observation in base_to_bridge:
        quote_observation = bridge_to_quote_by_date.get(base_observation.rate_date)
        if quote_observation is None:
            continue
        observations.append(
            FxRateObservation(
                base_currency=base_currency,
                quote_currency=quote_currency,
                rate=_quantize_rate(base_observation.rate * quote_observation.rate),
                rate_date=base_observation.rate_date,
                source=f"yahoo_finance:bridge:{bridge}",
            )
        )
    return observations


async def _fetch_provider_response(
    url: str,
    params: dict[str, str],
    *,
    failure_message: str,
    log_context: dict[str, str],
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
    return {
        "s": symbol,
        "d1": start_date.strftime("%Y%m%d"),
        "d2": end_date.strftime("%Y%m%d"),
        "i": "d",
    }


async def _fetch_yahoo_fx_rate(
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> FxRateObservation | None:
    """Fetch the latest Yahoo Finance FX close on or before the requested date."""
    observations = await _fetch_yahoo_fx_rate_series(
        base_currency,
        quote_currency,
        requested_date - timedelta(days=7),
        requested_date,
    )
    return max(observations, key=lambda item: item.rate_date, default=None) if observations is not None else None


async def _fetch_yahoo_fx_rate_series(
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
) -> list[FxRateObservation] | None:
    """Fetch Yahoo Finance FX closes for a bounded date range."""
    symbol = f"{base_currency}{quote_currency}"
    url = _YAHOO_FX_CHART_URL.format(symbol=quote(symbol, safe=""))
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
    if response is None:
        return None

    return _parse_yahoo_fx_response_series(response.json(), base_currency, quote_currency, start_date, end_date)


def _parse_yahoo_close_rows(
    payload: dict[str, Any],
    *,
    start_date: date,
    end_date: date,
) -> tuple[str, list[tuple[date, Decimal]]]:
    results = payload.get("chart", {}).get("result") or []
    if not results:
        return "USD", []

    result = results[0]
    currency = _normalize_currency((result.get("meta") or {}).get("currency") or "USD")
    timestamps = result.get("timestamp") or []
    closes = ((result.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    rows: list[tuple[date, Decimal]] = []
    for timestamp, close in zip(timestamps, closes, strict=False):
        if close is None:
            continue
        observed_date = datetime.fromtimestamp(int(timestamp), UTC).date()
        if observed_date < start_date or observed_date > end_date:
            continue
        rows.append((observed_date, Decimal(str(close))))
    return currency, rows


def _parse_yahoo_fx_response_series(
    payload: dict[str, Any],
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
) -> list[FxRateObservation]:
    _, rows = _parse_yahoo_close_rows(payload, start_date=start_date, end_date=end_date)
    return [
        FxRateObservation(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=_quantize_rate(rate),
            rate_date=observed_date,
            source="yahoo_finance",
        )
        for observed_date, rate in rows
    ]


async def _fetch_yahoo_stock_price(symbol: str, requested_date: date) -> StockPriceObservation | None:
    """Fetch the latest Yahoo Finance stock close on or before the requested date."""
    normalized = _normalize_symbol(symbol)
    observations = await _fetch_yahoo_stock_price_series(
        normalized,
        requested_date - timedelta(days=7),
        requested_date,
    )
    return max(observations, key=lambda item: item.price_date, default=None) if observations is not None else None


async def _fetch_yahoo_stock_price_series(
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[StockPriceObservation] | None:
    """Fetch Yahoo Finance stock closes for a bounded date range."""
    normalized = _normalize_symbol(symbol)
    if not _looks_like_ticker(normalized):
        # Free-text identifiers (e.g. brokerage fund names) are guaranteed Yahoo 404s.
        # Skip the request; these positions are valued from their AtomicPosition snapshot.
        logger.debug(
            "Skipping Yahoo stock fetch for non-ticker identifier",
            symbol=normalized,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        return None
    url = _YAHOO_STOCK_CHART_URL.format(symbol=quote(normalized, safe=".-"))
    response = await _fetch_provider_response(
        url,
        _yahoo_chart_params(start_date, end_date),
        failure_message="Yahoo Finance stock range fetch failed",
        log_context={
            "symbol": normalized,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    if response is None:
        return None

    return _parse_yahoo_stock_response_series(response.json(), normalized, start_date, end_date)


def _parse_yahoo_stock_response_series(
    payload: dict[str, Any],
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[StockPriceObservation]:
    currency, rows = _parse_yahoo_close_rows(payload, start_date=start_date, end_date=end_date)
    return [
        StockPriceObservation(
            symbol=symbol,
            price=_quantize_price(price),
            currency=currency,
            price_date=observed_date,
            source="yahoo_finance",
        )
        for observed_date, price in rows
    ]


async def _fetch_stooq_fx_rate(
    base_currency: str,
    quote_currency: str,
    requested_date: date,
) -> FxRateObservation | None:
    observations = await _fetch_stooq_fx_rate_series(
        base_currency,
        quote_currency,
        requested_date - timedelta(days=7),
        requested_date,
    )
    return max(observations, key=lambda item: item.rate_date, default=None) if observations is not None else None


async def _fetch_stooq_fx_rate_series(
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
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
    if response is None:
        return None

    return _parse_stooq_fx_csv_series(response.text, base_currency, quote_currency, start_date, end_date)


def _parse_stooq_close_rows(payload: str, *, start_date: date, end_date: date) -> list[tuple[date, Decimal]]:
    rows: list[tuple[date, Decimal]] = []
    for row in csv.DictReader(StringIO(payload)):
        close = row.get("Close")
        row_date = row.get("Date")
        if not close or not row_date or close == "N/D":
            continue
        observed_date = date.fromisoformat(row_date)
        if observed_date < start_date or observed_date > end_date:
            continue
        rows.append((observed_date, Decimal(close)))
    return rows


def _parse_stooq_fx_csv_series(
    payload: str,
    base_currency: str,
    quote_currency: str,
    start_date: date,
    end_date: date,
) -> list[FxRateObservation]:
    rows = _parse_stooq_close_rows(payload, start_date=start_date, end_date=end_date)
    return [
        FxRateObservation(
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=_quantize_rate(rate),
            rate_date=observed_date,
            source="stooq",
        )
        for observed_date, rate in rows
    ]


async def _fetch_stooq_stock_price(symbol: str, requested_date: date) -> StockPriceObservation | None:
    normalized = _normalize_symbol(symbol)
    observations = await _fetch_stooq_stock_price_series(
        normalized,
        requested_date - timedelta(days=7),
        requested_date,
    )
    return max(observations, key=lambda item: item.price_date, default=None) if observations is not None else None


async def _fetch_stooq_stock_price_series(
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[StockPriceObservation] | None:
    normalized = _normalize_symbol(symbol)
    response = await _fetch_provider_response(
        _STOOQ_DAILY_URL,
        _stooq_daily_params(_stooq_stock_symbol(normalized), start_date, end_date),
        failure_message="Stooq stock range fetch failed",
        log_context={
            "symbol": normalized,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )
    if response is None:
        return None

    return _parse_stooq_stock_csv_series(response.text, normalized, start_date, end_date)


def _parse_stooq_stock_csv_series(
    payload: str,
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[StockPriceObservation]:
    rows = _parse_stooq_close_rows(payload, start_date=start_date, end_date=end_date)
    return [
        StockPriceObservation(
            symbol=symbol,
            price=_quantize_price(price),
            currency="USD",
            price_date=observed_date,
            source="stooq",
        )
        for observed_date, price in rows
    ]
