"""E2E test configuration and fixtures for Playwright tests."""

from collections.abc import AsyncIterator

import pytest_asyncio
from playwright.async_api import Browser, BrowserContext, Page, async_playwright


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
