from __future__ import annotations; from typing import Any; from playwright.async_api import Page; from tests.e2e.auth_cookie import build_runner_browser_session
class BenchUiBridge:
    @staticmethod
    async def inject_runner_session_to_browser(page: Page, auth_context: dict[str, Any], app_url: str) -> None: cookie, init_script = build_runner_browser_session(auth_context, app_url); await page.context.add_cookies([cookie]); await page.context.add_init_script(init_script)
