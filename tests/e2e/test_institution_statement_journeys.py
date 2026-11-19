from __future__ import annotations

import csv
import io
import json
import re
import time
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

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
    assert_pinned_via_client,
    assert_statement_rows_equal,
    auth_headers,
    create_opening_balances,
    default_image_model,
    get_json,
    get_url,
    post_json,
    unique_pdf_copy,
    upload_statement,
    wait_for_statement,
)
from tests.e2e.description_fidelity import description_misreads, format_misread_line
from tests.e2e.journey_checkpoint import checkpoint
from tests.e2e.pdf_fixture_paths import committed_fixture_pdf
from tests.e2e.transport_retry import ReconnectCount, get_with_reconnect

EXPECTED_DIR = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pdf" / "generated"
)
PINGAN_KNOWN_DESCRIPTION_MISREADS = 2

CMB_DISPOSITIONS = {
    "工资入账": FixtureDisposition(
        "income", "INCOME", "The CMB fixture declares salary income.", "SALARY"
    ),
    "转账-房租": FixtureDisposition(
        "expense", "EXPENSE", "The CMB fixture declares rent expense.", "RENT"
    ),
    "微信支付-超市": FixtureDisposition(
        "expense", "EXPENSE", "The CMB fixture declares grocery expense.", "GROCERIES"
    ),
    "转账-父母": FixtureDisposition(
        "expense",
        "EXPENSE",
        "The CMB fixture declares family-support expense.",
        "FAMILY_SUPPORT",
    ),
    "报销入账": FixtureDisposition(
        "expense_refund",
        "EXPENSE",
        "The CMB fixture declares an expense reimbursement.",
        "REIMBURSEMENT",
    ),
    "水电费代扣": FixtureDisposition(
        "expense", "EXPENSE", "The CMB fixture declares utility expense.", "UTILITIES"
    ),
    "利息收入": FixtureDisposition(
        "income", "INCOME", "The CMB fixture declares interest income.", "INTEREST"
    ),
    "交易": FixtureDisposition(
        "expense", "EXPENSE", "CMB generic transaction", "SHOPPING"
    ),
}
MARIBANK_DISPOSITIONS = {
    "PayNow to KOPI SHOP PTE LTD": FixtureDisposition(
        "expense", "EXPENSE", "The MariBank fixture declares dining expense.", "DINING"
    ),
    "Interest Credited": FixtureDisposition(
        "income", "INCOME", "The MariBank fixture declares interest income.", "INTEREST"
    ),
    "PayNow to RIDE-HAIL SERVICES": FixtureDisposition(
        "expense",
        "EXPENSE",
        "The MariBank fixture declares transport expense.",
        "TRANSPORT",
    ),
    "Credit Card Repayment": FixtureDisposition(
        "card_repayment",
        "LIABILITY",
        "The MariBank fixture declares a credit-card repayment.",
    ),
    "PayNow from LEE WEI": FixtureDisposition(
        "income",
        "INCOME",
        "The MariBank fixture declares external miscellaneous income.",
        "OTHER_INCOME",
    ),
    "PayNow to ONLINE GROCER": FixtureDisposition(
        "expense",
        "EXPENSE",
        "The MariBank fixture declares grocery expense.",
        "GROCERIES",
    ),
}
PINGAN_DISPOSITIONS = {
    "工资代发": FixtureDisposition(
        "income", "INCOME", "The Pingan fixture declares salary income.", "SALARY"
    ),
    "转账汇款": FixtureDisposition(
        "expense",
        "EXPENSE",
        "The Pingan fixture declares this generated external transfer as family-support expense.",
        "FAMILY_SUPPORT",
    ),
    "快捷支付": FixtureDisposition(
        "expense",
        "EXPENSE",
        "The Pingan fixture declares shopping expense.",
        "SHOPPING",
    ),
    "信用卡还款": FixtureDisposition(
        "card_repayment",
        "LIABILITY",
        "The Pingan fixture declares a credit-card repayment.",
    ),
    "账户结息": FixtureDisposition(
        "income", "INCOME", "The Pingan fixture declares interest income.", "INTEREST"
    ),
    "账户信息": FixtureDisposition(
        "income",
        "INCOME",
        "The Pingan fixture declares interest income. The vision model reads 账户结息 as 账户信息 (#2932).",
        "INTEREST",
    ),
    "基金申购": FixtureDisposition(
        "investment_purchase",
        "ASSET",
        "The Pingan fixture declares an investment purchase.",
    ),
    "基金赎回": FixtureDisposition(
        "investment_sale", "ASSET", "The Pingan fixture declares an investment sale."
    ),
}
GXS_DISPOSITIONS = {
    "Interest Earned": FixtureDisposition(
        "income", "INCOME", "The GXS fixture declares interest income.", "INTEREST"
    ),
    "PayNow from ALVIN GOH": FixtureDisposition(
        "income",
        "INCOME",
        "The GXS fixture declares external miscellaneous income.",
        "OTHER_INCOME",
    ),
    "Payment to GrabPay Wallet": FixtureDisposition(
        "expense", "EXPENSE", "The GXS fixture declares transport expense.", "TRANSPORT"
    ),
    "PayNow to MERCHANT HAWKER": FixtureDisposition(
        "expense", "EXPENSE", "The GXS fixture declares dining expense.", "DINING"
    ),
}


def _fixture_envelope(expected: dict, rationale: str) -> FixtureEnvelope:
    src = expected["statement"]
    return FixtureEnvelope(
        currency=src["currency"],
        period_start=date.fromisoformat(src["period_start"]),
        period_end=date.fromisoformat(src["period_end"]),
        opening_balance=Decimal(src["opening_balance"]),
        closing_balance=Decimal(src["closing_balance"]),
        rationale=rationale,
    )


async def _run_institution_journey(
    page: Page,
    *,
    pdf_path: Path,
    institution: str,
    min_transactions: int,
    dispositions: dict[str, FixtureDisposition],
    record_property: Callable[[str, object], None] | None = None,
    reconnects: ReconnectCount | None = None,
    envelope: FixtureEnvelope | None = None,
    expected_events: list[dict] | None = None,
    known_description_misreads: int = 0,
) -> dict:
    active_reconnects = reconnects or ReconnectCount()
    async with httpx.AsyncClient(
        headers=await auth_headers(page), verify=False, timeout=120.0
    ) as client:
        model = await default_image_model(client, reconnects=active_reconnects)
        if record_property:
            record_property("selected_ocr_model", model)
        pdf_copy = unique_pdf_copy(pdf_path)
        statement_id = await upload_statement(
            client,
            filename=pdf_copy.name,
            content=pdf_copy.read_bytes(),
            content_type="application/pdf",
            institution=institution,
            model=model,
            label=institution,
        )
        if record_property:
            checkpoint(record_property, "U1")
        parsed = await wait_for_statement(
            client,
            statement_id,
            poll_seconds=5,
            gate_name="institution journey",
            model=model,
            reconnects=active_reconnects,
        )
        transactions = parsed.get("transactions") or []
        assert len(transactions) >= min_transactions, (
            f"{institution}: expected >= {min_transactions}, got {len(transactions)}"
        )
        if expected_events is not None:
            misreads = description_misreads(transactions, expected_events)
            print(
                format_misread_line(
                    misreads, known_description_misreads, len(transactions)
                )
            )
            if record_property:
                record_property("description_misreads", len(misreads))
            assert len(misreads) <= known_description_misreads, format_misread_line(
                misreads, known_description_misreads, len(transactions)
            )
        if parsed.get("status") == "approved":
            props = {
                "required_economic_review_decisions": 0,
                "required_statement_approvals": 0,
                "statement_approval_api_attempts": 0,
            }
        else:

            async def _reconnecting_get(url: str) -> httpx.Response:
                return await get_with_reconnect(client, url, active_reconnects)

            approval = await approve_statement_with_fixture_review(
                client,
                api_url=api_url,
                statement_id=statement_id,
                transactions=transactions,
                dispositions=dispositions,
                envelope=envelope,
                get=_reconnecting_get,
            )
            assert approval.get("status") == "approved"
            reviewed = approval.get("reviewed_dispositions", 0)
            props = {
                "required_economic_review_decisions": reviewed,
                "required_statement_approvals": 1,
                "statement_approval_api_attempts": 2 if reviewed else 1,
            }
        if record_property:
            for k, v in props.items():
                record_property(k, v)
        assert (
            await get_json(
                client, "/reports/balance-sheet", reconnects=active_reconnects
            )
        ).get("is_balanced") is True
        return parsed


async def _run_reported_journey(
    page: Page,
    record_property: Callable[[str, object], None],
    label: str,
    **kwargs: Any,
) -> dict:
    reconnects = ReconnectCount()
    try:
        return await _run_institution_journey(
            page, record_property=record_property, reconnects=reconnects, **kwargs
        )
    finally:
        record_property("get_reconnects", reconnects.value)
        print(f"{label} journey: GET reconnects = {reconnects.value}")


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_cmb_statement_journey(
    authenticated_page_unique: Page, record_property
) -> None:
    expected = json.loads(
        (EXPECTED_DIR / "cmb_statement_fixture_expected.json").read_text()
    )
    await _run_reported_journey(
        authenticated_page_unique,
        record_property,
        "CMB",
        pdf_path=committed_fixture_pdf("cmb_statement_fixture.pdf"),
        institution="CMB E2E Institution Journey",
        min_transactions=len(expected["events"]),
        dispositions=CMB_DISPOSITIONS,
        envelope=_fixture_envelope(
            expected, "The CMB fixture JSON declares these source facts."
        ),
    )


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_maribank_statement_journey(
    authenticated_page_unique: Page, record_property
) -> None:
    expected = json.loads(
        (EXPECTED_DIR / "maribank_statement_fixture_expected.json").read_text()
    )
    await _run_reported_journey(
        authenticated_page_unique,
        record_property,
        "MariBank",
        pdf_path=committed_fixture_pdf("maribank_statement_fixture.pdf"),
        institution="MariBank E2E Institution Journey",
        min_transactions=len(expected["events"]),
        dispositions=MARIBANK_DISPOSITIONS,
        envelope=_fixture_envelope(
            expected, "The MariBank fixture JSON declares these source facts."
        ),
    )


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_pingan_statement_journey(
    authenticated_page_unique: Page, record_property
) -> None:
    expected = json.loads(
        (EXPECTED_DIR / "pingan_statement_fixture_expected.json").read_text()
    )
    await _run_reported_journey(
        authenticated_page_unique,
        record_property,
        "Pingan",
        pdf_path=committed_fixture_pdf("pingan_statement_fixture.pdf"),
        institution="Pingan E2E Institution Journey",
        min_transactions=len(expected["events"]),
        dispositions=PINGAN_DISPOSITIONS,
        envelope=_fixture_envelope(
            expected, "The Pingan fixture JSON declares these source facts."
        ),
        expected_events=expected["events"],
        known_description_misreads=PINGAN_KNOWN_DESCRIPTION_MISREADS,
    )


@pytest.mark.e2e
@pytest.mark.tier3
@pytest.mark.critical
@pytest.mark.llm
async def test_gxs_statement_journey_matches_expected_balances(
    authenticated_page_unique: Page, record_property
) -> None:
    started, reconnects = time.monotonic(), ReconnectCount()
    expected = json.loads(
        (EXPECTED_DIR / "gxs_statement_fixture_expected.json").read_text()
    )
    expected_stmt = expected["statement"]
    try:
        async with httpx.AsyncClient(
            headers=await auth_headers(authenticated_page_unique),
            verify=False,
            timeout=120.0,
        ) as client:
            await assert_pinned_via_client(
                client,
                record_property,
                reconnects=reconnects,
                reason="complete live happy-flow proof",
            )
        parsed = await _run_institution_journey(
            authenticated_page_unique,
            pdf_path=committed_fixture_pdf("gxs_statement_fixture.pdf"),
            institution="GXS E2E Institution Journey",
            min_transactions=len(expected["events"]),
            dispositions=GXS_DISPOSITIONS,
            record_property=record_property,
            reconnects=reconnects,
        )
        assert Decimal(str(parsed["opening_balance"])) == Decimal(
            expected_stmt["opening_balance"]
        ) and Decimal(str(parsed["closing_balance"])) == Decimal(
            expected_stmt["closing_balance"]
        )
        await _assert_saved_gxs_package(
            authenticated_page_unique,
            parsed=parsed,
            expected=expected,
            record_property=record_property,
            reconnects=reconnects,
        )
        record_property(
            "happy_flow_elapsed_seconds", round(time.monotonic() - started, 2)
        )
    finally:
        record_property("get_reconnects", reconnects.value)
        print(f"GXS journey: GET reconnects = {reconnects.value}")


async def _assert_saved_gxs_package(
    page: Page,
    *,
    parsed: dict,
    expected: dict,
    record_property,
    reconnects: ReconnectCount,
) -> None:
    source = expected["statement"]
    async with httpx.AsyncClient(
        headers=await auth_headers(page), verify=False, timeout=120.0
    ) as client:
        await assert_pinned_via_client(
            client,
            record_property,
            reconnects=reconnects,
            reason="complete live happy-flow proof",
        )
        assert_statement_rows_equal(parsed["transactions"], expected["events"])
        checkpoint(record_property, "U2")

        needs_opening = (
            await get_json(
                client, "/accounts/opening-balance-readiness", reconnects=reconnects
            )
        )["needs_opening_balance"]
        record_property("required_opening_balance_confirmations", int(needs_opening))
        if needs_opening:
            account_id = (
                await get_json(
                    client, f"/statements/{parsed['id']}", reconnects=reconnects
                )
            )["account_id"]
            assert account_id
            await create_opening_balances(
                client,
                entry_date=(
                    date.fromisoformat(source["period_start"]) - timedelta(days=1)
                ).isoformat(),
                balances={account_id: source["opening_balance"]},
                currency=source["currency"],
                memo="GXS fixture source-declared opening balance",
            )

        entries = (
            await get_json(client, "/journal-entries?limit=100", reconnects=reconnects)
        )["items"]
        for txn in parsed["transactions"]:
            effects = [e for e in entries if e["source_id"] == txn["id"]]
            assert (
                len(effects) == 1
                and effects[0]["status"] == "posted"
                and effects[0]["decision_anchor_id"]
            )
        checkpoint(record_property, "U6")

        period = {
            "start_date": source["period_start"],
            "end_date": source["period_end"],
            "as_of_date": source["period_end"],
            "currency": source["currency"],
        }
        snapshot = await post_json(
            client,
            "/reports/package/snapshots",
            json=period,
            expected_status=(200,),
            label="package generation",
        )
        document = snapshot["document"]
        assert (
            snapshot["status"] == "trusted"
            and document["snapshot_id"] == snapshot["id"]
            and document["package_decision_id"]
            and document["input_manifest"]
        )
        assert all(item["decision_id"] for item in document["input_manifest"])
        manifest_refs = {
            ref for item in document["input_manifest"] for ref in item["input_refs"]
        }
        source_review = await get_json(
            client, f"/statements/{parsed['id']}/review", reconnects=reconnects
        )
        source_manifest = [
            item
            for item in document["input_manifest"]
            if any(r.startswith("statement_result:") for r in item["input_refs"])
        ]
        assert (
            len(source_manifest) == 1
            and source_manifest[0]["target_kind"] == "statement_extraction_result"
            and source_manifest[0]["target_version"]
            == source_review["source_result_digest"]
        )
        assert f"account:{source_review['account_id']}" in manifest_refs and any(
            r.startswith("source_document:") for r in source_manifest[0]["input_refs"]
        )
        assert {f"journal_entry:{e['id']}" for e in entries} <= manifest_refs and all(
            snapshot[k] == v for k, v in period.items()
        )

        sections = document["sections"]
        exp_income = sum(
            (
                Decimal(r["amount"])
                for r in expected["events"]
                if r["direction"] == "IN"
            ),
            Decimal("0"),
        )
        exp_expenses = sum(
            (
                Decimal(r["amount"])
                for r in expected["events"]
                if r["direction"] == "OUT"
            ),
            Decimal("0"),
        )
        assert (
            money_amount(
                sections["income_statement"]["total_income"], source["currency"]
            )
            == exp_income
            and money_amount(
                sections["income_statement"]["total_expenses"], source["currency"]
            )
            == exp_expenses
            and money_amount(
                sections["income_statement"]["net_income"], source["currency"]
            )
            == exp_income - exp_expenses
            and money_amount(
                sections["balance_sheet"]["total_assets"], source["currency"]
            )
            == Decimal(source["closing_balance"])
            and sections["balance_sheet"]["is_balanced"] is True
            and money_amount(
                sections["cash_flow"]["summary"]["ending_cash"], source["currency"]
            )
            == Decimal(source["closing_balance"])
            and sections["cash_flow"]["proof_state"] == "proven"
        )
        checkpoint(record_property, "U8")

        selected_path = f"/reports/package/snapshots/{snapshot['id']}"
        assert snapshot["id"] in {
            item["id"]
            for item in await get_json(
                client, "/reports/package/snapshots", reconnects=reconnects
            )
        }
        assert (await get_json(client, selected_path, reconnects=reconnects))[
            "document"
        ] == document
        exported_json, exported_csv = (
            await get_with_reconnect(
                client, api_url(f"{selected_path}/exports?format=json"), reconnects
            ),
            await get_with_reconnect(
                client, api_url(f"{selected_path}/exports?format=csv"), reconnects
            ),
        )
        assert (
            exported_json.status_code == 200
            and exported_json.json()["document"] == document
            and exported_csv.status_code == 200
        )
        csv_rows = list(csv.DictReader(io.StringIO(exported_csv.text)))
        assert csv_rows and {r["line_id"] for r in csv_rows} == {
            ln["line_id"] for ln in sections["traceability_appendix"]["lines"]
        }
        expected_refs = "|".join(
            sorted(
                f"{item['decision_id']}@{ref}"
                for item in document["input_manifest"]
                for ref in item["input_refs"]
            )
        )
        assert all(r["input_decision_references"] == expected_refs for r in csv_rows)
        csv_amounts = {
            r["line_id"]: Decimal(r["amount"]) for r in csv_rows if r["amount"]
        }
        assert (
            csv_amounts["balance_sheet.total_assets"]
            == Decimal(source["closing_balance"])
            and csv_amounts["income_statement.total_income"] == exp_income
            and csv_amounts["income_statement.total_expenses"] == exp_expenses
        )
        checkpoint(record_property, "U11")

        await _post_later_gxs_income(
            client,
            source=source,
            cash_account_id=source_review["account_id"],
            expected_income=exp_income,
            reconnects=reconnects,
        )
        assert (await get_json(client, selected_path, reconnects=reconnects))[
            "document"
        ] == document
        assert (
            await get_with_reconnect(
                client, api_url(f"{selected_path}/exports?format=json"), reconnects
            )
        ).content == exported_json.content
        assert (
            await get_with_reconnect(
                client, api_url(f"{selected_path}/exports?format=csv"), reconnects
            )
        ).content == exported_csv.content
        await _assert_gxs_snapshot_browser(
            page,
            snapshot=snapshot,
            json_bytes=exported_json.content,
            csv_bytes=exported_csv.content,
        )
        checkpoint(record_property, "U10")
        record_property("saved_package_browser_interactions", 5)


async def _post_later_gxs_income(
    client: httpx.AsyncClient,
    *,
    source: dict,
    cash_account_id: str,
    expected_income: Decimal,
    reconnects: ReconnectCount,
) -> None:
    income_account = next(
        (
            item
            for item in (
                await get_json(client, "/accounts?limit=100", reconnects=reconnects)
            )["items"]
            if item["type"] == "INCOME"
        ),
        None,
    )
    assert income_account is not None, (
        "fixture economic review must create an INCOME counter-account"
    )
    draft = await post_json(
        client,
        "/journal-entries",
        json={
            "entry_date": source["period_end"],
            "memo": "Later independent fixture income",
            "rationale": "Generated post-snapshot change verifies frozen artifact stability.",
            "lines": [
                {
                    "account_id": cash_account_id,
                    "direction": "DEBIT",
                    "amount": "1.00",
                    "currency": source["currency"],
                },
                {
                    "account_id": income_account["id"],
                    "direction": "CREDIT",
                    "amount": "1.00",
                    "currency": source["currency"],
                },
            ],
        },
        expected_status=(201,),
    )
    await post_json(
        client, f"/journal-entries/{draft['id']}/postings", expected_status=(200,)
    )
    live = await get_json(
        client,
        "/reports/income-statement",
        reconnects=reconnects,
        start_date=source["period_start"],
        end_date=source["period_end"],
        currency=source["currency"],
    )
    assert money_amount(
        live["total_income"], source["currency"]
    ) == expected_income + Decimal("1.00")


async def _assert_gxs_snapshot_browser(
    page: Page, *, snapshot: dict, json_bytes: bytes, csv_bytes: bytes
) -> None:
    resp = await page.goto(
        get_url(
            f"/reports?tab=package&start={snapshot['start_date']}&end={snapshot['end_date']}"
        )
    )
    assert resp is not None and resp.status == 200
    await page.get_by_role("button", name="US-like", exact=True).click()
    await expect(
        page.get_by_role("heading", name="Saved Package Artifacts")
    ).to_be_visible()
    row = page.get_by_role("row").filter(
        has_text=f"{snapshot['start_date']} to {snapshot['end_date']}"
    )
    await expect(row).to_have_count(1)
    await row.get_by_role("button", name="Reopen", exact=True).click()
    identity = page.get_by_role("region", name="Package document identity")
    await expect(identity).to_contain_text(f"Frozen snapshot {snapshot['id']}")
    await expect(identity).to_contain_text("Trusted")
    for fmt, expected_bytes in (("JSON", json_bytes), ("CSV", csv_bytes)):
        async with page.expect_download() as download_info:
            await row.get_by_role("button", name=re.compile(fmt)).click()
        path = await (await download_info.value).path()
        assert path is not None and Path(path).read_bytes() == expected_bytes
