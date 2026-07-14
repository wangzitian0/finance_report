"""EPIC-018 Phase 4: Tests for AI CSV parsing fallback."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.extraction.extension.service import ExtractionService


async def test_ai_csv_parsing_returns_valid_mapping():
    """AC-extraction.1804.1: AC18.4.3: AI CSV parsing returns valid column mapping and parses transactions."""
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
            "src.extraction.extension._csv.stream_ai_json",
            return_value=mock_stream,
        ),
        patch(
            "src.extraction.extension._csv.accumulate_stream",
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


async def test_ai_csv_parsing_skips_invalid_amount_rows():
    """AI CSV parser skips rows with invalid dates or amount values."""
    service = ExtractionService()

    ai_mapping = '{"date": "Txn Date", "description": "Narration", "amount": "Amount", "debit": null, "credit": null}'
    rows = [
        {"Txn Date": "bad-date", "Narration": "Bad Date", "Amount": "10.00"},
        {"Txn Date": "15/01/2025", "Narration": "Bad Amount", "Amount": "not-money"},
        {"Txn Date": "16/01/2025", "Narration": "Empty Amount", "Amount": ""},
        {"Txn Date": "17/01/2025", "Narration": "Refund", "Amount": "-4.50"},
    ]

    mock_accumulate = AsyncMock(return_value=ai_mapping)

    with (
        patch.object(service, "api_key", "test-key"),
        patch.object(service, "primary_model", "test-model"),
        patch.object(service, "base_url", "https://test.api"),
        patch("src.extraction.extension._csv.stream_ai_json", return_value=MagicMock()),
        patch("src.extraction.extension._csv.accumulate_stream", mock_accumulate),
    ):
        transactions, period_start, period_end = await service._ai_parse_csv(
            headers=["Txn Date", "Narration", "Amount"],
            rows=rows,
            institution="UnknownBank",
            parse_date=lambda value: datetime.strptime(value, "%d/%m/%Y").date() if "/" in value else None,
            parse_amount=lambda value: Decimal(value) if value not in {"", "not-money"} else None,
        )

    assert len(transactions) == 1
    assert transactions[0]["direction"] == "OUT"
    assert transactions[0]["amount"] == "4.50"
    assert period_start == period_end


async def test_ai_csv_parsing_skips_empty_debit_credit_rows():
    """AI CSV parser skips mapped debit/credit rows that contain no amount."""
    service = ExtractionService()

    ai_mapping = (
        '{"date": "Txn Date", "description": "Narration", "amount": null, "debit": "Debit", "credit": "Credit"}'
    )
    rows = [
        {"Txn Date": "15/01/2025", "Narration": "No Amount", "Debit": "", "Credit": ""},
        {"Txn Date": "16/01/2025", "Narration": "Salary", "Debit": "", "Credit": "3000.00"},
    ]

    mock_accumulate = AsyncMock(return_value=ai_mapping)

    with (
        patch.object(service, "api_key", "test-key"),
        patch.object(service, "primary_model", "test-model"),
        patch.object(service, "base_url", "https://test.api"),
        patch("src.extraction.extension._csv.stream_ai_json", return_value=MagicMock()),
        patch("src.extraction.extension._csv.accumulate_stream", mock_accumulate),
    ):
        transactions, _, _ = await service._ai_parse_csv(
            headers=["Txn Date", "Narration", "Debit", "Credit"],
            rows=rows,
            institution="UnknownBank",
            parse_date=lambda value: datetime.strptime(value, "%d/%m/%Y").date(),
            parse_amount=lambda value: Decimal(value) if value else None,
        )

    assert len(transactions) == 1
    assert transactions[0]["direction"] == "IN"


async def test_known_institution_csv_uses_hardcoded_parser():
    """Known institution CSV uses hardcoded parsers, no AI call needed."""
    service = ExtractionService()

    csv_content = b"Transaction Date,Transaction Ref1,Debit Amount,Credit Amount\n15 Jan 2025,Coffee Shop,25.00,\n16 Jan 2025,Salary,,3000.00\n"

    # No mocking of AI needed - DBS parser should handle this
    result = await service._parse_csv_content(csv_content, "DBS")

    assert len(result["transactions"]) == 2
    assert result["transactions"][0]["direction"] == "OUT"
    assert result["transactions"][1]["direction"] == "IN"


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
            "src.extraction.extension._csv.stream_ai_json",
            mock_stream,
        ),
    ):
        with pytest.raises(Exception, match="No valid transactions found"):
            await service._parse_csv_content(csv_content, "UnknownFormat")
