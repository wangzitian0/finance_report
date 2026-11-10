'AC-extraction.122.1 EPIC-026 EPIC-003'; from __future__ import annotations; from datetime import date; from decimal import Decimal; from uuid import UUID; from src.extraction import TransactionDirection; from src.extraction.base.validation import BALANCE_TOLERANCE, validate_balance; from src.extraction.extension.deduplication import DeduplicationService
def _make_statement(opening: Decimal, ins: list[Decimal], outs: list[Decimal]) -> dict: net = sum(ins, Decimal('0')) - sum(outs, Decimal('0')); txns = [{'amount': str(a), 'direction': 'IN'} for a in ins]; txns += [{'amount': str(a), 'direction': 'OUT'} for a in outs]; return {'opening_balance': str(opening), 'closing_balance': str(opening + net), 'transactions': txns}
_BALANCED_CASES = [(Decimal('0.00'), [Decimal('100.00')], []), (Decimal('1000.00'), [Decimal('200.00'), Decimal('50.00')], [Decimal('75.00')]), (Decimal('-50.00'), [Decimal('500.00')], [Decimal('499.99')]), (Decimal('9999.99'), [], [Decimal('9999.99')]), (Decimal('123.45'), [Decimal('10.10'), Decimal('20.20'), Decimal('30.30')], [Decimal('5.05'), Decimal('15.15')]), (Decimal('1000000.00'), [Decimal('0.01')] * 50, [Decimal('0.02')] * 25)]
class TestBalanceChainInvariantLP:
    'AC-extraction.1.1 AC-extraction.5.7 AC-extraction.5.19'
    def test_balance_chain_invariant_holds_for_consistent_statements(self):
        'AC-extraction.1.1 AC-extraction.5.7'
        for (opening, ins, outs) in _BALANCED_CASES: extracted = _make_statement(opening, ins, outs); result = validate_balance(extracted); net = sum(ins, Decimal('0')) - sum(outs, Decimal('0')); expected_closing = opening + net; assert result['balance_valid'] is True, f'chain should validate for opening={opening} net={net}: {result}'; assert Decimal(str(extracted['closing_balance'])) == expected_closing
        'AC-extraction.5.19'; 'AC-extraction.5.19'
        for (_m1_opening, _m1_ins, _m1_outs) in _BALANCED_CASES: _m1_extracted = _make_statement(_m1_opening, _m1_ins, _m1_outs); _m1_consistent_closing = Decimal(str(_m1_extracted['closing_balance'])); _m1_extracted['closing_balance'] = str(_m1_consistent_closing + BALANCE_TOLERANCE + Decimal('1.00')); _m1_result = validate_balance(_m1_extracted); assert _m1_result['balance_valid'] is False, f'broken chain must be flagged for opening={_m1_opening}: {_m1_result}'
        'AC-extraction.1.1'; 'AC-extraction.1.1'; _m2_base = _make_statement(Decimal('1000.00'), [Decimal('100.00')], []); _m2_computed = Decimal(str(_m2_base['closing_balance']))
        for _m2_delta in (BALANCE_TOLERANCE, -BALANCE_TOLERANCE): _m2_base['closing_balance'] = str(_m2_computed + _m2_delta); assert validate_balance(_m2_base)['balance_valid'] is True
class TestDedupConservationLP:
    'AC-extraction.5.19 AC-extraction.122.1'; _USER = UUID('00000000-0000-0000-0000-000000000001')
    def _hash(self, occurrence_index: int, balance_after: Decimal | None) -> str: return DeduplicationService.calculate_transaction_hash(user_id=self._USER, txn_date=date(2025, 1, 15), amount=Decimal('100.00'), direction=TransactionDirection.IN, description='SALARY', reference=None, balance_after=balance_after, occurrence_index=occurrence_index)
    def test_distinct_same_amount_rows_never_collapse(self):
        'AC-extraction.5.19'
        for n in range(1, 13):
            for balance_after in (None, Decimal('100.00')): hashes = {self._hash(i, balance_after) for i in range(n)}; assert len(hashes) == n, f'{n} distinct rows collapsed to {len(hashes)} (balance_after={balance_after}) — #1254 regression'
        'AC-extraction.5.19'; 'AC-extraction.5.19'; assert all((self._hash(0, _m1_balance_after) == self._hash(0, _m1_balance_after) and self._hash(3, _m1_balance_after) == self._hash(3, _m1_balance_after) for _m1_balance_after in (None, Decimal('100.00'))))
