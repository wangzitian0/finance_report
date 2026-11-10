'AC-extraction.2.1 AC-extraction.2.2 AC-extraction.3.1 AC-extraction.3.2 EPIC-003'; from decimal import Decimal; from io import BytesIO; from unittest.mock import AsyncMock, patch; import pytest; from fastapi import UploadFile; from src.extraction import BankStatementStatus, DocumentSource; from src.extraction.base.validation import route_by_threshold, validate_balance, validate_completeness; from src.extraction.extension.service import ExtractionError, ExtractionService; make_upload_file = lambda name, content: UploadFile(filename=name, file=BytesIO(content))
class TestInvalidParseNotPersisted:
    @pytest.fixture
    def service(self): return ExtractionService()
    async def test_extraction_error_not_persisted(self, service, tmp_path):
        'AC-extraction.4.1'; bad_file = tmp_path / 'bad.pdf'; bad_file.write_bytes(b'not a valid pdf')
        with patch.object(service, 'extract_financial_data', new_callable=AsyncMock) as mock_extract:
            mock_extract.side_effect = ExtractionError('Failed to parse document'); from uuid import uuid4
            with pytest.raises(ExtractionError, match='Failed to parse'): await service.parse_document(DocumentSource.resolve(path=bad_file, content=bad_file.read_bytes()), 'DBS', user_id=uuid4())
    async def test_parse_document_bank_balance_mismatch_records_validation_error(self, service, tmp_path):
        'AC-extraction.2.4 AC-extraction.2009.2'; pdf_file = tmp_path / 'test.pdf'; pdf_file.write_bytes(b'dummy'); mock_data = {'institution': 'DBS', 'account_last4': '1234', 'period_start': '2025-01-01', 'period_end': '2025-01-31', 'opening_balance': '1000.00', 'closing_balance': '2000.00', 'transactions': [{'date': '2025-01-15', 'description': 'Test', 'amount': '100.00', 'direction': 'IN'}]}
        with patch.object(service, 'extract_financial_data', new_callable=AsyncMock) as mock_extract: mock_extract.return_value = mock_data; from uuid import uuid4; result = await service.parse_document(DocumentSource.resolve(path=pdf_file, content=pdf_file.read_bytes()), 'DBS', user_id=uuid4()); assert result.balance_validated is False; assert result.review_reasons; assert 'llm_led_balance_chain_unreconciled' in result.review_reasons[0]
    def test_validate_balance_returns_invalid_on_mismatch(self): extracted = {'opening_balance': '100.00', 'closing_balance': '500.00', 'transactions': [{'amount': '50.00', 'direction': 'IN'}]}; result = validate_balance(extracted); assert result['balance_valid'] is False; assert 'mismatch' in result.get('notes', '').lower() or Decimal(result['difference']) > Decimal('0.1')
class TestFileSizeLimit:
    async def test_upload_file_exceeds_10mb_limit(self, client, monkeypatch): 'AC-extraction.5.2'; import src.routers.statements; monkeypatch.setattr(src.routers.statements, 'MAX_UPLOAD_BYTES', 1024); large_content = b'x' * 1025; response = await client.post('/statements/upload', files={'file': ('large.pdf', BytesIO(large_content), 'application/pdf')}, data={'institution': 'DBS'}); assert response.status_code == 413; assert '10MB' in response.json().get('detail', '')
    async def test_upload_file_at_limit_succeeds(self, client, monkeypatch):
        import src.routers.statements; monkeypatch.setattr(src.routers.statements, 'MAX_UPLOAD_BYTES', 1024); exact_content = b'x' * 1024; from unittest.mock import MagicMock; mock_storage = MagicMock(); monkeypatch.setattr('src.routers.statements.StorageService', MagicMock(return_value=mock_storage))
        async def fake_parse(*args, **kwargs): raise ExtractionError('test-only extraction bypass')
        from src.extraction.extension.service import ExtractionService; monkeypatch.setattr(ExtractionService, 'parse_document', fake_parse); response = await client.post('/statements/upload', files={'file': ('exact.pdf', BytesIO(exact_content), 'application/pdf')}, data={'institution': 'DBS'}); assert response.status_code != 413
class TestParsingTimeout:
    @pytest.fixture
    def service(self): return ExtractionService()
    async def test_extraction_timeout_raises_error(self, service):
        'AC-extraction.4.3'; service.api_key = 'test-key'; from src.llm import AIStreamError
        with patch('src.extraction.extension.service.stream_ai_json') as mock_stream:
            mock_stream.side_effect = AIStreamError('Connection timed out')
            with pytest.raises(ExtractionError): await service.extract_financial_data(b'content', 'DBS', 'pdf', file_url='https://example.com/file.pdf')
class TestGeminiRetry:
    @pytest.fixture
    def service(self): return ExtractionService()
    async def test_api_error_includes_status_code(self, service):
        service.api_key = 'test-key'; from src.llm import AIStreamError
        with patch('src.extraction.extension.service.stream_ai_json') as mock_stream:
            mock_stream.side_effect = AIStreamError('HTTP 429: Rate limit exceeded')
            with pytest.raises(ExtractionError, match='429'): await service.extract_financial_data(b'content', 'DBS', 'pdf', file_url='https://example.com/file.pdf')
    async def test_api_key_required(self, service):
        service.api_key = None
        with pytest.raises(ExtractionError, match='API key not configured'): await service.extract_financial_data(b'content', 'DBS', 'png')
class TestConfidenceRouting:
    def test_high_confidence_auto_accept(self): status = route_by_threshold(90, balance_valid=True); assert status == BankStatementStatus.APPROVED; _m1_status = route_by_threshold(75, balance_valid=True); assert _m1_status == BankStatementStatus.PARSED; _m2_status = route_by_threshold(50, balance_valid=True); assert _m2_status == BankStatementStatus.UPLOADED; _m3_status = route_by_threshold(95, balance_valid=False); assert _m3_status == BankStatementStatus.PARSED; assert _m3_status != BankStatementStatus.APPROVED
class TestStatementCompleteness:
    def test_missing_required_fields_detected(self): 'AC-extraction.2.3'; incomplete = {'institution': 'DBS', 'period_start': '2025-01-01'}; missing = validate_completeness(incomplete); assert 'period_end' in missing; assert 'opening_balance' in missing; assert 'closing_balance' in missing; _m1_complete = {'institution': 'DBS', 'period_start': '2025-01-01', 'period_end': '2025-01-31', 'opening_balance': '100.00', 'closing_balance': '150.00', 'transactions': [{'amount': '50.00', 'direction': 'IN'}]}; _m1_missing = validate_completeness(_m1_complete); assert len(_m1_missing) == 0
