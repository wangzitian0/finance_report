from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from io import StringIO
from urllib.parse import quote

import httpx
import pytest
from common.testing import money_amount
from playwright.async_api import Page, expect
from tests.fixtures.personal_report_package import REPRESENTATIVE_PACKAGE_FIXTURE
from tests.fixtures.provider_review import (
    FixtureDisposition,
    FixtureEnvelope,
    approve_statement_with_fixture_review,
)

from tests.e2e._journey_helpers import (
    api_url,
    auth_headers,
    create_manual_valuation,
    get_json,
    get_url,
    import_brokerage_and_holdings,
    line_total,
    post_json,
    reconcile_twice_and_assert_clean,
    unique_pdf_copy,
    upload_statement,
    wait_for_statement,
)
from tests.e2e.pdf_fixture_paths import generated_pdf_path

PACKAGE_FIXTURE = REPRESENTATIVE_PACKAGE_FIXTURE
BANK_DISPOSITIONS = {
    "Salary": FixtureDisposition(
        "income", "INCOME", "The synthetic fixture declares salary income.", "SALARY"
    ),
    "Freelance": FixtureDisposition(
        "income",
        "INCOME",
        "The synthetic fixture declares freelance income.",
        "FREELANCE",
    ),
    "Rent": FixtureDisposition(
        "expense", "EXPENSE", "The synthetic fixture declares rent expense.", "RENT"
    ),
    "Groceries": FixtureDisposition(
        "expense",
        "EXPENSE",
        "The synthetic fixture declares grocery expense.",
        "GROCERIES",
    ),
    "Utilities": FixtureDisposition(
        "expense",
        "EXPENSE",
        "The synthetic fixture declares utility expense.",
        "UTILITIES",
    ),
    "Travel": FixtureDisposition(
        "expense", "EXPENSE", "The synthetic fixture declares travel expense.", "TRAVEL"
    ),
}
MANUAL_SPECS = (
    ("property_value", "Family Home", "illiquid"),
    ("mortgage_balance", "Home Loan", "liability"),
    ("esop", "ACME ESOP", "restricted"),
    ("rsu", "ACME RSU", "restricted"),
    ("stock_options", "ACME Options", "restricted"),
)


def _assert_csv_totals(content: str, expected_totals: dict[str, Decimal]) -> None:
    rows = {
        row.get("section"): money_amount(row["amount"])
        for row in csv.DictReader(StringIO(content))
        if row.get("section")
    }
    for section, expected_value in expected_totals.items():
        assert section in rows and rows[section] == expected_value, (
            f"CSV mismatch for {section}: got {rows.get(section)}, expected {expected_value}"
        )


async def _all_evidence_pages(
    client: httpx.AsyncClient, path: str, query: str, item_key: str
) -> list[dict]:
    items, offset = [], 0
    while True:
        page = await get_json(client, f"{path}?{query}&limit=500&offset={offset}")
        items.extend(page[item_key])
        offset += 500
        if offset >= page["total"]:
            return items


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_personal_financial_report_package_post_merge_journey(
    authenticated_page_unique: Page,
) -> None:
    page, expected = authenticated_page_unique, PACKAGE_FIXTURE.expected_outputs
    p_start, p_end = expected.period_start, expected.period_end
    async with httpx.AsyncClient(
        headers=await auth_headers(page), verify=False, timeout=120.0
    ) as client:
        csv_path = PACKAGE_FIXTURE.bank.csv_path
        bank_id = await upload_statement(
            client,
            filename=csv_path.name,
            content=csv_path.read_bytes(),
            content_type="text/csv",
            institution=PACKAGE_FIXTURE.bank.institution,
            label="bank",
        )
        parsed_bank = await wait_for_statement(
            client,
            bank_id,
            poll_seconds=5,
            gate_name="bank CSV",
            require_transactions=True,
        )
        assert len(parsed_bank["transactions"]) == expected.transaction_count
        if parsed_bank.get("status") != "approved":
            approval = await approve_statement_with_fixture_review(
                client,
                api_url=api_url,
                statement_id=bank_id,
                transactions=parsed_bank["transactions"],
                dispositions=BANK_DISPOSITIONS,
                envelope=FixtureEnvelope(
                    currency="SGD",
                    period_start=date(2026, 5, 1),
                    period_end=date(2026, 5, 31),
                    opening_balance=Decimal("0.00"),
                    closing_balance=Decimal("0.00"),
                    rationale="Confirmed against the generated CSV header and its six transactions.",
                ),
            )
            assert (
                approval["journal_entries_created"] + approval["reviewed_dispositions"]
                == expected.transaction_count
            )
        journal_payload = await get_json(client, "/journal-entries?limit=20")
        assert (
            journal_payload["total"] == expected.transaction_count
            and len(journal_payload["items"]) == expected.transaction_count
        )
        allowed_types = {
            "manual",
            "user_confirmed",
            "auto_matched",
            "auto_parsed",
            "bank_statement",
        }
        for txn_id in {str(t["id"]) for t in parsed_bank["transactions"]}:
            related = [
                e for e in journal_payload["items"] if str(e.get("source_id")) == txn_id
            ]
            assert (
                related
                and {e.get("status") for e in related} <= {"posted", "reconciled"}
                and {str(e.get("source_type")) for e in related} <= allowed_types
            )
        await reconcile_twice_and_assert_clean(client, bank_id)

        pdf_path = unique_pdf_copy(
            generated_pdf_path(PACKAGE_FIXTURE.brokerage.source, period_end=p_end)
        )
        brokerage_id = await upload_statement(
            client,
            filename=pdf_path.name,
            content=pdf_path.read_bytes(),
            content_type="application/pdf",
            institution=PACKAGE_FIXTURE.brokerage.institution,
            label=PACKAGE_FIXTURE.brokerage.source,
        )
        parsed_brokerage = await wait_for_statement(
            client, brokerage_id, poll_seconds=5, gate_name="brokerage PDF"
        )
        _, holdings = await import_brokerage_and_holdings(
            client, parsed_brokerage["id"]
        )
        brokerage_value = sum(
            (money_amount(item["market_value"]) for item in holdings), Decimal("0.00")
        )
        assert (
            len(holdings) == expected.brokerage_position_count
            and brokerage_value == expected.brokerage_market_value
        )

        primary = holdings[0]
        assert (
            await post_json(
                client,
                "/pricing/price-overrides",
                json={
                    "updates": [
                        {
                            "asset_identifier": primary["asset_identifier"],
                            "price": str(expected.market_price),
                            "currency": primary["currency"],
                            "price_date": expected.market_price_date.isoformat(),
                        }
                    ]
                },
                expected_status=(200,),
            )
        )["updated_count"] == 1
        div = await post_json(
            client,
            f"/portfolio/{quote(primary['asset_identifier'], safe='')}/dividends",
            json={
                "payment_date": p_end.isoformat(),
                "amount": str(expected.dividend_income),
                "currency": primary["currency"],
            },
            expected_status=(201,),
        )
        assert money_amount(div["amount"]) == expected.dividend_income

        schedule = await get_json(
            client,
            f"/portfolio/performance/report-schedule?period_start={p_start.isoformat()}&period_end={p_end.isoformat()}&as_of_date={p_end.isoformat()}&currency=SGD",
        )
        assert (
            schedule["period_start"],
            schedule["period_end"],
            schedule["as_of_date"],
            schedule["currency"],
        ) == (p_start.isoformat(), p_end.isoformat(), p_end.isoformat(), "SGD")
        assert (
            schedule["holdings"]
            and schedule["notes"]
            and any(
                link.startswith("price_source:") for link in schedule["source_links"]
            )
        )
        assert (
            money_amount(schedule["dividend_income"]) == expected.dividend_income
            and money_amount(schedule["holdings"][0]["dividend_income"])
            == expected.dividend_income
        )
        # The fixture records no purchase: cost and profit are empty, not a number (#2920, #2923).
        assert (
            schedule["unrealized_pnl"],
            {(row["cost_basis"], row["unrealized_pnl"]) for row in schedule["holdings"]},
            sum(1 for note in schedule["notes"] if note.startswith("No purchase is recorded for ")),
        ) == (None, {(None, None)}, len(schedule["holdings"]))
        assert (
            schedule["data_freshness"]["manual_override_basis"]
            == f"{primary['asset_identifier']}:{expected.market_price_date.isoformat()}"
        )
        assert (
            date.fromisoformat(schedule["data_freshness"]["latest_price_date"])
            >= expected.market_price_date
        )

        await page.goto(get_url("/portfolio"))
        await expect(
            page.get_by_text("Investment Performance Report Schedule")
        ).to_be_visible()
        await expect(
            page.get_by_text("investment_performance", exact=True)
        ).to_be_visible()

        components = [
            PACKAGE_FIXTURE.component(ctype, label) for ctype, label, _ in MANUAL_SPECS
        ]
        for (ctype, _, expected_liq), comp in zip(MANUAL_SPECS, components):
            assert (
                await create_manual_valuation(
                    client,
                    component_type=ctype,
                    as_of_date=p_end,
                    value=comp.value,
                    source=comp.source,
                    notes=comp.notes,
                )
            )["liquidity_class"] == expected_liq

        manual_components = await get_json(
            client,
            f"/pricing/valuation-components?as_of_date={p_end.isoformat()}&include_restricted=true",
        )
        values_by_key = {
            (item["component_type"], item["source"]): money_amount(item["value"])
            for item in manual_components["items"]
        }
        assert all(
            values_by_key[ctype, comp.source] == comp.value
            for (ctype, _, _), comp in zip(MANUAL_SPECS, components)
        )
        notes_by_source = {
            s["source"]: s["notes"]
            for s in (
                await get_json(
                    client, f"/pricing/manual-valuations?as_of_date={p_end.isoformat()}"
                )
            )["items"]
        }
        restricted_comps = [
            c for (_, _, liq), c in zip(MANUAL_SPECS, components) if liq == "restricted"
        ]
        assert all(
            notes_by_source[comp.source] == comp.notes for comp in restricted_comps
        )

        pkg_query = f"start_date={p_start.isoformat()}&end_date={p_end.isoformat()}&as_of_date={p_end.isoformat()}&currency=SGD"
        package_doc = await get_json(
            client, f"/reports/package?{pkg_query}&include_restricted=true"
        )
        sections = package_doc["sections"]
        annualized = sections["annualized_income_long_term"]
        assert (
            annualized["section_id"],
            annualized["as_of_date"],
            annualized["trailing_period_days"],
        ) == ("annualized_income_long_term", p_end.isoformat(), 365)
        assert (
            money_amount(annualized["income"]["annualized_total"])
            == money_amount(expected.income)
            and annualized["income"]["currency"] == "SGD"
        )
        assert (
            annualized["income"]["calculation_basis"]
            == "posted_or_reconciled_income_journal_lines_trailing_12_months"
        )
        assert money_amount(annualized["restricted_fair_value_total"]) == sum(
            (c.value for c in restricted_comps), Decimal("0.00")
        )
        assert (
            annualized["net_worth_treatment"]["liquid_net_worth_default"]
            == "exclude_restricted_holdings"
        )
        ann_holdings = {h["ticker"]: h for h in annualized["restricted_holdings"]}
        assert all(
            ann_holdings[comp.source]["vesting_schedule"] == comp.notes
            for comp in restricted_comps
        )
        assert {h["compensation_type"] for h in ann_holdings.values()} == {
            "esop",
            "rsu",
            "stock_options",
        }

        notes_sec = sections["notes"]
        assert PACKAGE_FIXTURE.required_note_ids <= {
            n["note_id"] for n in notes_sec["notes"]
        }
        non_comp = notes_sec["non_compliance_statement"]
        assert (
            all(
                p in non_comp
                for p in (
                    "not a regulated filing",
                    "not legal advice",
                    "not tax advice",
                )
            )
            and "US GAAP compliant" not in non_comp
            and "HKEX filing" not in non_comp
        )

        trace = sections["traceability_appendix"]
        assert trace["status"] == "ready"
        assert any(
            anchor.get("detail_count", 0) > 0
            for ln in trace["lines"]
            if ln.get("line_id") != "notes.non_compliance_statement"
            for anchor in (ln.get("source_anchor", {}), ln.get("ledger_anchor", {}))
        )
        trace_lines = {line["line_id"]: line for line in trace["lines"]}
        assert PACKAGE_FIXTURE.required_traceability_line_ids <= set(trace_lines)
        manifest_entries = await _all_evidence_pages(
            client, "/reports/package/manifest-entries", pkg_query, "entries"
        )
        assert (
            len(manifest_entries)
            == package_doc["readiness"]["input_coverage"]["manifest_decision_count"]
        )
        manifest_decisions = {item["decision_id"] for item in manifest_entries}
        for line_id in PACKAGE_FIXTURE.required_traceability_line_ids:
            line = trace_lines[line_id]
            assert (
                line["source_anchor"]["state"] == "available"
                and line["ledger_anchor"]["state"] == "available"
                and line["ledger_anchor"]["entry_statuses"] == ["posted", "reconciled"]
                and line["blocker_codes"] == []
            )
            for anchor_name in ("source_anchor", "ledger_anchor"):
                details = await _all_evidence_pages(
                    client,
                    "/reports/package/line-details",
                    f"{pkg_query}&line_id={line_id}&anchor={anchor_name}",
                    "details",
                )
                assert (
                    len(details) == line[anchor_name]["detail_count"]
                    and details
                    and all(
                        d["review_state"] == "current_authoritative_decision"
                        and d["decision_id"] in manifest_decisions
                        for d in details
                    )
                )
        assert (
            trace_lines["annualized_income_long_term.restricted_fair_value_total"][
                "ledger_anchor"
            ]["state"]
            == "not_applicable"
        )
        assert {"missing_source_anchor", "manual_only_source", "stale_market_data"} <= {
            w["code"] for w in trace["completeness_warnings"]
        }

        exclusive_keys = {
            (item["component_type"], item["source"])
            for item in (
                await get_json(
                    client,
                    f"/pricing/valuation-components?as_of_date={p_end.isoformat()}&include_restricted=false",
                )
            )["items"]
        }
        assert all(
            (ctype, comp.source) not in exclusive_keys
            for (ctype, _, liq), comp in zip(MANUAL_SPECS, components)
            if liq == "restricted"
        )

        expected_assets = expected.total_assets(Decimal("0.00"))
        assert (
            money_amount(manual_components["total_assets"])
            == expected.manual_asset_total
            and money_amount(manual_components["total_liabilities"])
            == expected.manual_liability_total
            and money_amount(manual_components["net_worth_delta"])
            == expected.manual_asset_total - expected.manual_liability_total
        )

        balance = await get_json(
            client,
            f"/reports/balance-sheet?as_of_date={p_end.isoformat()}&currency=SGD&include_restricted=true",
        )
        assert (
            money_amount(balance["total_assets"]) == expected_assets
            and money_amount(balance["total_liabilities"])
            == expected.manual_liability_total
        )
        assert (
            money_amount(balance["total_equity"])
            + money_amount(balance["net_income"])
            + money_amount(balance["unrealized_fx_gain_loss"])
            + money_amount(balance["net_worth_adjustment_gain_loss"])
            == expected_assets - expected.manual_liability_total
        )
        assert (
            money_amount(balance["net_worth_adjustment_gain_loss"])
            == expected.net_worth_adjustment_gain_loss
            and money_amount(balance["equation_delta"]) == Decimal("0.00")
            and balance["is_balanced"] is True
        )
        assert line_total(balance["assets"]) == money_amount(
            balance["total_assets"]
        ) and line_total(balance["liabilities"]) == money_amount(
            balance["total_liabilities"]
        )

        current_balance = await get_json(
            client,
            f"/reports/balance-sheet?as_of_date={date.today().isoformat()}&currency=SGD&include_restricted=true",
        )
        assert money_amount(current_balance["total_assets"]) == expected.total_assets(
            brokerage_value
        ) and money_amount(current_balance["total_assets"]) > money_amount(
            balance["total_assets"]
        )

        income = await get_json(
            client,
            f"/reports/income-statement?start_date={p_start.isoformat()}&end_date={p_end.isoformat()}&currency=SGD",
        )
        assert (
            money_amount(income["total_income"]),
            money_amount(income["total_expenses"]),
            money_amount(income["net_income"]),
        ) == (expected.income, expected.expenses, expected.net_income)
        cash_flow = await get_json(
            client,
            f"/reports/cash-flow?start_date={p_start.isoformat()}&end_date={p_end.isoformat()}&currency=SGD",
        )
        assert (
            money_amount(cash_flow["summary"]["net_cash_flow"]),
            money_amount(cash_flow["summary"]["beginning_cash"]),
            money_amount(cash_flow["summary"]["ending_cash"]),
        ) == (
            money_amount(expected.net_income),
            Decimal("0.00"),
            money_amount(expected.bank_cash),
        )

        for params, expected_csv in (
            (
                {
                    "report_type": "balance-sheet",
                    "format": "csv",
                    "as_of_date": p_end.isoformat(),
                    "currency": "SGD",
                },
                {
                    "Total Assets": money_amount(balance["total_assets"]),
                    "Total Liabilities": money_amount(balance["total_liabilities"]),
                },
            ),
            (
                {
                    "report_type": "income-statement",
                    "format": "csv",
                    "start_date": p_start.isoformat(),
                    "end_date": p_end.isoformat(),
                    "currency": "SGD",
                },
                {
                    "Total Income": money_amount(income["total_income"]),
                    "Total Expenses": money_amount(income["total_expenses"]),
                    "Net Income": money_amount(income["net_income"]),
                },
            ),
        ):
            exp_resp = await client.get(api_url("/reports/exports"), params=params)
            assert (
                exp_resp.status_code == 200
                and "text/csv" in exp_resp.headers["content-type"]
            )
            _assert_csv_totals(exp_resp.text, expected_csv)

    await page.goto(get_url("/"))
    await page.wait_for_load_state("domcontentloaded")
    await expect(
        page.get_by_label("Three-statement cockpit", exact=True)
    ).to_be_visible(timeout=10000)
    for url, heading in (
        (
            f"/reports?tab=balance-sheet&end={p_end.isoformat()}&currency=SGD",
            "Balance Sheet",
        ),
        (
            f"/reports?tab=income-statement&start={p_start.isoformat()}&end={p_end.isoformat()}&currency=SGD",
            "Income Statement",
        ),
        (
            f"/reports?tab=cash-flow&start={p_start.isoformat()}&end={p_end.isoformat()}&currency=SGD",
            "Cash Flow Statement",
        ),
    ):
        await page.goto(get_url(url))
        await page.wait_for_load_state("domcontentloaded")
        await expect(page.get_by_role("heading", name=heading)).to_be_visible(
            timeout=10000
        )
