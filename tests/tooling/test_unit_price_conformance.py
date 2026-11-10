'EPIC-012'; from decimal import Decimal; import pytest; from common.audit.money import Money; from common.audit.quantity import Quantity; from common.audit.unit_price import UNIT_PRICE_DP, UNIT_PRICE_QUANTUM, UNIT_PRICE_ROUNDING, UndefinedUnitPriceError, UnitMismatchError, UnitPrice; from common.audit.unit_price.conformance import load_vectors; from common.testing.ac_proof import ac_proof; VECTORS = load_vectors()
@ac_proof(proof_id='test_unit_price_conformance_constants', ac_ids=['AC-audit.32.2'], ci_tier='pr_ci')
def test_AC12_32_2_unit_price_policy_matches_standard(): 'AC-audit.32.2'; assert str(UNIT_PRICE_QUANTUM) == VECTORS['unit_price_quantum']; assert UNIT_PRICE_DP == VECTORS['unit_price_dp']; assert UNIT_PRICE_ROUNDING == VECTORS['default_rounding']
@ac_proof(proof_id='test_unit_price_conformance_quantize', ac_ids=['AC-audit.32.2'], ci_tier='pr_ci')
@pytest.mark.parametrize('case', VECTORS['quantize'], ids=lambda c: f"{c['rate']}/{c['unit']}")
def test_AC12_32_2_unit_price_quantize_matches_standard(case): 'AC-audit.32.2'; got = UnitPrice(Decimal(case['rate']), case['currency'], case['unit']).quantize(); assert got.rate == Decimal(case['expected']), case
@ac_proof(proof_id='test_unit_price_conformance_product', ac_ids=['AC-audit.32.2'], ci_tier='pr_ci')
@pytest.mark.parametrize('case', VECTORS['product'], ids=lambda c: f"{c['rate']}x{c['quantity']}")
def test_AC12_32_2_unit_price_product_matches_standard(case): 'AC-audit.32.2'; price = UnitPrice(Decimal(case['rate']), case['currency'], case['unit']); money = price * Quantity(Decimal(case['quantity']), case['unit']); assert money == Money(Decimal(case['expected_amount']), case['currency']), case
@ac_proof(proof_id='test_unit_price_conformance_from_total', ac_ids=['AC-audit.32.2'], ci_tier='pr_ci')
@pytest.mark.parametrize('case', VECTORS['from_total'], ids=lambda c: f"{c['amount']}/{c['quantity']}")
def test_AC12_32_2_unit_price_from_total_matches_standard(case): 'AC-audit.32.2'; derived = UnitPrice.from_total(Money(Decimal(case['amount']), case['currency']), Quantity(Decimal(case['quantity']), case['unit'])); assert derived.quantize().rate == Decimal(case['expected_rate_6dp']), case
@ac_proof(proof_id='test_unit_price_conformance_errors', ac_ids=['AC-audit.32.2'], ci_tier='pr_ci')
def test_AC12_32_2_unit_price_error_cases_match_standard():
    'AC-audit.32.2'
    for case in VECTORS['from_total_undefined']:
        with pytest.raises(UndefinedUnitPriceError): UnitPrice.from_total(Money(Decimal(case['amount']), case['currency']), Quantity(Decimal(case['quantity']), case['unit']))
    for case in VECTORS['unit_mismatch']:
        with pytest.raises(UnitMismatchError): UnitPrice(Decimal(case['rate']), case['currency'], case['unit']) * Quantity(Decimal(case['quantity']), case['quantity_unit'])
