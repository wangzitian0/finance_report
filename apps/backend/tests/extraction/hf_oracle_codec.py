"""Deterministic CODE layer for the HF extraction oracle (Axiom D boundary).

The cassette persists the LLM's RAW output (LLM-LED, replayed). Everything here
is the CODE half that must stay code-guaranteed: parse the raw page text,
normalise to the production transaction schema, merge pages, and run the
deterministic self-checks. It REUSES the production validators
(``src.services.validation``) so this exercises the real code, not a parallel
copy. No LLM, no network — replayable in CI without a key.

    raw page outputs (LLM) --parse--> pages --merge--> statement --validate--> checks
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from src.services.validation import (
    detect_balance_chain_break,
    normalize_amount_direction,
    validate_balance,
)

_SCORED_TXN_FIELDS = ("date", "description", "amount", "direction", "balance_after")


def parse_page(raw_text: str) -> dict[str, Any]:
    """One page's RAW LLM output -> dict (tolerant of a ```json fence)."""
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        obj = json.loads(text)
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _normalize_txn(txn: dict[str, Any]) -> dict[str, Any]:
    try:
        amount, direction = normalize_amount_direction(Decimal(str(txn.get("amount", "0"))), txn.get("direction"))
    except (InvalidOperation, ValueError, TypeError):
        amount, direction = Decimal("0"), "OUT"
    bal = txn.get("balance_after")
    return {
        "date": str(txn.get("date", "")).strip(),
        "description": str(txn.get("description", "")).strip(),
        "amount": str(amount),
        "direction": direction,
        "balance_after": str(bal) if bal not in (None, "") else None,
    }


def merge_pages(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-page dicts into one statement (opening from first page that has
    it, closing from the last, transactions concatenated in order)."""
    txns: list[dict[str, Any]] = []
    opening = closing = None
    for pg in pages:
        if opening is None and pg.get("opening_balance") not in (None, ""):
            opening = pg["opening_balance"]
        if pg.get("closing_balance") not in (None, ""):
            closing = pg["closing_balance"]
        for t in pg.get("transactions") or []:
            txns.append(_normalize_txn(t))
    return {"opening_balance": opening, "closing_balance": closing, "transactions": txns}


def reconstruct(raw_pages: list[str]) -> dict[str, Any]:
    """RAW per-page LLM outputs -> one normalised statement (pure code)."""
    return merge_pages([parse_page(r) for r in raw_pages])


def self_checks(statement: dict[str, Any]) -> dict[str, Any]:
    """The code-guaranteed confidence signals on OUR extraction (no truth needed):
    opening+Σ≈closing, and the running-balance chain (row i validates row i-1)."""
    bal = validate_balance(statement)
    opening = statement.get("opening_balance")
    try:
        opening_dec = Decimal(str(opening)) if opening not in (None, "") else None
    except (InvalidOperation, ValueError, TypeError):
        opening_dec = None
    chain = detect_balance_chain_break(statement.get("transactions", []), opening_balance=opening_dec)
    return {
        "balance_valid": bool(bal["balance_valid"]),
        "balance_computable": bool(bal.get("balance_computable", True)),
        "chain_break_index": chain.index if chain else None,
    }


def _field_eq(name: str, got: object, want: object) -> bool:
    if want is None:
        return got is None
    if name in ("amount", "balance_after"):
        try:
            return Decimal(str(got)) == Decimal(str(want))
        except (InvalidOperation, ValueError, TypeError):
            return False
    if name == "description":
        return " ".join(str(got).split()).casefold() == " ".join(str(want).split()).casefold()
    return str(got).strip() == str(want).strip()


def field_score(extraction: dict[str, Any], truth: dict[str, Any]) -> tuple[float, dict[str, int]]:
    """Fraction of scored fields matching truth (per-row over the 5 fields +
    opening/closing). A missing/extra row scores its fields wrong."""
    got_txns = extraction.get("transactions", [])
    want_txns = truth.get("transactions", [])
    total = matched = 0
    for field in ("opening_balance", "closing_balance"):
        total += 1
        matched += _field_eq("amount", extraction.get(field), truth.get(field))
    for i in range(max(len(got_txns), len(want_txns))):
        g = got_txns[i] if i < len(got_txns) else {}
        w = want_txns[i] if i < len(want_txns) else {}
        for field in _SCORED_TXN_FIELDS:
            total += 1
            matched += _field_eq(field, g.get(field), w.get(field)) if w else 0
    return (matched / total if total else 0.0), {"total": total, "matched": matched}
