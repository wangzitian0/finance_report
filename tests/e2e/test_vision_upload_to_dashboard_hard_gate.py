"""
Tier 3 Browser/API E2E: deterministic upload-to-dashboard vision hard gate.

AC8.13.28–AC8.13.32 / issue #341 follow-up:
- fresh isolated user uploads a deterministic CSV fixture
- completes Stage 1 review and verifies auto-posted journal entries
- reruns reconciliation and verifies Stage 2 completion + idempotency
- verifies Processing visibility/status
- verifies dashboard + reports against exact expected totals
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import pytest
from playwright.async_api import Page, expect

APP_URL: str = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT_MS: int = int(os.getenv("PARSING_TIMEOUT_MS", "120000"))
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "e2e" / "fixtures" / "vision_hard_gate_statement.csv"
FIXTURE_PERIOD_START = "2026-05-01"
FIXTURE_PERIOD_END = "2026-05-31"
INSTITUTION_LABEL = "Generic Vision Hard Gate"
EXPECTED_TOTALS = {
    "transaction_count": 6,
    "total_income": Decimal("5600.00"),
    "total_expenses": Decimal("5600.00"),
    "net_income": Decimal("0.00"),
    "total_assets": Decimal("0.00"),
    "total_liabilities": Decimal("0.00"),
    "total_equity": Decimal("0.00"),
    "net_cash_flow": Decimal("0.00"),
    "beginning_cash": Decimal("0.00"),
    "ending_cash": Decimal("0.00"),
}


def _get_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}{path}"


def _require_fixture_path() -> Path:
    if not FIXTURE_PATH.exists():
        pytest.skip(f"Deterministic vision fixture missing: {FIXTURE_PATH}")
    return FIXTURE_PATH


def _money(value: object) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _read_fixture_rows() -> list[dict[str, str]]:
    with _require_fixture_path().open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return [dict(row) for row in reader]


def _format_grouped_int(amount: Decimal) -> str:
    return f"{int(amount):,}"


async def _auth_headers(page: Page) -> dict[str, str]:
    token = await page.evaluate("() => window.localStorage.getItem('finance_access_token')")
    assert token, "Missing finance_access_token in localStorage"
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def _api_json(
    page: Page,
    path: str,
    *,
    method: str = "GET",
    data: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    request_headers = headers or await _auth_headers(page)
    if method == "POST":
        response = await page.request.post(_get_url(path), data=data, headers=request_headers)
    else:
        response = await page.request.get(_get_url(path), headers=request_headers)
    body = await response.text()
    assert response.status == 200, f"{method} {path} failed: {response.status} {body}"
    return await response.json()


async def _wait_for_statement_status(page: Page, statement_id: str, target_status: str) -> dict:
    headers = await _auth_headers(page)
    deadline = asyncio.get_running_loop().time() + PARSING_TIMEOUT_MS / 1000
    last_statement: dict | None = None
    while asyncio.get_running_loop().time() < deadline:
        last_statement = await _api_json(page, f"/api/statements/{statement_id}", headers=headers)
        if last_statement.get("status") == target_status:
            return last_statement
        await page.wait_for_timeout(1_000)
    pytest.fail(
        f"statement {statement_id} never reached {target_status!r} within {PARSING_TIMEOUT_MS}ms; "
        f"last payload: {last_statement}"
    )


def _assert_expected_totals(payload: dict, expected: dict[str, Decimal], keys: Sequence[str]) -> None:
    for key in keys:
        assert _money(payload[key]) == expected[key], f"{key} mismatch: expected {expected[key]}, got {payload[key]}"


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
async def test_statement_upload_to_dashboard_vision_hard_gate(authenticated_page_unique: Page) -> None:
    """EPIC-003 EPIC-004 EPIC-005 EPIC-008 EPIC-010 EPIC-014 EPIC-015 EPIC-016 EPIC-018.

    AC8.13.28 AC8.13.29 AC8.13.30 AC8.13.31 AC8.13.32: upload fixture to trusted reports.
    """
    page = authenticated_page_unique
    fixture_path = _require_fixture_path()

    await page.goto(_get_url("/statements"))
    await page.wait_for_load_state("networkidle")

    await page.locator("#institution").fill(INSTITUTION_LABEL)
    await page.set_input_files("#file-upload", str(fixture_path))
    await expect(page.locator("p.font-medium", has_text=fixture_path.name)).to_be_visible(timeout=5_000)

    upload_resp = None
    upload_body_text = ""
    for attempt in range(1, 4):
        async with page.expect_response(lambda r: "/api/statements/upload" in r.url, timeout=30_000) as upload_info:
            await page.get_by_role("button", name="Upload & Parse Statement").click()
        upload_resp = await upload_info.value
        upload_body_text = await upload_resp.text()
        if upload_resp.status in (200, 201, 202):
            break
        if upload_resp.status != 503 or attempt == 3:
            break
        await asyncio.sleep(attempt * 2)
    assert upload_resp is not None
    assert upload_resp.status in (200, 201, 202), (
        f"Upload endpoint returned unexpected status {upload_resp.status}. Body: {upload_body_text}"
    )
    upload_body = await upload_resp.json()
    statement_id = upload_body.get("id")
    assert statement_id, f"Upload response missing statement id: {upload_body}"

    statement_row = page.locator("a").filter(has_text=INSTITUTION_LABEL).first
    await expect(statement_row).to_be_visible(timeout=15_000)
    parsed_statement = await _wait_for_statement_status(page, statement_id, "parsed")
    assert len(parsed_statement.get("transactions") or []) == EXPECTED_TOTALS["transaction_count"]

    await statement_row.click()
    await expect(page).to_have_url(re.compile(r"/statements/[^/]+$"), timeout=15_000)
    await expect(page.get_by_text("Transactions", exact=False)).to_be_visible(timeout=10_000)
    await expect(page.locator("table tbody tr")).to_have_count(EXPECTED_TOTALS["transaction_count"], timeout=10_000)

    await page.get_by_role("link", name=re.compile("Start Review")).click()
    await expect(page).to_have_url(re.compile(r"/statements/[^/]+/review$"), timeout=15_000)

    approve_button = page.get_by_role("button", name="Approve").first
    await expect(approve_button).to_be_enabled(timeout=10_000)
    async with page.expect_response(
        lambda r: f"/api/statements/{statement_id}/review/approve" in r.url
    ) as approve_info:
        await approve_button.click()
        dialog = page.locator('[role="dialog"]')
        await expect(dialog).to_be_visible(timeout=5_000)
        await dialog.get_by_role("button", name="Approve").click()
    approve_resp = await approve_info.value
    approve_body = await approve_resp.json()
    assert approve_resp.status == 200, f"Stage 1 approve failed: {approve_body}"
    assert approve_body["journal_entries_created"] == EXPECTED_TOTALS["transaction_count"]

    await expect(page).to_have_url(re.compile(r"/statements/[^/?]+(?:\?.*)?$"), timeout=15_000)
    await expect(page.locator("span.badge", has_text="approved")).to_be_visible(timeout=15_000)

    journal_entries = await _api_json(page, f"/api/journal-entries?limit={EXPECTED_TOTALS['transaction_count'] + 4}")
    assert journal_entries["total"] == EXPECTED_TOTALS["transaction_count"]
    assert len(journal_entries["items"]) == EXPECTED_TOTALS["transaction_count"]
    assert {item["status"].lower() for item in journal_entries["items"]} == {"posted"}
    assert {item["memo"] for item in journal_entries["items"]} == {row["Description"] for row in _read_fixture_rows()}

    reconciliation_headers = await _auth_headers(page)
    first_run = await _api_json(
        page,
        "/api/reconciliation/run",
        method="POST",
        data=f'{{"statement_id":"{statement_id}"}}',
        headers=reconciliation_headers,
    )
    assert first_run == {
        "matches_created": EXPECTED_TOTALS["transaction_count"],
        "auto_accepted": EXPECTED_TOTALS["transaction_count"],
        "pending_review": 0,
        "unmatched": 0,
    }

    second_run = await _api_json(
        page,
        "/api/reconciliation/run",
        method="POST",
        data=f'{{"statement_id":"{statement_id}"}}',
        headers=reconciliation_headers,
    )
    assert second_run == {
        "matches_created": 0,
        "auto_accepted": 0,
        "pending_review": 0,
        "unmatched": 0,
    }

    reconciliation_stats = await _api_json(page, "/api/reconciliation/stats")
    assert reconciliation_stats == {
        "total_transactions": EXPECTED_TOTALS["transaction_count"],
        "matched_transactions": EXPECTED_TOTALS["transaction_count"],
        "unmatched_transactions": 0,
        "pending_review": 0,
        "auto_accepted": EXPECTED_TOTALS["transaction_count"],
        "match_rate": 100.0,
        "score_distribution": {"0-59": 0, "60-79": 0, "80-89": 0, "90-100": EXPECTED_TOTALS["transaction_count"]},
    }

    stage2_queue = await _api_json(page, "/api/statements/stage2/queue")
    assert stage2_queue["pending_matches"] == []
    assert stage2_queue["consistency_checks"] == []
    assert stage2_queue["has_unresolved_checks"] is False

    await page.goto(_get_url(f"/review/run/{statement_id}"))
    await page.wait_for_load_state("networkidle")
    await expect(page.get_by_role("heading", name="Stage 2 Run Review")).to_be_visible(timeout=10_000)
    await expect(page.get_by_text("No pending matches")).to_be_visible(timeout=10_000)
    run_approve_button = page.get_by_role("button", name="Approve Run")
    await expect(run_approve_button).to_be_disabled()
    assert await run_approve_button.get_attribute("title") == "No pending matches remain"

    processing_summary = await _api_json(page, "/api/accounts/processing/summary")
    assert processing_summary == {
        "pending_count": 0,
        "pending_total": "0.00",
        "current_balance": "0.00",
        "currency": "SGD",
        "oldest_pending_date": None,
    }

    await page.goto(_get_url("/processing"))
    await page.wait_for_load_state("networkidle")
    await expect(page.get_by_role("heading", name="Processing Transfers")).to_be_visible(timeout=10_000)
    await expect(page.get_by_text("No pending transfers found.")).to_be_visible(timeout=10_000)

    balance_sheet = await _api_json(page, f"/api/reports/balance-sheet?as_of_date={FIXTURE_PERIOD_END}&currency=SGD")
    _assert_expected_totals(balance_sheet, EXPECTED_TOTALS, ("total_assets", "total_liabilities", "total_equity"))

    income_statement = await _api_json(
        page,
        f"/api/reports/income-statement?start_date={FIXTURE_PERIOD_START}&end_date={FIXTURE_PERIOD_END}&currency=SGD",
    )
    _assert_expected_totals(income_statement, EXPECTED_TOTALS, ("total_income", "total_expenses", "net_income"))

    cash_flow = await _api_json(
        page,
        f"/api/reports/cash-flow?start_date={FIXTURE_PERIOD_START}&end_date={FIXTURE_PERIOD_END}&currency=SGD",
    )
    _assert_expected_totals(
        cash_flow["summary"],
        EXPECTED_TOTALS,
        ("net_cash_flow", "beginning_cash", "ending_cash"),
    )

    await page.goto(_get_url("/dashboard"))
    await page.wait_for_load_state("networkidle")
    await expect(page.get_by_role("heading", name="Dashboard")).to_be_visible(timeout=10_000)
    await expect(
        page.locator(".card")
        .filter(has_text="Processing")
        .filter(has_text="SGD 0.00")
        .filter(has_text="0 Pending")
        .filter(has_text="Balanced")
    ).to_be_visible()
    await expect(
        page.locator(".card")
        .filter(has_text="Total Assets")
        .filter(has_text=_format_grouped_int(EXPECTED_TOTALS["total_assets"]))
    ).to_be_visible()
    await expect(
        page.locator(".card")
        .filter(has_text="Net Assets")
        .filter(has_text=_format_grouped_int(EXPECTED_TOTALS["total_assets"]))
    ).to_be_visible()
    await expect(
        page.locator(".card")
        .filter(has_text="This Month — Income")
        .filter(has_text=_format_grouped_int(EXPECTED_TOTALS["total_income"]))
    ).to_be_visible()
    await expect(
        page.locator(".card")
        .filter(has_text="This Month — Expenses")
        .filter(has_text=_format_grouped_int(EXPECTED_TOTALS["total_expenses"]))
    ).to_be_visible()
    await expect(
        page.locator(".card")
        .filter(has_text="This Month — Net")
        .filter(has_text=_format_grouped_int(EXPECTED_TOTALS["net_income"]))
    ).to_be_visible()

    await page.goto(_get_url(f"/reports/balance-sheet?as_of_date={FIXTURE_PERIOD_END}&currency=SGD"))
    await page.wait_for_load_state("networkidle")
    await expect(page.get_by_role("heading", name="Balance Sheet")).to_be_visible(timeout=10_000)
    await expect(page.locator(".card").filter(has_text="Assets").filter(has_text="Total:")).to_contain_text(
        _format_grouped_int(EXPECTED_TOTALS["total_assets"])
    )
    await expect(page.locator(".card").filter(has_text="Liabilities").filter(has_text="Total:")).to_contain_text(
        _format_grouped_int(EXPECTED_TOTALS["total_liabilities"])
    )

    await page.goto(
        _get_url(
            f"/reports/income-statement?start_date={FIXTURE_PERIOD_START}&end_date={FIXTURE_PERIOD_END}&currency=SGD"
        )
    )
    await page.wait_for_load_state("networkidle")
    await expect(page.get_by_role("heading", name="Income Statement")).to_be_visible(timeout=10_000)
    await expect(
        page.locator(".card")
        .filter(has_text="Total Income")
        .filter(has_text=_format_grouped_int(EXPECTED_TOTALS["total_income"]))
    ).to_be_visible()
    await expect(
        page.locator(".card")
        .filter(has_text="Total Expenses")
        .filter(has_text=_format_grouped_int(EXPECTED_TOTALS["total_expenses"]))
    ).to_be_visible()
    await expect(
        page.locator(".card")
        .filter(has_text="Net Income")
        .filter(has_text=_format_grouped_int(EXPECTED_TOTALS["net_income"]))
    ).to_be_visible()

    await page.goto(
        _get_url(f"/reports/cash-flow?start_date={FIXTURE_PERIOD_START}&end_date={FIXTURE_PERIOD_END}&currency=SGD")
    )
    await page.wait_for_load_state("networkidle")
    await expect(page.get_by_role("heading", name="Cash Flow Statement")).to_be_visible(timeout=10_000)
    await expect(
        page.locator(".card")
        .filter(has_text="Net Cash Flow")
        .filter(has_text=_format_grouped_int(EXPECTED_TOTALS["net_cash_flow"]))
    ).to_be_visible()
    await expect(
        page.locator(".card")
        .filter(has_text="Beginning Cash")
        .filter(has_text=_format_grouped_int(EXPECTED_TOTALS["beginning_cash"]))
    ).to_be_visible()
    await expect(
        page.locator(".card")
        .filter(has_text="Ending Cash")
        .filter(has_text=_format_grouped_int(EXPECTED_TOTALS["ending_cash"]))
    ).to_be_visible()


def test_vision_fixture_totals_match_expected_values() -> None:
    """EPIC-003 EPIC-005 EPIC-008 EPIC-016 EPIC-018.

    AC8.13.32: deterministic fixture totals stay pinned to exact reporting values.
    """
    rows = _read_fixture_rows()
    income = sum((_money(row["Amount"]) for row in rows if _money(row["Amount"]) > Decimal("0.00")), Decimal("0.00"))
    expenses = sum((-_money(row["Amount"]) for row in rows if _money(row["Amount"]) < Decimal("0.00")), Decimal("0.00"))
    net = income - expenses

    assert len(rows) == EXPECTED_TOTALS["transaction_count"]
    assert income == EXPECTED_TOTALS["total_income"]
    assert expenses == EXPECTED_TOTALS["total_expenses"]
    assert net == EXPECTED_TOTALS["net_income"]


def test_vision_fixture_balances_to_zero_for_stage1_approval() -> None:
    """EPIC-003 EPIC-005 EPIC-008 EPIC-016 EPIC-018.

    AC8.13.29: fixture net cash is zero so Stage 1 CSV approval remains balance-valid.
    """
    rows = _read_fixture_rows()
    net_cash = sum((_money(row["Amount"]) for row in rows), Decimal("0.00"))

    assert net_cash == EXPECTED_TOTALS["ending_cash"]
    assert EXPECTED_TOTALS["total_assets"] == Decimal("0.00")
