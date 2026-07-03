"""Map a provider instance + model id onto a litellm call (EPIC-023 EPIC A).

litellm selects a provider from the ``provider/model`` prefix on the model
string. This module is the single place that knows how each of the three
protocol families becomes a litellm call, so the client never branches on
provider quirks — that was the duplication litellm is meant to remove.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.llm.base import ProtocolFamily, ProviderRef

# litellm's provider token per protocol family. openai-compatible (Z.AI/GLM,
# DeepSeek, local vLLM, …) all ride the OpenAI wire format with a custom api_base.
_FAMILY_PREFIX: dict[ProtocolFamily, str] = {
    ProtocolFamily.OPENAI_COMPATIBLE: "openai",
    ProtocolFamily.ANTHROPIC_COMPATIBLE: "anthropic",
    ProtocolFamily.OPENROUTER_COMPATIBLE: "openrouter",
    ProtocolFamily.GOOGLE_GEMINI: "gemini",
}

# Families whose litellm route is the vendor's native endpoint — they must NOT be
# given a custom OpenAI-style ``api_base`` (it would point litellm at the wrong host).
_NATIVE_ENDPOINT_FAMILIES = frozenset({ProtocolFamily.ANTHROPIC_COMPATIBLE, ProtocolFamily.GOOGLE_GEMINI})


@dataclass(frozen=True, slots=True)
class LitellmCall:
    """A resolved, provider-agnostic litellm invocation."""

    model: str
    api_key: str
    api_base: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)

    def kwargs(self) -> dict[str, Any]:
        """litellm.acompletion keyword arguments for this call."""
        out: dict[str, Any] = {"model": self.model, "api_key": self.api_key}
        if self.api_base:
            out["api_base"] = self.api_base
        if self.extra_headers:
            out["extra_headers"] = dict(self.extra_headers)
        return out


def build_call(provider: ProviderRef, model_id: str) -> LitellmCall:
    """Resolve ``(provider, model_id)`` into a litellm call.

    ``model_id`` is the *bare* model — the provider has already been resolved and
    any ``provider_id/`` qualifier stripped by the caller. It may legitimately
    contain a slash (OpenRouter's ``vendor/model`` form, e.g.
    ``deepseek/deepseek-chat``), so segments are never stripped here; we only
    avoid double-prefixing when it already carries the litellm family token.

    OpenRouter gets the attribution headers it expects; OpenAI-compatible
    endpoints get their custom ``api_base``; Anthropic is native.
    """
    prefix = _FAMILY_PREFIX[provider.protocol]
    litellm_model = model_id if model_id.startswith(f"{prefix}/") else f"{prefix}/{model_id}"

    extra_headers: dict[str, str] = {}
    if provider.protocol is ProtocolFamily.OPENROUTER_COMPATIBLE:
        extra_headers = {
            "HTTP-Referer": "https://finance-report.local",
            "X-Title": "Finance Report Backend",
        }

    # Native-endpoint families (Anthropic, Gemini) use the vendor's own host; only
    # custom OpenAI-compatible and OpenRouter endpoints need an explicit api_base.
    api_base = None if provider.protocol in _NATIVE_ENDPOINT_FAMILIES else provider.api_base

    return LitellmCall(
        model=litellm_model,
        api_key=provider.api_key,
        api_base=api_base,
        extra_headers=extra_headers,
    )
