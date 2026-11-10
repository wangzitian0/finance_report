'AC-counter.1.2 EPIC-025'; import pytest; from common.testing.ac_proof import ac_proof; from src.counter import Count, NegativeCountError; pytestmark = pytest.mark.no_db
@ac_proof(proof_id='test_count_non_negative_ok', ac_ids=['AC-counter.1.2'], ci_tier='pr_ci')
def test_count_accepts_zero_and_positive(): 'AC-counter.1.2'; assert int(Count(0)) == 0; assert int(Count(7)) == 7; assert Count(3) < Count(4); assert Count(5) == Count(5)
@ac_proof(proof_id='test_count_non_negative_raises', ac_ids=['AC-counter.1.2'], ci_tier='pr_ci')
def test_count_rejects_negative():
    'AC-counter.1.2'
    with pytest.raises(NegativeCountError): Count(-1)
    with pytest.raises(NegativeCountError): Count(True)
