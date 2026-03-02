"""
Tier 3 Browser E2E: Full Statement Journey — AC8.12.1–AC8.12.5

DBS PDF upload → AI parsing (poll until parsed) → detail page review
→ approve via ConfirmDialog → balance sheet report verification

Requires APP_URL env var pointing to a running frontend+backend.
Run: moon run :test -- --e2e
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from playwright.async_api import Page, expect

APP_URL: str = os.getenv("APP_URL", "http://localhost:3000")

# AI parsing can take up to 2 minutes on a cold start
PARSING_TIMEOUT_MS: int = int(os.getenv("PARSING_TIMEOUT_MS", "120000"))

INSTITUTION_LABEL: str = "DBS E2E Full Journey"


def _get_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}{path}"


def _get_dbs_pdf_path() -> Path:
    """
    Locate (or generate) the pre-built DBS mock PDF fixture.
    Search order:
      1. output/dbs/test_dbs_{YYMM}.pdf   — current-month build
      2. output/dbs/test_dbs_*.pdf        — any prior build
      3. generate_pdf_fixtures.py         — on-the-fly generation
    environments that lack the pdf_fixtures dependencies (reportlab, yaml).
    """
    from datetime import datetime
    root = Path(__file__).resolve().parents[2]
    dbs_dir = root / "scripts" / "pdf_fixtures" / "output" / "dbs"
    yymm = datetime.now().strftime("%y%m")
    prebuilt = dbs_dir / f"test_dbs_{yymm}.pdf"
    if prebuilt.exists():
        return prebuilt
    if dbs_dir.exists():
        pdfs = sorted(dbs_dir.glob("test_dbs_*.pdf"))
        if pdfs:
            return pdfs[-1]

    script = root / "scripts" / "pdf_fixtures" / "generate_pdf_fixtures.py"
    if not script.exists():
        pytest.skip(
            f"PDF fixture generator not found: {script} — skipping full-journey E2E. "
            "Run: python scripts/pdf_fixtures/generate_pdf_fixtures.py --source dbs"
        )
    result = subprocess.run(
        [sys.executable, str(script), "--source", "dbs"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(
            f"PDF fixture generation failed (missing deps?) — skipping full-journey E2E.\n"
            f"{result.stdout}\n{result.stderr}"
        )
    pdfs = sorted(dbs_dir.glob("test_dbs_*.pdf")) if dbs_dir.exists() else []
    if not pdfs:
        pytest.skip(
            f"PDF generation script exited 0 but produced no output in {dbs_dir} — skipping."
        )
    return pdfs[-1]


@pytest.mark.e2e
@pytest.mark.tier3
async def test_dbs_statement_full_journey(authenticated_page: Page) -> None:
    """AC8.12.1–AC8.12.5: DBS PDF → parse → approve → balance sheet."""
    page = authenticated_page
    pdf_path = _get_dbs_pdf_path()

    # === AC8.12.1: Upload PDF ===
    await page.goto(_get_url("/statements"))
    await page.wait_for_load_state("networkidle")

    if "/login" in page.url:
        pytest.fail(
            f"Redirected to /login despite authenticated_page fixture. URL: {page.url}"
        )

    await page.locator("#institution").fill(INSTITUTION_LABEL)
    await page.set_input_files("#file-upload", str(pdf_path))
    await expect(page.get_by_text(pdf_path.name)).to_be_visible(timeout=5_000)

    async with page.expect_response(
        lambda r: "/api/statements/upload" in r.url,
        timeout=120_000,  # Upload + AI model validation may take up to 120s on cold-start
    ) as resp_info:
        await page.get_by_role("button", name="Upload & Parse Statement").click()
    upload_resp = await resp_info.value
    assert upload_resp.status in (200, 201, 202), (
        f"Upload endpoint returned unexpected status {upload_resp.status} — "
        f"expected 2xx. Response body: {await upload_resp.text()}"
    )

    # === AC8.12.2: Poll until "parsed" status badge appears in the list ===
    # The list page polls via TanStack Query every 3 s — we wait up to PARSING_TIMEOUT_MS.
    statement_row = page.locator("a").filter(has_text=INSTITUTION_LABEL).first
    await expect(statement_row).to_be_visible(timeout=15_000)

    parsed_badge = (
        page.locator("a")
        .filter(has_text=INSTITUTION_LABEL)
        .locator("span.badge", has_text="parsed")
    )
    await expect(parsed_badge).to_be_visible(timeout=PARSING_TIMEOUT_MS)

    # === AC8.12.3: Detail page shows transactions ===
    await statement_row.click()
    await page.wait_for_load_state("networkidle")

    assert "/statements/" in page.url, (
        f"Expected statement detail page, got: {page.url}"
    )

    await expect(page.locator("span.badge", has_text="parsed")).to_be_visible(
        timeout=15_000
    )
    await expect(page.get_by_text("Transactions", exact=False)).to_be_visible(
        timeout=10_000
    )
    await expect(page.locator("table tbody tr").first).to_be_visible(timeout=10_000)

    # === AC8.12.4: Approve via ConfirmDialog → badge changes to "approved" ===
    await page.get_by_role("button", name="Approve").click()
    dialog = page.locator('[role="dialog"]')
    await expect(dialog).to_be_visible(timeout=5_000)
    confirm_button = dialog.get_by_role("button", name="Approve")
    await expect(confirm_button).to_be_visible(timeout=3_000)
    await confirm_button.click()
    # After approve the frontend calls fetchStatement() and stays on /statements/{id}.
    # There is NO router.push redirect — the badge updates in-place.
    await expect(page.locator("span.badge", has_text="approved")).to_be_visible(
        timeout=15_000
    )
    assert "/statements/" in page.url, (
        f"Expected to remain on statement detail page after approve, got: {page.url}"
    )

    # === AC8.12.5: Balance sheet report loads ===
    await page.goto(_get_url("/reports/balance-sheet"))
    await page.wait_for_load_state("networkidle")

    await expect(page.get_by_text("Balance Sheet", exact=False).first).to_be_visible(
        timeout=10_000
    )
    await expect(page.get_by_text("Assets", exact=False).first).to_be_visible(
        timeout=10_000
    )
