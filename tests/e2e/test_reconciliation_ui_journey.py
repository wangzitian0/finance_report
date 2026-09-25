"""End-to-End interactive browser journey tests for Reconciliation (/reconciliation).

Covers:
- AC-reconciliation.workbench.1: Workbench review queue and match statistics.
- AC-reconciliation.review-queue.1: Confidence tiers and disposition workflow.
- AC8.13.9: Authenticated UI route verification.
"""

from __future__ import annotations

import os
import pytest
from playwright.async_api import Page, expect

from tests.e2e.conftest import TestConfig

APP_URL: str = os.getenv("APP_URL", TestConfig.APP_URL)


@pytest.mark.e2e
async def test_reconciliation_workbench_surface_and_navigation(
    authenticated_page: Page,
):
    """EPIC-007 EPIC-008 / AC-reconciliation.workbench.1 AC8.13.9: Reconciliation workbench layout and studio navigation."""
    page = authenticated_page
    await page.goto(f"{APP_URL}/reconciliation", wait_until="domcontentloaded")
    assert "/login" not in page.url

    # 1. Assert workbench heading and analytics
    await expect(
        page.get_by_role("heading", name="Reconciliation Workbench", exact=True)
    ).to_be_visible(timeout=15_000)
    await expect(page.get_by_text("Match Rate")).to_be_visible(timeout=10_000)
    await expect(
        page.get_by_role("heading", name="Score Distribution", exact=True)
    ).to_be_visible(timeout=10_000)

    # 2. Navigate to Unmatched Transactions Studio
    await page.get_by_role("link", name="Unmatched Studio").click()
    await expect(
        page.get_by_role("heading", name="Unmatched Transactions", exact=True)
    ).to_be_visible(timeout=15_000)

    # 3. Return to Workbench
    await page.get_by_role("link", name="← Workbench").click()
    await expect(
        page.get_by_role("heading", name="Reconciliation Workbench", exact=True)
    ).to_be_visible(timeout=15_000)


@pytest.mark.e2e
async def test_reconciliation_review_queue_surface(authenticated_page: Page):
    """EPIC-007 EPIC-008 / AC-reconciliation.review-queue.1 AC8.13.9: Reconciliation dedicated review queue."""
    page = authenticated_page
    await page.goto(
        f"{APP_URL}/reconciliation/review-queue", wait_until="domcontentloaded"
    )
    assert "/login" not in page.url

    await expect(
        page.get_by_role("heading", name="Review Queue", exact=True)
    ).to_be_visible(timeout=15_000)
    await expect(page.locator("body")).to_be_visible()
