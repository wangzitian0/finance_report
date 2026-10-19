"""Tests for the pure (non-network) helpers of the HF cassette recorder.

The live GLM/record path is ``# pragma: no cover`` (it needs the coding token); this
pins the data-shaping logic that determines what lands in git: date normalisation
across both HF schemas, amount/balance extraction, the source-reference URL, and the
masked ground-truth shape.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path as _P

from common.extraction import record_hf_cassettes as rec

_REC_PATH = (
    _P(__file__).resolve().parents[2] / "common/extraction/record_hf_cassettes.py"
)
assert _REC_PATH.is_file(), f"recorder script missing: {_REC_PATH}"


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


def test_main_requires_ai_api_key(monkeypatch) -> None:
    import pytest

    monkeypatch.delenv("AI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="AI_API_KEY is required"):
        rec.main([])


def test_pure_helpers_and_manifest_loading(monkeypatch, tmp_path) -> None:
    import hashlib

    assert rec._sha(b"hello") == hashlib.sha256(b"hello").hexdigest()
    assert rec._num(None) is None
    assert rec._num("1,234.50") == Decimal("1234.50")
    assert rec._num("not-a-number") is None
    assert rec._iso_date("unmatched_date_string") == "unmatched_"

    img_url = "data:image/jpeg;base64,AAA"
    messages = rec.build_messages([img_url])
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert isinstance(messages[0]["content"], str)
    assert messages[1]["role"] == "user"
    assert messages[1]["content"][0]["type"] == "text"
    assert messages[1]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": img_url},
    }

    stripped = rec.strip_request_images(messages)
    assert stripped[0] == messages[0]
    assert stripped[1]["content"][0] == messages[1]["content"][0]
    assert stripped[1]["content"][1] == {
        "type": "image_url",
        "image_bytes_sha256": hashlib.sha256(img_url.encode("utf-8")).hexdigest(),
    }

    manifest_file = tmp_path / "missing.json"
    monkeypatch.setattr(rec, "MANIFEST", manifest_file)
    assert rec._load_manifest() == {}

    manifest_file.write_text("{not-valid-json", encoding="utf-8")
    assert rec._load_manifest() == {}

    manifest_file.write_text('{"k": 1}', encoding="utf-8")
    assert rec._load_manifest() == {"k": 1}

    prompt_sha = rec._prompt_sha()
    assert len(prompt_sha) == 64
    int(prompt_sha, 16)
