"""LLM cassette integrity gate tests (EPIC-023 AC23.7 / issue #1307).

The gate (`tools/check_llm_cassettes.py`) is the detectable-drift check: every
committed statement-extraction cassette must satisfy the balance-chain invariant,
so a re-recorded cassette where the LLM drifted into an inconsistent extraction
fails CI. Runs in the lint job (pure Python, no key/network/DB).
"""

from __future__ import annotations

from decimal import Decimal

from common.ssot.check_llm_cassettes import (
    balance_violation,
    check,
    _response_text,
)


def test_AC23_7_1_committed_cassettes_satisfy_balance_chain() -> None:
    """AC23.7.1: every committed statement cassette satisfies opening + Σ == closing."""
    assert check() == []


def test_AC23_7_1_balance_violation_detects_a_drifted_cassette() -> None:
    """AC23.7.1: a statement whose chain does not reconcile is flagged (drift catch)."""
    good = {
        "opening_balance": "100.00",
        "closing_balance": "130.00",
        "transactions": [{"amount": "-5.00"}, {"amount": "+50.00"}, {"amount": "-15.00"}],
    }
    assert balance_violation(good) is None

    drifted = {
        "opening_balance": "100.00",
        "closing_balance": "130.00",
        "transactions": [{"amount": "-5.00"}],  # net -5 -> closing should be 95, not 130
    }
    assert balance_violation(drifted) is not None


def test_AC23_7_1_balance_uses_direction_not_just_amount_sign() -> None:
    """AC23.7.1: net is computed amount+direction aware (the canonical/vision shape),
    not a naive sum of unsigned amounts."""
    # Magnitudes + IN/OUT direction (how glm-4.6v reads a statement): -5 +50 -15 = +30.
    directional = {
        "opening_balance": "100.00",
        "closing_balance": "130.00",
        "transactions": [
            {"amount": "5.00", "direction": "OUT"},
            {"amount": "50.00", "direction": "IN"},
            {"amount": "15.00", "direction": "OUT"},
        ],
    }
    assert balance_violation(directional) is None
    # If direction were ignored (naive sum 5+50+15=70 -> 170 != 130) this would pass
    # incorrectly; flipping all to IN must be flagged, proving direction is applied.
    all_in = {
        "opening_balance": "100.00",
        "closing_balance": "130.00",
        "transactions": [
            {"amount": "5.00", "direction": "IN"},
            {"amount": "50.00", "direction": "IN"},
            {"amount": "15.00", "direction": "IN"},
        ],
    }
    assert balance_violation(all_in) is not None


def test_AC23_7_1_uses_decimal_not_float() -> None:
    """AC23.7.1: amounts that would lose precision as float still reconcile via Decimal."""
    payload = {
        "opening_balance": "0.00",
        "closing_balance": "0.30",
        "transactions": [{"amount": "0.10"}, {"amount": "0.10"}, {"amount": "0.10"}],
    }
    # 0.1 + 0.1 + 0.1 != 0.3 in float; Decimal makes it exact.
    assert balance_violation(payload) is None
    assert Decimal("0.10") * 3 == Decimal("0.30")


def test_AC23_7_1_extracts_response_text_across_shapes() -> None:
    """AC23.7.1: the gate reads the frozen text from stream_text / text / choices."""
    assert _response_text({"stream_text": "abc"}) == "abc"
    assert _response_text({"text": "xyz"}) == "xyz"
    assert _response_text({"choices": [{"message": {"content": "deep"}}]}) == "deep"
    assert _response_text("raw") == "raw"
    assert _response_text({"nothing": 1}) is None
