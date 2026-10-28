"""Shared Decimal-scalar coercion is one SSOT per layer (EPIC-012 AC12.36).

These guards ratchet the dedup: each base package's core module must route its
construction-time ``Decimal`` coercion through the shared ``decimal_scalar``
``coerce_decimal``, and the canonical float-rejection body must live *only* there,
so a per-package ``_coerce`` body cannot silently come back.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from common.testing.ac_proof import ac_proof

from common.audit.decimal_scalar import coerce_decimal

REPO = Path(__file__).resolve().parents[2]

# Marker of the canonical coercion body that must exist ONLY in decimal_scalar.
_COERCE_BODY_MARKER = "IEEE-754 precision loss"


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def _assert_layer_shares_one_coercion(layer_root: str, import_prefix: str) -> None:
    """Every base package under ``layer_root`` coerces via ``import_prefix.decimal_scalar``."""
    core_modules = {
        "money": f"{layer_root}/audit/money/money.py",
        # exchange_rate escaped the original list and re-inlined the _coerce
        # body (#1864 S1 backfill) — every construction-time coercion in the
        # money package routes through the shared coercion.
        "money.exchange_rate": f"{layer_root}/audit/money/exchange_rate.py",
        "quantity": f"{layer_root}/audit/quantity/quantity.py",
        "ratio": f"{layer_root}/audit/ratio/ratio.py",
        "unit_price": f"{layer_root}/audit/unit_price/unit_price.py",
    }

    for pkg, rel in core_modules.items():
        src = _read(rel)
        assert f"from {import_prefix}.decimal_scalar import coerce_decimal" in src, (
            f"{rel} must import the shared coercion"
        )
        assert "coerce_decimal(" in src, f"{rel} must coerce via the shared coercion"
        assert _COERCE_BODY_MARKER not in src, (
            f"{rel} still inlines the _coerce float-rejection body"
        )

    # The canonical logic lives only in the shared module.
    codec_src = _read(f"{layer_root}/audit/decimal_scalar.py")
    assert "def coerce_decimal(" in codec_src
    assert _COERCE_BODY_MARKER in codec_src, (
        f"{layer_root}/decimal_scalar.py is missing the canonical coercion body"
    )


@ac_proof(
    proof_id="test_common_base_packages_share_one_scalar_codec",
    ac_ids=["AC-audit.36.1"],
    ci_tier="pr_ci",
)
def test_AC12_36_1_common_base_packages_share_one_scalar_codec():
    """AC-audit.36.1: common.audit.decimal_scalar bridges to the single shared scalar codec."""
    from src.audit.decimal_scalar import coerce_decimal as backend_coerce

    assert coerce_decimal is backend_coerce
    _assert_layer_shares_one_coercion("apps/backend/src", "src.audit")


@ac_proof(
    proof_id="test_backend_base_packages_share_one_scalar_codec",
    ac_ids=["AC-audit.36.2"],
    ci_tier="pr_ci",
)
def test_AC12_36_2_backend_base_packages_share_one_scalar_codec():
    """AC-audit.36.2: the backend mirror shares one src.audit.decimal_scalar coercion."""
    _assert_layer_shares_one_coercion("apps/backend/src", "src.audit")


# ── behavioural coverage of the shared coercion (common layer) ───────────────


class _FloatError(TypeError):
    pass


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
