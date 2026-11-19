from __future__ import annotations

import pytest
from playwright.async_api import Page

from tests.e2e._journey_helpers import get_url


@pytest.mark.e2e
async def test_everyday_user_shell(authenticated_page: Page) -> None:
    page = authenticated_page
    await page.goto(get_url("/"), wait_until="domcontentloaded")
    nav = page.get_by_role("navigation", name="Sidebar navigation")
    await nav.get_by_role("link", name="Home", exact=True).wait_for()
    for target in ("Chat", "Audit", "More"):
        assert await nav.get_by_role("link", name=target, exact=True).is_visible(), (
            f"sidebar target missing: {target}"
        )
    assert await nav.get_by_role("button", name="Add").is_visible()
    await page.get_by_role("button", name="Workflow events").wait_for()
    assert await nav.get_by_role("link", name="Journal").count() == 0
