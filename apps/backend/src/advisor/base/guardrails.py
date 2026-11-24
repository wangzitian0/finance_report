"""Prompt guardrails: language, redaction, disclaimer.

Moved from ``src/services/ai_advisor/_guardrails.py`` (#1671 Wave B) — pure
text predicates and transforms, no I/O, so they live in ``base/``.
"""

from __future__ import annotations

import hashlib
import re

from src.advisor.base.constants import DISCLAIMER_BY_LANG, SENSITIVE_NUMBER_RE
from src.advisor.base.prompt import DISCLAIMER_EN


def detect_language(message: str) -> str:
    """Detect message language based on CJK presence."""
    if re.search(r"[\u4e00-\u9fff]", message):
        return "zh"
    return "en"


def normalize_question(message: str) -> str:
    """Normalize question string for caching."""
    cleaned = re.sub(r"\s+", " ", message.strip().lower())
    normalized = re.sub(r"[^a-z0-9\s]", "", cleaned)
    if normalized:
        return normalized
    return hashlib.sha1(message.encode("utf-8")).hexdigest()


def redact_sensitive(text: str) -> str:
    """Redact long number sequences to avoid sensitive data leaks."""
    return SENSITIVE_NUMBER_RE.sub("[REDACTED]", text)


def ensure_disclaimer(text: str, language: str) -> str:
    """Ensure the output ends with the disclaimer."""
    disclaimer = DISCLAIMER_BY_LANG.get(language, DISCLAIMER_EN)
    if text.strip().endswith(disclaimer):
        return text
    if not text.endswith("\n"):
        text += "\n\n"
    return f"{text}{disclaimer}"


class StreamRedactor:
    """Streaming redactor that masks sensitive numbers without breaking chunks."""

    def __init__(self, tail_size: int = 64) -> None:
        self._tail_size = tail_size
        self._buffer = ""

    def process(self, chunk: str) -> str:
        combined = self._buffer + chunk
        cut = len(combined) - self._tail_size
        if cut <= 0:
            self._buffer = combined
            return ""
        # A number that crosses the cut stays whole in the buffer: its digits must not leave in two parts, because
        # a model streams deltas of a few characters and the pattern cannot match a part (#3209 review).
        for match in SENSITIVE_NUMBER_RE.finditer(combined):
            if match.start() < cut < match.end():
                cut = match.start()
                break
        self._buffer = combined[cut:]
        return redact_sensitive(combined[:cut])

    def flush(self) -> str:
        if not self._buffer:
            return ""
        output = redact_sensitive(self._buffer)
        self._buffer = ""
        return output
