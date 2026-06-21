"""Prompt guardrails: language, injection/sensitive/non-financial checks, redaction, disclaimer."""

from __future__ import annotations

import hashlib
import re

from src.prompts.ai_advisor import DISCLAIMER_EN
from src.services.ai_advisor._base import (
    DISCLAIMER_BY_LANG,
    INJECTION_PATTERNS,
    NON_FINANCIAL_PATTERNS,
    REFUSAL_BY_REASON,
    SENSITIVE_NUMBER_RE,
    SENSITIVE_PATTERNS,
)


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


def estimate_tokens(text: str) -> int:
    """Estimate token count for usage tracking."""
    return max(1, len(text) // 4)


def _matches_any(message: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, message, re.IGNORECASE) for pattern in patterns)


def is_prompt_injection(message: str) -> bool:
    return _matches_any(message, INJECTION_PATTERNS)


def is_sensitive_request(message: str) -> bool:
    return _matches_any(message, SENSITIVE_PATTERNS)


def is_non_financial(message: str) -> bool:
    return _matches_any(message, NON_FINANCIAL_PATTERNS)


def is_write_request(message: str) -> bool:
    return _matches_any(
        message,
        (
            r"create (a )?(journal|entry)",
            r"post (a )?(journal|entry)",
            r"delete (a )?(journal|entry)",
            r"void (a )?(journal|entry)",
            r"modify (a )?(ledger|entry)",
            r"write (a )?(ledger|entry)",
        ),
    )


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


def build_refusal(reason: str, language: str) -> str:
    """Build refusal response with disclaimer."""
    message = REFUSAL_BY_REASON.get(reason, REFUSAL_BY_REASON["non_financial"]).get(
        language, REFUSAL_BY_REASON["non_financial"]["en"]
    )
    return ensure_disclaimer(message, language)


class StreamRedactor:
    """Streaming redactor that masks sensitive numbers without breaking chunks."""

    def __init__(self, tail_size: int = 64) -> None:
        self._tail_size = tail_size
        self._buffer = ""

    def process(self, chunk: str) -> str:
        combined = self._buffer + chunk
        if len(combined) <= self._tail_size:
            self._buffer = combined
            return ""
        safe_part = combined[: -self._tail_size]
        self._buffer = combined[-self._tail_size :]
        return redact_sensitive(safe_part)

    def flush(self) -> str:
        if not self._buffer:
            return ""
        output = redact_sensitive(self._buffer)
        self._buffer = ""
        return output
