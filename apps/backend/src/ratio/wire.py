"""Boundary codecs for backend ratio values."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from src.ratio.errors import FloatNotAllowedError, InvalidRatioPayloadError
from src.ratio.ratio import Ratio


def _decimal_to_wire(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _decimal_from_wire(value: object, what: str = "ratio value") -> Decimal:
    if isinstance(value, bool):
        raise FloatNotAllowedError(f"bool is not a valid {what}")
    if isinstance(value, float):
        raise FloatNotAllowedError(f"float is not allowed for {what}; use a decimal string")
    if not isinstance(value, str):
        raise FloatNotAllowedError(f"{what} must be encoded as a decimal string, got {type(value).__name__}")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise InvalidRatioPayloadError(f"{what} is not a valid decimal string") from exc
    if not parsed.is_finite():
        raise FloatNotAllowedError(f"{what} must be finite")
    return parsed


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
