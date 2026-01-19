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
