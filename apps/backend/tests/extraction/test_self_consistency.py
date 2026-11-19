from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from src.config import settings
from src.extraction.extension.service import ExtractionError, ExtractionService


def _bank(diff: str = "0"):
    txn_amount = Decimal("100.00") - Decimal(diff)
    return {
        "institution": "DBS",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "0.00",
        "closing_balance": "100.00",
        "currency": "SGD",
        "transactions": [{"date": "2025-01-10", "amount": f"{txn_amount:.2f}", "direction": "IN", "currency": "SGD"}],
    }


def _invalid():
    payload = _bank("0")
    payload["transactions"] = [{"date": "2025-01-10", "amount": "not-a-number", "direction": "IN"}]
    return payload


def _brokerage():
    return {
        "institution": "Futu",
        "period_start": "2025-06-01",
        "period_end": "2025-06-30",
        "opening_balance": "0.00",
        "closing_balance": "5000.00",
        "currency": "HKD",
        "positions": [{"symbol": "AAPL", "quantity": "10", "market_value": "5000.00"}],
        "transactions": [],
    }


async def _run(attempts_returns, *, max_attempts=3, seed=42):
    service = ExtractionService()
    mock = AsyncMock(side_effect=attempts_returns)
    with (
        patch.object(settings, "ai_extract_max_attempts", max_attempts),
        patch.object(settings, "ai_json_seed", seed),
        patch.object(service, "extract_financial_data", mock),
    ):
        slices, _ = await service._extract_with_balance_retry(
            file_content=b"x",
            institution="DBS",
            file_type="pdf",
            file_url=None,
            force_model=None,
            filename="statement.pdf",
        )
        return slices[0].payload, mock


@pytest.mark.parametrize(
    ("returns_fn", "max_attempts", "expected_calls", "check_fn"),
    [
        (lambda: [_bank("0")], 3, 1, lambda r: r["closing_balance"] == "100.00"),
        (lambda: [_bank("12.50"), _bank("0")], 3, 2, lambda r: r["transactions"][0]["amount"] == "100.00"),
        (
            lambda: [_bank("40.00"), _bank("3.00"), _bank("20.00")],
            3,
            3,
            lambda r: r["transactions"][0]["amount"] == "97.00",
        ),
        (lambda: [_brokerage(), _bank("0")], 3, 1, lambda r: "positions" in r),
        (lambda: [_bank("9.00")], 1, 1, lambda r: r["closing_balance"] == "100.00"),
        (lambda: [_invalid(), _bank("3.00")], 2, 2, lambda r: r["transactions"][0]["amount"] == "97.00"),
        (lambda: [_invalid(), _invalid()], 2, 2, lambda r: r["transactions"][0]["amount"] == "not-a-number"),
        (
            lambda: [_bank("5.00"), ExtractionError("429 rate limited")],
            2,
            2,
            lambda r: r["transactions"][0]["amount"] == "95.00",
        ),
        (lambda: [ExtractionError("timeout"), _bank("0")], 2, 2, lambda r: r["transactions"][0]["amount"] == "100.00"),
        (
            lambda: [_bank("8.00"), ExtractionError("429"), _bank("0")],
            3,
            3,
            lambda r: r["transactions"][0]["amount"] == "100.00",
        ),
    ],
    ids=[
        "first-reconciles",
        "retry-reconciles",
        "keeps-best",
        "brokerage-single",
        "max-1",
        "invalid-skipped",
        "all-invalid-last",
        "transient-keeps-usable",
        "first-err-recovers",
        "mid-err-continues",
    ],
)
async def test_retry_selection_matrix(returns_fn, max_attempts, expected_calls, check_fn):
    result, mock = await _run(returns_fn(), max_attempts=max_attempts)
    assert mock.await_count == expected_calls and check_fn(result)


async def test_seed_varies_and_all_attempts_error_reraises():
    _, mock = await _run([_bank("5.00"), _bank("5.00"), _bank("5.00")], max_attempts=3, seed=42)
    assert [c.kwargs.get("seed_override") for c in mock.await_args_list] == [None, 43, 44]
    with pytest.raises(ExtractionError):
        await _run([ExtractionError("boom"), ExtractionError("boom2")], max_attempts=2)
