"""HF extraction oracle: the CODE layer + committed-example replay.

Exercises the deterministic code (parse RAW LLM output -> normalise -> merge ->
validate, reusing the production validators) and replays the committed raw
examples through it (no LLM, no key). The cassette holds only the LLM's RAW
output; everything asserted here is code-guaranteed (Axiom D).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tests.extraction.hf_oracle_codec import (
    field_score,
    parse_page,
    reconstruct,
    self_checks,
)

ROOT = Path(__file__).resolve().parents[4]  # repo root (apps/backend/tests/extraction/<file>)
sys.path.insert(0, str(ROOT / "tools" / "_lib" / "pdf_fixtures"))
from hf_oracle_truth import build_truth  # noqa: E402

EXAMPLES = sorted((Path(__file__).resolve().parents[1] / "fixtures" / "hf_oracle").glob("*.json"))


def test_parse_page_tolerates_fence() -> None:
    assert parse_page('```json\n{"transactions": []}\n```') == {"transactions": []}
    assert parse_page("not json at all") == {}


def test_reconstruct_merges_pages_into_production_schema() -> None:
    pages = [
        '{"opening_balance":"100","transactions":[{"date":"2026-01-02",'
        '"description":"Coffee","amount":"5","direction":"OUT","balance_after":"95"}]}',
        '{"closing_balance":"145","transactions":[{"date":"2026-01-05",'
        '"description":"Salary","amount":"50","direction":"IN","balance_after":"145"}]}',
    ]
    st = reconstruct(pages)
    assert st["opening_balance"] == "100" and st["closing_balance"] == "145"
    assert [t["direction"] for t in st["transactions"]] == ["OUT", "IN"]
    assert st["transactions"][0]["balance_after"] == "95"


def test_self_checks_pass_a_balanced_chain_and_flag_a_break() -> None:
    good = reconstruct(
        [
            '{"opening_balance":"100","closing_balance":"145","transactions":['
            '{"date":"d","description":"a","amount":"5","direction":"OUT","balance_after":"95"},'
            '{"date":"d","description":"b","amount":"50","direction":"IN","balance_after":"145"}]}'
        ]
    )
    checks = self_checks(good)
    assert checks["balance_valid"] is True and checks["chain_break_index"] is None

    broken = reconstruct(
        [
            '{"opening_balance":"100","closing_balance":"145","transactions":['
            '{"date":"d","description":"a","amount":"5","direction":"OUT","balance_after":"999"}]}'
        ]
    )
    assert self_checks(broken)["chain_break_index"] == 0  # row's running balance is impossible


def test_mapped_truth_chain_validates() -> None:
    """The mapped truth is internally consistent under the production validator —
    a free quality check that the label's running-balance chain holds."""
    hf = {
        "opening_balance": 100.0,
        "closing_balance": 145.0,
        "transactions": [
            {"date": "d", "description": "a", "debit": 5.0, "credit": None, "balance": 95.0},
            {"date": "d", "description": "b", "debit": None, "credit": 50.0, "balance": 145.0},
        ],
    }
    truth = build_truth(hf, dirname="India_Bank_Statement_Scanned_Type1")["expected"]
    assert self_checks(truth)["chain_break_index"] is None


@pytest.mark.skipif(not EXAMPLES, reason="no recorded HF examples committed yet")
@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_recorded_example_replays_through_codec(path: Path) -> None:
    """A committed raw example: RAW LLM output -> codec -> scored vs truth, no key."""
    rec = json.loads(path.read_text(encoding="utf-8"))
    assert rec["synthetic"] is True
    assert isinstance(rec["raw_pages"], list) and rec["raw_pages"], "no raw LLM pages persisted"
    statement = reconstruct(rec["raw_pages"])
    assert statement["transactions"], "codec produced no transactions from the raw output"
    score, breakdown = field_score(statement, rec["truth"])
    assert 0.0 <= score <= 1.0 and breakdown["total"] > 0
    self_checks(statement)  # the code self-checks run without error
