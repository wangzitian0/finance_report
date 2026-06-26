"""Tests for the HF oracle truth mapper (production transaction schema).

Pure transform — no LLM, no network. Asserts HF debit/credit -> amount+direction
and that the running balance is preserved as `balance_after` (the field that
powers the running-balance self-check). The chain-validity of the mapped truth is
asserted in the backend codec test (it needs the production validators).
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "_lib" / "pdf_fixtures"))

from hf_oracle_truth import (  # noqa: E402
    amount_direction,
    build_truth,
    label_to_expected,
    modality_for_dir,
)

_HF = {
    "opening_balance": 100.0,
    "closing_balance": 130.0,
    "transactions": [
        {
            "date": "2026-01-02 11:30:55",
            "description": " Coffee  shop ",
            "debit": 5.0,
            "credit": None,
            "balance": 95.0,
        },
        {
            "date": "2026-01-05 09:00:00",
            "description": "Salary",
            "debit": None,
            "credit": 50.0,
            "balance": 145.0,
        },
        {
            "date": "2026-01-09 18:00:00",
            "description": "Groceries",
            "debit": 15.0,
            "credit": None,
            "balance": 130.0,
        },
    ],
}


def test_amount_direction_from_debit_credit() -> None:
    amt, direction = amount_direction({"credit": 50.0, "debit": None})
    assert Decimal(amt) == Decimal("50") and direction == "IN"
    amt, direction = amount_direction({"credit": None, "debit": 5.0})
    assert Decimal(amt) == Decimal("5") and direction == "OUT"


def test_modality_from_layout() -> None:
    assert modality_for_dir("India_Bank_Statement_Scanned_Type1") == "vision"
    assert modality_for_dir("India_Bank_Statement_Digital_Type2") == "text"


def test_label_to_expected_production_schema() -> None:
    exp = label_to_expected(_HF)
    assert Decimal(exp["opening_balance"]) == Decimal("100")
    first, second = exp["transactions"][0], exp["transactions"][1]
    assert first["date"] == "2026-01-02"  # datetime -> ISO date
    assert (
        Decimal(first["amount"]) == Decimal("5") and first["direction"] == "OUT"
    )  # debit
    assert Decimal(first["balance_after"]) == Decimal("95")  # running balance preserved
    assert (
        Decimal(second["amount"]) == Decimal("50") and second["direction"] == "IN"
    )  # credit


def test_build_truth_is_synthetic() -> None:
    truth = build_truth(_HF, dirname="India_Bank_Statement_Scanned_Type1")
    assert truth["synthetic"] is True and truth["modality"] == "vision"
    assert {"date", "description", "amount", "direction", "balance_after"} <= set(
        truth["expected"]["transactions"][0]
    )
