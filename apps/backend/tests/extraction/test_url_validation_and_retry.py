"""Tests for external URL validation and AI extraction timeout/retry logic."""

import pytest
from src.services.extraction import ExtractionError, ExtractionService


async def mock_stream_generator(content: str):
    """Helper to create async generator for streaming mock."""
    yield content


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

    def test_validate_url_accepts_valid_urls(self, service):
        """Test that valid URLs are accepted."""
        valid_urls = [
            "https://example.com/document.pdf",
            "https://example.com/document.jpg",
            "https://example.com/image.png",
            "https://api.example.com/api/documents/12345",
            "https://s3.amazonaws.com/bucket/path/file.pdf",
        ]

        for url in valid_urls:
            assert service._validate_external_url(url) is True


class TestAExtractionTimeoutRetry:
    """Test AI extraction timeout and retry behavior."""

    @pytest.fixture
    def service(self):
        return ExtractionService()

    async def test_extract_with_timeout_on_last_model(self, service):
        """Test extraction continues after timeout on second-to-last model."""
        from unittest.mock import patch

        service.api_key = "test-key"

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

    async def test_extract_with_connection_error(self, service):
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
