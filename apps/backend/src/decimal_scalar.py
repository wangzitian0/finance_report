"""Shared Decimal-scalar codec — the single boundary primitive the backend's
base-package value types route their raw-``Decimal`` conversions through.

Backend mirror of ``common/decimal_scalar.py`` (the reference impl). The backend
ships self-contained — it does not import ``common`` at runtime — so it keeps its
own copy, exactly like the ``money`` / ``quantity`` / ``ratio`` / ``unit_price``
value types are mirrored under ``apps/backend/src`` (#1167). Kept byte-for-byte in
step with the reference impl.

``base-packages.md`` §3 ("Raw Decimal boundary policy") requires that hand-written
semantic conversion at a value boundary go through *the owning base-package
codec*, never local ``Decimal(str(...))`` glue. Each base package used to
re-implement that codec — a byte-identical ``_decimal_to_wire``, a
``_decimal_from_wire`` / ``_payload_mapping`` / ``_field`` triad, and a
construction-time ``_coerce`` — differing only by which typed error it raised.
This module is that codec, factored once; each package supplies its own error
classes so the narrow per-domain error hierarchy is preserved.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


def decimal_to_wire(value: Decimal) -> str:
    """Canonical wire form for a ``Decimal``: fixed-point notation with trailing
    zeros trimmed, and a single ``"0"`` for any zero (including ``-0``)."""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def coerce_decimal(
    value: object,
    what: str,
    *,
    float_error: type[Exception],
    require_finite: bool = False,
) -> Decimal:
    """Coerce a construction-time input to ``Decimal``.

    Accepts ``Decimal`` and ``int`` (the exact numeric inputs); rejects ``bool``
    and ``float`` (the standing numeric red line) and any other type by raising
    ``float_error``. When ``require_finite`` is set, a non-finite ``Decimal``
    (NaN / Infinity) is rejected too.
    """
    if isinstance(value, bool):
        raise float_error(f"bool is not a valid {what}")
    if isinstance(value, float):
        raise float_error(f"float is not allowed for {what} (IEEE-754 precision loss); use Decimal")
    if isinstance(value, Decimal):
        if require_finite and not value.is_finite():
            raise float_error(f"{what} must be finite")
        return value
    if isinstance(value, int):
        return Decimal(value)
    raise float_error(f"{what} must be Decimal or int, got {type(value).__name__}")


@dataclass(frozen=True)
class WireCodec:
    """The wire-boundary triad (parse / mapping / field) bound to one package's
    typed errors. Wire payloads carry decimals as strings, never JSON numbers.
    """

    float_error: type[Exception]
    payload_error: type[Exception]

    def parse(self, value: object, what: str) -> Decimal:
        """Decode a wire decimal string into a finite ``Decimal``."""
        if isinstance(value, bool):
            raise self.float_error(f"bool is not a valid {what}")
        if isinstance(value, float):
            raise self.float_error(f"float is not allowed for {what}; use a decimal string")
        if not isinstance(value, str):
            raise self.float_error(f"{what} must be encoded as a decimal string, got {type(value).__name__}")
        try:
            parsed = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise self.payload_error(f"{what} is not a valid decimal string") from exc
        if not parsed.is_finite():
            raise self.float_error(f"{what} must be finite")
        return parsed

    def mapping(self, payload: object, what: str) -> Mapping[str, object]:
        """Require ``payload`` to be a mapping (the object envelope of a wire payload)."""
        if not isinstance(payload, Mapping):
            raise self.payload_error(f"{what} payload must be an object, got {type(payload).__name__}")
        return payload

    def field(self, payload: Mapping[str, object], key: str, what: str) -> object:
        """Read a required ``key`` from a wire payload mapping."""
        try:
            return payload[key]
        except KeyError as exc:
            raise self.payload_error(f"{what} payload missing {key!r}") from exc
