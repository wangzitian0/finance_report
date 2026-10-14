"""Core-journey proof U7: a transfer between two accounts clears through Processing (#2384).

An isolated user creates two SGD asset accounts and uploads one generated CSV
statement for each account. Account A has an OUT leg. Account B has an IN leg
for the same transfer. The user matches transfers, approves both statements
and reads the result from the product. The test makes no provider call.

Every expected value is a constant in this file. No expected value comes from
an application response.
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
    FixtureEnvelope,
    approve_statement_with_fixture_review,
)
from deployment_pin import assert_pinned_deployment, resolve_expected_commit
from journey_checkpoint import checkpoint
from playwright.async_api import Page

APP_URL = os.getenv("APP_URL", "http://localhost:3000")
PARSING_TIMEOUT_MS = int(os.getenv("PARSING_TIMEOUT_MS", "480000"))

CURRENCY = "SGD"
PERIOD_START = "2026-03-01"
PERIOD_END = "2026-03-31"
OUT_DATE = "2026-03-10"
IN_DATE = "2026-03-11"  # The IN leg settles one day after the OUT leg.

# Both legs carry the SAME full description text. The pairing policy scores the
# memo text of the two legs. For identical text the pair confidence is 87 and
# the auto-pair threshold is 85. This test proves the clearing mechanism, so it
# uses identical text. Memos that differ between the two legs score 74 to 80
# (product code, issue #2388). That is the 60-84 review band of
# common/ledger/readme.md, and no code implements it: the legs stay in transit.
# The product adds the prefixes "Transfer OUT: " and "Transfer IN: " to the
# two ledger memos.
TRANSFER_DESCRIPTION = (
    "Funds transfer between own accounts Account A to Account B "
    "reference TRF20260310001"
)

# Statement facts for account A and account B. The balance chain of each
# statement is: opening balance + net movement = closing balance.
A_OPENING = Decimal("1000.00")
A_OUT_AMOUNT = Decimal("500.00")
A_CLOSING = Decimal("500.00")
B_OPENING = Decimal("200.00")
B_IN_AMOUNT = Decimal("500.00")
B_CLOSING = Decimal("700.00")

# Expected product results. These constants stay independent of the fixture
# arithmetic above, so a change of one leg amount breaks an expected value.
EXPECTED_PROCESSING_BALANCE = Decimal("0.00")
EXPECTED_NET_INCOME = Decimal("0.00")
EXPECTED_BALANCE_A = Decimal("500.00")
EXPECTED_BALANCE_B = Decimal("700.00")
EXPECTED_TOTAL_ASSETS = Decimal("1200.00")

CSV_HEADER = (
    "Statement Currency,Statement Period Start,Statement Period End,"
    "Statement Opening Balance,Statement Closing Balance,Date,Description,Amount"
)


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


async def _assert_pinned_before_upload(page: Page, record_property) -> None:
    """Prove the pinned deployment before the first upload (#2370).

    The journey board reads the first unreached checkpoint as the failed one.
    A pin check before the upload keeps a later failure from showing as U12.
    """
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


def _statement_csv(
    *,
    opening: Decimal,
    closing: Decimal,
    day: str,
    amount: str,
    description: str = TRANSFER_DESCRIPTION,
) -> str:
    row = (
        f"{CURRENCY},{PERIOD_START},{PERIOD_END},{opening},{closing},"
        f"{day},{description},{amount}"
    )
    return "\n".join([CSV_HEADER, row, ""])


async def _create_asset_account(client: httpx.AsyncClient, name: str) -> str:
    response = await client.post(
        _api_url("/accounts"),
        json={"name": name, "type": "ASSET", "currency": CURRENCY},
    )
    assert response.status_code == 201, (
        f"account {name} creation failed: {response.status_code} {response.text}"
    )
    return str(response.json()["id"])


async def _upload_csv(
    client: httpx.AsyncClient, *, institution: str, account_id: str, content: str
) -> str:
    filename = f"transfer_proof_{uuid.uuid4().hex[:8]}.csv"
    response = await client.post(
        _api_url("/statements/upload"),
        data={"institution": institution, "account_id": account_id},
        files={"file": (filename, content.encode("utf-8"), "text/csv")},
    )
    assert response.status_code in (200, 201, 202), (
        f"{institution} upload failed: {response.status_code} {response.text}"
    )
    statement_id = response.json().get("id")
    assert statement_id, f"{institution} upload response missing id: {response.text}"
    return str(statement_id)


async def _wait_for_parsed(client: httpx.AsyncClient, statement_id: str) -> dict:
    """Poll until the CSV statement reaches the 'parsed' review state."""
    deadline = asyncio.get_running_loop().time() + PARSING_TIMEOUT_MS / 1000
    last_payload: dict | None = None
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(_api_url(f"/statements/{statement_id}"))
        assert response.status_code == 200, (
            f"statement poll failed for {statement_id}: "
            f"{response.status_code} {response.text}"
        )
        last_payload = response.json()
        status = last_payload.get("status")
        if status in ("rejected", "uploaded", "approved"):
            # A CSV export never carries a trusted envelope, so Stage 1 must not
            # approve it by itself. An approved status here is a defect.
            pytest.fail(
                f"statement {statement_id} ended in {status} instead of 'parsed': "
                f"{last_payload.get('validation_error')}"
            )
        if status == "parsed":
            return last_payload
        await asyncio.sleep(2)
    pytest.fail(
        f"statement {statement_id} did not reach 'parsed' within "
        f"{PARSING_TIMEOUT_MS}ms; last payload: {last_payload}"
    )


async def _get_json(client: httpx.AsyncClient, path: str) -> dict:
    response = await client.get(_api_url(path))
    assert response.status_code == 200, (
        f"GET {path} failed: {response.status_code} {response.text}"
    )
    return response.json()


def _processing_ledger_balance(entries: list[dict], processing_id: str) -> Decimal:
    """Net debit balance of the Processing account, summed from ledger lines."""
    balance = Decimal("0.00")
    for entry in entries:
        for line in entry["lines"]:
            if line["account_id"] != processing_id:
                continue
            amount = Decimal(line["amount"])
            balance += amount if line["direction"] == "DEBIT" else -amount
    return balance


@ac_proof(
    "transfer-clears-through-processing",
    ac_ids=["AC-ledger.transfer-clearing.1"],
    scope="behavioral",
    ci_tier="post_merge_environment",
    issue="#2384",
    required_markers=["e2e", "journey"],
)
@pytest.mark.e2e
@pytest.mark.journey
async def test_transfer_between_accounts_clears_through_processing(
    authenticated_page_unique: Page,
    record_property,
) -> None:
    """EPIC-004 EPIC-008 EPIC-015: AC-ledger.transfer-clearing.1: a transfer clears through the Processing account.

    Two generated CSV statements hold the OUT leg and the IN leg of one
    transfer. After transfer matching and approval, the Processing balance is
    0.00, no leg stays in transit, and net income is 0.00.
    """
    page = authenticated_page_unique
    await _assert_pinned_before_upload(page, record_property)

    headers = await _auth_headers(page)
    async with httpx.AsyncClient(
        headers=headers, verify=False, timeout=120.0
    ) as client:
        account_a = await _create_asset_account(client, "Transfer Proof A")
        account_b = await _create_asset_account(client, "Transfer Proof B")
        statement_a = await _upload_csv(
            client,
            institution="Transfer Proof Bank A",
            account_id=account_a,
            content=_statement_csv(
                opening=A_OPENING,
                closing=A_CLOSING,
                day=OUT_DATE,
                amount=f"-{A_OUT_AMOUNT}",
            ),
        )
        statement_b = await _upload_csv(
            client,
            institution="Transfer Proof Bank B",
            account_id=account_b,
            content=_statement_csv(
                opening=B_OPENING,
                closing=B_CLOSING,
                day=IN_DATE,
                amount=f"{B_IN_AMOUNT}",
            ),
        )
        parsed_a = await _wait_for_parsed(client, statement_a)
        parsed_b = await _wait_for_parsed(client, statement_b)
        assert len(parsed_a["transactions"]) == 1
        assert len(parsed_b["transactions"]) == 1

        # The product blocks the approval of a transfer row until transfer
        # matching records that row as a transfer leg. Run the matching first.
        matching = await client.post(_api_url("/reconciliation/runs"), json={})
        assert matching.status_code == 200, (
            f"transfer matching failed: {matching.status_code} {matching.text}"
        )
        assert matching.json() == {
            "matches_created": 2,
            "auto_accepted": 2,
            "pending_review": 0,
            "unmatched": 0,
        }

        # An empty disposition table makes any economic-review request fail.
        for statement_id, parsed, opening, closing in (
            (statement_a, parsed_a, A_OPENING, A_CLOSING),
            (statement_b, parsed_b, B_OPENING, B_CLOSING),
        ):
            approval = await approve_statement_with_fixture_review(
                client,
                api_url=_api_url,
                statement_id=statement_id,
                transactions=parsed["transactions"],
                dispositions={},
                envelope=FixtureEnvelope(
                    currency=CURRENCY,
                    period_start=date.fromisoformat(PERIOD_START),
                    period_end=date.fromisoformat(PERIOD_END),
                    opening_balance=opening,
                    closing_balance=closing,
                    rationale="The generated CSV header declares these source facts.",
                ),
            )
            assert approval.get("status") == "approved"

        # Both legs exist as transfer legs. This blocks a green result on empty data.
        matches = (await _get_json(client, "/reconciliation/matches?limit=200"))[
            "items"
        ]
        legs = [
            match
            for match in matches
            if match["transaction"]["description"] == TRANSFER_DESCRIPTION
        ]
        assert len(legs) == 2, f"expected two transfer legs, got {len(legs)}"
        by_kind = {
            next(iter(match["score_breakdown"])): match
            for match in legs
            if len(match["score_breakdown"]) == 1
        }
        assert set(by_kind) == {"transfer_out", "transfer_in"}
        out_leg = by_kind["transfer_out"]
        in_leg = by_kind["transfer_in"]
        assert out_leg["status"] == in_leg["status"] == "auto_accepted"
        assert out_leg["transaction"]["direction"] == "OUT"
        assert in_leg["transaction"]["direction"] == "IN"
        assert Decimal(out_leg["transaction"]["amount"]) == A_OUT_AMOUNT
        assert Decimal(in_leg["transaction"]["amount"]) == B_IN_AMOUNT

        # Each leg is one Processing entry. The OUT entry moves A to Processing.
        # The IN entry moves Processing to B. Both entries use one Processing account.
        entries = (await _get_json(client, "/journal-entries?limit=100"))["items"]
        entries_by_id = {entry["id"]: entry for entry in entries}
        out_entry = entries_by_id[out_leg["journal_entry_ids"][0]]
        in_entry = entries_by_id[in_leg["journal_entry_ids"][0]]
        out_lines = {line["account_id"]: line for line in out_entry["lines"]}
        in_lines = {line["account_id"]: line for line in in_entry["lines"]}
        assert account_a in out_lines
        assert account_b in in_lines
        processing_ids = (set(out_lines) - {account_a}) & (set(in_lines) - {account_b})
        assert len(processing_ids) == 1, (
            "both legs must use one shared Processing account"
        )
        processing_id = processing_ids.pop()
        assert out_lines[account_a]["direction"] == "CREDIT"
        assert out_lines[processing_id]["direction"] == "DEBIT"
        assert in_lines[account_b]["direction"] == "DEBIT"
        assert in_lines[processing_id]["direction"] == "CREDIT"

        # The in-transit list counts only entries with source_type "system" and
        # a posted or reconciled status. Both legs must meet that rule. An empty
        # list then means that the pairing removed the legs, and not that the
        # list never saw them.
        for leg_entry in (out_entry, in_entry):
            assert leg_entry["source_type"] == "system"
            assert leg_entry["status"] in ("posted", "reconciled")

        # The Processing balance is 0.00 from two sources: the ledger lines and
        # the product summary. The product recomputes the pairs on every read.
        # No API shows the saved pair. The empty in-transit list is therefore
        # the only product evidence that the two legs are paired.
        assert (
            _processing_ledger_balance(entries, processing_id)
            == EXPECTED_PROCESSING_BALANCE
        )
        summary = await _get_json(client, "/accounts/processing/summary")
        assert Decimal(summary["current_balance"]) == EXPECTED_PROCESSING_BALANCE
        assert summary["pending_count"] == 0
        assert Decimal(summary["pending_total"]) == Decimal("0.00")
        pending = await _get_json(client, "/accounts/processing/pending")
        assert pending["items"] == []
        assert pending["total"] == 0

        # The money moved from A to B and stayed in the user's accounts.
        accounts = (await _get_json(client, "/accounts?include_balance=true"))["items"]
        balances = {account["id"]: Decimal(account["balance"]) for account in accounts}
        assert balances[account_a] == EXPECTED_BALANCE_A
        assert balances[account_b] == EXPECTED_BALANCE_B

        # A transfer is neither income nor expense. The balance sheet shows
        # that the income statement reads the posted data.
        income = await _get_json(
            client,
            "/reports/income-statement"
            f"?start_date={PERIOD_START}&end_date={PERIOD_END}&currency={CURRENCY}",
        )
        assert Decimal(income["net_income"]) == EXPECTED_NET_INCOME
        assert income["income"] == []
        assert income["expenses"] == []
        balance_sheet = await _get_json(
            client,
            f"/reports/balance-sheet?as_of_date={PERIOD_END}&currency={CURRENCY}",
        )
        assert Decimal(balance_sheet["total_assets"]) == EXPECTED_TOTAL_ASSETS

        # Realistic different-memo scenario (issue #2388):
        # "TRANSFER TO SAVINGS ACCOUNT" on OUT leg and "TRANSFER FROM CURRENT ACCOUNT" on IN leg.
        # These memos score 74 in the 60-84 review band and generate a TRANSFER_PAIR consistency check.
        account_rev_a = await _create_asset_account(client, "Transfer Review A")
        account_rev_b = await _create_asset_account(client, "Transfer Review B")
        desc_rev_out = "TRANSFER TO SAVINGS ACCOUNT"
        desc_rev_in = "TRANSFER FROM CURRENT ACCOUNT"

        statement_rev_a = await _upload_csv(
            client,
            institution="Transfer Review Bank A",
            account_id=account_rev_a,
            content=_statement_csv(
                opening=A_OPENING,
                closing=A_CLOSING,
                day=OUT_DATE,
                amount=f"-{A_OUT_AMOUNT}",
                description=desc_rev_out,
            ),
        )
        statement_rev_b = await _upload_csv(
            client,
            institution="Transfer Review Bank B",
            account_id=account_rev_b,
            content=_statement_csv(
                opening=B_OPENING,
                closing=B_CLOSING,
                day=IN_DATE,
                amount=f"{B_IN_AMOUNT}",
                description=desc_rev_in,
            ),
        )
        parsed_rev_a = await _wait_for_parsed(client, statement_rev_a)
        parsed_rev_b = await _wait_for_parsed(client, statement_rev_b)
        assert len(parsed_rev_a["transactions"]) == 1
        assert len(parsed_rev_b["transactions"]) == 1

        matching_rev = await client.post(_api_url("/reconciliation/runs"), json={})
        assert matching_rev.status_code == 200

        for statement_id, parsed, opening, closing in (
            (statement_rev_a, parsed_rev_a, A_OPENING, A_CLOSING),
            (statement_rev_b, parsed_rev_b, B_OPENING, B_CLOSING),
        ):
            approval = await approve_statement_with_fixture_review(
                client,
                api_url=_api_url,
                statement_id=statement_id,
                transactions=parsed["transactions"],
                dispositions={},
                envelope=FixtureEnvelope(
                    currency=CURRENCY,
                    period_start=date.fromisoformat(PERIOD_START),
                    period_end=date.fromisoformat(PERIOD_END),
                    opening_balance=opening,
                    closing_balance=closing,
                    rationale="The generated CSV header declares these source facts.",
                ),
            )
            assert approval.get("status") == "approved"

        # Verify /accounts/processing/pending initially lists the 2 legs
        pending_rev_before = await _get_json(client, "/accounts/processing/pending")
        assert pending_rev_before["total"] == 2
        assert len(pending_rev_before["items"]) == 2

        # Run consistency checks for statement A
        run_checks_resp = await client.post(
            _api_url(f"/statements/{statement_rev_a}/stage2/run-checks")
        )
        assert run_checks_resp.status_code == 200, (
            f"run-checks failed: {run_checks_resp.text}"
        )
        checks_data = run_checks_resp.json()
        transfer_pair_check = next(
            (
                c
                for c in checks_data.get("items", [])
                if c.get("check_type") == "transfer_pair"
            ),
            None,
        )
        assert transfer_pair_check is not None, (
            f"expected transfer_pair check, got: {checks_data}"
        )

        # Resolve check with approve action
        check_id = transfer_pair_check["id"]
        resolve_resp = await client.post(
            _api_url(f"/statements/consistency-checks/{check_id}/resolve"),
            json={"action": "approve"},
        )
        assert resolve_resp.status_code == 200, (
            f"resolve check failed: {resolve_resp.text}"
        )

        # Verify /accounts/processing/pending is now empty
        pending_rev_after = await _get_json(client, "/accounts/processing/pending")
        assert pending_rev_after["items"] == []
        assert pending_rev_after["total"] == 0

        # Verify /accounts/processing/summary reports pending_count == 0 and current_balance == "0.00"
        summary_rev_after = await _get_json(client, "/accounts/processing/summary")
        assert summary_rev_after["pending_count"] == 0
        assert (
            Decimal(summary_rev_after["current_balance"]) == EXPECTED_PROCESSING_BALANCE
        )
        assert Decimal(summary_rev_after["pending_total"]) == Decimal("0.00")

        checkpoint(record_property, "U7")
