from __future__ import annotations

import os

import pytest
from playwright.async_api import Page

from tests.e2e._journey_helpers import api_url

PROVIDER_CONNECTIVITY_TIMEOUT_MS = int(
    os.getenv("PROVIDER_CONNECTIVITY_TIMEOUT_MS", "90000")
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
