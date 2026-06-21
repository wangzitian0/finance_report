"""E2E test configuration and fixtures.

Hosts the Playwright browser fixtures (``browser`` / ``context`` / ``page``) and
the API-tier ``seeded_parsed_statement`` fixture used by the non-Playwright,
no-LLM statement journeys (EPIC-008 / AC8.21). The reusable seeding helper and
its ``SeededParsedStatement`` handle live in :mod:`tests.factories` so tests can
import them without depending on ``conftest``.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import SeededParsedStatement, seed_parsed_statement


@pytest_asyncio.fixture(scope="function")
async def seeded_parsed_statement(db: AsyncSession, test_user) -> SeededParsedStatement:
    """Fixture-seeded, already-parsed statement that bypasses the LLM/OCR provider.

    Enables the no-LLM merge-blocking tier (``-m "... and not llm"``) to run the
    statement review -> reconcile -> report journeys that previously required a
    real provider. See :func:`tests.factories.seed_parsed_statement`.
    """
    return await seed_parsed_statement(db, test_user.id)


@pytest_asyncio.fixture(scope="session")
async def browser() -> AsyncIterator[Browser]:
    """Launch browser instance for the test session."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest_asyncio.fixture(scope="function")
async def context(browser: Browser) -> AsyncIterator[BrowserContext]:
    """Create a new browser context for each test."""
    context = await browser.new_context()
    yield context
    await context.close()


@pytest_asyncio.fixture(scope="function")
async def page(context: BrowserContext) -> AsyncIterator[Page]:
    """Create a new page for each test."""
    page = await context.new_page()
    yield page
    await page.close()
