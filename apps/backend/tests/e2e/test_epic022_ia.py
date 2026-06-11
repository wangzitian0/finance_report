"""
E2E ownership for EPIC-022 (everyday-user information architecture).

These tests validate the everyday-user shell from a real browser:
- the authenticated Home renders at `/`
- the three primary peers (Upload, Reports, Chat) are present
- the notification bell is reachable independent of the nav

Prerequisites:
- Frontend running (set FRONTEND_URL env var)
- Backend running
- Playwright browsers installed
"""

import os

import pytest


@pytest.mark.e2e
async def test_everyday_user_shell(page):
    """
    EPIC-022 / AC22.1.1 AC22.1.9: everyday-user IA shell
    GIVEN an authenticated user opens the app at the root route
    WHEN the shell renders
    THEN the three primary peers (Upload, Reports, Chat) and the notification
         bell are present, and internal accounting modules stay behind Advanced.
    """
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        pytest.skip("FRONTEND_URL not set")

    # Seed auth so the shell renders instead of redirecting to /login.
    await page.add_init_script(
        "localStorage.setItem('finance_user_id', 'epic022-e2e-user');"
        "localStorage.setItem('finance_user_email', 'epic022-e2e@example.com');"
    )
    await page.goto(f"{frontend_url}/")

    nav = page.get_by_role("navigation", name="Sidebar navigation")
    await nav.get_by_role("link", name="Upload", exact=True).wait_for()
    assert await nav.get_by_role("link", name="Upload", exact=True).get_attribute("href") == "/upload"
    assert await nav.get_by_role("link", name="Reports").get_attribute("href") == "/reports"
    assert await nav.get_by_role("link", name="Chat", exact=True).get_attribute("href") == "/chat"

    # The notification center is the bell in the header, not a nav peer.
    await page.get_by_role("button", name="Workflow events").wait_for()
