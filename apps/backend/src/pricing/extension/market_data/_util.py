"""Pure helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from src.pricing.extension.market_data._base import (
    _DEFAULT_INCREMENTAL_LOOKBACK_DAYS,
    _PRICE_QUANT,
    _PROVIDER_DISAGREEMENT_THRESHOLD,
    _RATE_QUANT,
    _TICKER_MAX_LENGTH,
    _TICKER_PATTERN,
    logger,
)
from src.pricing.extension.market_data._types import (
    FxRateObservation,
    ProviderDisagreement,
    StockPriceObservation,
    ValidatedMarketObservation,
    ValidatedMarketObservationSeries,
)


def _normalize_currency(code: str) -> str:
    return code.strip().upper()


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def _looks_like_ticker(symbol: str) -> bool:
    """Return True when ``symbol`` is plausibly a Yahoo ticker rather than free text.

    Brokerage fund positions store the full fund name (with spaces and identifier
    codes) as the asset identifier. Those are never valid tickers and 404 against
    Yahoo on every lookup, so callers should skip the provider request for them.
    Real tickers (AAPL, MSFT, BRK.B, 0700.HK) and FX pairs (USDSGD) still pass.
    """
    candidate = symbol.strip()
    if not candidate or len(candidate) > _TICKER_MAX_LENGTH:
        return False
    return _TICKER_PATTERN.fullmatch(candidate) is not None


def _quantize_rate(rate: Decimal) -> Decimal:
    return rate.quantize(_RATE_QUANT, rounding=ROUND_HALF_UP)


def _quantize_price(price: Decimal) -> Decimal:
    return price.quantize(_PRICE_QUANT, rounding=ROUND_HALF_UP)


def _date_to_epoch(value: date) -> int:
    return int(datetime.combine(value, time.min, tzinfo=UTC).timestamp())


def _iter_dates(start_date: date, end_date: date) -> Sequence[date]:
    days = (end_date - start_date).days
    if days < 0:
        return []
    return [start_date + timedelta(days=offset) for offset in range(days + 1)]


def _parse_fx_pair(pair: str) -> tuple[str, str]:
    parts = [item.strip() for item in pair.split("/", maxsplit=1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid FX pair '{pair}', expected BASE/QUOTE")
    return _normalize_currency(parts[0]), _normalize_currency(parts[1])


def _fx_scope(base_currency: str, quote_currency: str) -> str:
    return f"{_normalize_currency(base_currency)}/{_normalize_currency(quote_currency)}"


def _stock_scope(symbol: str) -> str:
    return _normalize_symbol(symbol)


def _default_start_date(end_date: date) -> date:
    return end_date - timedelta(days=_DEFAULT_INCREMENTAL_LOOKBACK_DAYS - 1)


def _incremental_start(last_stored_date: date | None, start_date: date | None, end_date: date) -> date | None:
    if last_stored_date is not None:
        if start_date is not None and last_stored_date >= end_date:
            start = start_date
        else:
            start = last_stored_date + timedelta(days=1)
    else:
        start = start_date or _default_start_date(end_date)
    if start > end_date:
        return None
    return start


def _relative_difference(primary: Decimal, secondary: Decimal) -> Decimal:
    denominator = max(abs(primary), abs(secondary))
    if denominator == Decimal("0"):
        return Decimal("0")
    return _quantize_rate(abs(primary - secondary) / denominator)


def _observation_date(observation: FxRateObservation | StockPriceObservation) -> date:
    if isinstance(observation, FxRateObservation):
        return observation.rate_date
    return observation.price_date


def _observations_by_date(
    observations: Sequence[FxRateObservation | StockPriceObservation] | None,
) -> dict[date, FxRateObservation | StockPriceObservation]:
    return {_observation_date(observation): observation for observation in observations or []}


def _normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hk_numeric_code(symbol: str) -> str | None:
    """Return the Hong Kong board-lot code (left-zero-padded to ≥4 digits), or ``None``.

    Brokerages store Hong Kong equities by their numeric exchange code (e.g.
    Xiaomi ``"01810"`` → ``"1810"``, Tencent ``"00700"`` → ``"0700"``). HKEX codes
    are 4–5 digits, so a 5-digit code is preserved (``"10000"`` → ``"10000"``).
    Market-data providers expect the ``"<code>.HK"`` form; sent verbatim the raw
    numeric 404s. An all-zero / zero-valued code is not a real ticker and returns
    ``None`` (CR on #1453); US tickers are alphabetic and never match here.
    """
    candidate = symbol.strip()
    if candidate.isdigit() and 1 <= len(candidate) <= 5 and int(candidate) != 0:
        return f"{int(candidate):04d}"
    return None


def _yahoo_stock_symbol(symbol: str) -> str:
    """Map a stored asset identifier to the symbol Yahoo Finance expects.

    Storage keeps the raw identifier (see ``_normalize_symbol``); only the
    outbound provider symbol is exchange-qualified, so the stored scope and
    dedup keys are unaffected.
    """
    normalized = _normalize_symbol(symbol)
    if "." in normalized:
        return normalized
    hk_code = _hk_numeric_code(normalized)
    if hk_code is not None:
        return f"{hk_code}.HK"
    return normalized


def _stooq_stock_symbol(symbol: str) -> str:
    normalized = _normalize_symbol(symbol)
    if "." in normalized:
        return normalized.lower()
    hk_code = _hk_numeric_code(normalized)
    if hk_code is not None:
        return f"{hk_code}.hk"
    return f"{normalized.lower()}.us"


def _stooq_fx_symbol(base_currency: str, quote_currency: str) -> str:
    return f"{base_currency.lower()}{quote_currency.lower()}"


def _select_validated_observation(
    *,
    asset: str,
    observed_date: date,
    primary: FxRateObservation | StockPriceObservation | None,
    secondary: FxRateObservation | StockPriceObservation | None,
) -> ValidatedMarketObservation:
    if primary is None:
        return ValidatedMarketObservation(observation=secondary)
    if secondary is None:
        return ValidatedMarketObservation(observation=primary)

    primary_value = primary.rate if isinstance(primary, FxRateObservation) else primary.price
    secondary_value = secondary.rate if isinstance(secondary, FxRateObservation) else secondary.price
    relative_difference = _relative_difference(primary_value, secondary_value)
    if relative_difference > _PROVIDER_DISAGREEMENT_THRESHOLD:
        disagreement = ProviderDisagreement(
            asset=asset,
            observed_date=observed_date,
            primary_source=primary.source,
            secondary_source=secondary.source,
            primary_value=primary_value,
            secondary_value=secondary_value,
            relative_difference=relative_difference,
            threshold=_PROVIDER_DISAGREEMENT_THRESHOLD,
        )
        logger.warning("Market data provider disagreement", **disagreement.to_dict())
        return ValidatedMarketObservation(observation=None, disagreement=disagreement)

    return ValidatedMarketObservation(
        observation=replace(primary, source=f"{primary.source}:validated:{secondary.source}"[:50])
    )


def _select_validated_observation_series(
    *,
    asset: str,
    start_date: date,
    end_date: date,
    primary: Sequence[FxRateObservation | StockPriceObservation] | None,
    secondary: Sequence[FxRateObservation | StockPriceObservation] | None,
    provider_success: bool,
) -> ValidatedMarketObservationSeries:
    primary_by_date = _observations_by_date(primary)
    secondary_by_date = _observations_by_date(secondary)
    observations: list[FxRateObservation | StockPriceObservation] = []
    disagreements: list[ProviderDisagreement] = []

    for observed_date in sorted(set(primary_by_date) | set(secondary_by_date)):
        if observed_date < start_date or observed_date > end_date:
            continue
        selected = _select_validated_observation(
            asset=asset,
            observed_date=observed_date,
            primary=primary_by_date.get(observed_date),
            secondary=secondary_by_date.get(observed_date),
        )
        if selected.disagreement is not None:
            disagreements.append(selected.disagreement)
        elif selected.observation is not None:
            observations.append(selected.observation)

    return ValidatedMarketObservationSeries(
        observations=observations,
        disagreements=disagreements,
        provider_success=provider_success,
    )


def _parse_sync_fx_scope(pair: str) -> tuple[str, str] | None:
    base, quote_currency = _parse_fx_pair(pair)
    if base == quote_currency:
        return None
    return base, quote_currency
