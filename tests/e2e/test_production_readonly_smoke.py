"""Production-safe browser/API smoke checks.

These tests must not mutate production data. Authenticated checks run only when
dedicated read-only smoke credentials are configured.
"""

from __future__ import annotations

import os
import re

import httpx
import pytest
from playwright.async_api import Page, expect

from conftest import TestConfig


@pytest.mark.e2e
@pytest.mark.smoke
@pytest.mark.prod_safe
async def test_AC8_13_9_production_public_runtime_contract() -> None:
    """AC-testing.deploy-gates.1: EPIC-007 EPIC-008 EPIC-010 EPIC-012 / AC8.13.9: Public runtime smoke."""
    app_url = TestConfig.APP_URL.rstrip("/")

    async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
        health = await client.get(f"{app_url}/api/health")
        assert health.status_code == 200, health.text
        payload = health.json()
        assert payload.get("status") == "healthy"
        assert payload.get("git_sha"), "Health payload must include deployed git_sha"

        protected = await client.get(f"{app_url}/api/statements")
        assert protected.status_code in {401, 429}, (
            "Protected statements API must reject anonymous production requests, "
            f"got {protected.status_code}: {protected.text}"
        )


@pytest.mark.e2e
@pytest.mark.smoke
@pytest.mark.prod_safe
async def test_AC8_13_9_production_browser_readonly_shell(page: Page) -> None:
    """EPIC-001 EPIC-007 EPIC-008 EPIC-016 / AC8.13.9: Browser shell smoke."""
    app_url = TestConfig.APP_URL.rstrip("/")

    await page.goto(app_url, wait_until="domcontentloaded")
    await expect(page).to_have_url(re.compile(r"/(dashboard|login)?$"), timeout=15_000)

    await page.goto(f"{app_url}/login", wait_until="domcontentloaded")
    await expect(page.locator("input[type='email']")).to_be_visible(timeout=10_000)
    await expect(page.locator("input[type='password']")).to_be_visible(timeout=10_000)

    await page.goto(f"{app_url}/dashboard", wait_until="domcontentloaded")
    await expect(page).to_have_url(re.compile(r"/login"), timeout=15_000)


@pytest.mark.e2e
@pytest.mark.smoke
@pytest.mark.prod_safe
async def test_AC8_13_9_production_authenticated_readonly_when_configured(
    page: Page,
) -> None:
    """EPIC-001 EPIC-007 EPIC-008 EPIC-016 / AC8.13.9: Read-only auth smoke."""
    email = os.getenv("PROD_SMOKE_EMAIL")
    password = os.getenv("PROD_SMOKE_PASSWORD")
    if not email or not password:
        pytest.skip("PROD_SMOKE_EMAIL/PROD_SMOKE_PASSWORD not configured")

    app_url = TestConfig.APP_URL.rstrip("/")
    await page.goto(f"{app_url}/login", wait_until="domcontentloaded")
    await page.locator("input[type='email']").fill(email)
    await page.locator("input[type='password']").fill(password)
    await page.get_by_role(
        "button", name=re.compile("login|log in|sign in", re.I)
    ).click()

    await expect(page).to_have_url(re.compile(r"/dashboard"), timeout=15_000)
    await expect(page.locator("body")).to_contain_text(
        re.compile("dashboard", re.I), timeout=15_000
    )
