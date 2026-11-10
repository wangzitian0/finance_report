'EPIC-012'; from decimal import Decimal; from uuid import uuid4; import pytest; from common.testing.ac_proof import ac_proof; from src.audit.money import Money; from src.ledger import DegenerateEntryError, Direction, Entry, Leg, UnbalancedEntryError; pytestmark = pytest.mark.no_db; A, B, C = (uuid4(), uuid4(), uuid4()); _m = lambda x, ccy='USD': Money(Decimal(x), ccy)
@ac_proof(proof_id='test_entry_balances', ac_ids=['AC-ledger.34.1'], ci_tier='pr_ci')
def test_AC12_34_1_balanced_entry_constructs(): 'AC-ledger.34.1'; e = Entry.transfer(debit=A, credit=B, money=_m('10.00')); assert len(e.legs) == 2; e3 = Entry.of(Leg(A, Direction.DEBIT, _m('100.00')), Leg(B, Direction.CREDIT, _m('80.00')), Leg(C, Direction.CREDIT, _m('20.00'))); assert len(e3.legs) == 3
@ac_proof(proof_id='test_entry_unbalanced_raises', ac_ids=['AC-ledger.34.1'], ci_tier='pr_ci')
def test_AC12_34_1_unbalanced_entry_is_unconstructable():
    'AC-ledger.34.1'
    with pytest.raises(UnbalancedEntryError): Entry.of(Leg(A, Direction.DEBIT, _m('100.00')), Leg(B, Direction.CREDIT, _m('80.00')))
    with pytest.raises(DegenerateEntryError): Entry.of()
    with pytest.raises(DegenerateEntryError): Entry.of(Leg(A, Direction.DEBIT, _m('10.00')))
@ac_proof(proof_id='test_entry_per_currency', ac_ids=['AC-ledger.34.1'], ci_tier='pr_ci')
def test_AC12_34_1_balance_is_checked_per_currency():
    'AC-ledger.34.1'; ok = Entry.of(Leg(A, Direction.DEBIT, _m('10.00', 'USD')), Leg(B, Direction.CREDIT, _m('10.00', 'USD')), Leg(A, Direction.DEBIT, _m('5.00', 'SGD')), Leg(B, Direction.CREDIT, _m('5.00', 'SGD'))); assert len(ok.legs) == 4
    with pytest.raises(UnbalancedEntryError): Entry.of(Leg(A, Direction.DEBIT, _m('10.00', 'USD')), Leg(B, Direction.CREDIT, _m('10.00', 'SGD')))
@ac_proof(proof_id='test_entry_leg_positive', ac_ids=['AC-ledger.34.1'], ci_tier='pr_ci')
def test_AC12_34_1_legs_must_be_positive():
    'AC-ledger.34.1'
    with pytest.raises(UnbalancedEntryError): Leg(A, Direction.DEBIT, _m('0.00'))
    with pytest.raises(UnbalancedEntryError): Leg(A, Direction.DEBIT, _m('-1.00'))
@ac_proof(proof_id='test_entry_leg_direction', ac_ids=['AC-ledger.34.1'], ci_tier='pr_ci')
def test_AC12_34_1_leg_direction_must_be_typed():
    'AC-ledger.34.1'
    with pytest.raises(TypeError): Leg(A, 'DEBIT', _m('10.00'))
