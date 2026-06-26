#!/usr/bin/env python
"""Map a Hugging Face bank-statement label -> our PRODUCTION transaction schema.

Pure transform (no LLM, no network). The transaction schema mirrors what the
extraction pipeline emits and what the deterministic validators consume
(``validate_balance`` / ``detect_balance_chain_break`` in
``apps/backend/src/services/validation.py``):

    transaction = {date, description, amount, direction, balance_after}
    statement   = {opening_balance, closing_balance, transactions: [...]}

- ``amount`` is the absolute magnitude (string, Decimal-safe); ``direction`` is
  ``IN``/``OUT`` (the HF debit/credit columns), NOT a signed amount — that is the
  shape ``normalize_amount_direction`` expects.
- ``balance_after`` is the per-row RUNNING balance (HF ``balance``). It is the
  field that powers the running-balance self-check (each row validates the
  previous one): ``prev_balance + signed_amount == balance_after``. Dropping it
  loses that confidence signal — so it is first-class here.

No anonymisation: the source is synthetic (Apache-2.0, fabricated names), and the
scored fields must match the document the LLM reads.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def _decimal_str(value: Any) -> str:
    return str(Decimal(str(value)))


def amount_direction(txn: dict[str, Any]) -> tuple[str, str]:
    """(absolute amount, IN/OUT) from the HF debit/credit columns."""
    credit, debit = txn.get("credit"), txn.get("debit")
    if credit not in (None, ""):
        return _decimal_str(credit), "IN"
    if debit not in (None, ""):
        return _decimal_str(debit), "OUT"
    return "0", "OUT"


def label_to_expected(hf: dict[str, Any]) -> dict[str, Any]:
    """HF statement label -> the production-schema ``expected`` block."""
    transactions = []
    for txn in hf.get("transactions", []):
        amount, direction = amount_direction(txn)
        bal = txn.get("balance")
        transactions.append(
            {
                "date": str(txn.get("date", "")).split(" ")[0],  # datetime -> ISO date
                "description": str(txn.get("description", "")).strip(),
                "amount": amount,
                "direction": direction,
                "balance_after": _decimal_str(bal) if bal not in (None, "") else None,
            }
        )
    return {
        "opening_balance": _decimal_str(hf["opening_balance"]),
        "closing_balance": _decimal_str(hf["closing_balance"]),
        "transactions": transactions,
    }


def modality_for_dir(dirname: str) -> str:
    return "vision" if "Scanned" in dirname else "text"


def build_truth(
    hf: dict[str, Any],
    *,
    dirname: str,
    institution_class: str = "generic_india",
    edge_condition: str = "happy_path",
) -> dict[str, Any]:
    """Full truth manifest for one HF statement (production transaction schema)."""
    return {
        "synthetic": True,
        "modality": modality_for_dir(dirname),
        "institution_class": institution_class,
        "edge_condition": edge_condition,
        "note": (
            "SYNTHETIC label from HF Akashved/Indian-Bank-Statements (Apache-2.0). "
            "Production schema: amount+direction (IN/OUT) + running balance_after."
        ),
        "expected": label_to_expected(hf),
    }
