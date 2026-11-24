"""Re-extract loop and page-batch merge (#2983, #2960)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from src.config import settings
from src.extraction.base.paged_extraction import merge_paged_extractions
from src.extraction.base.validation import balance_is_evaluable
from src.extraction.extension.service import ExtractionError, ExtractionService


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
    return {**_bank("0"), "opening_balance": None, "closing_balance": None}


async def _run(attempts: list, *, max_attempts: int = 2):
    service, mock = ExtractionService(), AsyncMock(side_effect=attempts)
    with (
        patch.object(settings, "ai_extract_max_attempts", max_attempts),
        patch.object(settings, "ai_json_seed", 42),
        patch.object(service, "extract_financial_data", mock),
    ):
        slices, _ = await service._extract_with_balance_retry(
            file_content=b"x", institution=None, file_type="pdf", file_url=None, force_model=None, filename="s.pdf"
        )
        return slices[0].payload, mock


@pytest.mark.parametrize(
    "error",
    [ExtractionError("model failed"), ValueError("v"), KeyError("k"), TypeError("t"), AttributeError("a"), ArithmeticError("n")],
    ids=lambda error: type(error).__name__,
)
async def test_AC_extraction_later_pass_failure_keeps_the_kept_pass_and_says_so(error, caplog):
    """A failed model call or a reading of the wrong shape in a later pass keeps the earlier pass, and the log says that the loop ended on a failure."""
    first = _bank("12.50")
    result, mock = await _run([first, error])
    assert result is first and mock.await_count == 2
    messages = [record.getMessage() for record in caplog.records if "keeping the best pass" in record.getMessage()]
    assert len(messages) == 1
    assert "'ended_on_failure': True" in messages[0] and f"'failed_pass': '{type(error).__name__}'" in messages[0]


async def test_AC_extraction_log_says_ended_on_failure_only_when_the_last_pass_failed(caplog):
    """Review of #3202: a failed pass 2 followed by a completed pass 3 is not a loop that ended on a failure."""
    result, mock = await _run([_bank("12.50"), ExtractionError("model failed"), _bank("4.00")], max_attempts=3)
    assert mock.await_count == 3 and result["transactions"][0]["amount"] == "96.00"
    messages = [record.getMessage() for record in caplog.records if "keeping the best pass" in record.getMessage()]
    assert len(messages) == 1 and "'ended_on_failure': False" in messages[0] and "'failed_pass': None" in messages[0]


@pytest.mark.parametrize(
    "error",
    [RuntimeError("bug"), AssertionError("bug"), OSError("disk"), NameError("bug"), ImportError("bug")],
    ids=lambda error: type(error).__name__,
)
async def test_AC_extraction_later_pass_bug_ends_the_loop_with_its_error(error):
    """An error of another class is a bug: it does not hide behind the kept pass."""
    with pytest.raises(type(error), match="bug|disk"):
        await _run([_bank("12.50"), error])


async def test_AC_extraction_retry_guard_cases():
    first = _bank("12.50")
    res1, m1 = await _run([first, ValueError("Multiple accounts in one extraction require separate source review")])
    with pytest.raises(ValueError, match="Duplicate currency"):
        await _run(
            [ValueError("Duplicate currency in balances: EUR"), ValueError("Duplicate currency in balances: EUR")]
        )

    only = _no_printed_balance()
    res2, m2 = await _run([only, _bank("0")])
    good = _bank("0")
    res3, m3 = await _run([_bank("12.50"), good])
    res4, m4 = await _run([first, _no_printed_balance()])
    assert (
        res1 is first,
        m1.await_count,
        res2 is only,
        m2.await_count,
        res3 is good,
        m3.await_count,
        res4 is first,
        m4.await_count,
    ) == (True, 2, True, 1, True, 2, True, 2)


def test_AC_extraction_merge_and_balance_evaluable():
    merged = merge_paged_extractions(
        [
            {"account_last4": "21001", "transactions": [{"amount": "1.00"}]},
            {"account_last4": "XXXX-XXXXX3-81001", "transactions": [{"amount": "2.00"}]},
        ]
    )
    with pytest.raises(ValueError, match="Multiple accounts"):
        merge_paged_extractions([{"account_last4": "1234"}, {"account_last4": "5678"}])
    assert (
        len(merged["transactions"]),
        balance_is_evaluable("0.00", "100.00", None),
        balance_is_evaluable(None, None, [{"currency": "SGD"}]),
        balance_is_evaluable("0.00", None, None),
        balance_is_evaluable(None, None, None),
    ) == (2, True, True, False, False)


def test_AC_extraction_3039_prefect_worker_poll_interval_is_bounded():
    """#3039: Worker entrypoint bounds Prefect poll wait <= 2s and keeps worker concurrency limit."""
    from pathlib import Path

    script = (Path(__file__).resolve().parents[2] / "scripts" / "prefect_worker_entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert "PREFECT_WORKER_QUERY_SECONDS" in script
    assert "--prefetch-seconds" in script
    assert "--limit" in script
