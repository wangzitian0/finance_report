"""Unit tests for the LLM contract value types (EPIC-023 AC23.1.1)."""

from __future__ import annotations

from decimal import Decimal

from src.llm.common import (
    Modality,
    ModelSpec,
    ProtocolFamily,
    ProviderRef,
    ReasoningEffort,
    Scene,
    SceneBinding,
    Usage,
)


def test_AC23_1_1_protocol_family_enumerates_exactly_three_universal_families():
    """AC23.1.1: axis 1 is exactly the three universally-compatible protocol families."""
    assert {f.value for f in ProtocolFamily} == {
        "openai-compatible",
        "anthropic-compatible",
        "openrouter-compatible",
    }


def test_AC23_1_1_scene_enumerates_the_fixed_call_sites():
    """AC23.1.1: axis 3 is the fixed, code-defined set of scenes (the binding keys)."""
    assert {s.value for s in Scene} == {
        "extraction.ocr",
        "extraction.vision",
        "extraction.json",
        "advisor.chat",
        "statement.summary",
    }


def test_AC23_1_1_model_spec_carries_capabilities_so_selection_is_data():
    """AC23.1.1: a model's modalities/free/pricing are data on ModelSpec, not code branches."""
    spec = ModelSpec(
        id="zai/glm-4.6v",
        provider_id="zai",
        modalities=frozenset({Modality.IMAGE, Modality.PDF}),
        is_free=False,
        input_price_per_mtok=Decimal("0.60"),
        output_price_per_mtok=Decimal("2.20"),
        supports_reasoning=False,
    )
    assert spec.accepts(Modality.IMAGE)
    assert spec.accepts(Modality.PDF)
    assert not spec.accepts(Modality.TEXT)
    # Money is Decimal, never float (project red line).
    assert isinstance(spec.input_price_per_mtok, Decimal)


def test_AC23_1_1_scene_binding_defaults_are_conservative():
    """AC23.1.1: a binding maps scene x model with safe defaults (no reasoning, no free pref)."""
    binding = SceneBinding(scene=Scene.EXTRACTION_VISION, model_id="zai/glm-4.6v")
    assert binding.reasoning is ReasoningEffort.NONE
    assert binding.prefer_free is False
    assert binding.fallback_model_ids == ()
    assert binding.max_tokens is None


def test_AC23_1_1_provider_ref_never_reprs_its_api_key():
    """AC23.1.1: the decrypted api_key is excluded from repr/str (no secret in logs)."""
    ref = ProviderRef(id="env", label="zai", protocol=ProtocolFamily.OPENAI_COMPATIBLE, api_key="sk-secret-123")
    assert "sk-secret-123" not in repr(ref)
    assert "sk-secret-123" not in str(ref)
    # The key is still accessible programmatically.
    assert ref.api_key == "sk-secret-123"


def test_AC23_1_1_usage_totals_tokens():
    """AC23.1.1: Usage exposes total tokens for cost accounting."""
    usage = Usage(prompt_tokens=1200, completion_tokens=300)
    assert usage.total_tokens == 1500
