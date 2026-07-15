#!/usr/bin/env python
"""Deterministic PII mask for committed extraction products (cassette responses).

The committed test artifact is the extraction OUTPUT plus a source reference (an HF
URL or a sha256 of a local file) — the source document itself is never committed, so
there is no PDF/image to leak and no repo bloat. This module masks the residual PII
in that output, uniformly for synthetic (HF) and real (own) statements:

- **Meta / identity fields** (account holder, account number, ``account_last4``,
  address, NRIC, phone, email, customer id) -> masked to a fixed ``**`` marker. The
  institution name, period and currency are kept (not identity PII).
- **Transaction descriptions** -> an irreversible, deterministic PSEUDONYM that keeps
  distinguishability (equal in → equal token, distinct in → distinct token) without
  leaking the text: ``"ACME TRADING PTE LTD"`` becomes e.g. ``"a1b2***c3d4"`` (sha256-
  derived ``<4 hex>***<4 hex>``). This supersedes a ``first3***last3`` scheme, which
  leaked the real first/last characters.
- **Flow values** (date, amount, direction, balance) are PII-free and kept verbatim,
  so the graded-eval (field accuracy) and balance-chain gates still mean something.

Pure + idempotent: re-masking an already-masked value is a no-op. No network, no model.
"""

from __future__ import annotations

import hashlib
import re
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
# A masked description token: 2 hex + stars + 2 hex (e.g. ``a3**************9f``), or all
# stars for a <=4-char source. The leading/trailing hex are sha256-derived (NOT the real
# characters); the star run preserves the original length.
_PSEUDONYM_RE = re.compile(r"[0-9a-f]{2}\*+[0-9a-f]{2}|\*+")


def mask_description(value: str) -> str:
    """Mask a description to a deterministic, NON-recoverable, LENGTH-PRESERVING token
    that keeps DISTINGUISHABILITY: equal descriptions → equal token, distinct → (almost
    surely) distinct token, but the original text cannot be recovered. The token is
    ``<2 hex>`` + ``*`` × (len − 4) + ``<2 hex>`` where the hex pairs are sha256-derived,
    NOT the real characters; its length equals the original. A ≤4-char source is all
    stars. Idempotent on an already-masked token.

    This supersedes a ``first3***last3`` scheme, which leaked the real first/last
    characters (residual PII for a real name)."""
    s = str(value)
    n = len(s)
    if n == 0:
        return ""
    if _PSEUDONYM_RE.fullmatch(s):  # already masked -> idempotent
        return s
    if n <= 4:
        return "*" * n
    digest = hashlib.sha256(" ".join(s.split()).casefold().encode("utf-8")).hexdigest()
    return f"{digest[:2]}{'*' * (n - 4)}{digest[2:4]}"


def mask_obj(obj: Any, *, _key: str | None = None) -> Any:
    """Recursively mask identity meta fields (-> ``**``) and descriptions (-> a
    non-recoverable pseudonym, see :func:`mask_description`). Flow values
    (date/amount/direction/balance/currency) and public security symbols are never PII
    and are kept. This is safe for BOTH synthetic and real statements: meta/free-text
    that could carry a name is either fully redacted or replaced by an irreversible
    pseudonym, so no original text can be recovered."""
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
    """Mask an extraction-output dict (returns a new masked dict): identity meta and
    free-text audit fields -> ``**``; descriptions -> an irreversible pseudonym."""
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
        return {"origin": "local", "sha256": hashlib.sha256(file_bytes).hexdigest()}
    raise ValueError("source_ref needs hf_url or file_bytes")


if __name__ == "__main__":
    # meta -> '**'; flow kept; descriptions -> irreversible distinguishable pseudonym.
    m = mask_extraction({"account_holder": "John Tan", "institution": "DBS", "account_last4": "1234"})
    assert m == {"account_holder": "**", "institution": "DBS", "account_last4": "**"}, m
    src = "ACME TRADING PTE LTD"
    a = mask_extraction({"transactions": [{"description": src, "amount": "10.00"}]})
    c = mask_extraction({"transactions": [{"description": "PHO KITCHEN", "amount": "10.00"}]})
    da = a["transactions"][0]["description"]
    assert _PSEUDONYM_RE.fullmatch(da), da
    assert len(da) == len(src)  # length preserved
    assert "ACME" not in da and "LTD" not in da  # not recoverable
    assert da != c["transactions"][0]["description"]  # distinct -> distinct token (distinguishability)
    assert a["transactions"][0]["amount"] == "10.00"  # flow kept
    print("extraction_pii_mask self-check OK")
