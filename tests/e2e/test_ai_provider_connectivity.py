"""Staging AI provider connectivity smoke tests."""

from __future__ import annotations

import json
import os

import httpx

from playwright.async_api import Page
import pytest


APP_URL = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")
PROVIDER_CONNECTIVITY_TIMEOUT_MS = int(
    os.getenv("PROVIDER_CONNECTIVITY_TIMEOUT_MS", "90000")
)


def _api_url(path: str) -> str:
    return f"{APP_URL}/api{path}"


def _sdk_default_model_ids() -> frozenset[str]:
    """The model ids that the infra2 SDK defaults name (#2566)."""
    # Imported here, so the chat smoke in this file does not need the SDK.
    from infra2_sdk.runtime.llm import LlmSettings

    sdk = LlmSettings()
    ids = (
        sdk.primary_model,
        sdk.ocr_model,
        sdk.vision_model,
        *sdk.fallback_models,
        *sdk.vision_fallback_models,
    )
    return frozenset(model_id for model_id in ids if model_id)


@pytest.mark.e2e
@pytest.mark.critical
@pytest.mark.llm
async def test_staging_ai_provider_chat_connectivity(
    authenticated_page_unique: Page,
) -> None:
    """EPIC-006 EPIC-008 EPIC-021 / AC8.13.120 AC21.1.1: one real AI provider chat round trip."""
    response = await authenticated_page_unique.request.post(
        _api_url("/chat"),
        data={
            "message": (
                "In one short sentence, confirm you can answer finance questions."
            )
        },
        timeout=PROVIDER_CONNECTIVITY_TIMEOUT_MS,
    )

    body = await response.text()
    assert response.status == 200, (
        f"AI provider chat connectivity failed: {response.status} {body[:500]}"
    )
    assert body.strip(), "AI provider chat connectivity returned an empty response"


@pytest.mark.e2e
@pytest.mark.critical
@pytest.mark.llm
async def test_staging_catalog_serves_the_sdk_default_models() -> None:
    """EPIC-008 EPIC-023 / AC-llm.sdk-model-defaults.3: staging serves exactly the infra2 SDK default models (#2566)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(_api_url("/llm/catalog"))
    body = response.text
    assert response.status_code == 200, (
        f"model catalog failed: {response.status_code} {body[:500]}"
    )
    model_ids = {model["id"].split("/")[-1] for model in json.loads(body)["models"]}
    assert model_ids, f"the deployed catalog lists no model: {body[:500]}"
    expected = _sdk_default_model_ids()
    assert model_ids == expected, (
        f"staging must serve the SDK default models {sorted(expected)}, "
        f"but its catalog lists {sorted(model_ids)}"
    )
