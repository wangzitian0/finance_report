"""``llm.base`` — the pure core: the errors of a model call and the token estimate.

No provider SDK, no storage and no network I/O: importing it pulls in neither the SDK nor the entry point.
"""

from __future__ import annotations

from src.llm.base.errors import LLMConfigError, LLMError, ModelCallFailed, ModelFailureKind
from src.llm.base.usage import estimate_tokens

__all__ = [
    "LLMConfigError",
    "LLMError",
    "ModelCallFailed",
    "ModelFailureKind",
    "estimate_tokens",
]
