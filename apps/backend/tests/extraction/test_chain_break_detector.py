"""AC13.20: Running-balance chain-break detector (root #1140).

Bank-statement under-extraction is probabilistic (LLM recall), so this suite pins
the deterministic slice around it: a pure, Decimal-based detector that walks the
running ``balance_after`` chain and returns the exact index where a row was dropped
(AC-extraction.120.1-.3). ``ExtractionService`` emits the ``chain_break`` metric from it.
"""

from __future__ import annotations

from decimal import Decimal

from src.extraction.base.validation import detect_balance_chain_break


# --------------------------------------------------------------------------- #
# Fixtures: a clean bank-statement shape, plus a dropped-row variant.
# --------------------------------------------------------------------------- #
def _clean_chain_payload() -> dict:
    """A clean bank statement whose running balance_after chain is consistent.

    opening 1000 -> +500 (1500) -> -200 (1300) -> +300 (1600) = closing 1600.
    """
    return {
        "institution": "DBS",
        "currency": "SGD",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "1000.00",
        "closing_balance": "1600.00",
        "transactions": [
            {"date": "2025-01-05", "amount": "500.00", "direction": "IN", "balance_after": "1500.00"},
            {"date": "2025-01-10", "amount": "200.00", "direction": "OUT", "balance_after": "1300.00"},
            {"date": "2025-01-20", "amount": "300.00", "direction": "IN", "balance_after": "1600.00"},
        ],
    }


def _dropped_row_payload() -> dict:
    """The clean statement with the second transaction (the -200 row) dropped.

    The chain now jumps 1500 -> (missing -200) -> 1300, so balance_after[i-1]
    (1500) + signed_amount of the NEXT surviving row (+300) = 1800 != 1300. The
    break therefore surfaces at index 1 (the first row that does not reconcile
    against its predecessor's balance_after).
    """
    payload = _clean_chain_payload()
    # Drop the middle OUT row; opening/closing stay as the *true* statement values
    # so the per-currency self-check also flags the under-extraction.
    payload["transactions"] = [
        {"date": "2025-01-05", "amount": "500.00", "direction": "IN", "balance_after": "1500.00"},
        {"date": "2025-01-20", "amount": "300.00", "direction": "IN", "balance_after": "1300.00"},
    ]
    return payload


# --------------------------------------------------------------------------- #
# AC-C1 — detector
# --------------------------------------------------------------------------- #
def test_AC13_20_1_detector_finds_break_index_on_dropped_row():
    """AC-extraction.120.1 (AC-C1): detector pinpoints the exact break index on a dropped-row chain."""
    payload = _dropped_row_payload()
    result = detect_balance_chain_break(payload["transactions"])
    assert result is not None
    # Index 1 is the first row whose balance_after does not follow from the prior
    # row's balance_after plus its own signed amount.
    assert result.index == 1
    # The detector reports the exact arithmetic it expected vs. observed.
    assert result.expected_balance == Decimal("1800.00")  # 1500 + 300 (IN)
    assert result.observed_balance == Decimal("1300.00")


def test_AC13_20_2_clean_chain_reports_no_break():
    """AC-extraction.120.2 (AC-C1): a fully-consistent chain reports no break (None)."""
    payload = _clean_chain_payload()
    assert detect_balance_chain_break(payload["transactions"]) is None


def test_AC13_20_3_detector_is_decimal_tolerant():
    """AC-extraction.120.3 (AC-C1): detection is Decimal-based and tolerant within BALANCE_TOLERANCE.

    A sub-tolerance rounding wobble (<= 0.10) must NOT be reported as a break, and
    the arithmetic must be exact Decimal (no 0.1+0.2 float drift).
    """
    txns = [
        {"date": "2025-01-05", "amount": "0.10", "direction": "IN", "balance_after": "1000.10"},
        # 1000.10 + 0.20 = 1000.30 exactly; observed 1000.35 is 0.05 off => within tolerance.
        {"date": "2025-01-06", "amount": "0.20", "direction": "IN", "balance_after": "1000.35"},
    ]
    assert detect_balance_chain_break(txns, opening_balance=Decimal("1000.00")) is None

    # Same chain but 0.50 off at the second row => beyond tolerance => break at index 1.
    txns[1]["balance_after"] = "1000.80"
    broken = detect_balance_chain_break(txns, opening_balance=Decimal("1000.00"))
    assert broken is not None and broken.index == 1


def test_AC13_20_detector_uses_opening_balance_for_first_row():
    """AC-C1: when an opening balance is supplied, the FIRST row is also checked."""
    txns = [
        # opening 1000 + 500 = 1500 expected, observed 1400 => break at index 0.
        {"date": "2025-01-05", "amount": "500.00", "direction": "IN", "balance_after": "1400.00"},
    ]
    result = detect_balance_chain_break(txns, opening_balance=Decimal("1000.00"))
    assert result is not None and result.index == 0
