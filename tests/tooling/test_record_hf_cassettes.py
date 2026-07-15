"""Tests for the pure (non-network) helpers of the HF cassette recorder.

The live GLM/record path is ``# pragma: no cover`` (it needs the coding token); this
pins the data-shaping logic that determines what lands in git: date normalisation
across both HF schemas, amount/balance extraction, the source-reference URL, and the
masked ground-truth shape.
"""

from __future__ import annotations

from decimal import Decimal

import importlib.util as _ilu
from pathlib import Path as _P

_REC_PATH = _P(__file__).resolve().parents[2] / "tools/_lib/record_hf_cassettes.py"
assert _REC_PATH.is_file(), f"recorder script missing: {_REC_PATH}"
_spec = _ilu.spec_from_file_location("record_hf_cassettes", _REC_PATH)
assert _spec is not None and _spec.loader is not None, f"unloadable: {_REC_PATH}"
rec = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(rec)


def test_iso_date_normalises_both_hf_schemas() -> None:
    assert rec._iso_date("2024-01-01 11:30:55") == "2024-01-01"  # Type1 (ISO + time)
    assert rec._iso_date("01/02/2024") == "2024-02-01"  # Type2 (DD/MM/YYYY)
    assert rec._iso_date("2024-03-31") == "2024-03-31"


def test_row_amount_across_schemas() -> None:
    assert rec._row_amount({"transaction_amount": 475617.41}) == Decimal(
        "475617.41"
    )  # Type2
    assert rec._row_amount({"credit": 6086.63, "debit": None}) == Decimal(
        "6086.63"
    )  # Type1 credit
    assert rec._row_amount({"credit": None, "debit": 513.47}) == Decimal(
        "513.47"
    )  # Type1 debit


def test_row_balance_across_schemas() -> None:
    assert rec._row_balance({"balance": "100.00"}) == Decimal("100.00")
    assert rec._row_balance({"available_balance": "200.00"}) == Decimal("200.00")


def test_hf_url_points_at_public_dataset() -> None:
    url = rec.hf_url("India_Bank_Statement_Digital_Type1/00001")
    assert url.startswith(
        "https://huggingface.co/datasets/Akashved/Indian-Bank-Statements/"
    )
    assert url.endswith("train/India_Bank_Statement_Digital_Type1/00001.pdf")


def test_build_truth_is_masked_and_balance_exempt() -> None:
    hf = {
        "transactions": [
            {
                "date": "2024-01-01 10:00:00",
                "description": "NEFT Cr ACME LTD",
                "credit": 100.0,
                "balance": 1100.0,
            },
            {
                "date": "2024-01-02 11:00:00",
                "description": "UPI DR SHOP XYZ",
                "debit": 50.0,
                "balance": 1050.0,
            },
        ]
    }
    truth = rec.build_truth(hf, modality="text")
    assert truth["synthetic"] is True
    assert truth["balance_reconciles"] is False  # AC-llm.7 exemption flag
    exp = truth["expected"]
    assert exp["transactions"][0]["date"] == "2024-01-01"  # normalised + ISO
    assert exp["transactions"][0]["amount"] == "100.0"  # credit magnitude
    assert "***" in exp["transactions"][0]["description"]  # masked
    assert "ACME" not in exp["transactions"][0]["description"]
