"""Shared Decimal-scalar codec is one SSOT per layer (EPIC-012 AC12.36).

These guards ratchet the dedup: each base package's wire/core modules must route
their raw-``Decimal`` conversion through the shared ``decimal_scalar`` codec, and
the canonical codec logic must live *only* there — so the per-package duplication
(``_decimal_to_wire`` / ``_decimal_from_wire`` / ``_payload_mapping`` / ``_field``
bodies + a construction-time ``_coerce`` body) cannot silently come back.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from common.testing.ac_proof import ac_proof

from common.decimal_scalar import WireCodec, coerce_decimal, decimal_to_wire

REPO = Path(__file__).resolve().parents[2]

# Markers of the canonical codec bodies that must exist ONLY in decimal_scalar.
_CODEC_BODY_MARKERS = (
    'rstrip("0").rstrip(".")',  # decimal_to_wire body
    "IEEE-754 precision loss",  # coerce_decimal float-rejection body
    "is not a valid decimal string",  # WireCodec.parse body
    "must be encoded as a decimal string",  # WireCodec.parse body
)


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _assert_layer_shares_one_codec(layer_root: str, import_prefix: str) -> None:
    """Every base package under ``layer_root`` routes through ``import_prefix.decimal_scalar``."""
    wire_modules = {
        "money": f"{layer_root}/audit/money/wire.py",
        "quantity": f"{layer_root}/audit/quantity/wire.py",
        "ratio": f"{layer_root}/audit/ratio/wire.py",
        "unit_price": f"{layer_root}/audit/unit_price/wire.py",
    }
    core_modules = {
        "money": f"{layer_root}/audit/money/money.py",
        "quantity": f"{layer_root}/audit/quantity/quantity.py",
        "ratio": f"{layer_root}/audit/ratio/ratio.py",
        "unit_price": f"{layer_root}/audit/unit_price/unit_price.py",
    }

    for pkg, rel in wire_modules.items():
        src = _read(rel)
        assert f"from {import_prefix}.decimal_scalar import" in src, (
            f"{rel} must import the shared codec"
        )
        assert "WireCodec(" in src, f"{rel} must bind a WireCodec to its typed errors"
        for marker in _CODEC_BODY_MARKERS:
            assert marker not in src, (
                f"{rel} still inlines codec body {marker!r} (route through decimal_scalar)"
            )

    for pkg, rel in core_modules.items():
        src = _read(rel)
        assert "coerce_decimal" in src, f"{rel} must coerce via the shared codec"
        assert "IEEE-754 precision loss" not in src, (
            f"{rel} still inlines the _coerce float-rejection body"
        )

    # The canonical logic lives only in the shared module.
    codec_src = _read(f"{layer_root}/decimal_scalar.py")
    assert "def decimal_to_wire(" in codec_src
    assert "def coerce_decimal(" in codec_src
    assert "class WireCodec" in codec_src
    for marker in _CODEC_BODY_MARKERS:
        assert marker in codec_src, (
            f"{layer_root}/decimal_scalar.py is missing canonical body {marker!r}"
        )


@ac_proof(
    proof_id="test_common_base_packages_share_one_scalar_codec",
    ac_ids=["AC12.36.1"],
    ci_tier="pr_ci",
)
def test_AC12_36_1_common_base_packages_share_one_scalar_codec():
    """AC12.36.1: the four common base packages share one decimal_scalar codec."""
    _assert_layer_shares_one_codec("common", "common")


@ac_proof(
    proof_id="test_backend_base_packages_share_one_scalar_codec",
    ac_ids=["AC12.36.2"],
    ci_tier="pr_ci",
)
def test_AC12_36_2_backend_base_packages_share_one_scalar_codec():
    """AC12.36.2: the backend mirror shares one src.decimal_scalar codec."""
    _assert_layer_shares_one_codec("apps/backend/src", "src")


# ── behavioural coverage of the shared codec (common layer) ──────────────────


class _FloatError(TypeError):
    pass


class _PayloadError(ValueError):
    pass


def test_decimal_to_wire_trims_and_normalizes_zero():
    assert decimal_to_wire(Decimal("10.5000")) == "10.5"
    assert decimal_to_wire(Decimal("3")) == "3"
    assert decimal_to_wire(Decimal("-0")) == "0"
    assert decimal_to_wire(Decimal("0.00")) == "0"


def test_coerce_decimal_accepts_decimal_and_int():
    assert coerce_decimal(Decimal("1.25"), "x", float_error=_FloatError) == Decimal(
        "1.25"
    )
    assert coerce_decimal(7, "x", float_error=_FloatError) == Decimal("7")


def test_coerce_decimal_rejects_bool_float_and_other_types():
    for bad in (True, 1.5, "1.5", None):
        with pytest.raises(_FloatError):
            coerce_decimal(bad, "x", float_error=_FloatError)


def test_coerce_decimal_require_finite_rejects_nan_infinity():
    # Non-finite is allowed when require_finite is off, rejected when on.
    assert coerce_decimal(Decimal("NaN"), "x", float_error=_FloatError).is_nan()
    for bad in (Decimal("NaN"), Decimal("Infinity")):
        with pytest.raises(_FloatError):
            coerce_decimal(bad, "x", float_error=_FloatError, require_finite=True)


def test_wire_codec_parse_decodes_and_validates():
    codec = WireCodec(_FloatError, _PayloadError)
    assert codec.parse("1.50", "x") == Decimal("1.50")
    for bad in (True, 1.5, b"1"):
        with pytest.raises(_FloatError):
            codec.parse(bad, "x")
    with pytest.raises(_PayloadError):
        codec.parse("not-a-number", "x")
    with pytest.raises(_FloatError):
        codec.parse("NaN", "x")


def test_wire_codec_mapping_and_field():
    codec = WireCodec(_FloatError, _PayloadError)
    assert codec.mapping({"a": "1"}, "X") == {"a": "1"}
    with pytest.raises(_PayloadError):
        codec.mapping(["not", "a", "map"], "X")
    assert codec.field({"a": "1"}, "a", "X") == "1"
    with pytest.raises(_PayloadError):
        codec.field({"a": "1"}, "missing", "X")
