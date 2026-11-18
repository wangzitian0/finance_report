"""Re-extract loop and page-batch merge (#2983, #2960)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from src.config import settings
from src.extraction.base.paged_extraction import merge_paged_extractions
from src.extraction.base.validation import balance_is_evaluable
from src.extraction.extension.service import ExtractionService


def _bank(diff: str = "0") -> dict:
    amount = Decimal("100.00") - Decimal(diff)
    return {"institution": "DBS", "period_start": "2025-01-01", "period_end": "2025-01-31", "opening_balance": "0.00", "closing_balance": "100.00", "currency": "SGD", "transactions": [{"date": "2025-01-10", "amount": f"{amount:.2f}", "direction": "IN", "currency": "SGD"}]}


def _no_printed_balance() -> dict:
    return {**_bank("0"), "opening_balance": None, "closing_balance": None}


async def _run(attempts: list, *, max_attempts: int = 2):
    service, mock = ExtractionService(), AsyncMock(side_effect=attempts)
    with patch.object(settings, "ai_extract_max_attempts", max_attempts), patch.object(settings, "ai_json_seed", 42), patch.object(service, "extract_financial_data", mock):
        return await service._extract_with_balance_retry(file_content=b"x", institution=None, file_type="pdf", file_url=None, force_model=None, filename="s.pdf"), mock


async def test_AC_extraction_retry_guard_cases():
    first = _bank("12.50")
    res1, m1 = await _run([first, ValueError("Multiple accounts in one extraction require separate source review")])
    with pytest.raises(ValueError, match="Duplicate currency"):
        await _run([ValueError("Duplicate currency in balances: EUR"), ValueError("Duplicate currency in balances: EUR")])

    only = _no_printed_balance()
    res2, m2 = await _run([only, _bank("0")])
    good = _bank("0")
    res3, m3 = await _run([_bank("12.50"), good])
    res4, m4 = await _run([first, _no_printed_balance()])
    assert (res1 is first, m1.await_count, res2 is only, m2.await_count, res3 is good, m3.await_count, res4 is first, m4.await_count) == (True, 2, True, 1, True, 2, True, 2)


def test_AC_extraction_merge_and_balance_evaluable():
    merged = merge_paged_extractions([{"account_last4": "21001", "transactions": [{"amount": "1.00"}]}, {"account_last4": "XXXX-XXXXX3-81001", "transactions": [{"amount": "2.00"}]}])
    with pytest.raises(ValueError, match="Multiple accounts"):
        merge_paged_extractions([{"account_last4": "1234"}, {"account_last4": "5678"}])
    assert (
        len(merged["transactions"]), balance_is_evaluable("0.00", "100.00", None),
        balance_is_evaluable(None, None, [{"currency": "SGD"}]), balance_is_evaluable("0.00", None, None), balance_is_evaluable(None, None, None),
    ) == (2, True, True, False, False)
