"""Behavioural coverage for the backend's shared Decimal-scalar coercion mirror (AC-audit.36.2).

The backend ships ``src.audit.decimal_scalar`` as a self-contained copy of
``common.audit.decimal_scalar`` (the value types route through it). This exercises every
branch directly so the mirror stays covered independent of the value-type suites.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.audit.decimal_scalar import coerce_decimal

pytestmark = pytest.mark.no_db


class _FloatError(TypeError):
    pass


def test_coerce_decimal_accepts_and_rejects():
    assert coerce_decimal(Decimal("1.25"), "x", float_error=_FloatError) == Decimal("1.25")
    assert coerce_decimal(7, "x", float_error=_FloatError) == Decimal("7")
    for bad in (True, 1.5, "1.5", None):
        with pytest.raises(_FloatError):
            coerce_decimal(bad, "x", float_error=_FloatError)


def test_coerce_decimal_require_finite():
    assert coerce_decimal(Decimal("NaN"), "x", float_error=_FloatError).is_nan()
    for bad in (Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(_FloatError):
            coerce_decimal(bad, "x", float_error=_FloatError, require_finite=True)
