"""``llm.base`` — the pure core: the frozen contract + the usage entity.

This layer holds only value types, protocols (ports), typed errors and the
in-memory usage meter — no provider SDK, no storage, no network I/O. It is the
agreed boundary the litellm client implementation and the environment
configuration (both in ``extension/``) build against; importing it never pulls
in either half (and never pulls in ``litellm``).
"""

from __future__ import annotations

from src.llm.base.config_source import ConfigSource
from src.llm.base.errors import (
    LLMBudgetExceeded,
    LLMConfigError,
    LLMError,
    ModelCallFailed,
    ModelFailureKind,
    ModelCatalogError,
)
from src.llm.base.protocols import LLMClient
from src.llm.base.types import (
    DecodeParams,
    Message,
    Modality,
    ModelSpec,
    ProtocolFamily,
    ProviderRef,
    ReasoningEffort,
    Scene,
    SceneBinding,
)
from src.llm.base.usage import (
    LlmUsageMeter,
    estimate_tokens,
    estimate_tokens_from_chars,
)

__all__ = [
    # config seam
    "ConfigSource",
    # errors
    "LLMError",
    "ModelCallFailed",
    "ModelFailureKind",
    "LLMConfigError",
    "LLMBudgetExceeded",
    "ModelCatalogError",
    # service protocols
    "LLMClient",
    # value types
    "ProtocolFamily",
    "Scene",
    "Modality",
    "ReasoningEffort",
    "ProviderRef",
    "ModelSpec",
    "SceneBinding",
    "DecodeParams",
    "Message",
    # usage entity + estimators
    "LlmUsageMeter",
    "estimate_tokens",
    "estimate_tokens_from_chars",
]
