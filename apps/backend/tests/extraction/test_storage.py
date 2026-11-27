from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.runtime import StorageError, StorageService, redact_presigned_url
from src.runtime.extension import storage as storage_module


@pytest.fixture
def mock_boto_client():
    with patch("boto3.client") as mock:
        yield mock


def _client_err(code: str, msg: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": msg}}, op)


def test_init_and_redact_presigned_url(mock_boto_client):
    StorageService._checked_buckets.clear()
    service = StorageService(bucket="test-bucket")
    assert service.bucket == "test-bucket" and mock_boto_client.call_count >= 1

    url = "https://s3.example.test/bucket/path/file.pdf?X-Amz-Signature=secret&token=abc#frag"
    redacted = redact_presigned_url(url)
    assert (
        redacted,
        "secret" not in redacted,
        "token=abc" not in redacted,
        "#frag" not in redacted,
        redact_presigned_url(None),
        redact_presigned_url(""),
        redact_presigned_url("http://[::1"),
    ) == (
        "https://s3.example.test/bucket/path/file.pdf?X-Amz-Signature=REDACTED&token=REDACTED",
        True,
        True,
        True,
        None,
        "",
        "<invalid-url>",
    )


def test_upload_and_presigned_url_success_and_missing_bucket(mock_boto_client, monkeypatch):
    mock_s3 = MagicMock()
    mock_s3.head_bucket.return_value = None
    mock_s3.generate_presigned_url.return_value = "https://example.com/signed"
    mock_boto_client.return_value = mock_s3
    StorageService._checked_buckets.clear()
    service = StorageService(bucket="test-bucket")
    service.upload_bytes(key="test/key.pdf", content=b"content", content_type="application/pdf")
    mock_s3.put_object.assert_called_once_with(
        Bucket="test-bucket", Key="test/key.pdf", Body=b"content", ContentType="application/pdf"
    )
    url = service.generate_presigned_url(key="test/key")
    call_args = mock_s3.generate_presigned_url.call_args
    assert (url, call_args[0][0], call_args[1]["Params"]["Bucket"], call_args[1]["Params"]["Key"]) == (
        "https://example.com/signed",
        "get_object",
        "test-bucket",
        "test/key",
    )

    for region, expected_kwargs in [
        (None, {"Bucket": "test-bucket"}),
        (
            "ap-southeast-1",
            {"Bucket": "test-bucket", "CreateBucketConfiguration": {"LocationConstraint": "ap-southeast-1"}},
        ),
    ]:
        s3 = MagicMock()
        s3.head_bucket.side_effect = _client_err("404", "Not Found", "head_bucket")
        mock_boto_client.return_value = s3
        StorageService._checked_buckets.clear()
        if region:
            monkeypatch.setattr(storage_module.settings, "s3_region", region)
        StorageService(bucket="test-bucket").upload_bytes(key="test/key", content=b"content")
        s3.create_bucket.assert_called_once_with(**expected_kwargs)
        s3.put_object.assert_called_once()


@pytest.mark.parametrize(
    ("setup_attr", "err", "call_fn", "match"),
    [
        (
            "put_object",
            _client_err("500", "Error", "put_object"),
            lambda s: s.upload_bytes(key="test/key", content=b"content"),
            "Failed to upload",
        ),
        (
            "generate_presigned_url",
            _client_err("500", "Error", "generate_presigned_url"),
            lambda s: s.generate_presigned_url(key="test/key"),
            "Failed to generate presigned URL",
        ),
        (
            "head_bucket",
            _client_err("403", "Forbidden", "head_bucket"),
            lambda s: s.upload_bytes(key="test/key", content=b"content"),
            "Failed to access bucket",
        ),
    ],
)
def test_storage_errors(mock_boto_client, setup_attr, err, call_fn, match):
    mock_s3 = MagicMock()
    setattr(mock_s3, setup_attr, MagicMock(side_effect=err))
    mock_boto_client.return_value = mock_s3
    StorageService._checked_buckets.clear()
    with pytest.raises(StorageError, match=match):
        call_fn(StorageService(bucket="test-bucket"))


def test_public_client_and_fallback(mock_boto_client, monkeypatch):
    monkeypatch.setattr(storage_module.settings, "s3_public_endpoint", "https://public.s3")
    monkeypatch.setattr(storage_module.settings, "s3_public_access_key", "pub_key")
    monkeypatch.setattr(storage_module.settings, "s3_public_secret_key", "pub_secret")
    mock_s3_internal, mock_s3_public = MagicMock(), MagicMock()
    mock_s3_public.generate_presigned_url.return_value = "https://public.s3/test-bucket/test/key"
    mock_boto_client.side_effect = [mock_s3_internal, mock_s3_public]
    StorageService._checked_buckets.clear()
    service = StorageService(bucket="test-bucket")
    assert mock_boto_client.call_count == 1
    assert service.generate_presigned_url(key="test/key", public=True) == "https://public.s3/test-bucket/test/key"
    assert mock_boto_client.call_count == 2
    assert (
        mock_boto_client.call_args_list[1][1]["endpoint_url"],
        mock_boto_client.call_args_list[1][1]["aws_access_key_id"],
    ) == ("https://public.s3", "pub_key")
    mock_s3_public.generate_presigned_url.assert_called_once()
    mock_s3_internal.generate_presigned_url.assert_not_called()

    mock_logger = MagicMock()
    monkeypatch.setattr(storage_module, "logger", mock_logger)
    monkeypatch.setattr(storage_module.settings, "s3_public_endpoint", None)
    mock_boto_client.side_effect = None
    StorageService._checked_buckets.clear()
    with pytest.raises(StorageError, match="Public storage client is not configured"):
        StorageService(bucket="test-bucket").generate_presigned_url(key="test/key", public=True)
    assert "no public S3 client configured" in mock_logger.error.call_args[0][0]
