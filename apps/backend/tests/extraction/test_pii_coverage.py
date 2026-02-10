"""Additional coverage tests for service layer.

These tests cover edge cases and error paths for service layer
that are not covered in the main test files.
"""

import pytest

from src.services.pii_redaction import detect_pii, mask_account_number, redact_text


@pytest.mark.asyncio
class TestServiceLayerCoverage:
    """Additional tests for service layer coverage."""

    async def test_pii_redaction_edge_cases(self):
        """AC3.5.1: PII redaction edge cases
        GIVEN text with edge case PII patterns
        WHEN redacting
        THEN it should handle gracefully
        """
        pii_matches = detect_pii("")
        assert pii_matches == []

        pii_matches = detect_pii("No PII here")
        assert len(pii_matches) == 0

        text_with_email = "Contact user@example.com for details"
        pii_matches = detect_pii(text_with_email)
        assert isinstance(pii_matches, list)

        result = redact_text("Some text here", replacement="[REDACTED]")
        assert result is not None
        assert hasattr(result, "redacted_text")

        masked = mask_account_number("1234567890", visible_digits=4)
        assert masked.endswith("7890")
        assert "*" in masked or "X" in masked
