from __future__ import annotations; from unittest.mock import MagicMock, patch; import pytest; from botocore.exceptions import ClientError; from src.advisor import StreamRedactor; from src.runtime import StorageError, StorageService
def test_stream_redactor_small_chunks(): 'AC-advisor.guardrail.13 AC2.12.5'; redactor = StreamRedactor(tail_size=10); result1 = redactor.process('Hello'); assert result1 == ''; result2 = redactor.process(' World'); assert len(result2) > 0 or len(redactor._buffer) == 10
def test_stream_redactor_flush_empty():
    'AC2.12.5'; redactor = StreamRedactor(tail_size=10); result = redactor.flush(); assert result == ''; _m1_service = StorageService(bucket='test-bucket'); _m1_service._checked_buckets.add(_m1_service.bucket)
    with patch.object(_m1_service.client, 'head_bucket') as _m1_mock_head: _m1_service._ensure_bucket(); _m1_mock_head.assert_not_called()
    _m2_service = StorageService(bucket='test-bucket'); _m2_service._checked_buckets.add(_m2_service.bucket)
    with patch.object(_m2_service.client, 'get_object', side_effect=ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')), pytest.raises(StorageError, match='Failed to download'): _m2_service.get_object('missing.pdf')
    _m3_service = StorageService(bucket='test-bucket'); _m3_service._checked_buckets.add(_m3_service.bucket); _m3_mock_response = {'Body': MagicMock()}; _m3_mock_response['Body'].read.return_value = b'test content'
    with patch.object(_m3_service.client, 'get_object', return_value=_m3_mock_response): _m3_result = _m3_service.get_object('test.pdf'); assert _m3_result == b'test content'
