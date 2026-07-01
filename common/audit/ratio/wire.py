"""Boundary codecs for ratio values."""

from __future__ import annotations

from decimal import Decimal

from common.audit.ratio.errors import FloatNotAllowedError, InvalidRatioPayloadError
from common.audit.ratio.ratio import Ratio
from common.decimal_scalar import WireCodec
from common.decimal_scalar import decimal_to_wire as _decimal_to_wire

# The shared scalar codec bound to ratio's typed errors (ratio wire is a bare
# decimal string, so only ``parse`` is needed — no payload envelope).
_CODEC = WireCodec(FloatNotAllowedError, InvalidRatioPayloadError)


def _decimal_from_wire(value: object, what: str = "ratio value") -> Decimal:
    return _CODEC.parse(value, what)


def ratio_to_wire(ratio: Ratio) -> str:
    if not isinstance(ratio, Ratio):
        raise TypeError(f"ratio_to_wire expects Ratio, got {type(ratio).__name__}")
    return _decimal_to_wire(ratio.value)


def ratio_from_wire(value: object) -> Ratio:
    return Ratio(_decimal_from_wire(value))


def ratio_to_db_value(ratio: Ratio) -> Decimal:
    if not isinstance(ratio, Ratio):
        raise TypeError(f"ratio_to_db_value expects Ratio, got {type(ratio).__name__}")
    return ratio.value


def ratio_from_db_value(value: object) -> Ratio:
    return Ratio(value)  # type: ignore[arg-type]
