from decimal import Decimal; import pytest; from common.audit.money import Currency, ExchangeRate, InvalidCurrencyError, Money, convert; from common.audit.money.conformance import load_vectors; from common.testing.ac_proof import ac_proof; VECTORS = load_vectors()
@ac_proof(proof_id='test_money_conformance_rounding', ac_ids=['AC-audit.20.1'], ci_tier='pr_ci', issue='#1170')
@pytest.mark.parametrize('case', VECTORS['rounding'], ids=lambda c: f"{c['amount']}/{c['rounding']}")
def test_AC2_20_1_conformance_rounding(case): 'AC-audit.20.1'; got = Money(Decimal(case['amount']), 'USD').quantize(case['rounding']).amount; assert got == Decimal(case['expected']), case
@ac_proof(proof_id='test_money_conformance_convert', ac_ids=['AC-audit.20.1'], ci_tier='pr_ci', issue='#1170')
@pytest.mark.parametrize('case', VECTORS['convert'], ids=lambda c: f"{c['amount']}*{c['rate']}")
def test_AC2_20_1_conformance_convert(case): 'AC-audit.20.1'; result = convert(Money(Decimal(case['amount']), case['from']), ExchangeRate(case['from'], case['to'], Decimal(case['rate'])), rounding=case['rounding']); assert result.amount == Decimal(case['expected']), case; assert result.currency.code == case['to'], case
@ac_proof(proof_id='test_money_conformance_currency', ac_ids=['AC-audit.19.1'], ci_tier='pr_ci', issue='#1170')
def test_AC2_19_1_conformance_currency_validation():
    'AC-audit.19.1'
    for case in VECTORS['currency_normalize']: assert Currency(case['input']).code == case['expected'], case
    for bad in VECTORS['currency_invalid']:
        with pytest.raises(InvalidCurrencyError): Currency(bad)
def test_money_quantum_matches_standard(): from common.audit.money import MONEY_QUANTUM; assert str(MONEY_QUANTUM) == VECTORS['money_quantum']; assert VECTORS['default_rounding'] == 'ROUND_HALF_EVEN'
@ac_proof(proof_id='test_money_conformance_iso_set_parity', ac_ids=['AC-audit.19.1'], ci_tier='pr_ci', issue='#1170')
def test_AC2_19_1_iso_currency_set_matches_standard(): 'AC-audit.19.1'; from common.audit.money.currency import ISO_4217_CODES; assert ISO_4217_CODES == set(VECTORS['iso4217'])
