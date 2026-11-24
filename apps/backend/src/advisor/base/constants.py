"""Shared AI-advisor constants and patterns (pure).

Moved from ``src/services/ai_advisor/_base.py`` (#1671 Wave B), minus the
logger — ``base/`` stays free of infra imports; the package logger lives in
``extension/service.py``.
"""

from __future__ import annotations

import re

from src.advisor.base.prompt import DISCLAIMER_EN, DISCLAIMER_ZH

MAX_CONTEXT_MESSAGES = 20
CACHE_TTL_SECONDS = 3600

CHAT_METADATA_SAFE_HREFS = (
    "/reports?tab=balance-sheet",
    "/reports?tab=income-statement",
    "/reports?tab=package",
    "/reports",
    "/reconciliation?tab=review-queue",
    "/audit",
    "/portfolio?panel=prices",
    "/portfolio",
    "/upload",
)

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
