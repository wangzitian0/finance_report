"""Per-user LLM configuration API (EPIC-023 AC23.4).

The runtime-config surface for ``src/llm``: each user manages their own provider
instances and scene→model bindings, with the deployment default as fallback. The
API key is encrypted at rest via the secret cipher on write and is **never**
returned or logged. ``GET /llm/config/status`` drives the first-run modal; the
catalogue and scene bindings feed the scene×model settings page.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import delete, select

from src.deps import CurrentUserId, DbSession
from src.llm.catalog import LitellmCatalog
from src.llm.common import Modality
from src.llm.common.errors import LLMConfigError
from src.llm.common.secrets import build_cipher
from src.llm.factory import get_config_source
from src.logger import get_logger
from src.models import LlmProvider, LlmSceneBinding
from src.schemas.llm import (
    LlmCatalogResponse,
    LlmConfigStatusResponse,
    LlmModelResponse,
    LlmProviderCreate,
    LlmProviderListResponse,
    LlmProviderResponse,
    LlmSceneBindingItem,
    LlmScenesResponse,
    LlmScenesUpdate,
)
from src.utils import raise_bad_request, raise_not_found, raise_service_unavailable

logger = get_logger(__name__)

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/config/status", response_model=LlmConfigStatusResponse)
async def get_config_status(user_id: CurrentUserId) -> LlmConfigStatusResponse:
    """Whether the current user has a usable config (their own, the deployment
    default, or the env fallback). Drives the first-run modal."""
    configured = await get_config_source(user_id).is_configured()
    return LlmConfigStatusResponse(configured=configured)


@router.get("/providers", response_model=LlmProviderListResponse)
async def list_providers(db: DbSession, user_id: CurrentUserId) -> LlmProviderListResponse:
    """List the current user's provider instances (keys never returned)."""
    rows = (
        await db.execute(select(LlmProvider).where(LlmProvider.user_id == user_id).order_by(LlmProvider.created_at))
    ).scalars().all()
    return LlmProviderListResponse(providers=[LlmProviderResponse.model_validate(r) for r in rows])


@router.post("/providers", response_model=LlmProviderResponse, status_code=201)
async def create_provider(
    payload: LlmProviderCreate,
    db: DbSession,
    user_id: CurrentUserId,
) -> LlmProviderResponse:
    """Create a provider for the current user, encrypting the API key at rest.

    Fails closed when secret encryption is not configured (``LLM_ENCRYPTION_KEYS``
    unset) — a DB-stored key must never be persisted in plaintext.
    """
    try:
        cipher = build_cipher()
    except LLMConfigError as exc:
        # Never store a plaintext key: refuse the write rather than degrade.
        raise_service_unavailable("LLM secret encryption is not configured.", cause=exc)

    sealed = cipher.encrypt(payload.api_key)
    provider = LlmProvider(
        user_id=user_id,
        label=payload.label,
        protocol=payload.protocol,
        api_key_ciphertext=sealed.ciphertext,
        api_key_version=sealed.key_version,
        api_base=payload.api_base,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)
    return LlmProviderResponse.model_validate(provider)


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: str, db: DbSession, user_id: CurrentUserId) -> None:
    """Delete one of the current user's providers (cascades to its bindings)."""
    row = (
        await db.execute(
            select(LlmProvider).where(LlmProvider.id == provider_id, LlmProvider.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise_not_found("Provider")
    await db.delete(row)
    await db.commit()


@router.get("/catalog", response_model=LlmCatalogResponse)
async def get_catalog(
    modality: Annotated[Modality | None, Query()] = None,
    free_only: Annotated[bool, Query()] = False,
) -> LlmCatalogResponse:
    """The dynamic model catalogue (configured models + litellm pricing)."""
    specs = await LitellmCatalog().list_models(modality=modality, free_only=free_only)
    models = [
        LlmModelResponse(
            id=s.id,
            provider_id=s.provider_id,
            modalities=sorted(s.modalities, key=lambda m: m.value),
            is_free=s.is_free,
            input_price_per_mtok=s.input_price_per_mtok,
            output_price_per_mtok=s.output_price_per_mtok,
            supports_reasoning=s.supports_reasoning,
        )
        for s in specs
    ]
    return LlmCatalogResponse(models=models)


@router.get("/scenes", response_model=LlmScenesResponse)
async def get_scenes(db: DbSession, user_id: CurrentUserId) -> LlmScenesResponse:
    """The current user's scene→model bindings."""
    rows = (
        await db.execute(select(LlmSceneBinding).where(LlmSceneBinding.user_id == user_id))
    ).scalars().all()
    bindings = [
        LlmSceneBindingItem(
            scene=r.scene,
            provider_id=r.provider_id,
            model=r.model,
            reasoning=r.reasoning,
            prefer_free=r.prefer_free,
            fallback_model_ids=[m.strip() for m in r.fallback_model_ids.split(",") if m.strip()],
            max_tokens=r.max_tokens,
        )
        for r in rows
    ]
    return LlmScenesResponse(bindings=bindings)


@router.put("/scenes", response_model=LlmScenesResponse)
async def put_scenes(
    payload: LlmScenesUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> LlmScenesResponse:
    """Replace the current user's scene bindings (PUT semantics).

    Validates that each binding references one of the user's own providers and
    that no scene appears twice, then atomically swaps the binding set.
    """
    scenes = [b.scene for b in payload.bindings]
    if len(scenes) != len(set(scenes)):
        raise_bad_request("Duplicate scene in bindings.")

    owned = set(
        (await db.execute(select(LlmProvider.id).where(LlmProvider.user_id == user_id))).scalars().all()
    )
    for b in payload.bindings:
        if b.provider_id not in owned:
            raise_bad_request(f"Provider {b.provider_id} is not owned by the current user.")

    await db.execute(delete(LlmSceneBinding).where(LlmSceneBinding.user_id == user_id))
    for b in payload.bindings:
        db.add(
            LlmSceneBinding(
                user_id=user_id,
                scene=b.scene,
                provider_id=b.provider_id,
                model=b.model,
                reasoning=b.reasoning,
                prefer_free=b.prefer_free,
                fallback_model_ids=",".join(b.fallback_model_ids),
                max_tokens=b.max_tokens,
            )
        )
    await db.commit()
    return await get_scenes(db, user_id)
