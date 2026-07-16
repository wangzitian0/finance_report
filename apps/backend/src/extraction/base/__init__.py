"""``extraction.base`` — pure extraction values and validation calculus.

Pure functions over parsed payloads (dicts/Decimals): per-currency balance
closure, balance-chain continuity, confidence scoring and threshold routing.
No ORM, no network, no LLM — the extension pipeline calls DOWN into these.
"""

from __future__ import annotations

from src.extraction.base.types import DocumentSource, ExtractedTransactionRow, ParseJob

__all__ = ["DocumentSource", "ExtractedTransactionRow", "ParseJob"]
