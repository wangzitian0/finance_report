from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
from playwright.async_api import Page, expect

from tests.e2e._journey_helpers import (
    get_url,
    poll_statement_via_page,
    upload_statement_via_ui,
)

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "csv_envelope_hard_gate_statement.csv"


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
async def test_statement_upload_to_dashboard_vision_hard_gate(
    authenticated_page_unique: Page,
) -> None:
    page = authenticated_page_unique
    if not FIXTURE_PATH.exists():
        pytest.skip(f"Deterministic vision fixture missing: {FIXTURE_PATH}")
    with FIXTURE_PATH.open(newline="", encoding="utf-8") as fh:
        expected_count = sum(1 for _ in csv.DictReader(fh))
    assert (
        await page.request.patch(get_url("/api/users/me/settings"), data={"enable_ai_classification": False})
    ).status == 200

    statement_id = await upload_statement_via_ui(
        page,
        institution="Generic Vision Hard Gate",
        file_path=FIXTURE_PATH,
        csv_mode=True,
    )
    statement_link = page.locator(f'a[href="/statements/{statement_id}"]').filter(has_text=FIXTURE_PATH.name)
    await expect(statement_link).to_be_visible(timeout=15000)
    parsed = await poll_statement_via_page(
        page, statement_id, timeout_ms=120000, poll_ms=1000, target_statuses=("parsed",)
    )
    assert len(parsed.get("transactions") or []) == expected_count

    await statement_link.click()
    await expect(page).to_have_url(re.compile(f"/statements/{re.escape(statement_id)}$"), timeout=15000)
    approve_btn = page.get_by_role("button", name="Approve", exact=True)
    await expect(approve_btn).to_be_disabled(timeout=15000)
    acc_resp = await page.request.post(
        get_url("/api/accounts"),
        data={"name": "Generated CSV custody", "type": "ASSET", "currency": "SGD"},
    )
    assert acc_resp.status == 201
    acc_id = (await acc_resp.json())["id"]
    await page.reload(wait_until="domcontentloaded")
    await page.get_by_label("Custody account").select_option(acc_id)
    for label, value in (
        ("Statement currency", "SGD"),
        ("Period start", "2026-05-01"),
        ("Period end", "2026-05-31"),
        ("Opening balance", "0.00"),
        ("Closing balance", "0.00"),
        (
            "Why are these facts confirmed?",
            "Confirmed against the generated CSV header and its six transactions.",
        ),
    ):
        await page.get_by_label(label, exact=True).fill(value)
    async with page.expect_response(lambda r: f"/api/statements/{statement_id}/review-envelopes" in r.url) as env_info:
        await page.get_by_role("button", name="Confirm statement details").click()
    assert (await env_info.value).status == 200
    await expect(approve_btn).to_be_enabled(timeout=20000)
    await expect(page.get_by_text("Transaction classifications need review")).to_be_visible(timeout=15000)
    async with page.expect_response(lambda r: f"/api/statements/{statement_id}/approvals" in r.url) as approve_info:
        await approve_btn.click()
        dialog = page.locator('[role="dialog"]')
        await expect(dialog).to_be_visible(timeout=5000)
        await expect(dialog).to_contain_text("filed under default categories")
        await dialog.get_by_role("button", name="Approve").click()
    assert (await approve_info.value).status == 200

    reviewed = await (await page.request.get(get_url(f"/api/statements/{statement_id}/review"))).json()
    assert reviewed["status"] == "approved" and reviewed["stage1_status"] == "approved"
    assert (await (await page.request.get(get_url("/api/journal-entries?limit=10"))).json())["total"] > 0
