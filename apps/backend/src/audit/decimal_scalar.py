"""Shared Decimal-scalar coercion — the single construction-time primitive the backend's
base-package value types route their raw-``Decimal`` conversions through.

Backend mirror of ``common/audit/decimal_scalar.py`` (the reference impl). The backend
ships self-contained — it does not import ``common`` at runtime — so it keeps its
own copy, exactly like the ``money`` / ``quantity`` / ``ratio`` / ``unit_price``
value types are mirrored under ``apps/backend/src`` (#1167). Kept byte-for-byte in
step with the reference impl.

``common/audit/readme.md#base-packages`` §3 ("Raw Decimal boundary policy")
requires that hand-written semantic conversion at a value boundary go through the
owning base-package value type, never local ``Decimal(str(...))`` glue. Each base
package used to re-implement a construction-time ``_coerce``, differing only by
which typed error it raised. :func:`coerce_decimal` is that coercion, factored once;
each package supplies its own error class so the narrow per-domain error hierarchy
is preserved.
"""

from __future__ import annotations

from decimal import Decimal


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
