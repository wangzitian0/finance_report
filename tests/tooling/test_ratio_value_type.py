'EPIC-012'; from decimal import ROUND_HALF_EVEN, Decimal; import pytest; from common.audit.ratio import PERCENT_DP, PERCENT_ROUNDING, FloatNotAllowedError, Ratio, RatioError, UndefinedRatioError; from common.testing.ac_proof import ac_proof
@ac_proof(proof_id='test_ratio_rejects_float', ac_ids=['AC-audit.9.1'], ci_tier='pr_ci', issue='#1167')
def test_AC12_9_1_ratio_rejects_float_and_is_decimal_backed():
    'AC-audit.9.1'
    with pytest.raises(FloatNotAllowedError): Ratio(0.125)
    with pytest.raises(FloatNotAllowedError): Ratio(True)
    with pytest.raises(FloatNotAllowedError): Ratio('0.1')
    assert isinstance(Ratio(1).value, Decimal); r = Ratio(Decimal('0.125'))
    with pytest.raises((AttributeError, TypeError)): r.value = Decimal('0.2')
@ac_proof(proof_id='test_ratio_percent_policy', ac_ids=['AC-audit.9.1'], ci_tier='pr_ci', issue='#1167')
def test_AC12_9_1_percent_display_is_half_up_two_dp(): 'AC-audit.9.1'; assert PERCENT_DP == 2; assert PERCENT_ROUNDING != ROUND_HALF_EVEN; assert Ratio(Decimal('0.12005')).to_percent() == Decimal('12.01'); assert Ratio(Decimal('0.125')).to_percent() == Decimal('12.50'); assert Ratio(Decimal('0.125')).format_percent() == '12.50%'; assert Ratio(Decimal('0.123455')).to_percent(4) == Decimal('12.3455')
@ac_proof(proof_id='test_ratio_fraction', ac_ids=['AC-audit.9.1'], ci_tier='pr_ci', issue='#1167')
def test_AC12_9_1_fraction_and_zero_whole_is_undefined():
    'AC-audit.9.1'; assert Ratio.fraction(1, 8).to_percent() == Decimal('12.50'); assert Ratio.fraction(Decimal('2'), Decimal('3')).to_percent() == Decimal('66.67'); assert Ratio.from_percent(Decimal('12.5')).to_percent() == Decimal('12.50')
    with pytest.raises(UndefinedRatioError): Ratio.fraction(1, 0)
    assert isinstance(UndefinedRatioError('x'), RatioError)
@ac_proof(proof_id='test_ratio_arithmetic', ac_ids=['AC-audit.9.1'], ci_tier='pr_ci', issue='#1167')
def test_AC12_9_1_dimensionless_arithmetic_and_compare():
    'AC-audit.9.1'; a, b = (Ratio(Decimal('0.1')), Ratio(Decimal('0.2'))); assert a + b == Ratio(Decimal('0.3')); assert b - a == Ratio(Decimal('0.1')); assert -a == Ratio(Decimal('-0.1')); assert a * 3 == Ratio(Decimal('0.3')); assert 3 * a == Ratio(Decimal('0.3')); assert a < b and a <= b and (b > a) and (b >= a); assert str(Ratio(Decimal('0.5'))) == '50.00%'; assert Ratio.zero() == Ratio(Decimal('0')); assert Ratio.zero().is_zero(); assert not a.is_zero()
    with pytest.raises(TypeError): _ = a + 0.1
