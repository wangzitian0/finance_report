"""AI advisor service for conversational financial insights (package).

Split from a single 1089-line module; the public import surface (incl. the
guardrail functions and the response cache) is preserved via these re-exports.
"""

from src.portfolio import PortfolioService
from src.services.ai_advisor._cache import _CACHE, ResponseCache
from src.services.ai_advisor._guardrails import (
    StreamRedactor,
    build_refusal,
    detect_language,
    ensure_disclaimer,
    estimate_tokens,
    is_non_financial,
    is_prompt_injection,
    is_sensitive_request,
    is_write_request,
    normalize_question,
    redact_sensitive,
)
from src.services.ai_advisor.service import AIAdvisorError, AIAdvisorService

__all__ = [
    "AIAdvisorError",
    "AIAdvisorService",
    "PortfolioService",
    "ResponseCache",
    "StreamRedactor",
    "_CACHE",
    "build_refusal",
    "detect_language",
    "ensure_disclaimer",
    "estimate_tokens",
    "is_non_financial",
    "is_prompt_injection",
    "is_sensitive_request",
    "is_write_request",
    "normalize_question",
    "redact_sensitive",
]
