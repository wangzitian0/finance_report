"""Unit tests for extraction service logging improvements.

These tests do NOT require database connection or fixtures.
They test the _extract_status_code helper method in isolation.
"""

import re

import pytest

from src.services.extraction import ExtractionService


class TestExtractStatusCode:
    """Test the _extract_status_code helper method."""

    def test_extract_status_code_from_http_error(self):
        service = ExtractionService()

        assert service._extract_status_code("HTTP 400 Bad Request") == "400"
        assert service._extract_status_code("HTTP 429: Rate limit exceeded") == "429"
        assert service._extract_status_code("Error: HTTP 500 Internal Server Error") == "500"
        assert service._extract_status_code("OpenRouter returned HTTP 503") == "503"

    def test_extract_status_code_no_match(self):
        service = ExtractionService()

        assert service._extract_status_code("Generic error message") is None
        assert service._extract_status_code("Connection timeout") is None
        assert service._extract_status_code("") is None

    def test_extract_status_code_multiple_codes(self):
        service = ExtractionService()

        msg = "HTTP 400 occurred, retry returned HTTP 500"
        assert service._extract_status_code(msg) == "400"


class TestHTTPErrorLogging:
    """Test enhanced HTTP error logging in extraction service."""

    def test_extract_status_code_regex_pattern(self):
        pattern = r"HTTP (\d{3})"

        assert re.search(pattern, "HTTP 200")
        assert re.search(pattern, "HTTP 404")
        assert re.search(pattern, "HTTP 500")

        assert not re.search(pattern, "HTTP 50")
        assert not re.search(pattern, "http 200")

        # Edge case: 4 digits matches first 3 (this is expected behavior)
        match = re.search(pattern, "HTTP 5000")
        assert match and match.group(1) == "500"  # Extracts first 3 digits

    def test_status_code_extraction_method_exists(self):
        service = ExtractionService()

        assert hasattr(service, "_extract_status_code")

        error_msg = "OpenRouter API error: HTTP 400 Bad Request"
        status_code = service._extract_status_code(error_msg)
        assert status_code == "400"


@pytest.mark.parametrize(
    "error_message,expected_code",
    [
        ("HTTP 200 OK", "200"),
        ("HTTP 201 Created", "201"),
        ("HTTP 400 Bad Request", "400"),
        ("HTTP 401 Unauthorized", "401"),
        ("HTTP 403 Forbidden", "403"),
        ("HTTP 404 Not Found", "404"),
        ("HTTP 429 Too Many Requests", "429"),
        ("HTTP 500 Internal Server Error", "500"),
        ("HTTP 502 Bad Gateway", "502"),
        ("HTTP 503 Service Unavailable", "503"),
        ("HTTP 504 Gateway Timeout", "504"),
    ],
)
def test_extract_status_code_all_common_codes(error_message, expected_code):
    service = ExtractionService()
    assert service._extract_status_code(error_message) == expected_code


def test_extract_status_code_edge_cases():
    service = ExtractionService()

    assert service._extract_status_code("HTTP 100") == "100"
    assert service._extract_status_code("HTTP 999") == "999"
    assert service._extract_status_code("HTTPS 200") is None
    assert service._extract_status_code("http 200") is None
    assert service._extract_status_code("200") is None
