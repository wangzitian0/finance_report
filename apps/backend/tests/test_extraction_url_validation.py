<<<<<<< HEAD
"""Tests for ExtractionService URL validation."""

import pytest

from src.services.extraction import ExtractionError, ExtractionService


class TestValidateExternalUrl:
    """Test _validate_external_url method."""

    @pytest.fixture
    def service(self):
        return ExtractionService()

    def test_localhost_rejected(self, service):
        """Localhost URLs should be rejected."""
        with pytest.raises(ExtractionError, match="localhost URL"):
            service._validate_external_url("http://localhost:9000/file.pdf")

    def test_127_0_0_1_rejected(self, service):
        """127.0.0.1 URLs should be rejected."""
        with pytest.raises(ExtractionError, match="localhost URL"):
            service._validate_external_url("http://127.0.0.1:9000/file.pdf")

    def test_private_10_network_rejected(self, service):
        """10.x.x.x URLs should be rejected."""
        with pytest.raises(ExtractionError, match="private network IP"):
            service._validate_external_url("http://10.0.1.35:9000/file.pdf")

    def test_private_172_network_rejected(self, service):
        """172.16-31.x.x URLs should be rejected."""
        with pytest.raises(ExtractionError, match="private network IP"):
            service._validate_external_url("http://172.17.0.1:9000/file.pdf")

    def test_private_192_168_rejected(self, service):
        """192.168.x.x URLs should be rejected."""
        with pytest.raises(ExtractionError, match="private network IP"):
            service._validate_external_url("http://192.168.1.100:9000/file.pdf")

    def test_docker_minio_hostname_rejected(self, service):
        """Docker MinIO hostnames should be rejected."""
        with pytest.raises(ExtractionError, match="internal Docker URL"):
            service._validate_external_url(
                "http://finance-report-minio-pr-85:9000/statements/file.pdf"
            )

    def test_docker_backend_hostname_rejected(self, service):
        """Docker backend hostnames should be rejected."""
        with pytest.raises(ExtractionError, match="internal Docker URL"):
            service._validate_external_url("http://my-app-backend:8000/api")

    def test_public_url_allowed(self, service):
        """Public URLs should pass validation."""
        # Should not raise
        service._validate_external_url("https://s3.amazonaws.com/bucket/file.pdf")
        service._validate_external_url("https://storage.googleapis.com/bucket/file.pdf")
        service._validate_external_url("https://example.com/file.pdf")

    def test_data_url_allowed(self, service):
        """Data URLs should pass validation (they have no hostname)."""
        # Data URLs have empty hostname, should pass
        service._validate_external_url("data:application/pdf;base64,SGVsbG8=")
=======
"""Tests for URL validation in ExtractionService."""

import pytest
from src.services.extraction import ExtractionService


@pytest.fixture
def service():
    """ExtractionService instance."""
    return ExtractionService()


def test_validate_external_url_public_https(service):
    """Public HTTPS URLs should be allowed."""
    assert service._validate_external_url("https://example.com/file.pdf") is True
    assert service._validate_external_url("https://s3.amazonaws.com/bucket/obj") is True


def test_validate_external_url_public_http(service):
    """Public HTTP URLs should be allowed."""
    assert service._validate_external_url("http://example.com/file.pdf") is True


def test_validate_external_url_reject_localhost(service):
    """Localhost should be rejected."""
    assert service._validate_external_url("http://localhost:9000/file.pdf") is False
    assert service._validate_external_url("http://127.0.0.1:9000/file.pdf") is False
    assert service._validate_external_url("http://[::1]:9000/file.pdf") is False


def test_validate_external_url_reject_private_10(service):
    """10.x.x.x private range should be rejected."""
    assert service._validate_external_url("http://10.0.0.1/file.pdf") is False
    assert service._validate_external_url("http://10.255.255.255/file.pdf") is False


def test_validate_external_url_reject_private_172(service):
    """172.16.x.x - 172.31.x.x private range should be rejected."""
    assert service._validate_external_url("http://172.16.0.1/file.pdf") is False
    assert service._validate_external_url("http://172.31.255.255/file.pdf") is False
    # 172.15 and 172.32 are public
    assert service._validate_external_url("http://172.15.0.1/file.pdf") is True
    assert service._validate_external_url("http://172.32.0.1/file.pdf") is True


def test_validate_external_url_reject_private_192(service):
    """192.168.x.x private range should be rejected."""
    assert service._validate_external_url("http://192.168.1.1/file.pdf") is False
    assert service._validate_external_url("http://192.168.0.254/file.pdf") is False


def test_validate_external_url_reject_internal_names(service):
    """Internal hostnames (no dots) should be rejected (common in Docker)."""
    assert service._validate_external_url("http://minio:9000/bucket/file") is False
    assert service._validate_external_url("http://postgres/file") is False
    assert service._validate_external_url("http://backend/file") is False


def test_validate_external_url_invalid_urls(service):
    """Invalid URLs should handle gracefully."""
    assert service._validate_external_url("not-a-url") is False
    assert service._validate_external_url("") is False
    assert service._validate_external_url("ftp://example.com") is True  # Technically external
>>>>>>> 6ba239f (fix: prefer base64 and validate external URLs to resolve OpenRouter 400 errors)
