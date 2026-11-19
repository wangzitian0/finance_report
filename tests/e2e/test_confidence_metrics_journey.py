from __future__ import annotations

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
    get_json,
    get_url,
    post_json,
    upload_parse_and_approve_csv,
    upload_statement,
    wait_for_statement,
)
from tests.e2e.journey_checkpoint import checkpoint

CURRENCY = "SGD"
CSV_HEADER = "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount"
LOW_CONFIDENCE_CSV_HEADER = "Statement Currency,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount"
DISPOSITIONS = {
    "salary credit acme": FixtureDisposition(
        "income", "INCOME", "Monthly salary credit", "SALARY"
    )
}


@pytest.mark.e2e
@pytest.mark.journey
async def test_proportion_of_low_confidence_data_is_measured(
    authenticated_page_unique: Page, record_property
) -> None:
    page = authenticated_page_unique
    async with httpx.AsyncClient(
        headers=await auth_headers(page), verify=False, timeout=120.0
    ) as client:
        await assert_pinned_via_client(client, record_property)
        account_id = await create_account(
            client, "Confidence Metrics Savings", currency=CURRENCY
        )
        valid_filename = f"confidence_valid_{uuid.uuid4().hex[:6]}.csv"
        valid_csv = "\n".join(
            [
                CSV_HEADER,
                "SGD,2026-01-01,2026-01-31,10000.00,20000.00,2026-01-05,Salary Credit ACME,5000.00",
                "SGD,2026-01-01,2026-01-31,10000.00,20000.00,2026-01-20,Salary Credit ACME,5000.00",
                "",
            ]
        )
        valid_id, valid_parsed = await upload_parse_and_approve_csv(
            client,
            filename=valid_filename,
            csv_bytes=valid_csv.encode("utf-8"),
            institution="Confidence Valid Bank",
            account_id=account_id,
            dispositions=DISPOSITIONS,
            expected_txns=2,
            envelope=FixtureEnvelope(
                currency=CURRENCY,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                opening_balance=Decimal("10000.00"),
                closing_balance=Decimal("20000.00"),
                rationale="The generated CSV declares these source facts.",
            ),
        )
        assert (
            valid_parsed["balance_validated"] is True
            and valid_parsed["confidence_score"] >= 50
        )
        assert await post_json(
            client,
            "/reconciliation/runs",
            json={"statement_id": valid_id},
            expected_status=(200,),
        ) == {
            "matches_created": 0,
            "auto_accepted": 0,
            "pending_review": 0,
            "unmatched": 0,
        }
        for txn in valid_parsed["transactions"]:
            await post_json(
                client,
                "/statements/corrections",
                json={"transaction_id": txn["id"], "corrected_category": "SALARY"},
                expected_status=(201,),
            )

        low_filename = f"confidence_low_{uuid.uuid4().hex[:6]}.csv"
        low_csv = "\n".join(
            [
                LOW_CONFIDENCE_CSV_HEADER,
                "SGD,20000.00,99999.00,2026-02-10,Unverified Expense,-500.00",
                "",
            ]
        )
        low_id = await upload_statement(
            client,
            filename=low_filename,
            content=low_csv.encode("utf-8"),
            content_type="text/csv",
            institution="Confidence Low Score Bank",
            account_id=account_id,
        )
        low_parsed = await wait_for_statement(
            client,
            low_id,
            poll_seconds=0.5,
            target_statuses=("parsed", "approved", "rejected"),
            fail_statuses=(),
        )
        assert (
            low_parsed["balance_validated"] is False
            and low_parsed["confidence_score"] < 50
            and len(low_parsed["transactions"]) == 1
        )

        replay = await get_json(client, "/statements/correction-loop/replay")
        prop_before, prop_after = (
            Decimal(str(replay["proportion_before"])),
            Decimal(str(replay["proportion_after"])),
        )
        assert (
            replay["holdout_size"] == 1
            and replay["grounded"] == 1
            and prop_before == Decimal("1.00000")
            and prop_after == Decimal("0.00000")
            and replay["reduced"] is True
        )
        stats = await get_json(client, "/reconciliation/stats")
        match_rate = Decimal(str(stats["match_rate"]))
        assert (
            stats["total_transactions"],
            stats["matched_transactions"],
            stats["unmatched_transactions"],
            match_rate,
        ) == (2, 2, 0, Decimal("100.00"))

        scoped = await get_json(
            client, "/reconciliation/unmatched", statement_id=low_id
        )
        assert (
            scoped["total"] == 1
            and [i["id"] for i in scoped["items"]]
            == [low_parsed["transactions"][0]["id"]]
            and (await get_json(client, "/reconciliation/unmatched"))["total"] == 0
        )
        stmts = (await get_json(client, "/statements"))["items"]
        low_count = sum(
            1
            for s in stmts
            if (s["confidence_score"] is not None and s["confidence_score"] < 50)
            or s["balance_validated"] is False
        )
        ratio = Decimal(low_count) / Decimal(len(stmts))
        assert len(stmts) == 2 and low_count == 1 and ratio == Decimal("0.5")

    await page.goto(get_url("/audit?tab=health"), wait_until="domcontentloaded")
    for phrase in (
        "Correction Loop Proof",
        "Accuracy on Past Edits",
        "Improves extraction",
        "Before correction reuse",
        "100.0%",
        "After correction reuse",
        "0.0%",
    ):
        await expect(page.locator("main")).to_contain_text(phrase, timeout=30000)
    await page.goto(get_url("/statements"), wait_until="domcontentloaded")
    await page.locator("main").wait_for(state="visible", timeout=30000)
    await expect(page.get_by_text("2 total")).to_be_visible(timeout=30000)
    for fname, status_label in (
        (valid_filename, "Approved"),
        (low_filename, "Ready to review"),
    ):
        row = page.locator(".relative.block").filter(has_text=fname)
        await expect(row).to_be_visible(timeout=30000)
        await expect(row).to_contain_text(status_label)
    for k, v in {
        "replay_proportion_before": str(prop_before),
        "replay_proportion_after": str(prop_after),
        "replay_reduced": str(replay["reduced"]),
        "statement_low_confidence_ratio": str(ratio),
        "reconciliation_match_rate": str(match_rate),
    }.items():
        record_property(k, v)
    checkpoint(record_property, "U13")
