"""Pure paged-extraction helpers: part prompts and multi-part payload merge (#1832).

Vision extraction renders PDF pages to images. Provider request limits bound how
many page images fit in one call, so documents longer than one batch are
extracted through several calls — one per page batch — and merged here. Silent
truncation (the pre-#1832 behavior: drop every page past the cap) is never
acceptable: it guarantees a running-balance-chain failure for any statement
longer than the cap and quarantines a perfectly good document.

This module is pure (no I/O, no model calls) so the merge semantics are
unit-testable in isolation:

- scalar metadata (institution, period, currency, ...): first non-empty part wins;
- ``opening_balance``: first non-empty part wins (statement header lives on page 1);
- ``closing_balance``: LAST non-empty part wins (the statement-level closing
  balance lives on the final transaction page; earlier parts are instructed to
  emit null rather than page carried-forward balances, this is the second line
  of defense);
- ``transactions`` / ``positions``: concatenated in part (= page) order.
"""

from __future__ import annotations

from typing import Any

_LIST_FIELDS = ("transactions", "positions")
_LAST_WINS_FIELDS = ("closing_balance",)


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def build_paged_prompt(
    base_prompt: str,
    *,
    part_index: int,
    part_count: int,
    page_start: int,
    page_end: int,
    total_pages: int,
    has_context_page: bool = False,
) -> str:
    """Append the multi-part extraction rules to the base parsing prompt.

    ``part_index`` is 1-based. The rules keep each part honest about what it can
    see: transactions only from its own pages, statement-level balances only when
    explicitly stated as such (page carried-forward subtotals must not be
    reported as the statement closing balance).

    ``has_context_page``: non-first parts carry the document's FIRST page as a
    leading context image — scanned statements and some brokers do not repeat
    table headers on continuation pages, so without it a part cannot tell which
    column is withdrawal vs deposit or which currency applies. The context page
    is for reading headers/metadata only; its transactions belong to part 1 and
    re-extracting them here would double-count (the dedup-conservation and
    balance-chain gates fail closed on that, but the instruction keeps the happy
    path happy).
    """
    if part_count <= 1:
        return base_prompt
    context_rule = (
        "- The FIRST image is page 1 of the document, included ONLY as context for "
        "table headers, column meanings, account metadata, and currency. Do NOT "
        "extract transactions from this context page — extract transactions "
        f"exclusively from the pages {page_start}-{page_end} images that follow it.\n"
        if has_context_page
        else ""
    )
    return (
        f"{base_prompt}\n\n"
        f"IMPORTANT — PARTIAL DOCUMENT ({part_index}/{part_count}): this request contains "
        f"only pages {page_start}-{page_end} of a {total_pages}-page statement.\n"
        f"{context_rule}"
        "- Extract EVERY transaction visible on these pages, in order.\n"
        "- opening_balance: report it only if the statement-level opening balance is "
        "explicitly stated on these pages; otherwise use null.\n"
        "- closing_balance: report it only if the statement-level closing/ending balance "
        "is explicitly stated on these pages; page subtotals or balance-carried-forward "
        "lines are NOT the closing balance — use null for those.\n"
        "- Other metadata (institution, account digits, period, currency): report what is "
        "visible on these pages, otherwise use null.\n"
        "- Do not invent transactions from pages you cannot see."
    )


def merge_paged_extractions(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-batch extraction payloads into one whole-document payload."""
    dict_parts = [part for part in parts if isinstance(part, dict)]
    if not dict_parts:
        raise ValueError("merge_paged_extractions needs at least one dict payload")
    if len(dict_parts) == 1:
        return dict_parts[0]

    merged: dict[str, Any] = dict(dict_parts[0])

    # Scalar metadata: first non-empty part wins.
    for part in dict_parts[1:]:
        for key, value in part.items():
            if key in _LIST_FIELDS or key in _LAST_WINS_FIELDS:
                continue
            if _is_empty(merged.get(key)) and not _is_empty(value):
                merged[key] = value

    # closing_balance: the last part that saw a statement-level closing balance wins.
    for part in dict_parts:
        if not _is_empty(part.get("closing_balance")):
            merged["closing_balance"] = part["closing_balance"]

    # Ordered concatenation for row lists (pages arrive in document order).
    for key in _LIST_FIELDS:
        if any(key in part for part in dict_parts):
            merged[key] = [row for part in dict_parts for row in (part.get(key) or [])]

    return merged
