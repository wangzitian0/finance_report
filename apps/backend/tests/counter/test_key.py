'AC-counter.1.1 EPIC-025'; import pytest; from common.testing.ac_proof import ac_proof; from src.counter import CounterKey, InvalidCounterKeyError; pytestmark = pytest.mark.no_db
@ac_proof(proof_id='test_counter_key_valid', ac_ids=['AC-counter.1.1'], ci_tier='pr_ci')
def test_counter_key_accepts_valid(): 'AC-counter.1.1'; assert all((str(CounterKey(value)) == value for value in ('report.generated', 'statement.uploaded', 'a.b.c', 'user.signed_in')))
@ac_proof(proof_id='test_counter_key_invalid', ac_ids=['AC-counter.1.1'], ci_tier='pr_ci')
def test_counter_key_rejects_invalid():
    'AC-counter.1.1'; invalid = ['', 'report', 'Report.Generated', 'report..generated', '.report', 'report.', 'report generated', 'report-generated', '1report.generated']
    for value in invalid:
        with pytest.raises(InvalidCounterKeyError): CounterKey(value)
@ac_proof(proof_id='test_counter_key_value_object', ac_ids=['AC-counter.1.1'], ci_tier='pr_ci')
def test_counter_key_is_frozen_value_object():
    'AC-counter.1.1'; a, b = (CounterKey('report.generated'), CounterKey('report.generated')); assert a == b; assert hash(a) == hash(b); assert len({a, b}) == 1
    with pytest.raises(Exception): a.value = 'other.key'
