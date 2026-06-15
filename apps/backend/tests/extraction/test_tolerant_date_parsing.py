"""Tolerant statement date parsing — non-ISO formats + non-fatal bad rows (#1086).

Before this, a single empty/non-ISO date aborted the entire document parse, making
Chinese-format statements (e.g. ``2025年01月15日``) unparseable and discarding an
otherwise-good multi-month statement on one bad row.
"""

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from src.prompts import get_parsing_prompt
from src.services.extraction import ExtractionService, _tolerant_parse_date


def test_AC13_19_4_parsing_prompt_instructs_iso_date_normalization():
    """AC13.19.4: the extraction prompt makes the model the primary date normalizer.

    Asserts the specific rule text and a concrete conversion example so the test fails
    if the prompt drops or weakens the ISO-normalization requirement (the tolerant
    parser is only a defensive fallback)."""
    prompt = get_parsing_prompt("DBS")
    # The explicit instruction to convert every source format to ISO.
    assert "Normalize EVERY date to ISO YYYY-MM-DD" in prompt
    assert "never echo a non-ISO source format" in prompt
    # At least one concrete conversion example, incl. the Chinese format that broke #1086.
    assert "2025年01月15日 -> 2025-01-15" in prompt


def test_AC13_19_1_tolerant_parse_date_accepts_non_iso_formats():
    """AC13.19.1: common non-ISO formats parse; empty/garbage return None."""
    assert _tolerant_parse_date("2025-01-15") == date(2025, 1, 15)
    assert _tolerant_parse_date("2025/01/15") == date(2025, 1, 15)
    assert _tolerant_parse_date("2025.01.15") == date(2025, 1, 15)
    assert _tolerant_parse_date("2025年01月15日") == date(2025, 1, 15)
    assert _tolerant_parse_date("15/01/2025") == date(2025, 1, 15)
    assert _tolerant_parse_date("15 Jan 2025") == date(2025, 1, 15)
    assert _tolerant_parse_date("2025-01-15T00:00:00") == date(2025, 1, 15)
    # Non-fatal sentinels and junk yield None so callers can skip/flag.
    for bad in (None, "", "   ", "None", "null", "n/a", "-", "not-a-date"):
        assert _tolerant_parse_date(bad) is None


async def test_AC13_19_2_chinese_format_statement_parses_instead_of_aborting():
    """AC13.19.2: a statement whose dates are in Chinese format parses successfully
    rather than being rejected with "Date is required"/"Invalid date format"."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "period_start": "2025年01月01日",
            "period_end": "2025年01月31日",
            "opening_balance": "100.00",
            "closing_balance": "150.00",
            "transactions": [
                {"date": "2025年01月15日", "amount": "50.00", "direction": "IN", "description": "工资"},
            ],
        }
    )

    statement, transactions = await service.parse_document(
        file_path=Path("zh.pdf"), institution="CMB", user_id=uuid4(), file_content=b"content"
    )

    assert statement.period_start == date(2025, 1, 1)
    assert statement.period_end == date(2025, 1, 31)
    assert len(transactions) == 1
    assert transactions[0].txn_date == date(2025, 1, 15)


async def test_AC13_19_3_one_bad_row_date_is_non_fatal():
    """AC13.19.3: one unparseable row date is skipped; the good rows still parse and
    the document is not rejected as a whole."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "100.00",
            "closing_balance": "150.00",
            "transactions": [
                {"date": "garbage-date", "amount": "10.00", "direction": "IN", "description": "Bad"},
                {"date": "2025/01/20", "amount": "50.00", "direction": "IN", "description": "Good"},
            ],
        }
    )

    statement, transactions = await service.parse_document(
        file_path=Path("mixed.pdf"), institution="DBS", user_id=uuid4(), file_content=b"content"
    )

    assert statement is not None
    assert len(transactions) == 1
    assert transactions[0].description == "Good"
    assert transactions[0].txn_date == date(2025, 1, 20)
