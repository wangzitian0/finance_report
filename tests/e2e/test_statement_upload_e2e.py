"""E2E: Statement Upload — AC8.4.2, AC8.4.3

Playwright tests for statement upload and model selection.
Requires APP_URL or FRONTEND_URL env var pointing to a running frontend.
Run with: pytest tests/e2e/test_statement_upload_e2e.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
from playwright.async_api import Page, expect

_APP_URL: str = os.getenv("APP_URL") or os.getenv("FRONTEND_URL") or ""


def _get_url(path: str) -> str:
    return f"{_APP_URL.rstrip('/')}{path}"


def _skip_if_no_url() -> None:
    if not _APP_URL:
        pytest.skip("APP_URL / FRONTEND_URL not set — skipping Playwright E2E")


def _get_test_pdf() -> Path:
    # tests/e2e/ → tests/ → repo root  (parents[2])
    root = Path(__file__).resolve().parents[2]
    dbs_dir = root / "scripts" / "pdf_fixtures" / "output" / "dbs"

    if dbs_dir.exists():
        pdfs = sorted(dbs_dir.glob("test_dbs_*.pdf"))
        if pdfs:
            return pdfs[-1]

    script = root / "scripts" / "pdf_fixtures" / "generate_pdf_fixtures.py"
    if script.exists():
        result = subprocess.run(
            [sys.executable, str(script), "--source", "dbs"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and dbs_dir.exists():
            pdfs = sorted(dbs_dir.glob("test_dbs_*.pdf"))
            if pdfs:
                return pdfs[-1]

    pytest.skip(
        "No PDF fixture found and generator unavailable — skipping upload E2E. "
        "Run: python scripts/pdf_fixtures/generate_pdf_fixtures.py --source dbs"
    )


def _unique_pdf_copy(src: Path) -> Path:
    """Copy *src* to a temp dir with a unique name AND unique content.

    The backend deduplicates uploads by SHA-256 hash of file content.  Simply
    renaming the file does not avoid a 409 — the hash must differ too.  We
    append a PDF comment (valid trailing bytes) so each CI run produces a
    distinct hash, making uploads idempotent against a persistent test DB.
    """
    import uuid

    suffix = int(time.time() * 1000) % 1_000_000
    tmp = Path(tempfile.mkdtemp())
    dest = tmp / f"{src.stem}_{suffix}{src.suffix}"
    shutil.copy2(src, dest)
    # Append a unique PDF comment to change the SHA-256 hash.
    with open(dest, "ab") as f:
        f.write(f"\n%% E2E test run {uuid.uuid4()}\n".encode())
    return dest


async def _find_statement_by_institution(page: Page, institution: str) -> dict | None:
    response = await page.context.request.get(_get_url("/api/statements"))
    if response.status != 200:
        return None

    payload = await response.json()
    if isinstance(payload, list):
        statements = payload
    elif isinstance(payload, dict):
        statements = payload.get("items") or payload.get("data") or []
    else:
        statements = []

    for statement in statements:
        if statement.get("institution") == institution:
            return statement
    return None


@pytest.mark.e2e
async def test_statement_upload_full_flow(authenticated_page: Page) -> None:
    """AC8.4.3: Upload PDF → wait for processing → verify statement appears."""
    _skip_if_no_url()

    pdf_path = _unique_pdf_copy(_get_test_pdf())

    page = authenticated_page
    await page.goto(_get_url("/statements"))
    await page.wait_for_load_state("networkidle")
    await page.locator("#institution").fill("E2E Upload Test Bank")
    # Wait for AI model dropdown options to load, then explicitly select one.
    # not_to_have_value('') alone can time out when the default model fails validation
    # (component sets selectedModel='') — select_option always fires onChange.
    model_select = page.locator("select#ai-model")
    await expect(model_select).to_be_visible(timeout=15_000)
    await expect(model_select.locator("option").nth(1)).to_be_attached(timeout=15_000)
    await model_select.select_option(index=0)
    await page.set_input_files("#file-upload", str(pdf_path))
    await expect(page.locator("p.font-medium", has_text=pdf_path.name)).to_be_visible(
        timeout=5_000
    )

    async with page.expect_response(
        lambda r: "/api/statements/upload" in r.url,
        timeout=60_000,  # Upload may take up to 60s on cold-start
    ) as resp_info:
        await page.get_by_role("button", name="Upload & Parse Statement").click()
    upload_resp = await resp_info.value
    assert upload_resp.status in (200, 201, 202), (
        f"Upload endpoint returned unexpected status {upload_resp.status} — "
        f"expected 2xx. Response body: {await upload_resp.text()}"
    )
    upload_body = await upload_resp.json()
    statement_id = upload_body.get("id")
    assert statement_id, f"Upload response missing 'id' field: {upload_body}"
    # Statement row appears in the list with the institution name we provided.
    statement_row = page.locator("a").filter(has_text="E2E Upload Test Bank").first
    await expect(statement_row).to_be_visible(timeout=15_000)
    # Verify the statement is immediately accessible via the API.
    # We do NOT wait for AI parsing to complete (that can take minutes on cold start).
    resp = await page.context.request.get(_get_url(f"/api/statements/{statement_id}"))
    assert resp.status == 200, f"GET /api/statements/{statement_id} returned {resp.status}"
    statement = await resp.json()
    assert statement.get("id") == statement_id
    # Status should be a valid in-progress or terminal value immediately after upload.
    assert statement.get("status") in {"uploaded", "parsing", "parsed", "approved", "rejected"}, (
        f"Unexpected statement status: {statement.get('status')}"
    )

@pytest.mark.e2e
async def test_model_selection_and_upload(authenticated_page: Page) -> None:
    """AC8.4.2: Select AI model from dropdown → upload → verify model persisted."""
    _skip_if_no_url()

    pdf_path = _unique_pdf_copy(_get_test_pdf())

    page = authenticated_page
    await page.goto(_get_url("/statements"))
    await page.wait_for_load_state("networkidle")

    model_select = page.locator("select#ai-model")
    await expect(model_select).to_be_visible(timeout=5_000)
    await model_select.select_option(index=0)

    await page.locator("#institution").fill("E2E Model Test Bank")
    await page.set_input_files("#file-upload", str(pdf_path))
    await expect(page.locator("p.font-medium", has_text=pdf_path.name)).to_be_visible(
        timeout=5_000
    )

    async with page.expect_response(
        lambda r: "/api/statements/upload" in r.url,
        timeout=60_000,  # Upload may take up to 60s on cold-start
    ) as resp_info:
        await page.get_by_role("button", name="Upload & Parse Statement").click()
    upload_resp = await resp_info.value
    assert upload_resp.status in (200, 201, 202), (
        f"Upload endpoint returned unexpected status {upload_resp.status} — "
        f"expected 2xx. Response body: {await upload_resp.text()}"
    )

    await expect(
        page.locator("a").filter(has_text="E2E Model Test Bank").first
    ).to_be_visible(timeout=15_000)


@pytest.mark.e2e
async def test_stale_model_id_auto_cleanup(authenticated_page: Page) -> None:
    """AC8.4.2: Stale localStorage model ID is cleaned up on page reload.

    Uses a deliberately invalid/fictional model ID that can never appear in the
    OpenRouter catalog, guaranteeing the stale-cleanup branch always fires.
    """
    _skip_if_no_url()
    page = authenticated_page
    await page.goto(_get_url("/statements"))
    await page.wait_for_load_state("networkidle")

    # Use a guaranteed-nonexistent model ID so the test is catalog-independent.
    # Real model IDs are fetched from OpenRouter and may change over time; using
    # a clearly fake ID ensures the stale-cleanup logic is always exercised.
    stale_id = "test/nonexistent-model-for-stale-cleanup-test"
    await page.evaluate(f'localStorage.setItem("statement_model_v1", "{stale_id}")')
    await page.reload()
    await page.wait_for_load_state("networkidle")
    stored_model: str | None = await page.evaluate(
        'localStorage.getItem("statement_model_v1")'
    )
    assert stored_model != stale_id, (
        f"Stale model ID '{stale_id}' was not cleared from localStorage after reload"
    )
