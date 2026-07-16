"""Value objects for the LLM abstraction's three orthogonal axes (EPIC-023).

Everything here is an immutable, dependency-free value type so both the litellm
client (EPIC A) and the DB configuration layer (EPIC B) can share it without a
cycle. Monetary values use :class:`~decimal.Decimal` per the project money rule;
``float`` must never appear here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

# An OpenAI-style chat message. Content may be a plain string or a list of
# multimodal content parts (text / image_url / file), so we keep it permissive.
Message = dict[str, Any]


class ProtocolFamily(StrEnum):
    """Axis 1 — the wire protocol a provider speaks.

    Concrete vendors map onto exactly one family; e.g. Z.AI/GLM and DeepSeek are
    ``OPENAI_COMPATIBLE`` (custom ``api_base``), Claude is ``ANTHROPIC_COMPATIBLE``,
    and Google Gemini (AI Studio / Vertex) is ``GOOGLE_GEMINI`` — its native API
    accepts a whole PDF as one ``file`` part (no per-page image rendering) and has
    a high output ceiling, which is why it is the provider of choice for extracting
    large or scanned statements.
    """

    OPENAI_COMPATIBLE = "openai-compatible"
    ANTHROPIC_COMPATIBLE = "anthropic-compatible"
    OPENROUTER_COMPATIBLE = "openrouter-compatible"
    GOOGLE_GEMINI = "google-gemini"


class Scene(StrEnum):
    """Axis 3 — a code-defined call site. Adding one is a contract change.

    The value is the stable identifier persisted in bindings; keep it in sync
    with ``common/llm/readme.md``.
    """

    EXTRACTION_OCR = "extraction.ocr"
    EXTRACTION_VISION = "extraction.vision"
    EXTRACTION_JSON = "extraction.json"
    ADVISOR_CHAT = "advisor.chat"
    STATEMENT_SUMMARY = "statement.summary"


class Modality(StrEnum):
    """Input modalities a model accepts."""

    TEXT = "text"
    IMAGE = "image"
    PDF = "pdf"
    FILE = "file"


class ReasoningEffort(StrEnum):
    """Per-scene reasoning depth, mapped onto each provider by the client.

    ``NONE`` means "do not request extended reasoning"; the others map to the
    litellm ``reasoning_effort`` parameter (which in turn maps to Anthropic
    thinking budgets / OpenAI reasoning levels).
    """

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class DecodeParams:
    """Provider-independent knobs that can change completion bytes."""

    max_tokens: int | None = None
    temperature: float | int | None = None
    reasoning: ReasoningEffort | None = None
    seed: int | None = None
    extra_body: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.extra_body is not None:
            object.__setattr__(self, "extra_body", MappingProxyType(dict(self.extra_body)))

    def as_request(self) -> dict[str, Any]:
        """Canonical request projection used by transport and cassette keys."""
        params: dict[str, Any] = {}
        if self.max_tokens is not None:
            params["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            params["temperature"] = self.temperature
        if self.reasoning is not None and self.reasoning is not ReasoningEffort.NONE:
            params["reasoning_effort"] = self.reasoning.value
        if self.seed is not None:
            params["seed"] = self.seed
        if self.extra_body:
            params["extra_body"] = dict(self.extra_body)
        return params


@dataclass(frozen=True, slots=True)
class Encrypted:
    """A provider secret at rest: ciphertext plus the key version that sealed it.

    ``key_version`` lets the DB layer (EPIC B) tell, during a key rotation pass,
    which rows still hold the old key. See :mod:`src.llm.base.secrets`.
    """

    ciphertext: str
    key_version: int


@dataclass(frozen=True, slots=True)
class ProviderRef:
    """A configured provider instance with its API key already decrypted.

    This is the projection a :class:`~src.llm.base.config_source.ConfigSource`
    hands to the client; persistence and encryption live below the contract.
    """

    id: str
    label: str
    protocol: ProtocolFamily
    # repr=False so the decrypted key never lands in logs/exceptions/debug output.
    api_key: str = field(repr=False)
    api_base: str | None = None


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Axis 2 — one entry of the dynamic model catalogue."""

    id: str
    provider_id: str
    modalities: frozenset[Modality] = field(default_factory=frozenset)
    is_free: bool = False
    input_price_per_mtok: Decimal | None = None
    output_price_per_mtok: Decimal | None = None
    supports_reasoning: bool = False

    def accepts(self, modality: Modality) -> bool:
        """Whether this model can take the given input modality."""
        return modality in self.modalities


@dataclass(frozen=True, slots=True)
class SceneBinding:
    """Axis 2 x Axis 3 — which model (and how) a scene resolves to."""

    scene: Scene
    model_id: str
    reasoning: ReasoningEffort = ReasoningEffort.NONE
    prefer_free: bool = False
    fallback_model_ids: tuple[str, ...] = ()
    max_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class Usage:
    """Token accounting for a single completion."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True, slots=True)
class ChatResult:
    """A non-streaming completion result with cost telemetry."""

    text: str
    model_id: str
    usage: Usage = field(default_factory=Usage)
    cost_usd: Decimal | None = None
