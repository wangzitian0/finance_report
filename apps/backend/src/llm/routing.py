"""Map a provider instance + model id onto a litellm call (EPIC-023 EPIC A).

litellm selects a provider from the ``provider/model`` prefix on the model
string. This module is the single place that knows how each of the three
protocol families becomes a litellm call, so the client never branches on
provider quirks — that was the duplication litellm is meant to remove.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.llm.common import ProtocolFamily, ProviderRef

# litellm's provider token per protocol family. openai-compatible (Z.AI/GLM,
# DeepSeek, local vLLM, …) all ride the OpenAI wire format with a custom api_base.
_FAMILY_PREFIX: dict[ProtocolFamily, str] = {
    ProtocolFamily.OPENAI_COMPATIBLE: "openai",
    ProtocolFamily.ANTHROPIC_COMPATIBLE: "anthropic",
    ProtocolFamily.OPENROUTER_COMPATIBLE: "openrouter",
}


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


def _strip_known_prefix(model_id: str) -> str:
    """Drop a leading ``provider/`` token if the binding already carries one.

    Bindings may store either ``glm-4.6v`` or ``zai/glm-4.6v``; we re-derive the
    litellm provider from the protocol family, so any leading family/vendor token
    is normalised away to avoid ``openai/zai/glm-4.6v``.
    """
    if "/" in model_id:
        return model_id.split("/", 1)[1]
    return model_id


def build_call(provider: ProviderRef, model_id: str) -> LitellmCall:
    """Resolve ``(provider, model_id)`` into a litellm call.

    OpenRouter gets the attribution headers it expects; OpenAI-compatible
    endpoints get their custom ``api_base``; Anthropic is native.
    """
    prefix = _FAMILY_PREFIX[provider.protocol]
    bare_model = _strip_known_prefix(model_id)
    litellm_model = f"{prefix}/{bare_model}"

    extra_headers: dict[str, str] = {}
    if provider.protocol is ProtocolFamily.OPENROUTER_COMPATIBLE:
        extra_headers = {
            "HTTP-Referer": "https://finance-report.local",
            "X-Title": "Finance Report Backend",
        }

    # Anthropic native uses its own endpoint; only custom OpenAI-compatible and
    # OpenRouter endpoints need an explicit api_base.
    api_base = provider.api_base if provider.protocol is not ProtocolFamily.ANTHROPIC_COMPATIBLE else None

    return LitellmCall(
        model=litellm_model,
        api_key=provider.api_key,
        api_base=api_base,
        extra_headers=extra_headers,
    )
