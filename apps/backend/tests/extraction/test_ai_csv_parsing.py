"""EPIC-018 Phase 4: Tests for AI CSV parsing fallback."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.extraction import ExtractionService


@pytest.mark.asyncio
async def test_ai_csv_parsing_returns_valid_mapping():
    """AC18.4.3: AI CSV parsing returns valid column mapping and parses transactions."""
    service = ExtractionService()

    # Mock AI response with column mapping
    ai_mapping = '{"date": "Txn Date", "description": "Narration", "amount": null, "debit": "Debit", "credit": "Credit", "balance": "Balance", "reference": null, "currency": null, "date_format": "%d/%m/%Y", "has_header": true, "institution_guess": "Unknown Bank"}'

    csv_content = b"Txn Date,Narration,Debit,Credit,Balance\n15/01/2025,Coffee Shop,25.00,,975.00\n16/01/2025,Salary,,3000.00,3975.00\n"

    mock_accumulate = AsyncMock(return_value=ai_mapping)
    mock_stream = MagicMock()

    with (
        patch.object(service, "api_key", "test-key"),
        patch.object(service, "primary_model", "test-model"),
        patch.object(service, "base_url", "https://test.api"),
        patch(
            "src.services.openrouter_streaming.stream_openrouter_json",
            return_value=mock_stream,
        ),
        patch(
            "src.services.openrouter_streaming.accumulate_stream",
            mock_accumulate,
        ),
    ):
        result = await service._parse_csv_content(csv_content, "UnknownBank")

    assert len(result["transactions"]) == 2
    assert result["transactions"][0]["direction"] == "OUT"
    assert result["transactions"][0]["amount"] == "25.00"
    assert result["transactions"][0]["description"] == "Coffee Shop"
    assert result["transactions"][1]["direction"] == "IN"
    assert result["transactions"][1]["amount"] == "3000.00"


@pytest.mark.asyncio
async def test_known_institution_csv_uses_hardcoded_parser():
    """Known institution CSV uses hardcoded parsers, no AI call needed."""
    service = ExtractionService()

    csv_content = b"Transaction Date,Transaction Ref1,Debit Amount,Credit Amount\n15 Jan 2025,Coffee Shop,25.00,\n16 Jan 2025,Salary,,3000.00\n"

    # No mocking of AI needed - DBS parser should handle this
    result = await service._parse_csv_content(csv_content, "DBS")

    assert len(result["transactions"]) == 2
    assert result["transactions"][0]["direction"] == "OUT"
    assert result["transactions"][1]["direction"] == "IN"


@pytest.mark.asyncio
async def test_ai_csv_parsing_graceful_failure():
    """AI CSV parsing failure falls through to standard error."""
    service = ExtractionService()

    csv_content = b"Col1,Col2,Col3\nfoo,bar,baz\n"

    mock_stream = MagicMock(side_effect=Exception("API error"))

    with (
        patch.object(service, "api_key", "test-key"),
        patch.object(service, "primary_model", "test-model"),
        patch.object(service, "base_url", "https://test.api"),
        patch(
            "src.services.openrouter_streaming.stream_openrouter_json",
            mock_stream,
        ),
    ):
        with pytest.raises(Exception, match="No valid transactions found"):
            await service._parse_csv_content(csv_content, "UnknownFormat")
