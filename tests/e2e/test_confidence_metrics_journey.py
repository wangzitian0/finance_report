"""Core-journey proof U13: The proportion of low-confidence data is measured (#2370).

Axiom B (vision.md) establishes the North-Star metric:
"The proportion of low-confidence data trends down over time."

This journey seeds two deterministic CSV statements (one balanced high-confidence
statement and one mismatched low-confidence statement), two user corrections on
recurring descriptions, and a reconciliation run, then proves on the pinned
deployed revision that:
* The live correction feedback loop replay endpoint (/api/metrics/correction-loop/replay)
  measures held-out low-confidence reduction (1.00000 -> 0.00000, reduced is True).
* A reconciliation run after the approval creates no match: the approval already
  posted both rows from their own statement (#2561).
* The reconciliation statistics endpoint (/api/reconciliation/stats) measures
  a non-zero transaction match rate (2 matched out of 3 total transactions = 66.67%).
  The 2 posted rows count as matched without a reconciliation match (#2465).
* The system-wide low-confidence statement ratio is strictly computed from non-empty
  statements (total_statements == 2, low_confidence_statements == 1, ratio == 0.5)
  with no empty-database fallback.
* The browser UI renders the replay metrics on /audit and the uploaded
  statements on /statements.
"""

from __future__ import annotations

import asyncio
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
from playwright.async_api import Page, expect

APP_URL = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT_MS = int(os.getenv("PARSING_TIMEOUT_MS", "480000"))

CURRENCY = "SGD"
EXPECTED_TOTAL_STATEMENTS = 2
EXPECTED_LOW_CONFIDENCE_STATEMENTS = 1
EXPECTED_LOW_CONFIDENCE_RATIO = Decimal("0.5")
EXPECTED_REPLAY_PROPORTION_BEFORE = Decimal("1.00000")
EXPECTED_REPLAY_PROPORTION_AFTER = Decimal("0.00000")
EXPECTED_MATCH_RATE = Decimal("66.67")

# Header mirrors test_twelve_month_journey.CSV_HEADER — update both together.
CSV_HEADER = (
    "Statement Currency,Statement Period Start,Statement Period End,"
    "Statement Opening Balance,Statement Closing Balance,Date,Description,Amount"
)
LOW_CONFIDENCE_CSV_HEADER = (
    "Statement Currency,Statement Opening Balance,Statement Closing Balance,"
    "Date,Description,Amount"
)

DISPOSITIONS = {
    "salary credit acme": FixtureDisposition(
        "income", "INCOME", "Monthly salary credit", "SALARY"
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
        if status in ("rejected", "approved", "parsed"):
            return last_payload
        await asyncio.sleep(0.5)
    raise TimeoutError(f"statement {statement_id} did not parse: {last_payload}")


@ac_proof(
    "confidence-metrics-measured-journey",
    ac_ids=["AC-extraction.1814.4"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    issue="#2370",
    required_markers=["e2e", "journey"],
)
@pytest.mark.e2e
@pytest.mark.journey
async def test_proportion_of_low_confidence_data_is_measured(
    authenticated_page_unique: Page,
    record_property,
) -> None:
    """EPIC-018 AC-extraction.1814.4 / Axiom B: The proportion of low-confidence data is measured.

    Checkpoints proven: U12 (pinned revision), U13 (low-confidence proportion measured).
    """
    page = authenticated_page_unique
    await _assert_pinned_before_journey(page, record_property)

    assert EXPECTED_TOTAL_STATEMENTS == 2
    assert EXPECTED_LOW_CONFIDENCE_STATEMENTS == 1
    assert EXPECTED_LOW_CONFIDENCE_RATIO == Decimal("0.5")
    assert EXPECTED_REPLAY_PROPORTION_BEFORE == Decimal("1.00000")
    assert EXPECTED_REPLAY_PROPORTION_AFTER == Decimal("0.00000")
    assert EXPECTED_MATCH_RATE == Decimal("66.67")

    headers = await _auth_headers(page)
    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        # 1. Create an isolated SGD asset account and seed two CSV statements:
        #    - Statement 1: balanced and complete (confidence_score == 59, balance_validated is True)
        #    - Statement 2: missing period dates and mismatched closing balance
        #      (confidence_score == 45, balance_validated is False)
        acc_resp = await client.post(
            _api_url("/accounts"),
            json={
                "name": "Confidence Metrics Savings",
                "type": "ASSET",
                "currency": CURRENCY,
            },
        )
        assert acc_resp.status_code == 201, f"account creation failed: {acc_resp.text}"
        account_id = acc_resp.json()["id"]

        valid_filename = f"confidence_valid_{uuid.uuid4().hex[:6]}.csv"
        valid_csv = "\n".join(
            [
                CSV_HEADER,
                "SGD,2026-01-01,2026-01-31,10000.00,20000.00,2026-01-05,Salary Credit ACME,5000.00",
                "SGD,2026-01-01,2026-01-31,10000.00,20000.00,2026-01-20,Salary Credit ACME,5000.00",
                "",
            ]
        )
        valid_upload = await client.post(
            _api_url("/statements/upload"),
            data={
                "institution": "Confidence Valid Bank",
                "account_id": account_id,
            },
            files={"file": (valid_filename, valid_csv.encode("utf-8"), "text/csv")},
        )
        assert valid_upload.status_code in (200, 201, 202), (
            f"valid statement upload failed: {valid_upload.text}"
        )
        valid_statement_id = valid_upload.json()["id"]
        valid_parsed = await _wait_for_parsed(client, valid_statement_id)
        assert valid_parsed["balance_validated"] is True
        assert valid_parsed["confidence_score"] >= 50
        assert len(valid_parsed["transactions"]) == 2

        approval = await approve_statement_with_fixture_review(
            client,
            api_url=_api_url,
            statement_id=valid_statement_id,
            transactions=valid_parsed["transactions"],
            dispositions=DISPOSITIONS,
            envelope=FixtureEnvelope(
                currency=CURRENCY,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                opening_balance=Decimal("10000.00"),
                closing_balance=Decimal("20000.00"),
                rationale="The generated CSV declares these source facts.",
            ),
        )
        assert approval["status"] == "approved", (
            f"valid statement approval failed: {approval}"
        )

        reconcile_resp = await client.post(
            _api_url("/reconciliation/runs"),
            json={"statement_id": valid_statement_id},
        )
        assert reconcile_resp.status_code == 200, (
            f"reconciliation run failed: {reconcile_resp.text}"
        )
        # The approval already posted both rows from their own statement, so the run
        # finds no pending row and creates no self-match (AC-reconciliation.2561.1).
        # The stats below still count both rows as matched (AC-reconciliation.2465.1).
        # unmatched == 0 shows that the run saw both rows of this statement as resolved.
        assert reconcile_resp.json() == {
            "matches_created": 0,
            "auto_accepted": 0,
            "pending_review": 0,
            "unmatched": 0,
        }, f"the run did not treat the posted rows as resolved: {reconcile_resp.json()}"

        for txn in valid_parsed["transactions"]:
            corr_resp = await client.post(
                _api_url("/corrections"),
                json={
                    "transaction_id": txn["id"],
                    "corrected_category": "SALARY",
                },
            )
            assert corr_resp.status_code == 201, (
                f"correction creation failed: {corr_resp.text}"
            )

        low_conf_filename = f"confidence_low_{uuid.uuid4().hex[:6]}.csv"
        low_conf_csv = "\n".join(
            [
                LOW_CONFIDENCE_CSV_HEADER,
                "SGD,20000.00,99999.00,2026-02-10,Unverified Expense,-500.00",
                "",
            ]
        )
        low_conf_upload = await client.post(
            _api_url("/statements/upload"),
            data={
                "institution": "Confidence Low Score Bank",
                "account_id": account_id,
            },
            files={
                "file": (
                    low_conf_filename,
                    low_conf_csv.encode("utf-8"),
                    "text/csv",
                )
            },
        )
        assert low_conf_upload.status_code in (200, 201, 202), (
            f"low-confidence statement upload failed: {low_conf_upload.text}"
        )
        low_conf_statement_id = low_conf_upload.json()["id"]
        low_conf_parsed = await _wait_for_parsed(client, low_conf_statement_id)
        assert low_conf_parsed["balance_validated"] is False
        assert low_conf_parsed["confidence_score"] < 50
        assert len(low_conf_parsed["transactions"]) == 1

        # 2. Query the live correction feedback loop replay endpoint.
        replay_resp = await client.get(_api_url("/metrics/correction-loop/replay"))
        assert replay_resp.status_code == 200, (
            f"correction loop replay failed: {replay_resp.status_code} {replay_resp.text}"
        )
        replay = replay_resp.json()
        assert replay["holdout_size"] == 1
        assert replay["grounded"] == 1
        prop_before = Decimal(str(replay["proportion_before"]))
        prop_after = Decimal(str(replay["proportion_after"]))
        assert prop_before == EXPECTED_REPLAY_PROPORTION_BEFORE
        assert prop_after == EXPECTED_REPLAY_PROPORTION_AFTER
        assert prop_after < prop_before
        assert replay["reduced"] is True

        # 3. Query reconciliation statistics.
        stats_resp = await client.get(_api_url("/reconciliation/stats"))
        assert stats_resp.status_code == 200, (
            f"reconciliation stats failed: {stats_resp.status_code} {stats_resp.text}"
        )
        stats = stats_resp.json()
        assert stats["total_transactions"] == 3
        assert stats["matched_transactions"] == 2
        assert stats["unmatched_transactions"] == 1
        assert (
            stats["matched_transactions"] + stats["unmatched_transactions"]
            == stats["total_transactions"]
        )
        match_rate = Decimal(str(stats["match_rate"]))
        assert match_rate == EXPECTED_MATCH_RATE

        # 4. Query statements to inspect confidence scores without empty-DB fallback.
        stmts_resp = await client.get(_api_url("/statements"))
        assert stmts_resp.status_code == 200, (
            f"statements list failed: {stmts_resp.status_code} {stmts_resp.text}"
        )
        stmts = stmts_resp.json()["items"]
        total_statements = len(stmts)
        assert total_statements > 0, "statements list must not be empty"
        assert total_statements == EXPECTED_TOTAL_STATEMENTS

        # Under Axiom B, low-confidence statements have score < 50 or failed balance validation.
        low_confidence_statements = sum(
            1
            for s in stmts
            if (s["confidence_score"] is not None and s["confidence_score"] < 50)
            or s["balance_validated"] is False
        )
        assert low_confidence_statements == EXPECTED_LOW_CONFIDENCE_STATEMENTS
        statement_low_confidence_ratio = Decimal(low_confidence_statements) / Decimal(
            total_statements
        )
        assert statement_low_confidence_ratio == EXPECTED_LOW_CONFIDENCE_RATIO

        # 5. Verify browser UI rendering on /audit and /statements.
        # The correction proof is on the Health tab of /audit (#2646).
        await page.goto(
            f"{APP_URL.rstrip('/')}/audit?tab=health", wait_until="domcontentloaded"
        )
        await expect(page.locator("main")).to_contain_text(
            "Correction Loop Proof", timeout=30000
        )
        await expect(page.locator("main")).to_contain_text(
            "Held-out replay", timeout=30000
        )
        await expect(page.locator("main")).to_contain_text(
            "Improves extraction", timeout=30000
        )
        await expect(page.locator("main")).to_contain_text(
            "Before correction reuse", timeout=30000
        )
        await expect(page.locator("main")).to_contain_text("100.0%", timeout=30000)
        await expect(page.locator("main")).to_contain_text(
            "After correction reuse", timeout=30000
        )
        await expect(page.locator("main")).to_contain_text("0.0%", timeout=30000)

        await page.goto(
            f"{APP_URL.rstrip('/')}/statements", wait_until="domcontentloaded"
        )
        await page.locator("main").wait_for(state="visible", timeout=30000)
        await expect(
            page.get_by_text(f"{EXPECTED_TOTAL_STATEMENTS} total")
        ).to_be_visible(timeout=30000)
        valid_row = page.locator(".relative.block").filter(has_text=valid_filename)
        await expect(valid_row).to_be_visible(timeout=30000)
        await expect(valid_row).to_contain_text("Approved")
        low_conf_row = page.locator(".relative.block").filter(
            has_text=low_conf_filename
        )
        await expect(low_conf_row).to_be_visible(timeout=30000)
        await expect(low_conf_row).to_contain_text("Ready to review")

        # Record metrics as observable JUnit test properties.
        record_property("replay_proportion_before", str(prop_before))
        record_property("replay_proportion_after", str(prop_after))
        record_property("replay_reduced", str(replay["reduced"]))
        record_property(
            "statement_low_confidence_ratio", str(statement_low_confidence_ratio)
        )
        record_property("reconciliation_match_rate", str(match_rate))

        # 6. Record checkpoint U13.
        checkpoint(record_property, "U13")
