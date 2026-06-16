"""EPIC-024 frontend browser observability E2E smoke.

Product-level proof of the browser-telemetry contract: the app loads and runs
even when no OTLP endpoint is configured (the SDK is a complete no-op until
``NEXT_PUBLIC_OTEL_EXPORTER_OTLP_ENDPOINT`` is set), and the telemetry mount
never throws an uncaught error into page load.
"""

from __future__ import annotations

from playwright.async_api import Page
import pytest


@pytest.mark.e2e
@pytest.mark.smoke
@pytest.mark.prod_safe
async def test_frontend_loads_without_uncaught_errors_epic024(page: Page) -> None:
    """EPIC-024 / AC24.1.1: the app loads with the browser-telemetry mount as a
    no-op (no configured OTLP endpoint) and raises no uncaught page error."""
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    response = await page.goto("/", wait_until="domcontentloaded")

    assert response is not None, "navigation to / returned no response"
    assert response.status < 500, f"app root returned a server error: {response.status}"
    # The FrontendTelemetry mount runs on load; a no-op SDK must not throw.
    assert not page_errors, f"uncaught page error(s) during load: {page_errors}"
