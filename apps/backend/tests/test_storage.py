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
    mock_boto_client.return_value = mock_s3
    
    service = StorageService(bucket="test-bucket")
    service.upload_bytes(
        key="test/key.pdf",
        content=b"content",
        content_type="application/pdf"
    )
    
    mock_s3.put_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="test/key.pdf",
        Body=b"content",
        ContentType="application/pdf"
    )


def test_upload_bytes_error(mock_boto_client):
    """Test upload failure."""
    mock_s3 = MagicMock()
    mock_s3.put_object.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "Error"}}, 
        "put_object"
    )
    mock_boto_client.return_value = mock_s3
    
    service = StorageService(bucket="test-bucket")
    
    with pytest.raises(StorageError, match="Failed to upload"):
        service.upload_bytes(key="test/key", content=b"content")


def test_generate_presigned_url_success(mock_boto_client):
    """Test presigned URL generation."""
    mock_s3 = MagicMock()
    mock_s3.generate_presigned_url.return_value = "https://example.com/signed"
    mock_boto_client.return_value = mock_s3
    
    service = StorageService(bucket="test-bucket")
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
    mock_s3.generate_presigned_url.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "Error"}}, 
        "generate_presigned_url"
    )
    mock_boto_client.return_value = mock_s3
    
    service = StorageService(bucket="test-bucket")
    
    with pytest.raises(StorageError, match="Failed to generate presigned URL"):
        service.generate_presigned_url(key="test/key")
