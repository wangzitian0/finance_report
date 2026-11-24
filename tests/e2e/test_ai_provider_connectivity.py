from __future__ import annotations

import os

import pytest
from playwright.async_api import Page

from tests.e2e._journey_helpers import api_url

PROVIDER_CONNECTIVITY_TIMEOUT_MS = int(
    os.getenv("PROVIDER_CONNECTIVITY_TIMEOUT_MS", "90000")
)


def _sdk_large_model() -> str:
    from infra2_sdk.runtime.llm import LlmSettings

    return LlmSettings().role_model("large")


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
    # Staging pins no model (#2566): the answer comes from the SDK default of the large role.
    answered_by = resp.headers.get("x-model-name")
    assert answered_by == _sdk_large_model(), (
        f"staging must answer with {_sdk_large_model()}, got {answered_by}"
    )
