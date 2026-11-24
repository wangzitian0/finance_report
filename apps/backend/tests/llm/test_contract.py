from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal

from src.llm.base import (
    ConfigSource,
    LLMBudgetExceeded,
    LLMClient,
    LLMConfigError,
    LLMError,
    Modality,
    ModelCatalogError,
    ModelSpec,
    ProtocolFamily,
    ProviderRef,
    ReasoningEffort,
    Scene,
    SceneBinding,
)
from src.llm.base.usage import LlmUsageMeter, estimate_tokens


class _FakeConfigSource:
    list_providers = staticmethod(lambda: None)
    get_provider = staticmethod(lambda _pid: None)
    get_binding = staticmethod(lambda _s: None)
    is_configured = staticmethod(lambda: None)


class _FakeClient:
    def stream(self, scene, messages, *, reasoning=None) -> AsyncIterator[str]:
        raise NotImplementedError


async def test_AC23_1_and_2_base_protocols_types_errors_and_usage() -> None:
    assert (
        isinstance(_FakeConfigSource(), ConfigSource),
        isinstance(_FakeClient(), LLMClient),
        isinstance(type("_NotCfg", (), {"list_providers": lambda _s: None})(), ConfigSource),
    ) == (True, True, False)
    assert {f.value for f in ProtocolFamily} == {"openai-compatible", "anthropic-compatible", "openrouter-compatible", "google-gemini"}
    assert {s.value for s in Scene} == {"extraction.ocr", "extraction.vision", "extraction.json", "advisor.chat", "statement.summary"}

    spec = ModelSpec(id="zai/test-vision-model", provider_id="zai", modalities=frozenset({Modality.IMAGE, Modality.PDF}), is_free=False, input_price_per_mtok=Decimal("0.60"), output_price_per_mtok=Decimal("2.20"), supports_reasoning=False)
    binding = SceneBinding(scene=Scene.EXTRACTION_VISION, model_id="zai/test-vision-model")
    ref = ProviderRef(id="env", label="zai", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="sk-secret-123")
    assert (spec.accepts(Modality.IMAGE), spec.accepts(Modality.PDF), spec.accepts(Modality.TEXT), isinstance(spec.input_price_per_mtok, Decimal)) == (True, True, False, True)
    assert (binding.reasoning, binding.max_tokens, hasattr(binding, "prefer_free"), hasattr(binding, "fallback_model_ids")) == (ReasoningEffort.NONE, None, False, False)
    assert "sk-secret-123" not in repr(ref) and "sk-secret-123" not in str(ref) and ref.api_key == "sk-secret-123"

    budget, catalog = LLMBudgetExceeded("over daily budget"), ModelCatalogError("catalogue unavailable", retryable=True)
    assert (isinstance(budget, LLMError), budget.retryable, isinstance(catalog, LLMError), catalog.retryable, issubclass(LLMConfigError, LLMError)) == (True, False, True, True, True)

    day, next_day, meter = date(2026, 1, 2), date(2026, 1, 3), LlmUsageMeter()
    await meter.record("test-vision-model", "extraction.json", 100, 40, today=day)
    await meter.record("test-vision-model", "advisor.chat", 10, 5, today=day)
    assert (meter.requests_today, meter.tokens_today) == (2, 155)
    await meter.record("m", "advisor.chat", 7, 3, today=next_day)
    assert (meter.requests_today, meter.tokens_today, estimate_tokens(""), estimate_tokens("abcd"), estimate_tokens("a" * 400)) == (1, 10, 0, 1, 100)
