'EPIC-012'; from decimal import Decimal; import pytest; from common.audit.quantity import QUANTITY_DP, QUANTITY_QUANTUM, QUANTITY_ROUNDING, InvalidUnitError, Quantity, Unit; from common.audit.quantity.conformance import load_vectors; from common.testing.ac_proof import ac_proof; VECTORS = load_vectors()
@ac_proof(proof_id='test_quantity_conformance_quantize', ac_ids=['AC-audit.30.2'], ci_tier='pr_ci')
@pytest.mark.parametrize('case', VECTORS['quantize'], ids=lambda c: f"{c['value']}/{c['unit']}")
def test_AC12_30_2_quantity_quantize_matches_standard(case): 'AC-audit.30.2'; assert Quantity(Decimal(case['value']), case['unit']).quantize().value == Decimal(case['expected']), case
@ac_proof(proof_id='test_quantity_conformance_units', ac_ids=['AC-audit.30.2'], ci_tier='pr_ci')
def test_AC12_30_2_quantity_unit_validation_matches_standard():
    'AC-audit.30.2'
    for case in VECTORS['unit_normalize']: assert Unit(case['input']).code == case['expected'], case
    for bad in VECTORS['unit_invalid']:
        with pytest.raises(InvalidUnitError): Unit(bad)
@ac_proof(proof_id='test_quantity_conformance_ratio', ac_ids=['AC-audit.30.2'], ci_tier='pr_ci')
def test_AC12_30_2_quantity_ratio_matches_standard():
    'AC-audit.30.2'
    for case in VECTORS['ratio']: got = Quantity(Decimal(case['part']), case['unit']).ratio_to(Quantity(Decimal(case['whole']), case['unit'])); assert str(got.value) == case['expected_ratio'], case; assert got.to_percent() == Decimal(case['expected_percent_2dp']), case
    assert str(QUANTITY_QUANTUM) == VECTORS['quantity_quantum']; assert QUANTITY_DP == VECTORS['quantity_dp']; assert QUANTITY_ROUNDING == VECTORS['default_rounding']
