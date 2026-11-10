'EPIC-012'; from decimal import ROUND_HALF_EVEN, Decimal; import pytest; from common.audit.quantity import QUANTITY_DP, QUANTITY_QUANTUM, QUANTITY_ROUNDING, FloatNotAllowedError, InvalidUnitError, Quantity, QuantityError, Unit, UnitMismatchError; from common.audit.ratio import Ratio; from common.testing.ac_proof import ac_proof
@ac_proof(proof_id='test_quantity_rejects_float', ac_ids=['AC-audit.30.1'], ci_tier='pr_ci')
def test_AC12_30_1_quantity_rejects_float_and_is_decimal_backed():
    'AC-audit.30.1'
    with pytest.raises(FloatNotAllowedError): Quantity(0.125, 'shares')
    with pytest.raises(FloatNotAllowedError): Quantity(True, 'shares')
    with pytest.raises(FloatNotAllowedError): Quantity('0.1', 'shares')
    assert isinstance(Quantity(1, 'shares').value, Decimal); q = Quantity(Decimal('0.125'), 'shares')
    with pytest.raises((AttributeError, TypeError)): q.value = Decimal('0.2')
    with pytest.raises(FloatNotAllowedError): q * 1.5
    with pytest.raises(FloatNotAllowedError): q * Decimal('NaN')
    with pytest.raises(FloatNotAllowedError): q * Decimal('Infinity')
@ac_proof(proof_id='test_quantity_unit_validation', ac_ids=['AC-audit.30.1'], ci_tier='pr_ci')
def test_AC12_30_1_unit_rejects_invalid_and_normalizes():
    'AC-audit.30.1'; assert Unit(' shares ').code == 'shares'; assert Unit('UNITS').code == 'units'
    for bad in ('', '   ', 'share lot', 'shares/usd', '1shares'):
        with pytest.raises(InvalidUnitError): Unit(bad)
    assert isinstance(InvalidUnitError('x'), QuantityError)
@ac_proof(proof_id='test_quantity_quantize_policy', ac_ids=['AC-audit.30.1'], ci_tier='pr_ci')
def test_AC12_30_1_quantize_is_six_dp_half_up(): 'AC-audit.30.1'; assert QUANTITY_DP == 6; assert QUANTITY_QUANTUM == Decimal('0.000001'); assert QUANTITY_ROUNDING != ROUND_HALF_EVEN; assert Quantity(Decimal('1.2345675'), 'shares').quantize() == Quantity(Decimal('1.234568'), 'shares'); assert Quantity(Decimal('0.0000005'), 'shares').quantize() == Quantity(Decimal('0.000001'), 'shares')
@ac_proof(proof_id='test_quantity_arithmetic', ac_ids=['AC-audit.30.1'], ci_tier='pr_ci')
def test_AC12_30_1_same_unit_arithmetic_compare_and_zero():
    'AC-audit.30.1'; a, b = (Quantity(Decimal('1.25'), 'shares'), Quantity(Decimal('2.75'), 'shares')); assert a + b == Quantity(Decimal('4.00'), 'shares'); assert b - a == Quantity(Decimal('1.50'), 'shares'); assert -a == Quantity(Decimal('-1.25'), 'shares'); assert abs(Quantity(Decimal('-3'), 'shares')) == Quantity(Decimal('3'), 'shares'); assert a * 2 == Quantity(Decimal('2.50'), 'shares'); assert 2 * a == Quantity(Decimal('2.50'), 'shares'); assert a < b and a <= b and (b > a) and (b >= a); assert Quantity.zero('shares').is_zero()
    with pytest.raises(UnitMismatchError): _ = a + Quantity(Decimal('1'), 'contracts')
    with pytest.raises(TypeError): _ = a + Decimal('1')
@ac_proof(proof_id='test_quantity_ratio', ac_ids=['AC-audit.30.1'], ci_tier='pr_ci')
def test_AC12_30_1_same_unit_ratio_derivation():
    'AC-audit.30.1'; part = Quantity(Decimal('2'), 'shares'); whole = Quantity(Decimal('8'), 'shares'); assert part.ratio_to(whole) == Ratio(Decimal('0.25')); assert part / whole == Ratio(Decimal('0.25'))
    with pytest.raises(UnitMismatchError): part.ratio_to(Quantity(Decimal('8'), 'contracts'))
    with pytest.raises(ZeroDivisionError): part.ratio_to(Quantity.zero('shares'))
