"""Tests for storage service."""

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.services.storage import StorageError, StorageService


@pytest.fixture
def mock_boto_client():
    """Mock boto3 client."""
    with patch("boto3.client") as mock:
        yield mock


def test_init(mock_boto_client):
    """Test service initialization."""
    service = StorageService(bucket="test-bucket")
    assert service.bucket == "test-bucket"
    mock_boto_client.assert_called_once()


def test_upload_bytes_success(mock_boto_client):
    """Test successful upload."""
    mock_s3 = MagicMock()
    mock_s3.head_bucket.return_value = None
    mock_boto_client.return_value = mock_s3

    service = StorageService(bucket="test-bucket")
    StorageService._checked_buckets.clear()
    service.upload_bytes(key="test/key.pdf", content=b"content", content_type="application/pdf")

    mock_s3.put_object.assert_called_once_with(
        Bucket="test-bucket", Key="test/key.pdf", Body=b"content", ContentType="application/pdf"
    )


def test_upload_bytes_error(mock_boto_client):
    """Test upload failure."""
    mock_s3 = MagicMock()
    mock_s3.head_bucket.return_value = None
    mock_s3.put_object.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "Error"}}, "put_object"
    )
    mock_boto_client.return_value = mock_s3

    service = StorageService(bucket="test-bucket")
    StorageService._checked_buckets.clear()

    with pytest.raises(StorageError, match="Failed to upload"):
        service.upload_bytes(key="test/key", content=b"content")


def test_generate_presigned_url_success(mock_boto_client):
    """Test presigned URL generation."""
    mock_s3 = MagicMock()
    mock_s3.head_bucket.return_value = None
    mock_s3.generate_presigned_url.return_value = "https://example.com/signed"
    mock_boto_client.return_value = mock_s3

    service = StorageService(bucket="test-bucket")
    StorageService._checked_buckets.clear()
    url = service.generate_presigned_url(key="test/key")

    assert url == "https://example.com/signed"
    mock_s3.generate_presigned_url.assert_called_once()
    call_args = mock_s3.generate_presigned_url.call_args
    assert call_args[0][0] == "get_object"
    assert call_args[1]["Params"]["Bucket"] == "test-bucket"
    assert call_args[1]["Params"]["Key"] == "test/key"


def test_generate_presigned_url_error(mock_boto_client):
    """Test presigned URL generation failure."""
    mock_s3 = MagicMock()
    mock_s3.head_bucket.return_value = None
    mock_s3.generate_presigned_url.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "Error"}}, "generate_presigned_url"
    )
    mock_boto_client.return_value = mock_s3

    service = StorageService(bucket="test-bucket")
    StorageService._checked_buckets.clear()

    with pytest.raises(StorageError, match="Failed to generate presigned URL"):
        service.generate_presigned_url(key="test/key")


def test_upload_bytes_creates_missing_bucket(mock_boto_client, monkeypatch):
    """Missing bucket should be created before upload."""
    mock_s3 = MagicMock()
    mock_s3.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "head_bucket"
    )
    mock_boto_client.return_value = mock_s3
    StorageService._checked_buckets.clear()

    service = StorageService(bucket="test-bucket")
    service.upload_bytes(key="test/key", content=b"content")

    mock_s3.create_bucket.assert_called_once_with(Bucket="test-bucket")
    mock_s3.put_object.assert_called_once()


def test_upload_bytes_creates_bucket_with_region(mock_boto_client, monkeypatch):
    """Missing bucket should include region configuration when needed."""
    from src.services import storage as storage_module

    mock_s3 = MagicMock()
    mock_s3.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "head_bucket"
    )
    mock_boto_client.return_value = mock_s3
    StorageService._checked_buckets.clear()
    monkeypatch.setattr(storage_module.settings, "s3_region", "ap-southeast-1")

    service = StorageService(bucket="test-bucket")
    service.upload_bytes(key="test/key", content=b"content")

    mock_s3.create_bucket.assert_called_once_with(
        Bucket="test-bucket",
        CreateBucketConfiguration={"LocationConstraint": "ap-southeast-1"},
    )
    mock_s3.put_object.assert_called_once()


def test_upload_bytes_bucket_access_denied(mock_boto_client):
    """Access denied when checking bucket should surface as StorageError."""
    StorageService._checked_buckets.clear()
    
    mock_s3 = MagicMock()
    mock_s3.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "403", "Message": "Forbidden"}}, "head_bucket"
    )
    mock_boto_client.return_value = mock_s3
    StorageService._checked_buckets.clear()

    service = StorageService(bucket="test-bucket")
    with pytest.raises(StorageError, match="Failed to access bucket"):
        service.upload_bytes(key="test/key", content=b"content")



def test_public_client_init(mock_boto_client, monkeypatch):
    """Test public client initialization."""
    from src.services import storage as storage_module

    monkeypatch.setattr(storage_module.settings, "s3_public_endpoint", "https://public.s3")
    monkeypatch.setattr(storage_module.settings, "s3_public_access_key", "pub_key")
    monkeypatch.setattr(storage_module.settings, "s3_public_secret_key", "pub_secret")

    service = StorageService()
    assert service.public_client is not None
    assert mock_boto_client.call_count == 2
    
    # Verify public client call args
    call_args = mock_boto_client.call_args_list[1]
    assert call_args[1]["endpoint_url"] == "https://public.s3"
    assert call_args[1]["aws_access_key_id"] == "pub_key"


def test_generate_presigned_url_public(mock_boto_client, monkeypatch):
    """Test generating public presigned URL."""
    from src.services import storage as storage_module

    monkeypatch.setattr(storage_module.settings, "s3_public_endpoint", "https://public.s3")
    
    mock_s3_internal = MagicMock()
    mock_s3_public = MagicMock()
    mock_s3_public.generate_presigned_url.return_value = "https://public.s3/test-bucket/test/key"
    
    # First call is internal, second is public
    mock_boto_client.side_effect = [mock_s3_internal, mock_s3_public]

    service = StorageService(bucket="test-bucket")
    url = service.generate_presigned_url(key="test/key", public=True)

    assert url == "https://public.s3/test-bucket/test/key"
    mock_s3_public.generate_presigned_url.assert_called_once()
    
    # Internal shouldn't be called for URL generation
    mock_s3_internal.generate_presigned_url.assert_not_called()


def test_public_url_fallback(mock_boto_client, monkeypatch):
    """Test fallback to internal client when public client is not configured."""
    from src.services import storage as storage_module
    
    # Mock logger
    mock_logger = MagicMock()
    monkeypatch.setattr(storage_module, "logger", mock_logger)

    # Ensure no public config
    monkeypatch.setattr(storage_module.settings, "s3_public_endpoint", None)
    StorageService._checked_buckets.clear()

    service = StorageService(bucket="test-bucket")
    
    # Mock internal client generate_presigned_url
    service.client.generate_presigned_url.return_value = "https://internal.s3/key"

    url = service.generate_presigned_url(key="test/key", public=True)
    
    assert url == "https://internal.s3/key"
    
    # Verify warning was logged
    mock_logger.warning.assert_called_once()
    assert "no public S3 client configured" in mock_logger.warning.call_args[0][0]
    
    service.client.generate_presigned_url.assert_called_once()
    mock_boto_client.assert_called_once() # Only internal client should be initialized
