from __future__ import annotations

import os

import pytest
from playwright.async_api import Page, expect

from tests.e2e._journey_helpers import get_url, unique_pdf_copy, upload_statement_via_ui
from tests.e2e.conftest import fail_or_skip_ai_ocr_gate, is_strict_or_ci
from tests.e2e.pdf_fixture_paths import generated_pdf_path

_APP_URL = os.getenv("APP_URL") or os.getenv("FRONTEND_URL") or ""


def _skip_if_no_url() -> None:
    if not _APP_URL:
        if is_strict_or_ci():
            pytest.fail(
                "Fatal: APP_URL or FRONTEND_URL must be explicitly provided in CI / strict gates"
            )
        pytest.skip("APP_URL / FRONTEND_URL not set — skipping Playwright E2E")


@pytest.mark.e2e
@pytest.mark.llm
async def test_statement_upload_full_flow(authenticated_page_unique: Page) -> None:
    _skip_if_no_url()
    page = authenticated_page_unique
    statement_id = await upload_statement_via_ui(
        page,
        institution="E2E Upload Test Bank",
        file_path=unique_pdf_copy(generated_pdf_path("dbs")),
        base_url=_APP_URL,
    )
    await expect(
        page.locator(".relative.block").filter(has_text="E2E Upload Test Bank").first
    ).to_be_visible(timeout=15000)
    api_resp = await page.request.get(
        get_url(f"/api/statements/{statement_id}", _APP_URL)
    )
    assert api_resp.status == 200
    statement = await api_resp.json()
    status = statement.get("status")
    if status == "rejected":
        fail_or_skip_ai_ocr_gate(
            "Statement upload returned status=rejected", statement=statement
        )
    assert statement.get("id") == statement_id and status in {
        "uploaded",
        "parsing",
        "parsed",
        "approved",
    }


@pytest.mark.e2e
@pytest.mark.llm
async def test_model_selection_and_upload(authenticated_page_unique: Page) -> None:
    _skip_if_no_url()
    page = authenticated_page_unique
    statement_id = await upload_statement_via_ui(
        page,
        institution="E2E Model Test Bank",
        file_path=unique_pdf_copy(generated_pdf_path("dbs")),
        base_url=_APP_URL,
    )
    await expect(
        page.locator(".relative.block").filter(has_text="E2E Model Test Bank").first
    ).to_be_visible(timeout=15000)
    resp = await page.context.request.get(get_url("/api/statements", _APP_URL))
    assert resp.status == 200
    payload = await resp.json()
    items = (
        payload
        if isinstance(payload, list)
        else payload.get("items") or payload.get("data") or []
    )
    assert (
        next(
            (s for s in items if s.get("institution") == "E2E Model Test Bank"), {}
        ).get("id")
        == statement_id
    )


@pytest.mark.e2e
async def test_stale_model_id_auto_cleanup(authenticated_page_unique: Page) -> None:
    _skip_if_no_url()
    page = authenticated_page_unique
    await page.goto(get_url("/upload", _APP_URL), wait_until="domcontentloaded")
    await expect(
        page.locator('[data-testid="uploader-model-statement"]')
    ).to_be_visible(timeout=15000)
    stale_id = "test/nonexistent-model-for-stale-cleanup-test"
    await page.evaluate(f'localStorage.setItem("statement_model_v1", "{stale_id}")')
    await page.reload(wait_until="domcontentloaded")
    await expect(
        page.locator('[data-testid="uploader-model-statement"]')
    ).to_be_visible(timeout=15000)
    await page.wait_for_function(
        "(staleId) => localStorage.getItem('statement_model_v1') !== staleId",
        arg=stale_id,
        timeout=15000,
    )
    assert await page.evaluate('localStorage.getItem("statement_model_v1")') != stale_id
