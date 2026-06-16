"""Frozen contract for the LLM abstraction (EPIC-023).

This package is the agreed boundary between the litellm client implementation
(EPIC A) and the DB-backed configuration layer (EPIC B). It contains only value
types, protocols, and the secret cipher — no provider SDK, no storage, no I/O
beyond encryption — so importing it never pulls in either half.
"""

from __future__ import annotations

from src.llm.common.config_source import ConfigSource
from src.llm.common.errors import (
    LLMBudgetExceeded,
    LLMConfigError,
    LLMError,
    ModelCatalogError,
)
from src.llm.common.protocols import CatalogProvider, CostMeter, LLMClient
from src.llm.common.secrets import FernetCipher, SecretCipher, build_cipher
from src.llm.common.types import (
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
    "CostMeter",
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
]
