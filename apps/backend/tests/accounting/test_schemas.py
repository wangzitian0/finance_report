'AC-ledger.9.1 AC-ledger.9.2 AC-ledger.9.3 AC-ledger.9.4'; from datetime import date; from decimal import Decimal; from uuid import uuid4; import pytest; from pydantic import ValidationError; from src.ledger import AccountType, Direction; from src.schemas import AccountCreate, AccountUpdate, JournalEntryCreate, JournalLineCreate, VoidJournalEntryRequest
class TestAccountSchemas:
    def test_account_create_valid(self):
        account = AccountCreate(name='Test Account', type=AccountType.ASSET, currency='SGD'); assert account.name == 'Test Account'; assert account.type == AccountType.ASSET; assert account.currency == 'SGD'; _m1_account = AccountCreate(name='Full Account', code='1100', type=AccountType.LIABILITY, currency='USD', description='Test description'); assert _m1_account.code == '1100'; assert _m1_account.description == 'Test description'
        with pytest.raises(ValidationError): AccountCreate(name='', type=AccountType.ASSET, currency='SGD')
        with pytest.raises(ValidationError): AccountCreate(name='Test', type=AccountType.ASSET, currency='SGDX')
        _m4_update = AccountUpdate(name='New Name'); assert _m4_update.name == 'New Name'; assert _m4_update.code is None; assert _m4_update.is_active is None
class TestJournalLineSchemas:
    def test_journal_line_create_valid(self):
        line = JournalLineCreate(account_id=uuid4(), direction=Direction.DEBIT, amount=Decimal('100.50'), currency='SGD'); assert line.amount == Decimal('100.50'); assert line.direction == Direction.DEBIT
        with pytest.raises(ValidationError): JournalLineCreate(account_id=uuid4(), direction=Direction.DEBIT, amount=Decimal('0'), currency='SGD')
        with pytest.raises(ValidationError): JournalLineCreate(account_id=uuid4(), direction=Direction.CREDIT, amount=Decimal('-10.00'), currency='SGD')
        _m2_line = JournalLineCreate(account_id=uuid4(), direction=Direction.CREDIT, amount=Decimal('1000.00'), currency='USD', fx_rate=Decimal('1.35')); assert _m2_line.fx_rate == Decimal('1.35')
class TestJournalEntrySchemas:
    def test_journal_entry_create_balanced(self):
        account1 = uuid4(); account2 = uuid4(); entry = JournalEntryCreate(entry_date=date.today(), memo='Test entry', lines=[JournalLineCreate(account_id=account1, direction=Direction.DEBIT, amount=Decimal('100.00'), currency='SGD'), JournalLineCreate(account_id=account2, direction=Direction.CREDIT, amount=Decimal('100.00'), currency='SGD')]); assert len(entry.lines) == 2; _m1_account1 = uuid4(); _m1_account2 = uuid4(); _m1_entry = JournalEntryCreate(entry_date=date.today(), memo='Unbalanced', lines=[JournalLineCreate(account_id=_m1_account1, direction=Direction.DEBIT, amount=Decimal('100.00'), currency='SGD'), JournalLineCreate(account_id=_m1_account2, direction=Direction.CREDIT, amount=Decimal('50.00'), currency='SGD')]); assert len(_m1_entry.lines) == 2
        with pytest.raises(ValidationError): JournalEntryCreate(entry_date=date.today(), memo='Single line', lines=[JournalLineCreate(account_id=uuid4(), direction=Direction.DEBIT, amount=Decimal('100.00'), currency='SGD')])
        with pytest.raises(ValidationError): JournalEntryCreate(entry_date=date.today(), memo='No lines', lines=[])
        _m4_account1 = uuid4(); _m4_account2 = uuid4(); _m4_entry = JournalEntryCreate(entry_date=date.today(), memo='Near balanced', lines=[JournalLineCreate(account_id=_m4_account1, direction=Direction.DEBIT, amount=Decimal('100.00'), currency='SGD'), JournalLineCreate(account_id=_m4_account2, direction=Direction.CREDIT, amount=Decimal('100.01'), currency='SGD')]); assert _m4_entry is not None
class TestVoidRequest:
    def test_void_request_valid(self):
        request = VoidJournalEntryRequest(reason='Test void reason'); assert request.reason == 'Test void reason'
        with pytest.raises(ValidationError): VoidJournalEntryRequest(reason='')
