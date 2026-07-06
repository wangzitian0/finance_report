"""Product E2E owner for EPIC-022 (everyday-user information architecture).

Relocated from ``apps/backend/tests/e2e/test_epic022_ia.py``, where it was
dead: the backend catch-all classified it ``backend_ci`` whose marker
(``not e2e``) deselected it, and the Tier-1 API lane has no frontend. The
in-runner preview stack (``preview.yml`` + ``docker-compose.ci-e2e.yml``)
serves the real frontend behind the nginx edge, so the shell proof runs
merge-blocking there instead of never.

The everyday-user shell from a real authenticated browser:
- the authenticated Home renders at ``/``
- the three primary peers (Upload, Reports, Chat) are present
- the notification bell is reachable independent of the nav
"""

from __future__ import annotations

import os

import pytest
from playwright.async_api import Page

APP_URL = os.getenv("APP_URL", "http://localhost:3000")


def get_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}{path}"


@pytest.mark.e2e
async def test_everyday_user_shell(authenticated_page: Page):
    """EPIC-022 / AC22.1.1 AC22.1.9: everyday-user IA shell.

    GIVEN an authenticated user opens the app at the root route
    WHEN the shell renders
    THEN the three primary peers (Upload, Reports, Chat) and the notification
         bell are present, and their hrefs point at the everyday routes.
    """
    page = authenticated_page
    await page.goto(get_url("/"), wait_until="domcontentloaded")

    nav = page.get_by_role("navigation", name="Sidebar navigation")
    await nav.get_by_role("link", name="Upload", exact=True).wait_for()
    assert await nav.get_by_role("link", name="Upload", exact=True).get_attribute("href") == "/upload"
    assert await nav.get_by_role("link", name="Reports").get_attribute("href") == "/reports"
    assert await nav.get_by_role("link", name="Chat", exact=True).get_attribute("href") == "/chat"

    # The notification center is the bell in the header, not a nav peer.
    await page.get_by_role("button", name="Workflow events").wait_for()
