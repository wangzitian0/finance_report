"""Core-journey proof U9: Twelve consecutive months tie out on a deployed revision (#2370).

One isolated user creates an SGD asset account and records an opening balance on
2025-12-31. The user uploads 12 consecutive monthly statements for the year 2026
(2026-01 through 2026-12).

Each monthly statement carries two transactions:
* Monthly salary credit (inflow)
* Monthly rent expense (outflow)

Each statement satisfies the balance-chain constraint:
* Month opening balance + monthly net movement = Month closing balance
* Month (n+1) opening balance = Month (n) closing balance

After all 12 statements are approved and posted to the ledger:
* The balance sheet as of 2026-12-31 ties out and is balanced (delta = 0.00).
* Total assets match the independent Decimal oracle (opening cash + 12 * net).
* The income statement matches total income and total expenses.
* The cash flow statement ending cash equals the balance sheet cash.
* An annual report package generates with status 'trusted'.
"""

from __future__ import annotations

import asyncio
import calendar
import os
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
from common.testing.ac_proof import ac_proof
from common.testing.provider_review import (
    FixtureDisposition,
    FixtureEnvelope,
    approve_statement_with_fixture_review,
)
from deployment_pin import assert_pinned_deployment, resolve_expected_commit
from journey_checkpoint import checkpoint
from playwright.async_api import Page

APP_URL = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT_MS = int(os.getenv("PARSING_TIMEOUT_MS", "480000"))

CURRENCY = "SGD"
INITIAL_OPENING_BALANCE = Decimal("10000.00")
MONTHLY_SALARY = Decimal("5000.00")
MONTHLY_RENT = Decimal("1500.00")
MONTHLY_NET = MONTHLY_SALARY - MONTHLY_RENT  # 3500.00

TOTAL_MONTHS = 12
EXPECTED_TOTAL_INCOME = MONTHLY_SALARY * TOTAL_MONTHS  # 60000.00
EXPECTED_TOTAL_EXPENSES = MONTHLY_RENT * TOTAL_MONTHS  # 18000.00
EXPECTED_NET_INCOME = EXPECTED_TOTAL_INCOME - EXPECTED_TOTAL_EXPENSES  # 42000.00
EXPECTED_ENDING_CASH = INITIAL_OPENING_BALANCE + EXPECTED_NET_INCOME  # 52000.00
EXPECTED_TOTAL_ASSETS = EXPECTED_ENDING_CASH

CSV_HEADER = (
    "Statement Currency,Statement Period Start,Statement Period End,"
    "Statement Opening Balance,Statement Closing Balance,Date,Description,Amount"
)

DISPOSITIONS = {
    "salary credit acme": FixtureDisposition(
        "income", "INCOME", "Monthly salary credit", "SALARY"
    ),
    "rent payment landlord": FixtureDisposition(
        "expense", "EXPENSE", "Monthly rent expense", "HOUSING"
    ),
}


def _api_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}/api{path}"


async def _auth_headers(page: Page) -> dict[str, str]:
    cookies = await page.context.cookies(APP_URL)
    auth_cookie = next(
        (cookie for cookie in cookies if cookie["name"] == "finance_access_token"),
        None,
    )
    assert auth_cookie, "authenticated Playwright context is missing auth cookie"
    return {"Cookie": f"finance_access_token={auth_cookie['value']}"}


async def _assert_pinned_before_journey(page: Page, record_property) -> None:
    """Prove the pinned deployment before the journey starts (#2370)."""
    expected_version = os.getenv("EXPECTED_SHA")
    assert expected_version, "core-journey proof requires an explicit EXPECTED_SHA"
    expected_commit = resolve_expected_commit(expected_version)
    headers = await _auth_headers(page)
    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        health = await client.get(_api_url("/health"))
        assert health.status_code == 200
        assert_pinned_deployment(health.json(), expected_version, expected_commit)
        frontend = await client.get(f"{APP_URL.rstrip('/')}/frontend-version.json")
        assert frontend.status_code == 200, (
            "frontend deployment version must be observable"
        )
        assert_pinned_deployment(frontend.json(), expected_version, expected_commit)
    checkpoint(record_property, "U12")


def _month_csv(
    *,
    period_start: date,
    period_end: date,
    opening: Decimal,
    closing: Decimal,
) -> str:
    salary_date = date(period_start.year, period_start.month, 5)
    rent_date = date(period_start.year, period_start.month, 20)
    rows = [
        CSV_HEADER,
        (
            f"{CURRENCY},{period_start},{period_end},{opening},{closing},"
            f"{salary_date},Salary Credit ACME,{MONTHLY_SALARY}"
        ),
        (
            f"{CURRENCY},{period_start},{period_end},{opening},{closing},"
            f"{rent_date},Rent Payment Landlord,-{MONTHLY_RENT}"
        ),
        "",
    ]
    return "\n".join(rows)


async def _wait_for_parsed(client: httpx.AsyncClient, statement_id: str) -> dict:
    deadline = asyncio.get_running_loop().time() + PARSING_TIMEOUT_MS / 1000
    last_payload: dict | None = None
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(_api_url(f"/statements/{statement_id}"))
        assert response.status_code == 200, (
            f"statement poll failed for {statement_id}: {response.text}"
        )
        last_payload = response.json()
        status = last_payload.get("status")
        if status in ("rejected", "approved"):
            return last_payload
        if status == "parsed":
            return last_payload
        await asyncio.sleep(0.5)
    raise TimeoutError(f"statement {statement_id} did not parse: {last_payload}")


@ac_proof(
    "twelve-month-statement-to-report-journey",
    ac_ids=["AC-reporting.full-year.1"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    issue="#2370",
    required_markers=["e2e", "journey"],
)
@pytest.mark.e2e
@pytest.mark.journey
async def test_twelve_consecutive_months_tie_out_on_deployed_revision(
    authenticated_page_unique: Page,
    record_property,
) -> None:
    """EPIC-003 EPIC-008 EPIC-019 / AC-reporting.full-year.1: Twelve consecutive months tie out.

    Checkpoints proven: U12 (pinned revision), U9 (twelve consecutive months tie out).
    """
    page = authenticated_page_unique
    await _assert_pinned_before_journey(page, record_property)

    headers = await _auth_headers(page)
    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        # 1. Create dedicated asset account for the full year proof.
        acc_resp = await client.post(
            _api_url("/accounts"),
            json={
                "name": "Twelve Month Proof Savings",
                "type": "ASSET",
                "currency": CURRENCY,
            },
        )
        assert acc_resp.status_code == 201, f"account creation failed: {acc_resp.text}"
        account_id = acc_resp.json()["id"]

        # 2. Record opening balance on 2025-12-31.
        opening_resp = await client.post(
            _api_url("/accounts/opening-balances"),
            json={
                "entry_date": "2025-12-31",
                "balances": {account_id: str(INITIAL_OPENING_BALANCE)},
                "currency": CURRENCY,
                "memo": "Initial opening cash before 2026 statements",
            },
        )
        assert opening_resp.status_code == 201, (
            f"opening balance failed: {opening_resp.status_code} {opening_resp.text}"
        )

        # 3. Sequentially ingest 12 consecutive months.
        running_balance = INITIAL_OPENING_BALANCE
        for month_idx in range(1, TOTAL_MONTHS + 1):
            days_in_month = calendar.monthrange(2026, month_idx)[1]
            period_start = date(2026, month_idx, 1)
            period_end = date(2026, month_idx, days_in_month)
            month_opening = running_balance
            month_closing = running_balance + MONTHLY_NET

            csv_text = _month_csv(
                period_start=period_start,
                period_end=period_end,
                opening=month_opening,
                closing=month_closing,
            )
            filename = f"statement_2026_{month_idx:02d}_{uuid.uuid4().hex[:6]}.csv"
            upload_resp = await client.post(
                _api_url("/statements/upload"),
                data={
                    "institution": "Twelve Month Savings Bank",
                    "account_id": account_id,
                },
                files={"file": (filename, csv_text.encode("utf-8"), "text/csv")},
            )
            assert upload_resp.status_code in (200, 201, 202), (
                f"month {month_idx} upload failed: {upload_resp.text}"
            )
            statement_id = upload_resp.json()["id"]

            parsed = await _wait_for_parsed(client, statement_id)
            assert len(parsed.get("transactions") or []) == 2

            approval = await approve_statement_with_fixture_review(
                client,
                api_url=_api_url,
                statement_id=statement_id,
                transactions=parsed["transactions"],
                dispositions=DISPOSITIONS,
                envelope=FixtureEnvelope(
                    currency=CURRENCY,
                    period_start=period_start,
                    period_end=period_end,
                    opening_balance=month_opening,
                    closing_balance=month_closing,
                    rationale="The generated monthly CSV declares these source facts.",
                ),
            )
            assert approval.get("status") == "approved", (
                f"month {month_idx} approval failed: {approval}"
            )
            running_balance = month_closing

        # 4. Verify the annual balance sheet as of 2026-12-31.
        bs_resp = await client.get(
            _api_url("/reports/balance-sheet"),
            params={"as_of_date": "2026-12-31", "currency": CURRENCY},
        )
        assert bs_resp.status_code == 200, f"balance sheet failed: {bs_resp.text}"
        bs = bs_resp.json()
        assert bs.get("is_balanced") is True, f"balance sheet not balanced: {bs}"
        assert Decimal(str(bs.get("equation_delta", "1"))) == Decimal("0.00")
        assert Decimal(str(bs.get("total_assets", "0"))) == EXPECTED_TOTAL_ASSETS

        # 5. Verify the annual income statement for 2026.
        inc_resp = await client.get(
            _api_url("/reports/income-statement"),
            params={
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "currency": CURRENCY,
            },
        )
        assert inc_resp.status_code == 200, f"income statement failed: {inc_resp.text}"
        inc = inc_resp.json()
        assert Decimal(str(inc.get("total_income", "0"))) == EXPECTED_TOTAL_INCOME
        assert Decimal(str(inc.get("total_expenses", "0"))) == EXPECTED_TOTAL_EXPENSES
        assert Decimal(str(inc.get("net_income", "0"))) == EXPECTED_NET_INCOME

        # 6. Verify the annual cash flow statement for 2026.
        cf_resp = await client.get(
            _api_url("/reports/cash-flow"),
            params={
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "currency": CURRENCY,
            },
        )
        assert cf_resp.status_code == 200, f"cash flow failed: {cf_resp.text}"
        cf = cf_resp.json()
        ending_cash = Decimal(str(cf.get("summary", {}).get("ending_cash", "0")))
        assert ending_cash == EXPECTED_ENDING_CASH

        # 7. Generate annual report package and verify trusted status.
        pkg_resp = await client.post(
            _api_url("/reports/package/generate"),
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "as_of_date": "2026-12-31",
                "currency": CURRENCY,
            },
        )
        assert pkg_resp.status_code == 200, f"package generate failed: {pkg_resp.text}"
        pkg = pkg_resp.json()
        assert pkg.get("status") == "trusted", f"package not trusted: {pkg}"

        # 8. Verify reports and statements in the real browser UI.
        await page.goto(f"{APP_URL.rstrip('/')}/reports", wait_until="domcontentloaded")
        await page.locator("main").wait_for(state="visible", timeout=30000)
        reports_content = await page.locator("main").inner_text()
        assert (
            "52,000" in reports_content
            or "52000" in reports_content
            or "Reports" in reports_content
        ), "reports UI must show ending cash or report heading"
        await page.goto(
            f"{APP_URL.rstrip('/')}/statements", wait_until="domcontentloaded"
        )
        await page.locator("main").wait_for(state="visible", timeout=30000)

        # 9. Record checkpoint U9.
        checkpoint(record_property, "U9")
