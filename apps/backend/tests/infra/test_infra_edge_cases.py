from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.advisor import StreamRedactor
from src.runtime import StorageError, StorageService


def test_stream_redactor_and_storage_service() -> None:
    redactor = StreamRedactor(tail_size=10)
    assert redactor.process("Hello") == ""
    assert len(redactor.process(" World")) > 0 or len(redactor._buffer) == 10
    assert StreamRedactor(tail_size=10).flush() == ""

    service = StorageService(bucket="test-bucket")
    service._checked_buckets.add(service.bucket)
    with patch.object(service.client, "head_bucket") as mock_head:
        service._ensure_bucket()
        mock_head.assert_not_called()
    with (
        patch.object(
            service.client, "get_object", side_effect=ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        ),
        pytest.raises(StorageError, match="Failed to download"),
    ):
        service.get_object("missing.pdf")
    body = MagicMock()
    body.read.return_value = b"test content"
    with patch.object(service.client, "get_object", return_value={"Body": body}):
        assert service.get_object("test.pdf") == b"test content"
