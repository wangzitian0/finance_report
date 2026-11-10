import json; from decimal import Decimal; from unittest.mock import AsyncMock, patch; from uuid import UUID, uuid4; import pytest; from src.extraction import DocumentSource; from src.extraction.extension.service import ExtractionError, ExtractionService
async def mock_stream_generator(content: str): yield content
class TestExtractionServiceFlow:
    'AC-extraction.5.1 AC-extraction.5.2 AC-extraction.5.3 AC-extraction.5.4 AC18.1.1 AC18.1.2'
    @pytest.fixture
    def service(self): return ExtractionService()
    async def test_parse_document_auto_detects_institution(self, service, tmp_path):
        pdf_file = tmp_path / 'test.pdf'; pdf_file.write_bytes(b'dummy content'); mock_data = {'institution': 'UOB', 'account_last4': '6789', 'currency': 'SGD', 'period_start': '2025-01-01', 'period_end': '2025-01-31', 'opening_balance': '1000.00', 'closing_balance': '1100.00', 'transactions': [{'date': '2025-01-15', 'description': 'Salary', 'amount': '1000.00', 'direction': 'IN'}]}
        with patch.object(service, 'extract_financial_data', new=AsyncMock(return_value=mock_data)): result = await service.parse_document(DocumentSource.resolve(path=pdf_file, content=pdf_file.read_bytes()), institution=None, user_id=uuid4())
        assert result.institution == 'UOB'; assert result.account_last4 == '6789'
    async def test_parse_document_csv_success(self, service, tmp_path):
        csv_file = tmp_path / 'test.csv'; csv_file.write_bytes(b'dummy csv'); mock_data = {'period_start': '2025-01-01', 'period_end': '2025-01-31', 'opening_balance': '0.00', 'closing_balance': '0.00', 'transactions': []}
        with patch.object(service, '_parse_csv_content', new_callable=AsyncMock) as mock_csv: mock_csv.return_value = mock_data; result = await service.parse_document(DocumentSource.resolve(path=csv_file, content=csv_file.read_bytes()), 'DBS', user_id=UUID('00000000-0000-0000-0000-000000000001'), file_type='csv'); assert result.institution == 'DBS'; assert len(result.transactions) == 0
    async def test_parsed_statement_sets_stage1_pending_review(self, service, tmp_path):
        'AC-extraction.1622.8'; csv_file = tmp_path / 'review.csv'; csv_file.write_bytes(b'dummy csv'); mock_data = {'period_start': '2025-01-01', 'period_end': '2025-01-31', 'opening_balance': '0.00', 'closing_balance': '0.00', 'transactions': []}
        with patch.object(service, '_parse_csv_content', new_callable=AsyncMock) as mock_csv: mock_csv.return_value = mock_data; result = await service.parse_document(DocumentSource.resolve(path=csv_file, content=csv_file.read_bytes()), 'DBS', user_id=UUID('00000000-0000-0000-0000-000000000002'), file_type='csv')
        assert result.institution == 'DBS'; assert result.transactions == ()
    async def test_parse_document_csv_without_statement_balances_remains_reviewable(self, service, tmp_path): 'AC-extraction.2.5'; csv_file = tmp_path / 'dbs-export.csv'; csv_file.write_bytes(b'Transaction Date,Reference,Debit Amount,Credit Amount,Transaction Ref1\n15 Jan 2025,REF001,,500.00,SALARY\n16 Jan 2025,REF002,100.00,,GROCERIES\n'); result = await service.parse_document(DocumentSource.resolve(path=csv_file, content=csv_file.read_bytes()), 'DBS', user_id=UUID('00000000-0000-0000-0000-000000000001'), file_type='csv'); assert len(result.transactions) == 2; assert result.balance_validated is None; assert result.confidence == Decimal('0.25'); assert result.review_reasons == ('Source is missing required facts: statement currency, statement period, opening and closing balances, transaction currency',)
    async def test_parse_document_unsupported_type(self, service, tmp_path):
        'AC-extraction.4.2'; txt_file = tmp_path / 'test.txt'; txt_file.write_bytes(b'text')
        with pytest.raises(ExtractionError, match='Unsupported file type'): await service.parse_document(DocumentSource.resolve(path=txt_file, content=txt_file.read_bytes()), 'DBS', user_id=UUID('00000000-0000-0000-0000-000000000001'), file_type='txt')
    async def test_extract_financial_data_success_json(self, service, tmp_path):
        service.api_key = 'test-key'; json_content = json.dumps({'test': 'data'})
        with patch('src.extraction.extension.service.stream_ai_json') as mock_stream: mock_stream.return_value = mock_stream_generator(json_content); result = await service.extract_financial_data(b'content', 'DBS', 'png'); assert result == {'test': 'data'}
    async def test_extract_financial_data_markdown_json(self, service):
        'AC-extraction.114.5'; service.api_key = 'test-key'; content = 'Here is json:\n```json\n{"test": "markdown"}\n```'
        with patch('src.extraction.extension.service.stream_ai_json') as mock_stream: mock_stream.return_value = mock_stream_generator(content); result = await service.extract_financial_data(b'content', 'DBS', 'png'); assert result == {'test': 'markdown'}
    async def test_extract_financial_data_salvages_extra_text(self, service):
        'AC-extraction.114.2'; service.api_key = 'test-key'; content = 'Sure! {"test": "value"}\nThanks!'
        with patch('src.extraction.extension.service.stream_ai_json') as mock_stream: mock_stream.return_value = mock_stream_generator(content); result = await service.extract_financial_data(b'content', 'DBS', 'png'); assert result == {'test': 'value'}
    async def test_extract_financial_data_rejects_array(self, service):
        service.api_key = 'test-key'; content = json.dumps([{'test': 'value'}])
        with patch('src.extraction.extension.service.stream_ai_json') as mock_stream:
            mock_stream.return_value = mock_stream_generator(content)
            with pytest.raises(ExtractionError, match='strict JSON object'): await service.extract_financial_data(b'content', 'DBS', 'png')
    async def test_extract_financial_data_api_error(self, service):
        service.api_key = 'test-key'; from src.llm import AIStreamError
        with patch('src.extraction.extension.service.stream_ai_json') as mock_stream:
            mock_stream.side_effect = AIStreamError('HTTP 400: Bad Request')
            with pytest.raises(ExtractionError, match='failed'): await service.extract_financial_data(b'content', 'DBS', 'png')
    async def test_extract_financial_data_no_key(self, service):
        service.api_key = None
        with pytest.raises(ExtractionError, match='AI provider API key not configured'): await service.extract_financial_data(b'content', 'DBS', 'pdf')
    async def test_extract_financial_data_prefers_content(self, service):
        service.api_key = 'test-key'; content = b'file-content'; url = 'http://internal-url.local/file.png'; json_content = json.dumps({'success': True})
        with patch('src.extraction.extension.service.stream_ai_json') as mock_stream: mock_stream.return_value = mock_stream_generator(json_content); await service.extract_financial_data(file_content=content, file_url=url, institution='DBS', file_type='png'); call_args = mock_stream.call_args; payload = call_args.kwargs['messages']; message_content = payload[0]['content']; media_part = message_content[1]; assert media_part['type'] == 'image_url'; assert media_part['image_url']['url'].startswith('data:image/png;base64,')
    async def test_extract_financial_data_valid_public_url(self, service):
        service.api_key = 'test-key'; url = 'https://example.com/public.pdf'; json_content = json.dumps({'success': True})
        with patch('src.extraction.extension.service.stream_ai_json') as mock_stream: mock_stream.return_value = mock_stream_generator(json_content); await service.extract_financial_data(file_content=None, file_url=url, institution='DBS', file_type='pdf'); call_args = mock_stream.call_args; payload = call_args.kwargs['messages']; media_part = payload[0]['content'][1]; assert media_part['type'] == 'image_url'; assert media_part['image_url']['url'] == url
    async def test_extract_financial_data_rejects_private_url(self, service):
        service.api_key = 'test-key'; url = 'http://192.168.1.1/private.pdf'
        with pytest.raises(ExtractionError, match='No valid file content or accessible URL'): await service.extract_financial_data(file_content=None, file_url=url, institution='DBS', file_type='pdf')
    async def test_extract_financial_data_pdf_renders_content_for_zai_vision(self, service):
        service.api_key = 'test-key'; pdf_bytes = b'%PDF-1.4 fake content'; image_payload = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,iVBORw0KGgo='}}; json_content = json.dumps({'success': True})
        with patch.object(service, '_render_pdf_pages_as_image_payload_batches', return_value=[[image_payload]]) as mock_render, patch('src.extraction.extension.service.stream_ai_json') as mock_stream: mock_stream.return_value = mock_stream_generator(json_content); await service.extract_financial_data(file_content=pdf_bytes, file_url=None, institution='DBS', file_type='pdf'); mock_render.assert_called_once_with(pdf_bytes); payload = mock_stream.call_args.kwargs['messages']; assert payload[0]['content'][1] == image_payload
    async def test_force_model_pdf_renders_content_for_zai(self, service):
        'AC-extraction.105.1'; service.api_key = 'test-key'; pdf_bytes = b'%PDF-1.4 fake content'; image_payload = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,iVBORw0KGgo='}}; json_content = json.dumps({'success': True})
        with patch.object(service, '_render_pdf_pages_as_image_payload_batches', return_value=[[image_payload]]) as mock_render, patch('src.extraction.extension.service.stream_ai_json') as mock_stream: mock_stream.return_value = mock_stream_generator(json_content); await service.extract_financial_data(file_content=pdf_bytes, file_url=None, institution='DBS', file_type='pdf', force_model='test-vision-model'); mock_render.assert_called_once_with(pdf_bytes); payload = mock_stream.call_args.kwargs['messages']; assert payload[0]['content'][1] == image_payload
    async def test_extract_financial_data_pdf_prefers_rendered_content_for_zai_vision(self, service):
        service.api_key = 'test-key'; pdf_bytes = b'%PDF-1.4 fake content'; url = 'https://example.com/public.pdf'; image_payload = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,iVBORw0KGgo='}}; json_content = json.dumps({'success': True})
        with patch.object(service, '_render_pdf_pages_as_image_payload_batches', return_value=[[image_payload]]) as mock_render, patch('src.extraction.extension.service.stream_ai_json') as mock_stream: mock_stream.return_value = mock_stream_generator(json_content); await service.extract_financial_data(file_content=pdf_bytes, file_url=url, institution='DBS', file_type='pdf'); mock_render.assert_called_once_with(pdf_bytes); call_args = mock_stream.call_args; payload = call_args.kwargs['messages']; media_part = payload[0]['content'][1]; assert media_part['type'] == 'image_url'; assert media_part['image_url']['url'].startswith('data:image/png;base64,')
    async def test_extract_financial_data_pdf_no_content_no_url_raises(self, service):
        service.api_key = 'test-key'
        with pytest.raises(ExtractionError, match='File content is required'): await service.extract_financial_data(file_content=None, file_url=None, institution='DBS', file_type='pdf')
