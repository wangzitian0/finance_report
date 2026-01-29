"""Tests for external URL validation and AI extraction timeout/retry logic."""

import pytest
from src.services.extraction import ExtractionService


class TestURLValidationEdgeCases:
    """Test URL validation edge cases beyond basic tests."""

    @pytest.fixture
    def service(self):
        return ExtractionService()

    def test_validate_url_rejects_user_data_urls(self, service):
        """Test that user-data: URLs are rejected."""
        user_data_urls = [
            "user-data://example.com/file.pdf",
            "blob:https://example.com/file.pdf",
            "data:custom/path",
        ]

        for url in user_data_urls:
            assert service._validate_external_url(url) is False

    def test_validate_url_accepts_subdomains_without_dots(self, service):
        """Test that subdomains without dots (e.g., example.com) are accepted."""
        valid_urls = [
            "https://example.com/file.pdf",
            "https://sub.example.com/file.pdf",
        ]

        for url in valid_urls:
            assert service._validate_external_url(url) is True

    def test_validate_url_rejects_urls_with_query_params(self, service):
        """Test that URLs with suspicious query parameters are rejected."""
        suspicious_urls = [
            "https://example.com/file.pdf?token=secret",
            "https://example.com/file.pdf?redirect=http://evil.com",
            "https://example.com/file.pdf?user=admin",
        ]

        for url in suspicious_urls:
            assert service._validate_external_url(url) is False

    def test_validate_url_accepts_file_extensions(self, service):
        """Test that valid file extensions are accepted in URLs."""
        valid_extensions = [
            "https://example.com/statement.pdf",
            "https://example.com/data.csv",
            "https://example.com/document.jpg",
        ]

        for url in valid_extensions:
            assert service._validate_external_url(url) is True


class TestAExtractionTimeoutRetry:
    """Test AI extraction timeout and retry behavior."""

    @pytest.fixture
    def service(self):
        return ExtractionService()

    def test_extract_with_timeout_on_last_model(self, service):
        """Test extraction continues after timeout on second-to-last model."""
        from unittest.mock import patch

        service.api_key = "test-key"

        mock_responses = [
            "Timeout on first model",
            "Success on second model",
        ]

        mock_stream_values = iter(mock_responses)

        with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
            mock_stream.return_value = mock_stream_generator("timeout")
            mock_stream.side_effect = [
                Exception("HTTP 504"),
                iter(
                    [
                        {
                            "institution": "DBS",
                            "account_last4": "1234",
                            "transactions": [],
                        }
                    ]
                ),
            ]

            with patch("src.services.extraction.models") as mock_models:
                with patch.object(service, "api_key", "test-key"):
                    await service.extract_financial_data(
                        b"content",
                        "DBS",
                        "pdf",
                    )

    def test_extract_with_connection_error(self, service):
        """Test extraction handles connection errors gracefully."""
        from unittest.mock import patch

        service.api_key = "test-key"

        with patch("src.services.extraction.stream_openrouter_json") as mock_stream:
            mock_stream.side_effect = Exception("Connection refused")

            from src.services.openrouter_streaming import OpenRouterStreamError

            with pytest.raises(ExtractionError, match="connection error"):
                await service.extract_financial_data(
                    b"content",
                    "DBS",
                    "pdf",
                )
