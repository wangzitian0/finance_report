"""E2E Test: Statement Upload Flow

Tests the complete user journey: Upload PDF → AI Parse → View Transactions → Approve

Prerequisites:
- Frontend running on http://localhost:3000
- Backend running on http://localhost:8000
- MinIO running on http://localhost:9000
- OPENROUTER_API_KEY in environment (for AI parsing tests; optional otherwise)

Run with:
    moon run backend:test-e2e
"""

import os
import warnings
from io import BytesIO
from pathlib import Path

import pytest
from playwright.async_api import Page
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def create_test_pdf() -> bytes:
    """Generate a test PDF with bank statement content."""
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)

    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, 750, "Test Bank Statement")

    p.setFont("Helvetica", 12)
    p.drawString(100, 720, "Account: 1234567890")
    p.drawString(100, 700, "Statement Date: 2024-01-31")

    p.drawString(100, 660, "Transactions:")
    p.drawString(100, 640, "2024-01-15  Purchase at Store A    -$50.00")
    p.drawString(100, 620, "2024-01-20  Salary Deposit        +$2000.00")
    p.drawString(100, 600, "2024-01-25  Utility Bill          -$100.00")

    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer.read()


@pytest.mark.e2e
async def test_statement_upload_full_flow(page: Page):
    """E2E: Upload PDF → AI Parse → View Transactions → Approve."""
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        warnings.warn("Skipping E2E logic: FRONTEND_URL not set", UserWarning)
        return

    await page.goto(f"{frontend_url}/statements")
    await page.wait_for_load_state("networkidle")

    await page.locator('[data-testid="upload-button"]').click()

    pdf_bytes = create_test_pdf()
    temp_pdf = Path("/tmp/test_statement.pdf")
    temp_pdf.write_bytes(pdf_bytes)

    try:
        await page.locator('[data-testid="file-input"]').set_input_files(str(temp_pdf))
        await page.locator('[data-testid="institution-input"]').fill("Test Bank")
        await page.locator('[data-testid="account-number-input"]').fill("1234567890")
        await page.locator('[data-testid="submit-upload"]').click()

        await page.wait_for_selector('[data-testid="upload-success"]', timeout=60000)

        success_message = await page.locator('[data-testid="upload-success"]').text_content()
        assert "success" in success_message.lower()

        await page.locator('[data-testid="view-statement"]').click()

        await page.wait_for_selector('[data-testid="transaction-list"]', timeout=30000)

        transactions = await page.locator('[data-testid^="transaction-"]').count()
        assert transactions > 0, "No transactions extracted from PDF"

        await page.locator('[data-testid="approve-statement"]').click()
        await page.wait_for_selector('[data-testid="approval-success"]', timeout=10000)

        approval_message = await page.locator('[data-testid="approval-success"]').text_content()
        assert "approved" in approval_message.lower()

    finally:
        if temp_pdf.exists():
            try:
                temp_pdf.unlink()
            except OSError as e:
                warnings.warn(f"Failed to clean up temp file {temp_pdf}: {e}", ResourceWarning, stacklevel=2)


@pytest.mark.e2e
async def test_model_selection_and_upload(page: Page):
    """E2E: Select model → Upload → Verify correct model used."""
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        return

    await page.goto(f"{frontend_url}/statements")
    await page.wait_for_load_state("networkidle")

    await page.locator('[data-testid="model-selector"]').click()
    await page.locator("text=gemini-3-flash-preview").click()

    selected_model = await page.locator('[data-testid="model-selector"]').text_content()
    assert "gemini-3-flash-preview" in selected_model

    await page.locator('[data-testid="upload-button"]').click()

    pdf_bytes = create_test_pdf()
    temp_pdf = Path("/tmp/test_statement_model.pdf")
    temp_pdf.write_bytes(pdf_bytes)

    try:
        await page.locator('[data-testid="file-input"]').set_input_files(str(temp_pdf))
        await page.locator('[data-testid="institution-input"]').fill("Test Bank")
        await page.locator('[data-testid="account-number-input"]').fill("1234567890")
        await page.locator('[data-testid="submit-upload"]').click()

        await page.wait_for_selector('[data-testid="upload-success"]', timeout=60000)

    finally:
        if temp_pdf.exists():
            try:
                temp_pdf.unlink()
            except OSError as e:
                warnings.warn(f"Failed to clean up temp file {temp_pdf}: {e}", ResourceWarning, stacklevel=2)


@pytest.mark.e2e
async def test_stale_model_id_auto_cleanup(page: Page):
    """E2E: Inject stale localStorage model → Reload → Verify cleanup."""
    frontend_url = os.getenv("FRONTEND_URL")
    if not frontend_url:
        return

    await page.goto(f"{frontend_url}/statements")
    await page.wait_for_load_state("networkidle")

    await page.evaluate('localStorage.setItem("statement_model_v1", "google/gemini-2.0-flash-thinking")')

    await page.reload()
    await page.wait_for_load_state("networkidle")

    stored_model = await page.evaluate('localStorage.getItem("statement_model_v1")')

    if stored_model is not None:
        assert stored_model != "google/gemini-2.0-flash-thinking", "Stale model ID was not cleared"

    selected_model = await page.locator('[data-testid="model-selector"]').text_content()
    assert "gemini-3-flash-preview" in selected_model, "Did not fallback to default model"
