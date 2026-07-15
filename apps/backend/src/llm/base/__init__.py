"""``llm.base`` — the pure core: the frozen contract + the usage entity.

This layer holds only value types, protocols (ports), typed errors, the secret
cipher, and the in-memory usage meter — no provider SDK, no storage, no network
I/O. It is the agreed boundary the litellm client implementation and the
DB-backed configuration layer (both in ``extension/``) build against; importing
it never pulls in either half (and never pulls in ``litellm``).
"""

from __future__ import annotations

from src.llm.base.config_source import ConfigSource
from src.llm.base.errors import (
    LLMBudgetExceeded,
    LLMConfigError,
    LLMError,
    ModelCatalogError,
)
from src.llm.base.protocols import CatalogProvider, LLMClient
from src.llm.base.secrets import FernetCipher, SecretCipher, build_cipher
from src.llm.base.types.core import (
    ChatResult,
    Encrypted,
    Message,
    Modality,
    ModelSpec,
    ProtocolFamily,
    ProviderRef,
    ReasoningEffort,
    Scene,
    SceneBinding,
    Usage,
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
    "LLMConfigError",
    "LLMBudgetExceeded",
    "ModelCatalogError",
    # service protocols
    "LLMClient",
    "CatalogProvider",
    # secrets
    "SecretCipher",
    "FernetCipher",
    "build_cipher",
    # value types
    "ProtocolFamily",
    "Scene",
    "Modality",
    "ReasoningEffort",
    "Encrypted",
    "ProviderRef",
    "ModelSpec",
    "SceneBinding",
    "Usage",
    "ChatResult",
    "Message",
    # usage entity + estimators
    "LlmUsageMeter",
    "estimate_tokens",
    "estimate_tokens_from_chars",
]
