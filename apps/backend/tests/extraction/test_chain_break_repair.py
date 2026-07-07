"""AC13.20: Running-balance chain-break detector + repair-pass hook (root #1140).

Bank-statement under-extraction is probabilistic (LLM recall), so this suite pins
the *deterministic* slice around the soft recall metric:

- AC-C1 (AC-extraction.120.1-.3): a pure, Decimal-based detector that walks the running
  ``balance_after`` chain and returns the exact index where a row was dropped.
- AC-C2 (AC-extraction.120.4-.6): a repair-pass hook keyed off the balance self-check delta
  that re-extracts the broken region exactly once via an injectable backend, and
  is a safe no-op when there is no detector signal or no backend.
- AC-C3 (AC-extraction.120.7): a synthetic dropped-row regression fixture that drives both.

No live LLM: the re-extraction backend is a deterministic test double, so these
tests stay reproducible in CI.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

from src.extraction.base.validation import detect_balance_chain_break, validate_balance
from src.extraction.extension.chain_repair import (
    ChainRepairResult,
    repair_under_extraction,
)
from src.extraction.extension.service import ExtractionService

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load_corpus() -> dict:
    with (FIXTURES / "clean_bank_dropped_row_corpus.json").open() as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
# Fixtures (AC-C3): a clean bank-statement shape, plus a dropped-row variant.
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


# --------------------------------------------------------------------------- #
# AC-C2 — repair-pass hook
# --------------------------------------------------------------------------- #
class _RecordingReExtractor:
    """Deterministic injectable backend that records its calls and returns a
    repaired payload with the dropped row re-inserted (no live LLM)."""

    def __init__(self, repaired_payload: dict | None = None):
        self.calls: list[dict] = []
        self._repaired = repaired_payload

    def reextract_region(self, *, payload, break_info):
        self.calls.append({"payload": payload, "break_info": break_info})
        return self._repaired


def test_AC13_20_4_repair_hook_invoked_once_on_mismatch():
    """AC-extraction.120.4 (AC-C2): on a balance mismatch with a detected break, the hook fires once."""
    payload = _dropped_row_payload()
    # Sanity: the self-check itself flags the under-extraction.
    assert validate_balance(payload)["balance_valid"] is False

    repaired = _clean_chain_payload()
    backend = _RecordingReExtractor(repaired_payload=repaired)

    result = repair_under_extraction(payload, reextractor=backend)
    assert isinstance(result, ChainRepairResult)
    assert result.attempted is True
    assert len(backend.calls) == 1
    # The break info handed to the backend is the detector's pinpointed region.
    assert backend.calls[0]["break_info"].index == 1
    # The repaired payload reconciles, so the hook reports a successful repair.
    assert result.repaired is True
    assert result.payload is repaired


def test_AC13_20_5_repair_hook_not_invoked_on_clean_chain():
    """AC-extraction.120.5 (AC-C2): a reconciling chain never invokes the repair backend."""
    payload = _clean_chain_payload()
    backend = _RecordingReExtractor(repaired_payload=_clean_chain_payload())
    result = repair_under_extraction(payload, reextractor=backend)
    assert result.attempted is False
    assert result.repaired is False
    assert backend.calls == []
    # No-op must return the original payload untouched.
    assert result.payload is payload


def test_AC13_20_6_repair_is_safe_noop_without_backend():
    """AC-extraction.120.6 (AC-C2): with no backend injected, the hook is a safe no-op (original payload)."""
    payload = _dropped_row_payload()
    result = repair_under_extraction(payload, reextractor=None)
    # The detector still signals (so callers can log), but nothing is mutated.
    assert result.attempted is False
    assert result.repaired is False
    assert result.payload is payload
    assert result.break_info is not None and result.break_info.index == 1


def test_AC13_20_repair_noop_on_non_computable_payload():
    """AC-C2: a structurally-broken (non-computable) payload must NOT trigger the repair backend.

    ``validate_balance`` returns ``balance_valid=False`` *and*
    ``balance_computable=False`` when amounts are non-numeric/missing. In that case
    the self-check delta is undefined, so attempting region re-extraction is
    pointless/possibly harmful; the hook must short-circuit to a safe no-op without
    invoking the backend.
    """
    payload = _clean_chain_payload()
    # Corrupt an amount so the balance self-check cannot even be computed.
    payload["transactions"][0]["amount"] = "not-a-number"
    balance = validate_balance(payload)
    assert balance["balance_valid"] is False
    assert balance["balance_computable"] is False

    backend = _RecordingReExtractor(repaired_payload=_clean_chain_payload())
    result = repair_under_extraction(payload, reextractor=backend)

    # The backend must never be invoked on a non-computable payload.
    assert backend.calls == []
    assert result.attempted is False
    assert result.repaired is False
    assert result.break_info is None
    # No-op must return the original payload untouched.
    assert result.payload is payload


def test_AC13_20_repair_only_once_even_if_still_broken():
    """AC-C2: the repair pass runs at most once; a still-broken re-extract is not
    retried in a loop (bounded, deterministic)."""
    payload = _dropped_row_payload()
    # Backend returns a payload that STILL does not reconcile.
    still_broken = _dropped_row_payload()
    backend = _RecordingReExtractor(repaired_payload=still_broken)
    result = repair_under_extraction(payload, reextractor=backend)
    assert len(backend.calls) == 1
    assert result.attempted is True
    assert result.repaired is False
    # On a failed repair the hook keeps the original payload (no regression).
    assert result.payload is payload


# --------------------------------------------------------------------------- #
# AC-C3 — regression fixture wiring detector + repair together
# --------------------------------------------------------------------------- #
def test_AC13_20_7_regression_fixture_detects_and_repairs():
    """AC-extraction.120.7 (AC-C3): the synthetic dropped-row fixture drives the detector to the right
    index and triggers the repair hook exactly once, yielding a reconciling parse."""
    under_extracted = _dropped_row_payload()

    # 1) detector pinpoints the dropped region
    break_info = detect_balance_chain_break(under_extracted["transactions"])
    assert break_info is not None and break_info.index == 1

    # 2) repair hook re-extracts that region via the injected (deterministic) backend
    backend = _RecordingReExtractor(repaired_payload=_clean_chain_payload())
    result = repair_under_extraction(under_extracted, reextractor=backend)

    assert len(backend.calls) == 1
    assert result.repaired is True
    # 3) the repaired payload now reconciles under the same hard self-check guard
    assert validate_balance(result.payload)["balance_valid"] is True


# --------------------------------------------------------------------------- #
# AC-C3 end-to-end: the regression-corpus fixture drives the repair pass through
# the live ExtractionService retry loop with an injected RegionReExtractor.
# --------------------------------------------------------------------------- #
async def test_AC13_20_8_corpus_fixture_triggers_repair_end_to_end():
    """AC-extraction.120.8 (AC-C3): the clean-bank dropped-row corpus fixture triggers the chain-break
    detector + repair_under_extraction hook end-to-end through ExtractionService.

    Unlike AC-extraction.120.7 (which calls the bare detector/hook functions), this drives the
    actual ``_extract_with_balance_retry`` path: every model attempt returns the
    under-extracted (dropped-row) payload so the whole-document retry never
    reconciles, the repair pass runs the deterministic detector, and the injected
    ``RegionReExtractor`` re-extracts the dropped region exactly once — yielding a
    reconciling parse without any live LLM.
    """
    corpus = _load_corpus()
    under_extracted = corpus["dropped_row"]
    clean = corpus["clean"]

    # Sanity: the corpus shapes are what AC-C3 needs — the dropped-row chain breaks
    # at the documented index and the clean shape reconciles.
    assert validate_balance(under_extracted)["balance_valid"] is False
    assert detect_balance_chain_break(under_extracted["transactions"]).index == corpus["break_index"]
    assert validate_balance(clean)["balance_valid"] is True

    service = ExtractionService()
    # Every attempt yields the same under-extracted parse (recall is the problem;
    # re-sampling alone does not recover the dropped row), forcing the retry loop to
    # fall through to the repair pass.
    service.extract_financial_data = AsyncMock(return_value=dict(under_extracted))
    # Inject the deterministic region re-extractor that recovers the dropped row.
    backend = _RecordingReExtractor(repaired_payload=clean)
    service.region_reextractor = backend

    result = await service._extract_with_balance_retry(
        file_content=b"%PDF-1.7",
        institution="DBS",
        file_type="pdf",
        file_url=None,
        force_model=None,
        filename="dbs-dropped-row-2503.pdf",
    )

    # The injected re-extractor fired exactly once and the returned parse now
    # reconciles under the same hard self-check guard.
    assert len(backend.calls) == 1
    assert backend.calls[0]["break_info"].index == corpus["break_index"]
    assert validate_balance(result)["balance_valid"] is True
    assert result is clean
