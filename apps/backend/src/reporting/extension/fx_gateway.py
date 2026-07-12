"""Reporting's FX seam — wired at the composition root (#1666).

Reporting's statement math converts through ``pricing``'s FX surface
(``src.pricing``: ``get_exchange_rate``/``get_average_rate``/``convert_*``,
``fx_warnings`` side-channel, ``PrefetchedFxRates`` batch prefetch). Rather
than import ``pricing`` directly, the concrete FX callables and the two FX
types arrive by injection — the same inversion as platform's readiness port
(#1676) and the uploaded-document readers (#1675 D3): ``src/main.py``
registers the real ``src.pricing`` objects at startup; the backend test
conftest registers them for direct (no-app) test runs. Kept as an injection
seam rather than a direct import even after #1610 landed (retiring
``services/fx.py``) so reporting keeps owning zero FX logic — a rename in
pricing's internals never touches this package's consumer modules.

Two access shapes, chosen so behavior and monkeypatch surfaces survive the
move unchanged:

- The four conversion callables are exposed as stable module-level ``async``
  wrappers (import-safe before wiring; dispatch to the registered slot at call
  time). Consumer modules ``from ...fx_gateway import get_exchange_rate`` and
  tests keep patching the per-module name.
- ``FxRateError`` / ``PrefetchedFxRates`` are the *injected real objects*
  exposed as module attributes; consumer modules reference them late-bound
  (``fx_gateway.FxRateError`` at except-time, ``fx_gateway.PrefetchedFxRates``
  at instantiation time) so exception identity matches what the injected
  callables actually raise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

#: Structural warning-dict alias (same shape as ``src.pricing.FxWarning``).
#: Pure annotation vocabulary — identity is irrelevant, so it is defined
#: locally instead of injected.
FxWarning = dict[str, str]


class _FxGatewayNotRegisteredError(Exception):
    """Placeholder bound to :data:`FxRateError` before wiring.

    Never raised by anything, so a pre-wiring ``except fx_gateway.FxRateError``
    simply matches nothing instead of crashing on a non-exception sentinel.
    """


class _UnwiredPrefetchedFxRates:
    """Placeholder bound to :data:`PrefetchedFxRates` before wiring.

    A bare ``None`` default would make ``fx_gateway.PrefetchedFxRates(...)``
    fail with a confusing ``TypeError: 'NoneType' object is not callable``.
    Instantiating this placeholder instead raises the same clear wiring error
    :func:`_require` gives the callables, at the point of use.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError(
            "fx_gateway.register_fx_gateway() was never called (needed for "
            "'PrefetchedFxRates') — main.py wires it at startup (#1666); a "
            "test exercising reporting without the app must call it too "
            "(the backend test conftest does)."
        )


#: The injected FX-unavailable exception class (``src.pricing.PricingError``
#: today). Reference late-bound as ``fx_gateway.FxRateError``.
FxRateError: type[Exception] = _FxGatewayNotRegisteredError

#: The injected prefetch-batch helper class (``src.pricing.PrefetchedFxRates``
#: today). Reference late-bound as ``fx_gateway.PrefetchedFxRates``.
PrefetchedFxRates: Any = _UnwiredPrefetchedFxRates

_get_exchange_rate: Callable[..., Awaitable[Any]] | None = None
_get_average_rate: Callable[..., Awaitable[Any]] | None = None
_convert_amount: Callable[..., Awaitable[Any]] | None = None
_convert_money: Callable[..., Awaitable[Any]] | None = None


def register_fx_gateway(
    *,
    get_exchange_rate: Callable[..., Awaitable[Any]],
    get_average_rate: Callable[..., Awaitable[Any]],
    convert_amount: Callable[..., Awaitable[Any]],
    convert_money: Callable[..., Awaitable[Any]],
    prefetched_fx_rates: type,
    fx_rate_error: type[Exception],
) -> None:
    """Wire the FX implementation (see module note above)."""
    global _get_exchange_rate, _get_average_rate, _convert_amount, _convert_money
    global PrefetchedFxRates, FxRateError
    _get_exchange_rate = get_exchange_rate
    _get_average_rate = get_average_rate
    _convert_amount = convert_amount
    _convert_money = convert_money
    PrefetchedFxRates = prefetched_fx_rates
    FxRateError = fx_rate_error


def _require(slot: Callable[..., Awaitable[Any]] | None, name: str) -> Callable[..., Awaitable[Any]]:
    if slot is None:
        raise RuntimeError(
            f"fx_gateway.register_fx_gateway() was never called (needed for {name!r}) — "
            "main.py wires it at startup (#1666); a test exercising reporting without "
            "the app must call it too (the backend test conftest does)."
        )
    return slot


async def get_exchange_rate(*args: Any, **kwargs: Any) -> Any:
    """Dispatch to the registered ``get_exchange_rate`` implementation."""
    return await _require(_get_exchange_rate, "get_exchange_rate")(*args, **kwargs)


async def get_average_rate(*args: Any, **kwargs: Any) -> Any:
    """Dispatch to the registered ``get_average_rate`` implementation."""
    return await _require(_get_average_rate, "get_average_rate")(*args, **kwargs)


async def convert_amount(*args: Any, **kwargs: Any) -> Any:
    """Dispatch to the registered ``convert_amount`` implementation."""
    return await _require(_convert_amount, "convert_amount")(*args, **kwargs)


async def convert_money(*args: Any, **kwargs: Any) -> Any:
    """Dispatch to the registered ``convert_money`` implementation."""
    return await _require(_convert_money, "convert_money")(*args, **kwargs)
