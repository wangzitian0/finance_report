"""Provider routing maps families onto litellm calls (EPIC-023 AC23.2.1)."""

from __future__ import annotations

from src.llm.common import ProtocolFamily, ProviderRef
from src.llm.routing import build_call


def _provider(protocol: ProtocolFamily, api_base: str | None = None) -> ProviderRef:
    return ProviderRef(id="p", label="p", protocol=protocol, api_key="k", api_base=api_base)


def test_AC23_2_1_openai_compatible_prefixes_and_keeps_api_base():
    """AC23.2.1: openai-compatible (Z.AI/GLM, vLLM…) -> openai/ prefix + custom api_base."""
    call = build_call(_provider(ProtocolFamily.OPENAI_COMPATIBLE, "https://api.z.ai/api/coding/paas/v4"), "glm-4.6v")
    assert call.model == "openai/glm-4.6v"
    assert call.api_base == "https://api.z.ai/api/coding/paas/v4"
    assert call.extra_headers == {}


def test_AC23_2_1_openrouter_adds_attribution_headers():
    """AC23.2.1: openrouter-compatible -> openrouter/ prefix + attribution headers."""
    call = build_call(_provider(ProtocolFamily.OPENROUTER_COMPATIBLE), "deepseek/deepseek-chat")
    assert call.model.startswith("openrouter/")
    assert call.extra_headers.get("HTTP-Referer")
    assert call.extra_headers.get("X-Title")


def test_AC23_2_1_anthropic_is_native_without_api_base():
    """AC23.2.1: anthropic-compatible -> anthropic/ prefix, no custom api_base."""
    call = build_call(_provider(ProtocolFamily.ANTHROPIC_COMPATIBLE, "ignored"), "claude-opus-4-8")
    assert call.model == "anthropic/claude-opus-4-8"
    assert call.api_base is None


def test_AC23_2_1_existing_provider_prefix_is_normalised():
    """AC23.2.1: a binding model already qualified as vendor/model is re-derived, not doubled."""
    call = build_call(_provider(ProtocolFamily.OPENAI_COMPATIBLE, "https://x"), "zai/glm-5.1")
    assert call.model == "openai/glm-5.1"


def test_AC23_2_1_kwargs_only_include_set_fields():
    """AC23.2.1: kwargs() omits api_base/headers when not applicable."""
    call = build_call(_provider(ProtocolFamily.ANTHROPIC_COMPATIBLE), "claude-x")
    kw = call.kwargs()
    assert kw["model"] == "anthropic/claude-x"
    assert kw["api_key"] == "k"
    assert "api_base" not in kw
    assert "extra_headers" not in kw
