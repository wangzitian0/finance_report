"""Staging AI provider connectivity smoke tests."""

from __future__ import annotations

import os

from playwright.async_api import Page
import pytest


APP_URL = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")
PROVIDER_CONNECTIVITY_TIMEOUT_MS = int(
    os.getenv("PROVIDER_CONNECTIVITY_TIMEOUT_MS", "90000")
)


def _api_url(path: str) -> str:
    return f"{APP_URL}/api{path}"


@pytest.mark.e2e
@pytest.mark.critical
@pytest.mark.llm
async def test_staging_ai_provider_chat_connectivity(
    authenticated_page_unique: Page,
) -> None:
    """EPIC-006 EPIC-008 / AC8.13.120: one real AI provider chat round trip."""
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
