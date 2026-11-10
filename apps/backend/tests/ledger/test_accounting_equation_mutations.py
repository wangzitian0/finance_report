'AC-ledger.2.1'; from decimal import Decimal; from uuid import uuid4; import pytest; from src.audit.money import Money; from src.ledger import Direction, JournalLine, Leg, UnbalancedEntryError, ValidationError, validate_fx_rates, validate_journal_balance; pytestmark = pytest.mark.no_db; _make_line = lambda *, direction, amount, currency='SGD', fx_rate=None: JournalLine(id=uuid4(), journal_entry_id=uuid4(), account_id=uuid4(), direction=direction, amount=amount, currency=currency, fx_rate=fx_rate)
def test_imbalance_exceeding_tolerance_is_strictly_rejected():
    lines = [_make_line(direction=Direction.DEBIT, amount=Decimal('100.00')), _make_line(direction=Direction.CREDIT, amount=Decimal('100.00'))]; validate_journal_balance(lines); imbalanced_debit = [_make_line(direction=Direction.DEBIT, amount=Decimal('100.02')), _make_line(direction=Direction.CREDIT, amount=Decimal('100.00'))]
    with pytest.raises(ValidationError, match='Journal entry not balanced'): validate_journal_balance(imbalanced_debit)
    imbalanced_credit = [_make_line(direction=Direction.DEBIT, amount=Decimal('100.00')), _make_line(direction=Direction.CREDIT, amount=Decimal('99.98'))]
    with pytest.raises(ValidationError, match='Journal entry not balanced'): validate_journal_balance(imbalanced_credit)
    _m1_only_debits = [_make_line(direction=Direction.DEBIT, amount=Decimal('50.00')), _make_line(direction=Direction.DEBIT, amount=Decimal('50.00'))]
    with pytest.raises(ValidationError, match='Journal entry not balanced'): validate_journal_balance(_m1_only_debits)
    _m1_only_credits = [_make_line(direction=Direction.CREDIT, amount=Decimal('100.00'))]
    with pytest.raises(ValidationError, match='Journal entry must have at least 2 lines'): validate_journal_balance(_m1_only_credits)
    _m2_account_id = uuid4()
    with pytest.raises(UnbalancedEntryError): Leg(_m2_account_id, Direction.DEBIT, Money(Decimal('0.00'), 'SGD'))
    with pytest.raises(UnbalancedEntryError): Leg(_m2_account_id, Direction.DEBIT, Money(Decimal('-10.00'), 'SGD'))
    with pytest.raises(ValidationError, match='Journal entry must have at least 2 lines'): validate_journal_balance([])
    _m4_lines_missing_fx = [_make_line(direction=Direction.DEBIT, amount=Decimal('100.00'), currency='USD', fx_rate=None), _make_line(direction=Direction.CREDIT, amount=Decimal('130.00'), currency='SGD', fx_rate=Decimal('1.0'))]
    with pytest.raises(ValidationError, match='fx_rate required for currency USD'): validate_fx_rates(_m4_lines_missing_fx, base_currency='SGD')
def test_concurrent_journal_line_mutation_race():
    from concurrent.futures import ThreadPoolExecutor
    def _worker(worker_id: int) -> bool:
        is_balanced = worker_id % 2 == 0; amt_credit = Decimal('100.00') if is_balanced else Decimal('90.00'); lines = [_make_line(direction=Direction.DEBIT, amount=Decimal('100.00')), _make_line(direction=Direction.CREDIT, amount=amt_credit)]
        try: validate_journal_balance(lines); return True
        except ValidationError: return False
    with ThreadPoolExecutor(max_workers=8) as pool: results = list(pool.map(_worker, range(100)))
    assert sum(results) == 50
    for (idx, passed) in enumerate(results): expected = idx % 2 == 0; assert passed is expected, f'Worker {idx} expectation mismatch: got {passed}, expected {expected}'
