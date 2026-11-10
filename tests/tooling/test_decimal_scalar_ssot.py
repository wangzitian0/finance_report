'EPIC-012'; from __future__ import annotations; from decimal import Decimal; from pathlib import Path; import pytest; from common.testing.ac_proof import ac_proof; from common.audit.decimal_scalar import coerce_decimal; REPO = Path(__file__).resolve().parents[2]; _COERCE_BODY_MARKER = 'IEEE-754 precision loss'; _read = lambda rel: (REPO / rel).read_text(encoding='utf-8')
def _assert_layer_shares_one_coercion(layer_root: str, import_prefix: str) -> None:
    core_modules = {'money': f'{layer_root}/audit/money/money.py', 'money.exchange_rate': f'{layer_root}/audit/money/exchange_rate.py', 'quantity': f'{layer_root}/audit/quantity/quantity.py', 'ratio': f'{layer_root}/audit/ratio/ratio.py', 'unit_price': f'{layer_root}/audit/unit_price/unit_price.py'}
    for (pkg, rel) in core_modules.items(): src = _read(rel); assert f'from {import_prefix}.decimal_scalar import coerce_decimal' in src, f'{rel} must import the shared coercion'; assert 'coerce_decimal(' in src, f'{rel} must coerce via the shared coercion'; assert _COERCE_BODY_MARKER not in src, f'{rel} still inlines the _coerce float-rejection body'
    codec_src = _read(f'{layer_root}/audit/decimal_scalar.py'); assert 'def coerce_decimal(' in codec_src; assert _COERCE_BODY_MARKER in codec_src, f'{layer_root}/decimal_scalar.py is missing the canonical coercion body'
@ac_proof(proof_id='test_common_base_packages_share_one_scalar_codec', ac_ids=['AC-audit.36.1'], ci_tier='pr_ci')
def test_AC12_36_1_common_base_packages_share_one_scalar_codec(): 'AC-audit.36.1'; from src.audit.decimal_scalar import coerce_decimal as backend_coerce; assert coerce_decimal is backend_coerce; _assert_layer_shares_one_coercion('apps/backend/src', 'src.audit')
@ac_proof(proof_id='test_backend_base_packages_share_one_scalar_codec', ac_ids=['AC-audit.36.2'], ci_tier='pr_ci')
def test_AC12_36_2_backend_base_packages_share_one_scalar_codec(): 'AC-audit.36.2'; _assert_layer_shares_one_coercion('apps/backend/src', 'src.audit')
class _FloatError(TypeError): pass
def test_coerce_decimal_accepts_decimal_and_int():
    assert coerce_decimal(Decimal('1.25'), 'x', float_error=_FloatError) == Decimal('1.25'); assert coerce_decimal(7, 'x', float_error=_FloatError) == Decimal('7')
    for _m1_bad in (True, 1.5, '1.5', None):
        with pytest.raises(_FloatError): coerce_decimal(_m1_bad, 'x', float_error=_FloatError)
    assert coerce_decimal(Decimal('NaN'), 'x', float_error=_FloatError).is_nan()
    for _m2_bad in (Decimal('NaN'), Decimal('Infinity')):
        with pytest.raises(_FloatError): coerce_decimal(_m2_bad, 'x', float_error=_FloatError, require_finite=True)
