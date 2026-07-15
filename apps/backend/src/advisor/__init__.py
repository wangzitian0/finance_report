"""``advisor`` — the backend implementation of the ``advisor`` package (#1425/#1671).

The application-layer AI financial advisor (EPIC-006 / EPIC-021): a read-only
conversational interface over the user's financial state.  The advisor
**never writes a ledger number** — every write/mutation request, prompt
injection, and sensitive-data request is refused before any LLM call, and
sensitive numeric patterns are redacted from both directions of the stream.

Physically moved here from ``src/services/ai_advisor/`` (#1671 Wave B),
absorbing ``services/annualized_income.py``, ``prompts/ai_advisor.py``, and
``models/chat.py`` (→ ``orm/chat.py``).  Cross-domain reads go through each
package's published root (``platform``/``portfolio``/``pricing``/
``reconciliation``/``llm``/``audit``/``reporting``); the one read whose owner
still lives in the app remainder (the observed-FX-pair composer, pending
#1610) is injected through the ``extension/app_reads.py`` port, wired by the
composition root (``src/main.py``).

This ``__all__`` is the package's published language; the contract copy lives
at ``common/advisor/contract.py`` (``interface``) and the gate keeps the two
identical.
"""

from src.advisor.base.guardrails import (
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
from src.advisor.base.prompt import DISCLAIMER_EN, DISCLAIMER_ZH, get_ai_advisor_prompt
from src.advisor.base.types.chat import ChatStreamEnvelope
from src.advisor.extension.annualized_income import generate_annualized_income_schedule
from src.advisor.extension.app_reads import register_fx_conversion, register_fx_pairs_read
from src.advisor.extension.cache import ResponseCache
from src.advisor.extension.service import AIAdvisorError, AIAdvisorService, ChatStream
from src.advisor.orm.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus

__all__ = [
    "AIAdvisorError",
    "AIAdvisorService",
    "ChatMessage",
    "ChatMessageRole",
    "ChatSession",
    "ChatSessionStatus",
    "ChatStream",
    "ChatStreamEnvelope",
    "DISCLAIMER_EN",
    "DISCLAIMER_ZH",
    "ResponseCache",
    "StreamRedactor",
    "build_refusal",
    "detect_language",
    "ensure_disclaimer",
    "estimate_tokens",
    "generate_annualized_income_schedule",
    "get_ai_advisor_prompt",
    "is_non_financial",
    "is_prompt_injection",
    "is_sensitive_request",
    "is_write_request",
    "normalize_question",
    "redact_sensitive",
    "register_fx_conversion",
    "register_fx_pairs_read",
]
