"""Shared AI-advisor constants, patterns, and logger."""

from __future__ import annotations

import re

from src.logger import get_logger
from src.prompts.ai_advisor import DISCLAIMER_EN, DISCLAIMER_ZH

logger = get_logger(__name__)

MAX_CONTEXT_MESSAGES = 20
CACHE_TTL_SECONDS = 3600

INJECTION_PATTERNS = (
    r"ignore (all|previous|prior) instructions",
    r"disregard (all|previous|prior) instructions",
    r"reveal (the )?(system|developer) prompt",
    r"system prompt",
    r"developer message",
    r"jailbreak",
    r"bypass safety",
    r"override (rules|policy)",
    r"forget what we talked about",
    r"you are now a",
)

SENSITIVE_PATTERNS = (
    r"password",
    r"account number",
    r"card number",
    r"credit card",
    r"cvv",
    r"otp",
    r"pin",
    r"social security",
    r"ssn",
    r"secret key",
)

NON_FINANCIAL_PATTERNS = (
    r"weather",
    r"joke",
    r"movie",
    r"music",
    r"recipe",
    r"sports",
    r"news",
    r"code",
    r"programming",
)

CHAT_METADATA_SAFE_HREFS = (
    "/reports/balance-sheet",
    "/reports/income-statement",
    "/reports/package",
    "/reports",
    "/reconciliation/review-queue",
    "/review",
    "/portfolio/prices",
    "/portfolio",
    "/assets",
    "/statements/upload",
)

CONFIDENCE_WORST_ORDER = {
    "LOW": 0,
    "MEDIUM": 1,
    "HIGH": 2,
    "TRUSTED": 3,
    "DETERMINISTIC": 3,
}

# SECURITY: Match long number sequences but avoid common date/time patterns
# (YYYY-MM-DD, DD/MM/YYYY, etc.)
# Generic branch: 12+ consecutive digits (no separators) to reduce accidental date matches
SENSITIVE_NUMBER_RE = re.compile(
    r"(?<!\d)\d{12,}(?!\d)"  # 12+ contiguous digits (account numbers, identifiers)
    r"|"
    r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)"  # Credit card format: 4x4 digits
)

DISCLAIMER_BY_LANG = {
    "en": DISCLAIMER_EN,
    "zh": DISCLAIMER_ZH,
}

REFUSAL_BY_REASON = {
    "injection": {
        "en": "I cannot help with that request. Please ask a finance-related question.",
        "zh": (
            "\u6211\u65e0\u6cd5\u534f\u52a9\u8be5\u8bf7\u6c42\u3002"
            "\u8bf7\u63d0\u51fa\u4e0e\u8d22\u52a1\u76f8\u5173\u7684\u95ee\u9898\u3002"
        ),
    },
    "write": {
        "en": (
            "I can only provide read-only analysis and cannot create or modify ledger entries. "
            "Please use the manual entry workflow."
        ),
        "zh": (
            "\u6211\u53ea\u80fd\u63d0\u4f9b\u53ea\u8bfb\u5206\u6790\uff0c"
            "\u65e0\u6cd5\u521b\u5efa\u6216\u4fee\u6539\u5206\u5f55\u3002"
            "\u8bf7\u4f7f\u7528\u624b\u52a8\u5f55\u5165\u6d41\u7a0b\u3002"
        ),
    },
    "sensitive": {
        "en": "For safety reasons, I cannot provide sensitive information.",
        "zh": (
            "\u51fa\u4e8e\u5b89\u5168\u539f\u56e0\uff0c\u6211\u65e0\u6cd5\u63d0\u4f9b\u654f\u611f\u4fe1\u606f\u3002"
        ),
    },
    "non_financial": {
        "en": "This assistant only answers finance-related questions.",
        "zh": ("\u8be5\u52a9\u624b\u4ec5\u56de\u7b54\u8d22\u52a1\u76f8\u5173\u95ee\u9898\u3002"),
    },
}
