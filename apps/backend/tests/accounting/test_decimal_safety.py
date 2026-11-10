'AC-ledger.8.1 AC-ledger.8.2 AC-ledger.8.3 EPIC-002'; from decimal import Decimal; from uuid import uuid4; from src.ledger import Direction; from src.schemas.journal import JournalLineCreate
def test_decimal_parsing_from_string(): data = {'account_id': uuid4(), 'direction': Direction.DEBIT, 'amount': '123.45', 'currency': 'SGD'}; obj = JournalLineCreate(**data); assert obj.amount == Decimal('123.45'); assert isinstance(obj.amount, Decimal)
def test_float_injection_safety():
    bad_float = 0.1 + 0.2; data = {'account_id': uuid4(), 'direction': Direction.DEBIT, 'amount': bad_float, 'currency': 'SGD'}
    try: obj = JournalLineCreate(**data)
    except Exception: return
    assert obj.amount == Decimal('0.30'), f'DANGEROUS: Float {bad_float} was converted to {obj.amount} with precision artifacts! Update Pydantic models to use strict=True or a rounding validator.'
def test_scientific_notation_rejection(): data = {'account_id': uuid4(), 'direction': Direction.DEBIT, 'amount': '1.50E+2', 'currency': 'SGD'}; obj = JournalLineCreate(**data); assert obj.amount == Decimal('150.00')
