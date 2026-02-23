"""Coverage boost for error paths and edge cases

This test file adds coverage for hard-to-reach error handling paths
across multiple services to reach the 97.5% coverage target.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.services.ai_advisor import StreamRedactor
from src.services.storage import StorageError, StorageService


def test_stream_redactor_small_chunks():
    """AC2.12.5 - Stream redactor accumulates small chunks in buffer"""
    redactor = StreamRedactor(tail_size=10)

    result1 = redactor.process("Hello")
    assert result1 == ""

    result2 = redactor.process(" World")
    assert len(result2) > 0 or len(redactor._buffer) == 10


def test_stream_redactor_flush_empty():
    """AC2.12.5 - Stream redactor flush on empty buffer returns empty string"""
    redactor = StreamRedactor(tail_size=10)
    result = redactor.flush()
    assert result == ""


def test_storage_service_bucket_already_checked():
    """AC2.11.4 - Storage service skips bucket check if already verified"""
    service = StorageService(bucket="test-bucket")
    service._checked_buckets.add(service.bucket)

    with patch.object(service.client, "head_bucket") as mock_head:
        service._ensure_bucket()
        mock_head.assert_not_called()


def test_storage_service_get_object_client_error():
    """AC2.11.4 - Storage service get_object raises StorageError on ClientError"""
    service = StorageService(bucket="test-bucket")
    service._checked_buckets.add(service.bucket)

    with patch.object(
        service.client,
        "get_object",
        side_effect=ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject"),
    ):
        with pytest.raises(StorageError, match="Failed to download"):
            service.get_object("missing.pdf")


def test_storage_service_get_object_success():
    """AC2.11.4 - Storage service get_object returns bytes on success"""
    service = StorageService(bucket="test-bucket")
    service._checked_buckets.add(service.bucket)

    mock_response = {"Body": MagicMock()}
    mock_response["Body"].read.return_value = b"test content"

    with patch.object(service.client, "get_object", return_value=mock_response):
        result = service.get_object("test.pdf")
        assert result == b"test content"
