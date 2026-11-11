#!/usr/bin/env python
"""Deterministic PII mask for committed extraction products (cassette responses)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

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
        "raw_text",
        "reference",
        "cheque_no",
        "branch_code",
    }
)
_DESC_KEYS = frozenset(
    {"description", "desc", "narrative", "remarks", "counterparty", "payee", "merchant"}
)
_META_MARK = "**"
_PSEUDONYM_RE = re.compile(r"[0-9a-f]{2}\*+[0-9a-f]{2}|\*+")


def mask_description(value: str) -> str:
    s = str(value)
    n = len(s)
    if n == 0 or _PSEUDONYM_RE.fullmatch(s):
        return s
    if n <= 4:
        return "*" * n
    digest = hashlib.sha256(" ".join(s.split()).casefold().encode("utf-8")).hexdigest()
    return f"{digest[:2]}{'*' * (n - 4)}{digest[2:4]}"


def mask_obj(obj: Any, *, _key: str | None = None) -> Any:
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
    return mask_obj(extracted)


def source_ref(
    *, hf_url: str | None = None, file_bytes: bytes | None = None
) -> dict[str, str]:
    if hf_url:
        return {"origin": "huggingface", "url": hf_url}
    if file_bytes is not None:
        return {"origin": "local", "sha256": hashlib.sha256(file_bytes).hexdigest()}
    raise ValueError("source_ref needs hf_url or file_bytes")
