"""Staging AI provider connectivity smoke tests."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

from playwright.async_api import Page
import pytest


APP_URL = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")
PROVIDER_CONNECTIVITY_TIMEOUT_MS = int(
    os.getenv("PROVIDER_CONNECTIVITY_TIMEOUT_MS", "90000")
)


def _api_url(path: str) -> str:
    return f"{APP_URL}/api{path}"


def _approved_model_ids() -> frozenset[str]:
    policy = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "backend"
        / "src"
        / "llm"
        / "model_policy.py"
    )
    spec = importlib.util.spec_from_file_location("model_policy", policy)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.APPROVED_MODEL_IDS


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
async def test_deployed_catalog_lists_only_approved_models(
    authenticated_page_unique: Page,
) -> None:
    """EPIC-008 EPIC-023 / AC-llm.approved-models.3: the deployed /api/llm/catalog lists only approved model ids (#2566)."""
    response = await authenticated_page_unique.request.get(_api_url("/llm/catalog"))
    body = await response.text()
    assert response.status == 200, (
        f"model catalog failed: {response.status} {body[:500]}"
    )
    model_ids = {model["id"].split("/")[-1] for model in json.loads(body)["models"]}
    assert model_ids, f"the deployed catalog lists no model: {body[:500]}"
    outside = sorted(model_ids - _approved_model_ids())
    assert outside == [], (
        f"the deployed catalog lists models outside the approved set: {outside}"
    )
