"""Bridge between Bench V2 financial scenario runners and Playwright browser sessions."""

from __future__ import annotations

import json
from typing import Any
from playwright.async_api import Page
from tests.e2e.auth_cookie import build_auth_cookie


class BenchUiBridge:
    """Injects authenticated user credentials from ScenarioBenchmarkRunner into Playwright Page."""

    @staticmethod
    async def inject_runner_session_to_browser(
        page: Page,
        auth_context: dict[str, Any],
        app_url: str,
    ) -> None:
        """Inject access token and user storage metadata directly into Playwright browser context."""
        user_data = auth_context["user_data"]
        user_email = auth_context["user_email"]
        token = user_data["access_token"]
        user_id = user_data.get("id") or user_data.get("user", {}).get("id")

        # 1. Inject HTTP auth cookie
        await page.context.add_cookies([build_auth_cookie(app_url, token)])

        # 2. Inject localStorage credentials for client-side React session bootstrap
        await page.context.add_init_script(
            f"""
            localStorage.setItem('finance_user_id', {json.dumps(str(user_id))});
            localStorage.setItem('finance_user_email', {json.dumps(user_email)});
        """
        )
