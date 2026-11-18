from __future__ import annotations

import pytest

from src.llm.base import ProtocolFamily, ProviderRef
from src.llm.extension.routing import build_call


@pytest.mark.parametrize(
    ("protocol", "api_base", "model", "expected_model", "expected_base", "expect_headers"),
    [
        (ProtocolFamily.OPENAI_COMPATIBLE, "https://api.z.ai/api/coding/paas/v4", "test-vision-model", "openai/test-vision-model", "https://api.z.ai/api/coding/paas/v4", False),
        (ProtocolFamily.OPENAI_COMPATIBLE, "https://x", "openai/glm-5.1", "openai/glm-5.1", "https://x", False),
        (ProtocolFamily.OPENROUTER_COMPATIBLE, None, "deepseek/deepseek-chat", "openrouter/deepseek/deepseek-chat", None, True),
        (ProtocolFamily.ANTHROPIC_COMPATIBLE, "ignored", "claude-opus-4-8", "anthropic/claude-opus-4-8", None, False),
        (ProtocolFamily.GOOGLE_GEMINI, "https://api.z.ai/api/coding/paas/v4", "gemini-3-flash-preview", "gemini/gemini-3-flash-preview", None, False),
    ],
)
def test_AC23_2_1_protocol_routing_and_kwargs(
    protocol: ProtocolFamily, api_base: str | None, model: str, expected_model: str, expected_base: str | None, expect_headers: bool
) -> None:
    call = build_call(ProviderRef(id="p", label="p", protocol=protocol, api_key="k", api_base=api_base), model)
    kw = call.kwargs()
    assert (call.model, call.api_base, kw["model"], kw["api_key"]) == (expected_model, expected_base, expected_model, "k")
    assert (bool(call.extra_headers.get("HTTP-Referer") and call.extra_headers.get("X-Title")), ("extra_headers" in kw)) == (expect_headers, expect_headers)
    assert ("api_base" in kw) is (expected_base is not None)
