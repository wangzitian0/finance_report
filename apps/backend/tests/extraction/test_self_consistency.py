"""AC13.17: Balance-aware self-consistency re-extract (#989 Step B).

When the extracted running-balance chain fails to reconcile, re-extract a bounded
number of times before accepting the result (which would route the statement to
`uploaded`). Each attempt varies the decoding seed so retries are *different but
reproducible* samples; the first attempt that reconciles wins, otherwise the
best-by-difference result is kept so routing is unchanged.
"""

from decimal import Decimal
from unittest.mock import AsyncMock, patch

from src.config import settings
from src.services.extraction import ExtractionService


def _bank(diff: str = "0"):
    """A bank payload whose closing balance is off by ``diff`` (0 => reconciles)."""
    # Money math uses Decimal so test data is exact (no float rounding artifacts).
    txn_amount = Decimal("100.00") - Decimal(diff)
    return {
        "institution": "DBS",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "0.00",
        "closing_balance": "100.00",
        "currency": "SGD",
        # one IN txn; opening 0 + txn vs stated closing 100 => off by `diff`
        "transactions": [{"date": "2025-01-10", "amount": f"{txn_amount:.2f}", "direction": "IN", "currency": "SGD"}],
    }


def _structurally_invalid():
    """A payload whose balance is uncomputable (non-numeric amount); validate_balance
    returns balance_computable=False with difference '0'."""
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


async def _run(service, attempts_returns, *, max_attempts=3, seed=42):
    mock = AsyncMock(side_effect=attempts_returns)
    with (
        patch.object(settings, "ai_extract_max_attempts", max_attempts),
        patch.object(settings, "ai_json_seed", seed),
        patch.object(service, "extract_financial_data", mock),
    ):
        result = await service._extract_with_balance_retry(
            file_content=b"x",
            institution="DBS",
            file_type="pdf",
            file_url=None,
            force_model=None,
            filename="statement.pdf",
        )
    return result, mock


async def test_reconciles_first_attempt_single_call():
    """AC13.17.1: a reconciling first parse is returned without retry."""
    service = ExtractionService()
    result, mock = await _run(service, [_bank("0")])
    assert result["closing_balance"] == "100.00"
    assert mock.await_count == 1


async def test_retries_until_reconciles():
    """AC13.17.2: a failing parse is retried and the reconciling result wins."""
    service = ExtractionService()
    good = _bank("0")
    result, mock = await _run(service, [_bank("12.50"), good])
    assert result is good
    assert mock.await_count == 2


async def test_keeps_best_when_none_reconcile():
    """AC13.17.3: when no attempt reconciles, the smallest-difference result is kept
    (so routing to `uploaded` is unchanged) and all attempts are used."""
    service = ExtractionService()
    worst, best = _bank("40.00"), _bank("3.00")
    result, mock = await _run(service, [worst, best, _bank("20.00")], max_attempts=3)
    assert result is best
    assert mock.await_count == 3


async def test_brokerage_is_not_retried():
    """AC13.17.4: brokerage payloads do not reconcile like bank statements and must
    not burn retries."""
    service = ExtractionService()
    result, mock = await _run(service, [_brokerage(), _bank("0")])
    assert "positions" in result
    assert mock.await_count == 1


async def test_seed_varies_per_attempt():
    """AC13.17.5: attempt 0 uses the configured seed; retries use seed+1, seed+2 ..."""
    service = ExtractionService()
    _, mock = await _run(service, [_bank("5.00"), _bank("5.00"), _bank("5.00")], max_attempts=3, seed=42)
    seeds = [c.kwargs.get("seed_override") for c in mock.await_args_list]
    # attempt 0 -> None (falls back to settings seed); retries -> 43, 44
    assert seeds == [None, 43, 44]


async def test_max_attempts_one_disables_retry():
    """AC13.17.6: max_attempts=1 keeps current single-shot behavior."""
    service = ExtractionService()
    result, mock = await _run(service, [_bank("9.00")], max_attempts=1)
    assert result["closing_balance"] == "100.00"
    assert mock.await_count == 1


async def test_structurally_invalid_parse_does_not_win_as_best():
    """AC13.17.7: a structurally-invalid parse (balance uncomputable, difference
    defaults to '0') must not beat a numerically-close parse when none reconcile."""
    service = ExtractionService()
    close = _bank("3.00")
    result, mock = await _run(service, [_structurally_invalid(), close], max_attempts=2)
    assert result is close
    assert mock.await_count == 2


async def test_all_invalid_returns_last_parse():
    """AC13.17.8: if every attempt is structurally invalid, the last parse is
    returned so parse_document's own validation reports the failure (unchanged)."""
    service = ExtractionService()
    last = _structurally_invalid()
    result, _ = await _run(service, [_structurally_invalid(), last], max_attempts=2)
    assert result is last
