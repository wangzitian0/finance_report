"""``llm`` — the backend implementation of the ``llm`` package (EPIC-023 → #1426).

``src/llm`` is the single entry point for talking to language models, built
around three orthogonal axes (see ``common/llm/readme.md``):

- **Protocol family** — ``openai-compatible`` / ``anthropic-compatible`` / …;
  every concrete vendor slots into a family, never a special case.
- **Model** — a dynamic catalogue, each entry carrying capabilities.
- **Scene** — the fixed, code-defined set of call sites (``extraction.ocr``,
  ``advisor.chat``, …); the ``scene -> model`` binding is the configurable
  surface.

Files converge by layer (common/meta/migration-standard.md): ``base/`` is the
frozen contract (types, ports, errors, secret cipher) plus the usage entity;
``extension/`` holds the adapters — the litellm transport (the single litellm
chokepoint), catalogue, routing, env/DB config sources, the input-keyed
cassette record/replay subsystem, and the ORM entities; ``data/`` is the
reserved projection layer (usage rollup lands there, package-internal).

The names re-exported below are the entire public surface (``__all__`` must
equal ``contract.interface``). The litellm-dependent symbols
(``litellm_stream`` / ``cassette_completion`` / ``resolve_provider_and_model``
/ ``LitellmCatalog``) are exposed **lazily** (PEP 562): importing this root
never imports ``litellm``, so minimal tooling environments can load the
package; the heavy dependency is paid on first use of those four names only.
"""

from __future__ import annotations

from typing import Any

from src.llm.base import (
    CatalogProvider,
    ChatResult,
    ConfigSource,
    Encrypted,
    FernetCipher,
    LLMBudgetExceeded,
    LLMClient,
    LLMConfigError,
    LLMError,
    LlmUsageMeter,
    Message,
    Modality,
    ModelCatalogError,
    ModelSpec,
    ProtocolFamily,
    ProviderRef,
    ReasoningEffort,
    Scene,
    SceneBinding,
    SecretCipher,
    Usage,
    build_cipher,
    estimate_tokens,
    estimate_tokens_from_chars,
)
from src.llm.extension import (
    CASSETTE_DIR,
    AIStreamError,
    Cassette,
    CassetteMiss,
    CassetteRecorder,
    CassetteStore,
    CassetteTag,
    CassetteValidationError,
    DbConfigSource,
    EnvConfigSource,
    LayeredConfigSource,
    LitellmCall,
    accumulate_stream,
    ai_semantic_score,
    build_call,
    fingerprint,
    get_config_source,
    get_usage_meter,
    miss_summary,
    ocr_layout_call,
    protocol_for,
    stream_ai_chat,
    stream_ai_json,
)

# ORM models owned by this package (moved from src/models, #1675); imported
# eagerly so importing the package registers the mappers on Base.metadata.
from src.llm.orm.config import LlmProvider, LlmSceneBinding

# The litellm-heavy surface, resolved lazily so ``import src.llm`` stays
# litellm-free (the no-litellm-at-root invariant; see common/llm/contract.py).
_LAZY_CLIENT = frozenset({"litellm_stream", "cassette_completion", "resolve_provider_and_model"})


def __getattr__(name: str) -> Any:
    if name in _LAZY_CLIENT:
        from src.llm.extension import client

        return getattr(client, name)
    if name == "LitellmCatalog":
        from src.llm.extension.catalog import LitellmCatalog

        return LitellmCatalog
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AIStreamError",
    "CASSETTE_DIR",
    "Cassette",
    "CassetteMiss",
    "CassetteRecorder",
    "CassetteStore",
    "CassetteTag",
    "CassetteValidationError",
    "CatalogProvider",
    "ChatResult",
    "ConfigSource",
    "DbConfigSource",
    "Encrypted",
    "EnvConfigSource",
    "FernetCipher",
    "LLMBudgetExceeded",
    "LLMClient",
    "LLMConfigError",
    "LLMError",
    "LayeredConfigSource",
    "LitellmCall",
    "LitellmCatalog",
    "LlmProvider",
    "LlmSceneBinding",
    "LlmUsageMeter",
    "Message",
    "Modality",
    "ModelCatalogError",
    "ModelSpec",
    "ProtocolFamily",
    "ProviderRef",
    "ReasoningEffort",
    "Scene",
    "SceneBinding",
    "SecretCipher",
    "Usage",
    "accumulate_stream",
    "ai_semantic_score",
    "build_call",
    "build_cipher",
    "cassette_completion",
    "estimate_tokens",
    "estimate_tokens_from_chars",
    "fingerprint",
    "get_config_source",
    "get_usage_meter",
    "litellm_stream",
    "miss_summary",
    "ocr_layout_call",
    "protocol_for",
    "resolve_provider_and_model",
    "stream_ai_chat",
    "stream_ai_json",
]
