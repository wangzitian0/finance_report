"""Bridge between Bench V2 financial scenario runners and Playwright browser sessions."""

from __future__ import annotations

from typing import Any
from playwright.async_api import Page
from tests.e2e.auth_cookie import build_runner_browser_session


class BenchUiBridge:
    """Injects authenticated user credentials from ScenarioBenchmarkRunner into Playwright Page."""

    @staticmethod
    async def inject_runner_session_to_browser(
        page: Page,
        auth_context: dict[str, Any],
        app_url: str,
    ) -> None:
        """Inject access token and user storage metadata directly into Playwright browser context."""
        cookie, init_script = build_runner_browser_session(auth_context, app_url)

        # 1. Inject HTTP auth cookie
        await page.context.add_cookies([cookie])

        # 2. Inject localStorage credentials for client-side React session bootstrap
        await page.context.add_init_script(init_script)
