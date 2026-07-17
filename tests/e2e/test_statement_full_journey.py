"""
Tier 3 Browser E2E: Full Statement Journey — AC8.13.1–AC8.13.5

DBS PDF upload → AI parsing (poll until parsed) → detail page review
→ approve via ConfirmDialog → balance sheet report verification

Requires APP_URL env var pointing to a running frontend+backend.
Run from repo root: pytest -m e2e tests/e2e/
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from decimal import Decimal
from pathlib import Path

import pytest
from common.testing import money_amount
from common.testing.ac_proof import ac_proof
from conftest import fail_or_skip_ai_ocr_gate
from pdf_fixture_paths import committed_fixture_pdf
from playwright.async_api import Page, expect

APP_URL: str = os.getenv("APP_URL", "http://localhost:3000")

# AI parsing can take up to 2 minutes on a cold start
PARSING_TIMEOUT_MS: int = int(os.getenv("PARSING_TIMEOUT_MS", "120000"))

INSTITUTION_LABEL: str = "DBS E2E Full Journey"
PARSED_STATUS_BADGE_RE = re.compile(r"^(Parsed|Ready to review)$", re.I)

# Ground truth for the COMMITTED DBS fixture (#1826 G-value-oracle): the
# expected-JSON pair describes the PDF's true source values, independent of
# whatever the extraction pipeline outputs. The balances below are hand-pinned
# from that source document; test_dbs_ground_truth_balances_stay_pinned locks
# them against the committed expected file and re-sums its event chain.
DBS_EXPECTED_PATH = (
    Path(__file__).resolve().parents[2]
    / "common"
    / "testing"
    / "fixtures"
    / "pdf"
    / "generated"
    / "dbs_statement_fixture_expected.json"
)
DBS_EXPECTED_OPENING_BALANCE = Decimal("12000.00")
DBS_EXPECTED_CLOSING_BALANCE = Decimal("15242.05")
DBS_EXPECTED_CURRENCY = "SGD"


def _get_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}{path}"


def _statement_row(page: Page, institution: str):
    return page.locator(".relative.block").filter(has_text=institution).first


def test_parsed_status_badge_pattern_accepts_user_facing_ready_to_review_label() -> (
    None
):
    """EPIC-003 EPIC-004 EPIC-008 EPIC-013 EPIC-016 EPIC-018.

    Parsed upload rows may use the user-facing review label.
    """
    assert PARSED_STATUS_BADGE_RE.search("Parsed")
    assert PARSED_STATUS_BADGE_RE.search("Ready to review")


def _get_dbs_pdf_path() -> Path:
    """The COMMITTED DBS fixture PDF (paired with its expected-JSON file).

    Runtime-generated builds (``generated_pdf_path``) have randomized
    amounts, so no ground truth can exist for them — the committed pair is
    what lets this journey grade extraction against exact expected values
    (#1826 G-value-oracle; same pattern as the GXS graded journey).
    """
    return committed_fixture_pdf("dbs_statement_fixture.pdf")


def test_dbs_ground_truth_balances_stay_pinned() -> None:
    """AC-extraction.813.11: EPIC-003 EPIC-004 EPIC-008 EPIC-013 EPIC-016 EPIC-018.

    The hand-pinned oracle constants match the committed ground-truth file,
    and its event chain re-sums exactly from opening to closing balance —
    the oracle is internally consistent before any implementation runs
    (#1826 G-value-oracle).
    """
    expected = json.loads(DBS_EXPECTED_PATH.read_text(encoding="utf-8"))
    stmt = expected["statement"]
    assert Decimal(stmt["opening_balance"]) == DBS_EXPECTED_OPENING_BALANCE
    assert Decimal(stmt["closing_balance"]) == DBS_EXPECTED_CLOSING_BALANCE
    assert stmt["currency"] == DBS_EXPECTED_CURRENCY
    assert stmt["balance_validated"] is True

    signed_movement = sum(
        (
            Decimal(event["amount"])
            if event["direction"] == "IN"
            else -Decimal(event["amount"])
            for event in expected["events"]
        ),
        Decimal("0.00"),
    )
    assert (
        DBS_EXPECTED_OPENING_BALANCE + signed_movement == DBS_EXPECTED_CLOSING_BALANCE
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


@ac_proof(
    "dbs-pdf-full-journey",
    ac_ids=["AC-extraction.813.11"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    trust_mode="llm_ocr_post_merge",
    source_classes=["bank_statement"],
    mirror_proof_id="structured-source-reporting-pr",
    issue="#443",
    required_markers=["e2e", "tier3", "critical", "llm"],
)
@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_dbs_statement_full_journey(authenticated_page_unique: Page) -> None:
    """AC-extraction.813.11 AC-audit.global-invariant.2: EPIC-003 EPIC-004 EPIC-008 EPIC-013 EPIC-016 EPIC-018.

    AC8.13.1 AC8.13.2 AC8.13.3 AC8.13.4 AC8.13.5 AC8.13.7: DBS PDF to balance sheet.
    """
    page = authenticated_page_unique
    pdf_path = _unique_pdf_copy(_get_dbs_pdf_path())

    # === AC8.13.1: Upload PDF ===
    await page.goto(_get_url("/upload"))
    await page.wait_for_load_state("domcontentloaded")

    if "/login" in page.url:
        pytest.fail(
            f"Redirected to /login despite authenticated_page fixture. URL: {page.url}"
        )

    await page.locator('[data-testid="uploader-institution-statement"]').fill(
        INSTITUTION_LABEL
    )
    # Fetch the default model from the backend API and select it explicitly.
    # Selecting by value ensures we always use the backend-configured OCR model.
    models_resp = await page.evaluate(
        "async () => { const r = await fetch('/api/llm/catalog?modality=image'); return r.json(); }"
    )
    default_model: str = (
        models_resp.get("default_model") or models_resp["models"][0]["id"]
    )
    model_select = page.locator('[data-testid="uploader-model-statement"]')
    await expect(model_select).to_be_visible(timeout=15_000)
    await expect(model_select).not_to_have_value("", timeout=15_000)
    await model_select.select_option(value=default_model)
    await page.set_input_files('[data-testid="uploader-file-statement"]', str(pdf_path))
    await expect(page.locator("p.font-medium", has_text=pdf_path.name)).to_be_visible(
        timeout=5_000
    )

    async with (
        page.expect_response(
            lambda r: "/api/statements/upload" in r.url,
            timeout=120_000,  # Upload + AI model validation may take up to 120s on cold-start
        ) as resp_info
    ):
        await page.get_by_role("button", name="Upload & Parse Statement").click()
    upload_resp = await resp_info.value
    assert upload_resp.status in (200, 201, 202), (
        f"Upload endpoint returned unexpected status {upload_resp.status} — "
        f"expected 2xx. Response body: {await upload_resp.text()}"
    )
    upload_body = await upload_resp.json()
    statement_id = upload_body.get("id")
    assert statement_id, f"Upload response missing 'id' field: {upload_body}"
    # === AC8.13.2: Poll until "parsed" status badge appears in the list ===
    # The list page polls via TanStack Query every 3 s — we wait up to PARSING_TIMEOUT_MS.
    statement_row = _statement_row(page, INSTITUTION_LABEL)
    await expect(statement_row).to_be_visible(timeout=15_000)

    parsed_badge = statement_row.locator("span.badge", has_text=PARSED_STATUS_BADGE_RE)
    approved_badge = statement_row.locator(
        "span.badge", has_text=re.compile(r"^Approved$", re.I)
    )
    rejected_badge = statement_row.locator(
        "span.badge", has_text=re.compile(r"^Rejected$", re.I)
    )
    # Poll the statement API by ID until parsed, but fail fast with the stored
    # validation error if the AI/OCR provider rejects parsing.
    # This avoids waiting the full PARSING_TIMEOUT_MS when the AI service fails.
    import asyncio

    deadline = asyncio.get_running_loop().time() + PARSING_TIMEOUT_MS / 1000
    last_statement: dict | None = None
    while asyncio.get_running_loop().time() < deadline:
        api_resp = await page.request.get(
            _get_url(f"/api/statements/{statement_id}"),
        )
        assert api_resp.status == 200, (
            f"GET /api/statements/{statement_id} returned {api_resp.status} — response body: {await api_resp.text()}"
        )
        last_statement = await api_resp.json()
        if (
            last_statement.get("status") == "rejected"
            or await rejected_badge.is_visible()
        ):
            fail_or_skip_ai_ocr_gate(
                "Statement parsing failed (status=rejected) — AI service may be "
                "unavailable or misconfigured on the test environment.",
                statement=last_statement,
                model=default_model,
            )
        # A high-confidence, balance-valid parse with a detected account skips
        # 'parsed' entirely and auto-posts straight to 'approved'
        # (route_by_threshold + #1467 auto-account-create, #1780) -- both
        # states are success; the review section below branches on which one
        # actually happened.
        status = last_statement.get("status")
        if status == "parsed":
            await expect(parsed_badge).to_be_visible(timeout=15_000)
            break
        if status == "approved":
            await expect(approved_badge).to_be_visible(timeout=15_000)
            break
        await page.wait_for_timeout(3_000)
    else:
        pytest.fail(
            f"Statement never reached 'parsed' or 'approved' status within {PARSING_TIMEOUT_MS}ms. "
            f"Last statement payload: {last_statement}"
        )

    already_approved = last_statement.get("status") == "approved"

    # === AC8.13.3: Detail page shows transactions ===
    await page.goto(_get_url(f"/statements/{statement_id}"))
    # Wait for navigation to /statements/{id} explicitly; generic load-state
    # waits can resolve before the Next.js router commits the URL change.
    await expect(page).to_have_url(re.compile(r"/statements/[^/]+$"), timeout=15_000)

    await expect(page.get_by_text("Transactions", exact=False)).to_be_visible(
        timeout=10_000
    )
    await expect(page.locator("table tbody tr").first).to_be_visible(timeout=10_000)

    if already_approved:
        # Auto-posted before we ever observed 'parsed' -- nothing left to
        # review/approve through the UI; just confirm the detail page already
        # reflects the approved state.
        await expect(page.locator("span.badge", has_text="approved")).to_be_visible(
            timeout=15_000
        )
    else:
        # === AC8.13.4: Start Review → approve via ConfirmDialog ===
        await page.get_by_role("link", name=re.compile("Start Review")).click()
        await expect(page).to_have_url(
            re.compile(r"/statements/[^/]+/review$"), timeout=15_000
        )
        await page.get_by_role("button", name="Approve").click()
        dialog = page.locator('[role="dialog"]')
        await expect(dialog).to_be_visible(timeout=5_000)
        confirm_button = dialog.get_by_role("button", name="Approve")
        await expect(confirm_button).to_be_visible(timeout=3_000)
        await confirm_button.click()
        await expect(page).to_have_url(
            re.compile(r"/statements/[^/?]+(?:\?.*)?$"), timeout=15_000
        )
        await expect(page.locator("span.badge", has_text="approved")).to_be_visible(
            timeout=15_000
        )

    await page.goto(_get_url("/upload"))
    await expect(page).to_have_url(re.compile(r"/upload$"), timeout=15_000)
    approved_row = _statement_row(page, INSTITUTION_LABEL)
    await expect(approved_row).to_be_visible(timeout=15_000)
    await expect(
        approved_row.locator("span.badge", has_text=re.compile(r"^Approved$", re.I))
    ).to_be_visible(timeout=15_000)

    # === #1826 G-value-oracle: grade extraction against the committed ground
    # truth (source-ledger-report-traceability must carry the NUMBER, not just
    # the flow). Same committed-pair grading pattern as the GXS journey. ===
    expected = json.loads(DBS_EXPECTED_PATH.read_text(encoding="utf-8"))
    expected_stmt = expected["statement"]
    detail_resp = await page.request.get(_get_url(f"/api/statements/{statement_id}"))
    assert detail_resp.status == 200, (
        f"statement detail failed: {detail_resp.status} {await detail_resp.text()}"
    )
    detail = await detail_resp.json()
    assert money_amount(detail["opening_balance"]) == DBS_EXPECTED_OPENING_BALANCE, (
        f"DBS opening balance drifted from ground truth: "
        f"{detail['opening_balance']} != {DBS_EXPECTED_OPENING_BALANCE}"
    )
    assert money_amount(detail["closing_balance"]) == DBS_EXPECTED_CLOSING_BALANCE, (
        f"DBS closing balance drifted from ground truth: "
        f"{detail['closing_balance']} != {DBS_EXPECTED_CLOSING_BALANCE}"
    )
    assert (detail.get("currency") or "").upper() == DBS_EXPECTED_CURRENCY
    assert len(detail.get("transactions") or []) >= len(expected["events"]), (
        f"extracted {len(detail.get('transactions') or [])} transactions, ground "
        f"truth has {len(expected['events'])}"
    )
    account_id = detail.get("account_id")
    assert account_id, (
        f"approved statement has no linked account (auto-create failed): {detail}"
    )

    # Record the statement's true opening balance through the product's guided
    # flow, then the balance sheet must report the ACTUAL closing balance —
    # not the period's net flow (the 2026-06-29 staging P0 class).
    opening_resp = await page.request.post(
        _get_url("/api/accounts/opening-balances"),
        data=json.dumps(
            {
                "entry_date": expected_stmt["period_start"],
                "balances": {account_id: str(DBS_EXPECTED_OPENING_BALANCE)},
                "currency": DBS_EXPECTED_CURRENCY,
                "memo": "DBS E2E opening balance",
            }
        ),
        headers={"Content-Type": "application/json"},
    )
    assert opening_resp.status == 201, (
        f"opening-balance posting failed: {opening_resp.status} "
        f"{await opening_resp.text()}"
    )

    report_resp = await page.request.get(
        _get_url(
            f"/api/reports/balance-sheet?as_of_date={expected_stmt['period_end']}"
            f"&currency={DBS_EXPECTED_CURRENCY}"
        )
    )
    assert report_resp.status == 200, (
        f"balance sheet failed: {report_resp.status} {await report_resp.text()}"
    )
    report = await report_resp.json()
    assert money_amount(report["total_assets"]) == DBS_EXPECTED_CLOSING_BALANCE, (
        f"balance sheet must report the statement's actual closing balance "
        f"({DBS_EXPECTED_CLOSING_BALANCE}), got {report['total_assets']} — "
        f"net-flow-instead-of-balance regression"
    )
    assert report.get("opening_balance_warnings") == []
    assert money_amount(report["equation_delta"]) == Decimal("0.00")
    assert report["is_balanced"] is True

    # === AC8.13.5: Balance sheet report loads ===
    await page.goto(_get_url("/reports/balance-sheet"))
    await page.wait_for_load_state("domcontentloaded")

    await expect(page.get_by_text("Balance Sheet", exact=False).first).to_be_visible(
        timeout=10_000
    )
    await expect(page.get_by_text("Assets", exact=False).first).to_be_visible(
        timeout=10_000
    )
