from datetime import date; from decimal import Decimal; from uuid import uuid4; import pytest; from src.audit import JournalEntrySourceType; from src.ledger import Direction; from src.portfolio import InvestmentAccountingService, InvestmentAccountingValidationError; from src.reporting.extension.reporting_calc import _provenance_from_source_type, _quantize_money, income_bucket; from src.schemas.journal import JournalEntryCreate, JournalLineCreate
class TestReportingHelpers:
    'AC11.8.1'
    def test_income_bucket_classifies_known_keywords(self): assert income_bucket('Monthly Salary') == 'salary'; assert income_bucket('Annual Bonus') == 'bonus'; assert income_bucket('Dividend payout') == 'dividend'; assert income_bucket('grocery refund') is None; _m2_result = _quantize_money(5); assert _m2_result == Decimal('5.00'); assert _quantize_money(Decimal('1.005')) == Decimal('1.00')
    @pytest.mark.parametrize(('source_type', 'expected'), [(JournalEntrySourceType.MANUAL, 'manual'), ('bank_statement', 'imported'), (JournalEntrySourceType.SYSTEM, 'derived'), (JournalEntrySourceType.FX_REVALUATION, 'derived'), ('manual', 'manual'), (None, None), ('not-a-valid-source', None)])
    def test_provenance_from_source_type(self, source_type, expected): assert _provenance_from_source_type(source_type) == expected
class TestJournalEntrySchema:
    def test_cross_currency_entry_preserves_fx_rate(self): debit, credit = (uuid4(), uuid4()); entry = JournalEntryCreate(entry_date=date(2026, 1, 1), memo='SGD<->USD transfer', lines=[JournalLineCreate(account_id=debit, direction=Direction.DEBIT, amount=Decimal('135.00'), currency='SGD'), JournalLineCreate(account_id=credit, direction=Direction.CREDIT, amount=Decimal('100.00'), currency='USD', fx_rate=Decimal('1.350000'))]); assert len(entry.lines) == 2; assert entry.lines[1].fx_rate == Decimal('1.350000'); _m1_entry = JournalEntryCreate(entry_date=date(2026, 1, 1), memo='ledger validates FX', lines=[JournalLineCreate(account_id=uuid4(), direction=Direction.DEBIT, amount=Decimal('100.00'), currency='USD'), JournalLineCreate(account_id=uuid4(), direction=Direction.CREDIT, amount=Decimal('100.00'), currency='USD')]); assert all((_m1_line.fx_rate is None for _m1_line in _m1_entry.lines))
class TestInvestmentValidation:
    'AC-portfolio.1.2'
    def test_validate_positive_rejects_zero(self):
        service = InvestmentAccountingService()
        with pytest.raises(InvestmentAccountingValidationError, match='must be positive'): service._validate_positive(Decimal('0'), 'quantity')
        InvestmentAccountingService()._validate_positive(Decimal('1'), 'quantity'); _m2_service = InvestmentAccountingService()
        with pytest.raises(InvestmentAccountingValidationError, match='cannot be negative'): _m2_service._validate_non_negative(Decimal('-1'), 'fees')
        InvestmentAccountingService()._validate_non_negative(Decimal('0'), 'fees')
