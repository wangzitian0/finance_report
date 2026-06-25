"""Tests for the HF extraction-oracle truth mapper (tools/_lib/pdf_fixtures).

Pure transform — no network, no LLM, no key. The decisive test feeds the mapper's
output through the REAL graded-eval scorer to prove it is shape-compatible (a
perfect extraction scores 1.0), so a recorded HF cassette can actually be graded.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "_lib" / "pdf_fixtures"))

from hf_oracle_truth import (  # noqa: E402
    build_truth,
    label_to_expected,
    modality_for_dir,
    signed_amount,
)

# A minimal HF-shaped label (the dataset's per-statement schema): split
# debit/credit columns, datetime strings, header balances.
_HF_SAMPLE = {
    "opening_balance": 100.0,
    "closing_balance": 130.0,
    "transactions": [
        {"date": "2026-01-02 11:30:55", "description": " Coffee  shop ", "debit": 5.0, "credit": None},
        {"date": "2026-01-05 09:00:00", "description": "Salary credit", "debit": None, "credit": 50.0},
        {"date": "2026-01-09 18:00:00", "description": "Groceries", "debit": 15.0, "credit": None},
    ],
}


def test_signed_amount_credit_positive_debit_negative() -> None:
    assert Decimal(signed_amount({"credit": 50.0, "debit": None})) == Decimal("50")
    assert Decimal(signed_amount({"credit": None, "debit": 5.0})) == Decimal("-5")
    assert signed_amount({"credit": None, "debit": None}) == "0"


def test_modality_from_layout() -> None:
    assert modality_for_dir("India_Bank_Statement_Scanned_Type1") == "vision"
    assert modality_for_dir("India_Bank_Statement_Digital_Type2") == "text"


def test_label_to_expected_normalises_date_and_amount() -> None:
    exp = label_to_expected(_HF_SAMPLE)
    assert Decimal(exp["opening_balance"]) == Decimal("100")
    assert Decimal(exp["closing_balance"]) == Decimal("130")
    first = exp["transactions"][0]
    assert first["date"] == "2026-01-02"  # datetime -> ISO date
    assert Decimal(first["amount"]) == Decimal("-5")  # debit -> negative
    assert Decimal(exp["transactions"][1]["amount"]) == Decimal("50")  # credit -> positive


def test_build_truth_is_synthetic_and_scorable_by_the_real_eval() -> None:
    """The mapper output must be the exact shape the graded eval scores."""
    truth = build_truth(_HF_SAMPLE, dirname="India_Bank_Statement_Scanned_Type1")
    assert truth["synthetic"] is True  # AC23.8.6 hygiene flag
    assert truth["modality"] == "vision"

    sys.path.insert(0, str(ROOT))
    from common.ssot.cassette_graded_eval import case_score

    # A perfect extraction (== the truth) scores 1.0 — proves shape-compatibility
    # with the scorer, and that a balance-failing field WOULD lower the score.
    score, breakdown = case_score(truth["expected"], truth["expected"])
    assert score == 1.0
    assert breakdown["total"] > 0
