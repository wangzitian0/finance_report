from __future__ import annotations

import calendar
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
from playwright.async_api import Page, expect
from tests.fixtures.provider_review import FixtureDisposition, FixtureEnvelope

from tests.e2e._journey_helpers import (
    assert_pinned_via_client,
    auth_headers,
    create_account,
    create_opening_balances,
    get_json,
    get_url,
    post_json,
    upload_parse_and_approve_csv,
)
from tests.e2e.journey_checkpoint import checkpoint
from tests.e2e.transport_retry import ReconnectCount, get_with_reconnect

CURRENCY, YEAR_START, YEAR_END = "SGD", "2026-01-01", "2026-12-31"
INITIAL_OPENING_BALANCE, MONTHLY_SALARY, MONTHLY_RENT, TOTAL_MONTHS = (
    Decimal("10000.00"),
    Decimal("5000.00"),
    Decimal("1500.00"),
    12,
)
MONTHLY_NET = MONTHLY_SALARY - MONTHLY_RENT
EXPECTED_TOTAL_INCOME, EXPECTED_TOTAL_EXPENSES = (
    MONTHLY_SALARY * TOTAL_MONTHS,
    MONTHLY_RENT * TOTAL_MONTHS,
)
EXPECTED_NET_INCOME = EXPECTED_TOTAL_INCOME - EXPECTED_TOTAL_EXPENSES
EXPECTED_ENDING_CASH = INITIAL_OPENING_BALANCE + EXPECTED_NET_INCOME
CSV_HEADER = "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount"
DISPOSITIONS = {
    "salary credit acme": FixtureDisposition(
        "income", "INCOME", "Monthly salary credit", "SALARY"
    ),
    "rent payment landlord": FixtureDisposition(
        "expense", "EXPENSE", "Monthly rent expense", "HOUSING"
    ),
}


@pytest.mark.e2e
@pytest.mark.journey
async def test_twelve_consecutive_months_tie_out_on_deployed_revision(
    authenticated_page_unique: Page, record_property
) -> None:
    page, reconnects = authenticated_page_unique, ReconnectCount()
    try:
        async with httpx.AsyncClient(
            headers=await auth_headers(page), verify=False, timeout=120.0
        ) as client:
            await assert_pinned_via_client(
                client, record_property, reconnects=reconnects
            )
            account_id = await create_account(
                client, "Twelve Month Proof Savings", currency=CURRENCY
            )
            await create_opening_balances(
                client,
                entry_date="2025-12-31",
                balances={account_id: str(INITIAL_OPENING_BALANCE)},
                currency=CURRENCY,
                memo="Initial opening cash before 2026 statements",
            )
            assert (
                EXPECTED_TOTAL_INCOME,
                EXPECTED_TOTAL_EXPENSES,
                EXPECTED_NET_INCOME,
                EXPECTED_ENDING_CASH,
            ) == (
                Decimal("60000.00"),
                Decimal("18000.00"),
                Decimal("42000.00"),
                Decimal("52000.00"),
            )
            running, uploaded_filenames = INITIAL_OPENING_BALANCE, []

            async def _reconnecting_get(url: str) -> httpx.Response:
                return await get_with_reconnect(client, url, reconnects)

            for m_idx in range(1, TOTAL_MONTHS + 1):
                p_start, p_end = (
                    date(2026, m_idx, 1),
                    date(2026, m_idx, calendar.monthrange(2026, m_idx)[1]),
                )
                m_open, m_close = running, running + MONTHLY_NET
                filename = f"statement_2026_{m_idx:02d}_{uuid.uuid4().hex[:6]}.csv"
                uploaded_filenames.append(filename)
                csv_text = "\n".join(
                    [
                        CSV_HEADER,
                        f"{CURRENCY},{p_start},{p_end},{m_open},{m_close},{date(2026, m_idx, 5)},Salary Credit ACME,{MONTHLY_SALARY}",
                        f"{CURRENCY},{p_start},{p_end},{m_open},{m_close},{date(2026, m_idx, 20)},Rent Payment Landlord,-{MONTHLY_RENT}",
                        "",
                    ]
                )
                await upload_parse_and_approve_csv(
                    client,
                    filename=filename,
                    csv_bytes=csv_text.encode("utf-8"),
                    institution="Twelve Month Savings Bank",
                    account_id=account_id,
                    dispositions=DISPOSITIONS,
                    expected_txns=2,
                    reconnects=reconnects,
                    get=_reconnecting_get,
                    envelope=FixtureEnvelope(
                        currency=CURRENCY,
                        period_start=p_start,
                        period_end=p_end,
                        opening_balance=m_open,
                        closing_balance=m_close,
                        rationale="The generated monthly CSV declares these source facts.",
                    ),
                )
                running = m_close

            bs = await get_json(
                client,
                "/reports/balance-sheet",
                reconnects=reconnects,
                as_of_date=YEAR_END,
                currency=CURRENCY,
            )
            assert (
                bs["is_balanced"] is True
                and Decimal(str(bs["equation_delta"])) == Decimal("0.00")
                and Decimal(str(bs["total_assets"])) == EXPECTED_ENDING_CASH
                and Decimal(str(bs["total_equity"])) + Decimal(str(bs["net_income"]))
                == EXPECTED_ENDING_CASH
            )
            inc = await get_json(
                client,
                "/reports/income-statement",
                reconnects=reconnects,
                start_date=YEAR_START,
                end_date=YEAR_END,
                currency=CURRENCY,
            )
            assert (
                Decimal(str(inc["total_income"])),
                Decimal(str(inc["total_expenses"])),
                Decimal(str(inc["net_income"])),
            ) == (EXPECTED_TOTAL_INCOME, EXPECTED_TOTAL_EXPENSES, EXPECTED_NET_INCOME)
            cf = (
                await get_json(
                    client,
                    "/reports/cash-flow",
                    reconnects=reconnects,
                    start_date=YEAR_START,
                    end_date=YEAR_END,
                    currency=CURRENCY,
                )
            )["summary"]
            assert (
                Decimal(str(cf["beginning_cash"])),
                Decimal(str(cf["net_cash_flow"])),
                Decimal(str(cf["ending_cash"])),
            ) == (INITIAL_OPENING_BALANCE, EXPECTED_NET_INCOME, EXPECTED_ENDING_CASH)
            assert (
                await post_json(
                    client,
                    "/reports/package/snapshots",
                    json={
                        "start_date": YEAR_START,
                        "end_date": YEAR_END,
                        "as_of_date": YEAR_END,
                        "currency": CURRENCY,
                    },
                    expected_status=(200,),
                )
            )["status"] == "trusted"
            assert (
                len(
                    [
                        s
                        for s in (
                            await get_json(client, "/statements", reconnects=reconnects)
                        )["items"]
                        if s["status"] == "approved"
                    ]
                )
                == TOTAL_MONTHS
            )

        await page.goto(
            get_url(f"/reports?tab=balance-sheet&end={YEAR_END}&currency={CURRENCY}"),
            wait_until="domcontentloaded",
        )
        for sel in ("#assets", "#equity"):
            await expect(page.locator(sel)).to_contain_text(
                f"{EXPECTED_ENDING_CASH:,.2f}", timeout=30000
            )
        await page.goto(
            get_url(
                f"/reports?tab=income-statement&start={YEAR_START}&end={YEAR_END}&currency={CURRENCY}"
            ),
            wait_until="domcontentloaded",
        )
        for label, val in (
            ("Total Income", EXPECTED_TOTAL_INCOME),
            ("Total Expenses", EXPECTED_TOTAL_EXPENSES),
            ("Net Income", EXPECTED_NET_INCOME),
        ):
            await expect(page.locator(".card").filter(has_text=label)).to_contain_text(
                f"{val:,.2f}", timeout=30000
            )
        await page.goto(
            get_url(
                f"/reports?tab=cash-flow&start={YEAR_START}&end={YEAR_END}&currency={CURRENCY}"
            ),
            wait_until="domcontentloaded",
        )
        for caption, val in (
            ("Net Cash Flow", EXPECTED_NET_INCOME),
            ("Ending Cash", EXPECTED_ENDING_CASH),
        ):
            await expect(
                page.locator(".card").filter(has=page.get_by_text(caption, exact=True))
            ).to_contain_text(f"{val:,.2f}", timeout=30000)
            await expect(page.get_by_label("Cash reconciliation")).to_contain_text(
                f"{val:,.2f}", timeout=30000
            )
        await page.goto(get_url("/statements"), wait_until="domcontentloaded")
        await page.locator("main").wait_for(state="visible", timeout=30000)
        await expect(page.get_by_text(f"{TOTAL_MONTHS} total")).to_be_visible(
            timeout=30000
        )
        for expected_filename in uploaded_filenames:
            row = page.locator(".relative.block").filter(has_text=expected_filename)
            await expect(row).to_be_visible(timeout=30000)
            await expect(row).to_contain_text("Approved")
        checkpoint(record_property, "U9")
    finally:
        record_property("get_reconnects", reconnects.value)
        print(f"twelve-month journey: GET reconnects = {reconnects.value}")
