#!/usr/bin/env python
"""Deterministic PII mask for committed extraction products (cassette responses).

The committed test artifact is the extraction OUTPUT plus a source reference (an HF
URL or a sha256 of a local file) — the source document itself is never committed, so
there is no PDF/image to leak and no repo bloat. This module masks the residual PII
in that output, uniformly for synthetic (HF) and real (own) statements:

- **Meta / identity fields** (account holder, account number, ``account_last4``,
  address, NRIC, phone, email, customer id) -> masked to a fixed ``**`` marker. The
  institution name, period and currency are kept (not identity PII).
- **Transaction descriptions** -> keep first 3 + ``***`` + last 3 chars, so a
  counterparty name like ``"ACME TRADING PTE LTD"`` becomes ``"ACM***LTD"``. Short
  strings (<= 6 chars) are fully starred.
- **Flow values** (date, amount, direction, balance) are PII-free and kept verbatim,
  so the graded-eval (field accuracy) and balance-chain gates still mean something.

Pure + idempotent: re-masking an already-masked value is a no-op (the markers don't
re-trigger). No network, no model.
"""

from __future__ import annotations

from typing import Any

# Top-level extraction keys that carry identity PII (vs the institution/period/flow).
_META_PII_KEYS = frozenset(
    {
        "account_holder",
        "account_holder_name",
        "account_name",
        "account_number",
        "account_no",
        "account_last4",
        "customer_name",
        "customer_id",
        "address",
        "nric",
        "phone",
        "email",
        "iban",
        "holder",
        "name",
        # Free-text audit fields that echo the WHOLE original line (counterparty names,
        # branch/reference numbers, account ids) — the biggest residual PII surface.
        "raw_text",
        "reference",
        "cheque_no",
        "branch_code",
    }
)
# Per-transaction free-text keys whose value may carry a counterparty name.
_DESC_KEYS = frozenset({"description", "desc", "narrative", "remarks", "counterparty", "payee", "merchant"})
_META_MARK = "**"


def mask_description(value: str) -> str:
    """Mask a description to ``first3 + *** + last3`` (counterparty-name safe)."""
    s = str(value)
    if "***" in s:  # already masked -> idempotent
        return s
    if len(s) <= 6:
        return "*" * len(s)
    return f"{s[:3]}***{s[-3:]}"


def mask_obj(obj: Any, *, _key: str | None = None) -> Any:
    """Recursively mask identity meta fields (-> ``**``) and descriptions (first3***last3)."""
    if isinstance(obj, dict):
        return {k: mask_obj(v, _key=k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_obj(x, _key=_key) for x in obj]
    if isinstance(obj, str):
        if _key in _META_PII_KEYS:
            return _META_MARK
        if _key in _DESC_KEYS:
            return mask_description(obj)
    return obj


def mask_extraction(extracted: dict[str, Any]) -> dict[str, Any]:
    """Mask an extraction-output dict in place-safe (returns a new masked dict)."""
    return mask_obj(extracted)


def mask_response_text(text: str) -> str:
    """Mask a raw model response that is (possibly fenced) JSON; preserve non-JSON as-is."""
    import json

    body = text.strip()
    fenced = body.startswith("```")
    if fenced:
        body = body.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        masked = mask_extraction(json.loads(body))
    except json.JSONDecodeError:
        return text  # not JSON -> nothing structured to mask
    out = json.dumps(masked, ensure_ascii=False, indent=2)
    return f"```json\n{out}\n```" if fenced else out


def source_ref(*, hf_url: str | None = None, file_bytes: bytes | None = None) -> dict[str, str]:
    """Build the committed source REFERENCE — never the document itself.

    HF statements reference their public dataset URL; a local/own statement records
    only a sha256 so the source stays off-repo (no PII, no bloat) while replay can
    verify it against a locally-present file.
    """
    if hf_url:
        return {"origin": "huggingface", "url": hf_url}
    if file_bytes is not None:
        import hashlib

        return {"origin": "local", "sha256": hashlib.sha256(file_bytes).hexdigest()}
    raise ValueError("source_ref needs hf_url or file_bytes")


_TEST_VECTORS = [
    ({"account_holder": "John Tan", "institution": "DBS", "account_last4": "1234"},
     {"account_holder": "**", "institution": "DBS", "account_last4": "**"}),
    ({"transactions": [{"description": "ACME TRADING PTE LTD", "amount": "10.00", "direction": "OUT"}]},
     {"transactions": [{"description": "ACM***LTD", "amount": "10.00", "direction": "OUT"}]}),
]
if __name__ == "__main__":
    for raw, want in _TEST_VECTORS:
        got = mask_extraction(raw)
        assert got == want, f"{got} != {want}"
    print("extraction_pii_mask self-check OK")
