'EPIC-022'; from __future__ import annotations; import os; import pytest; from playwright.async_api import Page; APP_URL = os.getenv('APP_URL', 'http://localhost:3000'); get_url = lambda path: f"{APP_URL.rstrip('/')}{path}"
@pytest.mark.e2e
async def test_everyday_user_shell(authenticated_page: Page):
    'AC22.1.1 AC22.1.9 EPIC-022'; page = authenticated_page; await page.goto(get_url('/'), wait_until='domcontentloaded'); nav = page.get_by_role('navigation', name='Sidebar navigation'); await nav.get_by_role('link', name='Home', exact=True).wait_for()
    for target in ('Chat', 'Audit', 'More'): assert await nav.get_by_role('link', name=target, exact=True).is_visible(), f'sidebar target missing: {target}'
    assert await nav.get_by_role('button', name='Add').is_visible(); await page.get_by_role('button', name='Workflow events').wait_for(); assert await nav.get_by_role('link', name='Journal').count() == 0
