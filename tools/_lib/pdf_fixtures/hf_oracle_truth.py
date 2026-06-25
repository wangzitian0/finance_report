#!/usr/bin/env python
"""Map a Hugging Face bank-statement label -> our graded-eval ground truth.

Pure transform (no LLM, no network). Turns the dataset's per-statement field
label into the ``expected`` shape that ``common.ssot.cassette_graded_eval`` scores
against (``docs/ssot/cassette-graded-eval.md`` §2). Used by ``record_hf_oracle.py``
to write ``ground_truth/<fingerprint>.truth.json`` next to a freshly recorded
cassette.

Key choices:
- **Signed amount.** The HF label splits ``debit`` / ``credit`` into two nullable
  columns; our scored ``amount`` is a single signed Decimal-string (credit
  positive, debit negative), matching the existing truth fixtures.
- **No anonymisation.** This source is already synthetic (Apache-2.0, tagged
  ``synthetic``; fabricated names/accounts), so there is no PII to strip — and the
  scored fields (date / description / amount) MUST match the document the LLM
  reads, so mangling them would make the case ungradeable. The desensitisation
  policy applies to *real* statements (``tmp/input/*``), which have no label and
  are consistency-only. ``synthetic: True`` is carried so the AC23.8.6 hygiene
  gate stays satisfied.
- **Modality from layout.** Scanned dirs -> ``vision`` (OCR of a degraded image,
  the real accuracy signal); digital dirs -> ``text``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def _decimal_str(value: Any) -> str:
    """Decimal-safe string (never float): ``59131.72`` / ``"5.00"`` -> canonical."""
    return str(Decimal(str(value)))


def signed_amount(txn: dict[str, Any]) -> str:
    """Single signed amount from the HF debit/credit columns (credit +, debit -)."""
    credit, debit = txn.get("credit"), txn.get("debit")
    if credit not in (None, ""):
        return _decimal_str(credit)
    if debit not in (None, ""):
        return str(-Decimal(str(debit)))
    return "0"


def label_to_expected(hf: dict[str, Any]) -> dict[str, Any]:
    """HF statement label -> the scored ``expected`` block."""
    transactions = [
        {
            # "2024-01-01 11:30:55" -> "2024-01-01"; the eval normalises ISO/slash.
            "date": str(txn.get("date", "")).split(" ")[0],
            "description": str(txn.get("description", "")).strip(),
            "amount": signed_amount(txn),
        }
        for txn in hf.get("transactions", [])
    ]
    return {
        "opening_balance": _decimal_str(hf["opening_balance"]),
        "closing_balance": _decimal_str(hf["closing_balance"]),
        "transactions": transactions,
    }


def modality_for_dir(dirname: str) -> str:
    """Scanned layouts are image OCR (``vision``); digital are text."""
    return "vision" if "Scanned" in dirname else "text"


def build_truth(
    hf: dict[str, Any],
    *,
    dirname: str,
    institution_class: str = "generic_india",
    edge_condition: str = "happy_path",
) -> dict[str, Any]:
    """Full ``<fingerprint>.truth.json`` manifest for one HF statement."""
    return {
        "synthetic": True,
        "modality": modality_for_dir(dirname),
        "institution_class": institution_class,
        "edge_condition": edge_condition,
        "note": (
            "SYNTHETIC label from HF Akashved/Indian-Bank-Statements (Apache-2.0). "
            "Independent per-statement field label; signed amounts (debit negative). "
            "Per-file consolidated table — proves field accuracy, not page assembly."
        ),
        "expected": label_to_expected(hf),
    }
