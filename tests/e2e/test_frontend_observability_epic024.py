'EPIC-024'; from __future__ import annotations; from playwright.async_api import Page; import pytest
@pytest.mark.e2e
@pytest.mark.smoke
@pytest.mark.prod_safe
async def test_frontend_loads_without_uncaught_errors_epic024(page: Page) -> None: 'AC24.1.1 EPIC-024'; page_errors: list[str] = []; page.on('pageerror', lambda exc: page_errors.append(str(exc))); response = await page.goto('/', wait_until='domcontentloaded'); assert response is not None, 'navigation to / returned no response'; assert response.status < 500, f'app root returned a server error: {response.status}'; assert not page_errors, f'uncaught page error(s) during load: {page_errors}'
