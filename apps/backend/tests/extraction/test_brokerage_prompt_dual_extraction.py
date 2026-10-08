"""Tests for brokerage prompt dual extraction instructions and empty extraction guard."""

from uuid import uuid4

from src.extraction.base.types import DocumentSource
from src.extraction.extension.prompts.statement import get_parsing_prompt
from src.extraction.extension.service import ExtractionService


def test_brokerage_prompt_contains_dual_extraction_guidance():
    """BROKERAGE_POSITIONS_PROMPT must explicitly instruct extracting both cash activity and positions."""
    prompt = get_parsing_prompt(document_kind="brokerage")
    assert "extract both" in prompt.lower()
    assert "no cash transactions occurred" in prompt.lower()


async def test_empty_extraction_sets_clear_validation_error(monkeypatch):
    """When both transactions and positions are empty, validation_error must warn the user."""
    service = ExtractionService()

    async def mock_extract(*args, **kwargs):
        return {
            "institution": "Futu",
            "currency": "USD",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "positions": [],
            "transactions": [],
        }

    monkeypatch.setattr(service, "_extract_vision_source", mock_extract)

    source = DocumentSource(
        path=None,
        content=b"dummy",
        url=None,
        filename="futu_empty.pdf",
        content_hash="0" * 64,
    )

    result = await service.parse_document(
        source=source,
        institution="Futu",
        user_id=uuid4(),
    )

    assert any("no transactions or holdings in recognizable format" in r.lower() for r in result.review_reasons)
