"""Tier-3 browser proof that source confirmation cannot invent economic meaning."""

from __future__ import annotations

import asyncio
import csv
import os
import re
from pathlib import Path

import pytest
from common.testing.ac_proof import ac_proof
from playwright.async_api import Page, expect

APP_URL: str = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT_MS: int = int(os.getenv("PARSING_TIMEOUT_MS", "120000"))
FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "vision_hard_gate_statement.csv"
)
INSTITUTION_LABEL = "Generic Vision Hard Gate"


def _get_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}{path}"


def _require_fixture_path() -> Path:
    if not FIXTURE_PATH.exists():
        pytest.skip(f"Deterministic vision fixture missing: {FIXTURE_PATH}")
    return FIXTURE_PATH


def _fixture_transaction_count() -> int:
    with _require_fixture_path().open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


async def _wait_for_statement_status(
    page: Page, statement_id: str, target_status: str
) -> dict:
    deadline = asyncio.get_running_loop().time() + PARSING_TIMEOUT_MS / 1000
    last_statement: dict | None = None
    while asyncio.get_running_loop().time() < deadline:
        response = await page.request.get(_get_url(f"/api/statements/{statement_id}"))
        body = await response.text()
        assert response.status == 200, body
        last_statement = await response.json()
        if last_statement.get("status") == target_status:
            return last_statement
        await page.wait_for_timeout(1_000)
    pytest.fail(
        f"statement {statement_id} never reached {target_status!r} within {PARSING_TIMEOUT_MS}ms; "
        f"last payload: {last_statement}"
    )


@ac_proof(
    "deterministic-source-review-boundary",
    ac_ids=["AC-testing.product-gates.2"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    trust_mode="hybrid",
    source_classes=["bank_statement", "csv_export"],
    issue="#950",
    required_markers=["e2e", "tier3", "critical"],
)
@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
async def test_statement_upload_to_dashboard_vision_hard_gate(
    authenticated_page_unique: Page,
) -> None:
    """AC-testing.product-gates.2: EPIC-003 EPIC-008 EPIC-013 EPIC-016; parsed CSV facts without authority remain in review."""
    page = authenticated_page_unique
    fixture_path = _require_fixture_path()

    await page.goto(_get_url("/statements"), wait_until="domcontentloaded")
    csv_section = page.locator("details").filter(has_text="CSV import")
    await csv_section.locator("summary").click()
    await csv_section.locator('[data-testid="uploader-institution-csv"]').fill(
        INSTITUTION_LABEL
    )
    await page.set_input_files('[data-testid="uploader-file-csv"]', str(fixture_path))
    await expect(
        csv_section.locator("p.font-medium", has_text=fixture_path.name)
    ).to_be_visible(timeout=10_000)

    async with page.expect_response(
        lambda response: "/api/statements/upload" in response.url
    ) as upload_info:
        await csv_section.get_by_role("button", name="Upload & Parse Statement").click()
    upload_response = await upload_info.value
    upload_body = await upload_response.json()
    assert upload_response.status == 202, upload_body
    statement_id = upload_body["id"]

    statement_link = page.locator(f'a[href="/statements/{statement_id}"]')
    await expect(statement_link).to_be_visible(timeout=15_000)
    parsed_statement = await _wait_for_statement_status(page, statement_id, "parsed")
    assert (
        len(parsed_statement.get("transactions") or []) == _fixture_transaction_count()
    )

    review_path = f"/statements/{statement_id}/review"
    await statement_link.click()
    review_link = page.locator(f"a[href='{review_path}']")
    await expect(review_link).to_be_visible(timeout=10_000)
    await review_link.click()
    await expect(page).to_have_url(
        re.compile(r"/statements/[^/]+/review$"), timeout=15_000
    )

    approve_button = page.get_by_role("button", name="Approve", exact=True)
    await expect(approve_button).to_be_enabled(timeout=20_000)
    async with page.expect_response(
        lambda response: f"/api/statements/{statement_id}/review/approve"
        in response.url
    ) as approve_info:
        await approve_button.click()
        dialog = page.locator('[role="dialog"]')
        await expect(dialog).to_be_visible(timeout=5_000)
        await dialog.get_by_role("button", name="Approve").click()
    approve_response = await approve_info.value
    approve_body = await approve_response.json()
    assert approve_response.status == 409, approve_body
    assert approve_body["detail"] == "Economic review required: intent_missing"

    await expect(page).to_have_url(
        re.compile(r"/statements/[^/]+/review$"), timeout=15_000
    )
    await expect(
        page.get_by_text(
            "Economic classification needs review before entries can be posted."
        )
    ).to_be_visible(timeout=15_000)

    reviewed_statement = await _wait_for_statement_status(page, statement_id, "parsed")
    assert reviewed_statement["stage1_status"] == "pending_review"
    assert (
        reviewed_statement["validation_error"]
        == "Economic review required: intent_missing"
    )

    journal_response = await page.request.get(_get_url("/api/journal-entries?limit=10"))
    journal_body = await journal_response.json()
    assert journal_response.status == 200, journal_body
    assert journal_body["total"] == 0
