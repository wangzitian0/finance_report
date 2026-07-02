"""Behavioural coverage for the backend's shared Decimal-scalar codec mirror (AC-audit.36.2).

The backend ships ``src.audit.decimal_scalar`` as a self-contained copy of
``common.audit.decimal_scalar`` (the value types route through it). This exercises every
branch directly so the mirror stays covered independent of the value-type suites.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.audit.decimal_scalar import WireCodec, coerce_decimal, decimal_to_wire

pytestmark = pytest.mark.no_db


class _FloatError(TypeError):
    pass


class _PayloadError(ValueError):
    pass


def test_decimal_to_wire_trims_and_normalizes_zero():
    assert decimal_to_wire(Decimal("10.5000")) == "10.5"
    assert decimal_to_wire(Decimal("3")) == "3"
    assert decimal_to_wire(Decimal("-0")) == "0"
    assert decimal_to_wire(Decimal("0.00")) == "0"


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


def test_wire_codec_parse_mapping_field():
    codec = WireCodec(_FloatError, _PayloadError)
    assert codec.parse("1.50", "x") == Decimal("1.50")
    for bad in (True, 1.5, b"1"):
        with pytest.raises(_FloatError):
            codec.parse(bad, "x")
    with pytest.raises(_PayloadError):
        codec.parse("not-a-number", "x")
    with pytest.raises(_FloatError):
        codec.parse("Infinity", "x")
    assert codec.mapping({"a": "1"}, "X") == {"a": "1"}
    with pytest.raises(_PayloadError):
        codec.mapping(["x"], "X")
    assert codec.field({"a": "1"}, "a", "X") == "1"
    with pytest.raises(_PayloadError):
        codec.field({"a": "1"}, "missing", "X")
