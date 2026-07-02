"""LLM cassette integrity gate tests (migrated from EPIC-023's AC23.7 group to
the `testing` package; see common/testing/contract.py roadmap; issue #1307).

AC-testing.11.1

The gate (`tools/check_llm_cassettes.py`) is the detectable-drift check: every
committed statement-extraction cassette must satisfy the balance-chain invariant,
so a re-recorded cassette where the LLM drifted into an inconsistent extraction
fails CI. Runs in the lint job (pure Python, no key/network/DB).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from common.ssot.check_llm_cassettes import (
    balance_violation,
    check,
    exempt_count,
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
    # `directional` reconciles ONLY because OUT subtracts (+50 - 5 - 15 = +30). A
    # direction-ignoring magnitude sum would be 5+50+15 = 70 -> 170 != 130 and would
    # WRONGLY flag this — so a None result here proves direction is applied.
    assert balance_violation(directional) is None
    # Sanity: an all-credit set genuinely does not reconcile (+70 -> 170 != 130).
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


def _write_statement_cassette(cassette_dir: Path, fp: str, *, reconciles: bool) -> None:
    """A statement cassette whose chain does NOT reconcile (opening 100 + (-5) != 130)."""
    (cassette_dir / f"{fp}.json").write_text(
        json.dumps(
            {
                "fingerprint": fp,
                "role": "text",
                "response": {
                    "stream_text": json.dumps(
                        {"opening_balance": "100.00", "closing_balance": "130.00", "transactions": [{"amount": "-5.00"}]}
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    if reconciles is False:
        gt = cassette_dir / "ground_truth"
        gt.mkdir(exist_ok=True)
        (gt / f"{fp}.truth.json").write_text(json.dumps({"synthetic": True, "balance_reconciles": False}), encoding="utf-8")


def test_AC23_7_1_non_reconciling_source_is_balance_exempt(tmp_path: Path) -> None:
    """AC23.7.1: a statement cassette whose truth declares balance_reconciles=false is
    skipped by the balance gate (its source doesn't reconcile by construction) and
    counted as exempt — while the same broken cassette WITHOUT that truth is flagged."""
    # Exempt: broken balance + truth marking the source non-reconciling -> no violation.
    _write_statement_cassette(tmp_path, "a" * 8, reconciles=False)
    assert check(tmp_path) == []
    assert exempt_count(tmp_path) == 1

    # Not exempt: same broken cassette, no such truth -> flagged (real-statement drift).
    other = tmp_path / "sub"
    other.mkdir()
    _write_statement_cassette(other, "b" * 8, reconciles=True)
    assert check(other) != []
    assert exempt_count(other) == 0


def test_AC23_7_1_extracts_response_text_across_shapes() -> None:
    """AC23.7.1: the gate reads the frozen text from stream_text / text / choices."""
    assert _response_text({"stream_text": "abc"}) == "abc"
    assert _response_text({"text": "xyz"}) == "xyz"
    assert _response_text({"choices": [{"message": {"content": "deep"}}]}) == "deep"
    assert _response_text("raw") == "raw"
    assert _response_text({"nothing": 1}) is None
