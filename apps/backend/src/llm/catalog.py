"""Dynamic model catalogue (EPIC-023 EPIC A).

Implements ``CatalogProvider`` over the configured models, enriched with litellm's
pricing table so free-tier and per-token cost are data, not guesses. This is the
``src/llm`` replacement for ``services/ai_models``; it deliberately keeps the
local/configured catalogue (deterministic in CI/prod) and layers litellm pricing
on top rather than depending on a remote ``/models`` round-trip.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

import litellm

from src.config import settings
from src.llm.common import Modality, ModelSpec
from src.llm.env_config import _PROVIDER_ENV_ID

# Configured roles -> the modalities each accepts. Vision/OCR models accept text
# plus the document modalities (image, pdf, file); text models are text-only.
_VISION_MODALITIES = frozenset({Modality.TEXT, Modality.IMAGE, Modality.PDF, Modality.FILE})
_TEXT_MODALITIES = frozenset({Modality.TEXT})


def _price(raw: object) -> Decimal | None:
    if raw is None:
        return None
    try:
        # litellm prices are per-token USD; express per-million-tokens.
        return (Decimal(str(raw)) * Decimal(1_000_000)).normalize()
    except (TypeError, ValueError, InvalidOperation):
        return None


def _pricing_for(model_id: str) -> tuple[Decimal | None, Decimal | None, bool]:
    """Best-effort (input, output) per-Mtok price + free flag from litellm."""
    info = litellm.model_cost.get(model_id) or litellm.model_cost.get(model_id.split("/")[-1]) or {}
    in_price = _price(info.get("input_cost_per_token"))
    out_price = _price(info.get("output_cost_per_token"))
    is_free = in_price == Decimal(0) and out_price == Decimal(0)
    return in_price, out_price, is_free


def _configured_specs() -> list[ModelSpec]:
    entries: list[tuple[str, frozenset[Modality]]] = [
        (settings.primary_model, _TEXT_MODALITIES),
        (settings.ocr_model, _VISION_MODALITIES),
        (settings.vision_model, _VISION_MODALITIES),
        *((m, _TEXT_MODALITIES) for m in settings.fallback_models),
        *((m, _VISION_MODALITIES) for m in settings.vision_fallback_models),
    ]
    specs: list[ModelSpec] = []
    seen: set[str] = set()
    for model_id, modalities in entries:
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        in_price, out_price, is_free = _pricing_for(model_id)
        specs.append(
            ModelSpec(
                id=model_id,
                provider_id=_PROVIDER_ENV_ID,
                modalities=modalities,
                is_free=is_free,
                input_price_per_mtok=in_price,
                output_price_per_mtok=out_price,
                supports_reasoning=bool(litellm.supports_reasoning(model_id))
                if hasattr(litellm, "supports_reasoning")
                else False,
            )
        )
    return specs


class LitellmCatalog:
    """``CatalogProvider`` backed by configured models + litellm pricing."""

    async def list_models(
        self,
        *,
        provider_id: str | None = None,
        modality: Modality | None = None,
        free_only: bool = False,
    ) -> list[ModelSpec]:
        specs = _configured_specs()
        if provider_id is not None:
            specs = [s for s in specs if s.provider_id == provider_id]
        if modality is not None:
            specs = [s for s in specs if s.accepts(modality)]
        if free_only:
            specs = [s for s in specs if s.is_free]
        return specs
