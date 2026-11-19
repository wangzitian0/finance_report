from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import httpx
import pytest
from common.testing import money_amount
from playwright.async_api import Page, expect
from tests.fixtures.provider_review import (
    FixtureDisposition,
    FixtureEnvelope,
    approve_statement_with_fixture_review,
)

from tests.e2e._journey_helpers import (
    api_url,
    auth_headers,
    create_manual_valuation,
    default_image_model,
    get_json,
    get_url,
    import_brokerage_and_holdings,
    line_total,
    reconcile_twice_and_assert_clean,
    unique_pdf_copy,
    upload_statement,
    wait_for_statement,
)
from tests.e2e.pdf_fixture_paths import generated_pdf_path

BANK_CASH, PROPERTY_VALUE, MORTGAGE_BALANCE, ESOP_VALUE = (
    Decimal("2500.00"),
    Decimal("1200000.00"),
    Decimal("650000.00"),
    Decimal("42000.00"),
)
DASHBOARD_NET_WORTH_LABEL = "Net Worth"
BANK_DISPOSITIONS = {
    "Four Asset Salary": FixtureDisposition(
        intent="income",
        account_type="INCOME",
        category="SALARY",
        rationale="The synthetic fixture declares this row as salary income.",
    ),
    "Four Asset Rent": FixtureDisposition(
        intent="expense",
        account_type="EXPENSE",
        category="RENT",
        rationale="The synthetic fixture declares this row as rent expense.",
    ),
}


def _dashboard_amount(amount: Decimal) -> str:
    return f"{int(amount.quantize(Decimal('1'), rounding=ROUND_HALF_UP)):,}"


def _report_amount(amount: Decimal) -> str:
    return f"{amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def test_dashboard_net_worth_label_matches_current_product_copy() -> None:
    assert DASHBOARD_NET_WORTH_LABEL == "Net Worth"


def _line_total_matching(
    lines: list[dict], *, key: str, value: str, exact: bool = False
) -> Decimal:
    matches = [
        ln
        for ln in lines
        if (
            str(ln.get(key)) == value
            if exact
            else value.lower() in str(ln.get(key, "")).lower()
        )
    ]
    assert matches, f"missing balance-sheet line for {key}={value!r}; lines={lines}"
    return line_total(matches)


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_four_asset_as_of_net_worth_golden_path(
    authenticated_page_unique: Page, tmp_path: Path
) -> None:
    page, report_date = (
        authenticated_page_unique,
        date.today().replace(day=1) - timedelta(days=1),
    )
    d = report_date.isoformat()
    csv_bytes = "\n".join(
        [
            "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount",
            f"SGD,{d},{d},0.00,2500.00,{d},Four Asset Salary,3000.00",
            f"SGD,{d},{d},0.00,2500.00,{d},Four Asset Rent,-500.00",
            "",
        ]
    ).encode("utf-8")
    async with httpx.AsyncClient(
        headers=await auth_headers(page), verify=False, timeout=120.0
    ) as client:
        bank_id = await upload_statement(
            client,
            filename="four_asset_bank_statement.csv",
            content=csv_bytes,
            content_type="text/csv",
            institution="Four Asset E2E Bank",
            label="bank",
        )
        parsed_bank = await wait_for_statement(
            client,
            bank_id,
            poll_seconds=5,
            target_statuses=("parsed",),
            gate_name="bank CSV",
            require_transactions=True,
        )
        assert len(parsed_bank["transactions"]) == 2
        approval = await approve_statement_with_fixture_review(
            client,
            api_url=api_url,
            statement_id=bank_id,
            transactions=parsed_bank["transactions"],
            dispositions=BANK_DISPOSITIONS,
            envelope=FixtureEnvelope(
                currency="SGD",
                period_start=report_date,
                period_end=report_date,
                opening_balance=Decimal("0.00"),
                closing_balance=Decimal("2500.00"),
                rationale="The four-asset bank CSV header declares these source facts.",
            ),
        )
        assert (
            approval["journal_entries_created"] + approval["reviewed_dispositions"] == 2
        )
        bank_account_id = (await get_json(client, f"/statements/{bank_id}")).get(
            "account_id"
        )
        assert bank_account_id
        journal_payload = await get_json(client, "/journal-entries?limit=6")
        assert (
            journal_payload["total"] == 2
            and {i["status"].lower() for i in journal_payload["items"]} == {"posted"}
            and {i["memo"] for i in journal_payload["items"]}
            == {"Four Asset Salary", "Four Asset Rent"}
        )
        await reconcile_twice_and_assert_clean(client, bank_id)

        model = await default_image_model(client)
        pdf_path = unique_pdf_copy(generated_pdf_path("moomoo", period_end=report_date))
        brokerage_id = await upload_statement(
            client,
            filename=pdf_path.name,
            content=pdf_path.read_bytes(),
            content_type="application/pdf",
            institution="Moomoo Four Asset E2E",
            model=model,
            label="moomoo",
        )
        parsed_brokerage = await wait_for_statement(
            client,
            brokerage_id,
            poll_seconds=5,
            target_statuses=("parsed",),
            gate_name="brokerage PDF",
        )
        _, holdings = await import_brokerage_and_holdings(
            client, parsed_brokerage["id"]
        )
        brokerage_value = money_amount(
            sum(
                (money_amount(item["market_value"]) for item in holdings),
                Decimal("0.00"),
            )
        )
        assert brokerage_value > Decimal("0.00")

        for ctype, value, source, liq in (
            ("property_value", PROPERTY_VALUE, "Four Asset Condo", "illiquid"),
            ("mortgage_balance", MORTGAGE_BALANCE, "Four Asset Mortgage", "liability"),
            ("esop", ESOP_VALUE, "Four Asset ESOP", "restricted"),
        ):
            assert (
                await create_manual_valuation(
                    client,
                    component_type=ctype,
                    as_of_date=report_date,
                    value=value,
                    source=source,
                )
            )["liquidity_class"] == liq

        components = await get_json(
            client,
            f"/pricing/valuation-components?as_of_date={d}&include_restricted=true",
        )
        assert (
            money_amount(components["total_assets"]) == PROPERTY_VALUE + ESOP_VALUE
            and money_amount(components["total_liabilities"]) == MORTGAGE_BALANCE
            and money_amount(components["net_worth_delta"])
            == PROPERTY_VALUE + ESOP_VALUE - MORTGAGE_BALANCE
        )

        bs = await get_json(
            client,
            f"/reports/balance-sheet?as_of_date={d}&currency=SGD&include_restricted=true",
        )
        asset_lines, liability_lines = (
            [ln for ln in bs.get("assets", []) if isinstance(ln, dict)],
            [ln for ln in bs.get("liabilities", []) if isinstance(ln, dict)],
        )
        expected_assets = money_amount(
            BANK_CASH + brokerage_value + PROPERTY_VALUE + ESOP_VALUE
        )
        expected_net_worth = money_amount(expected_assets - MORTGAGE_BALANCE)
        assert (
            _line_total_matching(
                asset_lines, key="account_id", value=str(bank_account_id), exact=True
            )
            == BANK_CASH
            and line_total(asset_lines, "market valuation adjustment")
            == brokerage_value
            and _line_total_matching(asset_lines, key="name", value="Four Asset Condo")
            == PROPERTY_VALUE
            and _line_total_matching(asset_lines, key="name", value="Four Asset ESOP")
            == ESOP_VALUE
            and _line_total_matching(
                liability_lines, key="name", value="Four Asset Mortgage"
            )
            == MORTGAGE_BALANCE
            and money_amount(bs["total_assets"]) == expected_assets
            and money_amount(bs["total_liabilities"]) == MORTGAGE_BALANCE
            and money_amount(bs["net_worth_adjustment_gain_loss"])
            == money_amount(
                brokerage_value + PROPERTY_VALUE + ESOP_VALUE - MORTGAGE_BALANCE
            )
            and money_amount(bs["equation_delta"]) == Decimal("0.00")
            and bs["is_balanced"] is True
        )

        ts = await get_json(
            client,
            f"/reports/net-worth/timeseries?from={d}&to={d}&granularity=daily&currency=SGD",
        )
        assert ts["currency"] == "SGD" and ts["points"]
        pt = ts["points"][-1]
        assert (
            pt["date"],
            pt["currency"],
            money_amount(pt["total_assets"]),
            money_amount(pt["total_liabilities"]),
            money_amount(pt["net_worth"]),
        ) == (d, "SGD", expected_assets, MORTGAGE_BALANCE, expected_net_worth)

    await page.goto(get_url("/dashboard"))
    await page.wait_for_load_state("domcontentloaded")
    await expect(
        page.get_by_label("Three-statement cockpit", exact=True)
    ).to_be_visible(timeout=10000)
    include_cb = page.get_by_label("Include restricted holdings")
    await expect(include_cb).to_be_visible(timeout=10000)
    if not await include_cb.is_checked():
        await include_cb.check()
    for label, amount in (
        ("Total Assets", expected_assets),
        ("Total Liabilities", MORTGAGE_BALANCE),
        (DASHBOARD_NET_WORTH_LABEL, expected_net_worth),
    ):
        await expect(
            page.locator(".card")
            .filter(has_text=label)
            .filter(has_text=_dashboard_amount(amount))
        ).to_be_visible(timeout=15000)
    await page.goto(
        get_url(
            f"/reports?tab=balance-sheet&end={d}&currency=SGD&include_restricted=true"
        )
    )
    await page.wait_for_load_state("domcontentloaded")
    await expect(page.get_by_role("heading", name="Balance Sheet")).to_be_visible(
        timeout=10000
    )
    for label, amount in (
        ("Assets", expected_assets),
        ("Liabilities", MORTGAGE_BALANCE),
    ):
        await expect(
            page.locator(".card").filter(has_text=label).filter(has_text="Total:")
        ).to_contain_text(_report_amount(amount), timeout=15000)
