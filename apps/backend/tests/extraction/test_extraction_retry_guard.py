"""Re-extract loop and page-batch merge (#2983, #2960).

Evidence of the run of 2026-11-11 on staging: a failed second pass threw away a usable first
parse, two printed suffixes of one account were taken as two accounts, and a statement that
prints no balance was extracted twice although no second pass can reconcile it.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from src.config import settings
from src.extraction.base.paged_extraction import merge_paged_extractions
from src.extraction.base.validation import balance_is_evaluable
from src.extraction.extension.service import ExtractionService


def _bank(diff: str = "0") -> dict:
    amount = Decimal("100.00") - Decimal(diff)
    return {
        "institution": "DBS",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "0.00",
        "closing_balance": "100.00",
        "currency": "SGD",
        "transactions": [{"date": "2025-01-10", "amount": f"{amount:.2f}", "direction": "IN", "currency": "SGD"}],
    }


def _no_printed_balance() -> dict:
    payload = _bank("0")
    payload["opening_balance"] = None
    payload["closing_balance"] = None
    return payload


async def _run(attempts: list, *, max_attempts: int = 2):
    service = ExtractionService()
    mock = AsyncMock(side_effect=attempts)
    with (
        patch.object(settings, "ai_extract_max_attempts", max_attempts),
        patch.object(settings, "ai_json_seed", 42),
        patch.object(service, "extract_financial_data", mock),
    ):
        result = await service._extract_with_balance_retry(
            file_content=b"x", institution=None, file_type="pdf", file_url=None, force_model=None, filename="s.pdf"
        )
    return result, mock


async def test_AC_extraction_2983_1_value_error_in_a_later_pass_keeps_the_earlier_parse():
    """AC-extraction.2983.1: A ValueError in a later pass keeps the parse of the earlier pass."""
    first = _bank("12.50")
    result, mock = await _run([first, ValueError("Multiple accounts in one extraction require separate source review")])
    assert result is first
    assert mock.await_count == 2


async def test_AC_extraction_2983_2_value_error_in_every_pass_is_raised():
    """AC-extraction.2983.2: A ValueError in every pass reaches the caller."""
    with pytest.raises(ValueError, match="Duplicate currency"):
        await _run(
            [ValueError("Duplicate currency in balances: EUR"), ValueError("Duplicate currency in balances: EUR")]
        )


def test_AC_extraction_2983_3_merge_compares_the_account_suffix_after_sanitizing():
    """AC-extraction.2983.3: The merge compares account suffixes after sanitizing them."""
    # The Amex sample prints "-21001" on most pages and "XXXX-XXXXX3-81001" in a rewards table.
    merged = merge_paged_extractions(
        [
            {"account_last4": "21001", "transactions": [{"amount": "1.00"}]},
            {"account_last4": "XXXX-XXXXX3-81001", "transactions": [{"amount": "2.00"}]},
        ]
    )
    assert len(merged["transactions"]) == 2


def test_AC_extraction_2983_4_merge_still_rejects_two_different_accounts():
    """AC-extraction.2983.4: The merge still rejects two different accounts."""
    with pytest.raises(ValueError, match="Multiple accounts"):
        merge_paged_extractions([{"account_last4": "1234"}, {"account_last4": "5678"}])


async def test_AC_extraction_2960_1_a_statement_with_no_printed_balance_is_extracted_once():
    """AC-extraction.2960.1: A statement with no printed balance is extracted once."""
    only = _no_printed_balance()
    result, mock = await _run([only, _bank("0")])
    assert result is only
    assert mock.await_count == 1


async def test_AC_extraction_2960_2_a_printed_balance_that_does_not_reconcile_is_still_retried():
    """AC-extraction.2960.2: A printed balance that does not reconcile is extracted again."""
    good = _bank("0")
    result, mock = await _run([_bank("12.50"), good])
    assert result is good
    assert mock.await_count == 2


async def test_AC_extraction_2960_4_a_later_pass_without_balances_does_not_replace_a_reconcilable_parse():
    """AC-extraction.2960.4: A later pass without balances does not replace a reconcilable parse."""
    first = _bank("12.50")
    result, mock = await _run([first, _no_printed_balance()])
    assert result is first
    assert mock.await_count == 2


def test_AC_extraction_2960_3_balance_is_evaluable_with_both_ends_or_a_per_currency_list():
    """AC-extraction.2960.3: A statement is evaluable with both ends or a per-currency list."""
    assert balance_is_evaluable("0.00", "100.00", None) is True
    assert balance_is_evaluable(None, None, [{"currency": "SGD"}]) is True
    assert balance_is_evaluable("0.00", None, None) is False
    assert balance_is_evaluable(None, None, None) is False
