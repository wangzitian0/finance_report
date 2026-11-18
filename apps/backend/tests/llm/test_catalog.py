from __future__ import annotations

from decimal import Decimal

import src.llm.extension.catalog as catalog_mod
from src.config import settings
from src.llm.base import Modality
from src.llm.extension.catalog import LitellmCatalog


def _patch_catalog(monkeypatch, small: str, large: str, multi: str, cost: dict | None = None, reasoning=None) -> LitellmCatalog:
    monkeypatch.setattr(settings, "small_model", small)
    monkeypatch.setattr(settings, "large_model", large)
    monkeypatch.setattr(settings, "multimodal_model", multi)
    monkeypatch.setattr(catalog_mod.litellm, "model_cost", cost or {}, raising=False)
    monkeypatch.setattr(catalog_mod.litellm, "supports_reasoning", reasoning or (lambda _m: False), raising=False)
    return LitellmCatalog()


async def test_AC23_2_5_catalog_pricing_filters_dedup_and_get(monkeypatch) -> None:
    catalog = _patch_catalog(monkeypatch, "glm-5.1", "free-mini", "test-vision-model", {"glm-5.1": {"input_cost_per_token": 6e-07, "output_cost_per_token": 2.2e-06}, "free-mini": {"input_cost_per_token": 0.0, "output_cost_per_token": 0.0}}, lambda m: m == "glm-5.1")
    primary = {m.id: m for m in await catalog.list_models()}["glm-5.1"]
    free = await catalog.list_models(free_only=True)
    image_ids = {m.id for m in await catalog.list_models(modality=Modality.IMAGE)}
    bare, qualified = await catalog.get("test-vision-model"), await catalog.get("some-provider/test-vision-model")
    assert (primary.input_price_per_mtok, primary.output_price_per_mtok, primary.is_free, primary.supports_reasoning) == (Decimal("0.6"), Decimal("2.2"), False, True)
    assert {m.id for m in free} == {"free-mini"} and all(m.is_free for m in free) and "test-vision-model" in image_ids and "glm-5.1" not in image_ids
    assert bare is not None and qualified is not None and bare.id == qualified.id and bare.accepts(Modality.IMAGE) and await catalog.get("definitely-not-a-real-model-xyz") is None

    assert (await _patch_catalog(monkeypatch, "weird", "weird", "weird", {"weird": {"input_cost_per_token": "n/a"}}).list_models())[0].input_price_per_mtok is None
    assert [m.id for m in await _patch_catalog(monkeypatch, "glm-5.1", "glm-5.1", "test-vision-model").list_models()] == ["glm-5.1", "test-vision-model"]

    merged = await _patch_catalog(monkeypatch, "glm-5.3-flash", "glm-5.3-flash", "glm-5.3-flash").list_models()
    assert [m.id for m in merged] == ["glm-5.3-flash"] and {Modality.TEXT, Modality.IMAGE} <= merged[0].modalities

    ordered = _patch_catalog(monkeypatch, "model-small", "model-large", "model-multimodal")
    assert [m.id for m in await ordered.list_models()] == [m.id for m in await ordered.list_models(modality=Modality.TEXT)] == ["model-small", "model-large", "model-multimodal"]
    for mod in (Modality.IMAGE, Modality.PDF, Modality.FILE):
        assert [m.id for m in await ordered.list_models(modality=mod)] == ["model-multimodal"]
