from __future__ import annotations

import json
import os

import httpx
import pytest
from playwright.async_api import Page

from tests.e2e._journey_helpers import api_url

PROVIDER_CONNECTIVITY_TIMEOUT_MS = int(
    os.getenv("PROVIDER_CONNECTIVITY_TIMEOUT_MS", "90000")
)


def _sdk_default_model_ids() -> frozenset[str]:
    from infra2_sdk.runtime.llm import LlmSettings

    sdk = LlmSettings()
    return frozenset(
        m
        for m in (
            sdk.role_model("large"),
            sdk.role_model("small"),
            sdk.role_model("multimodal"),
        )
        if m
    )


@pytest.mark.e2e
@pytest.mark.critical
@pytest.mark.llm
async def test_staging_ai_provider_chat_connectivity(
    authenticated_page_unique: Page,
) -> None:
    resp = await authenticated_page_unique.request.post(
        api_url("/chat"),
        data={
            "message": "In one short sentence, confirm you can answer finance questions."
        },
        timeout=PROVIDER_CONNECTIVITY_TIMEOUT_MS,
    )
    body = await resp.text()
    assert resp.status == 200, (
        f"AI provider chat connectivity failed: {resp.status} {body[:500]}"
    )
    assert body.strip(), "AI provider chat connectivity returned an empty response"


@pytest.mark.e2e
@pytest.mark.critical
@pytest.mark.llm
async def test_staging_catalog_serves_the_sdk_default_models() -> None:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(api_url("/llm/catalog"))
    assert resp.status_code == 200, (
        f"model catalog failed: {resp.status_code} {resp.text[:500]}"
    )
    model_ids = {m["id"].split("/")[-1] for m in json.loads(resp.text)["models"]}
    assert model_ids, f"the deployed catalog lists no model: {resp.text[:500]}"
    expected = _sdk_default_model_ids()
    assert model_ids == expected, (
        f"staging must serve {sorted(expected)}, got {sorted(model_ids)}"
    )
