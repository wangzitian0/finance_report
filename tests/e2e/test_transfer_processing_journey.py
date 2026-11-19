from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
from playwright.async_api import Page
from tests.fixtures.provider_review import (
    FixtureEnvelope,
    approve_statement_with_fixture_review,
)

from tests.e2e._journey_helpers import (
    api_url,
    assert_pinned_via_client,
    auth_headers,
    create_account,
    get_json,
    post_json,
    upload_statement,
    wait_for_statement,
)
from tests.e2e.journey_checkpoint import checkpoint

CURRENCY, PERIOD_START, PERIOD_END = "SGD", "2026-03-01", "2026-03-31"
TRANSFER_DESCRIPTION = "Funds transfer between own accounts Account A to Account B reference TRF20260310001"
EXPECTED_PROCESSING_BALANCE = Decimal("0.00")
CSV_HEADER = "Statement Currency,Statement Period Start,Statement Period End,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount"


async def _run_transfer_pair(
    client: httpx.AsyncClient,
    *,
    specs: list[tuple[str, str, str, Decimal, Decimal, str, str]],
    period_start: str,
    period_end: str,
    expected_reconciliation: dict[str, int] | None = None,
) -> list[tuple[str, str, dict]]:
    items = []
    for account_name, institution, day, opening, closing, amount, description in specs:
        acc_id = await create_account(client, account_name, currency=CURRENCY)
        csv_text = "\n".join(
            [
                CSV_HEADER,
                f"{CURRENCY},{period_start},{period_end},{opening},{closing},{day},{description},{amount}",
                "",
            ]
        )
        items.append(
            (acc_id, institution, day, opening, closing, csv_text.encode("utf-8"))
        )
    parsed_items = []
    for acc_id, institution, _, opening, closing, csv_bytes in items:
        stmt_id = await upload_statement(
            client,
            filename=f"transfer_proof_{uuid.uuid4().hex[:8]}.csv",
            content=csv_bytes,
            content_type="text/csv",
            institution=institution,
            account_id=acc_id,
            label=institution,
        )
        parsed = await wait_for_statement(
            client,
            stmt_id,
            poll_seconds=2,
            target_statuses=("parsed",),
            fail_statuses=("rejected", "uploaded", "approved"),
        )
        assert len(parsed["transactions"]) == 1
        parsed_items.append((acc_id, stmt_id, parsed, opening, closing))
    matching = await post_json(
        client,
        "/reconciliation/runs",
        json={},
        expected_status=(200,),
        label="transfer matching",
    )
    if expected_reconciliation is not None:
        assert matching == expected_reconciliation
    for _, stmt_id, parsed, opening, closing in parsed_items:
        await approve_statement_with_fixture_review(
            client,
            api_url=api_url,
            statement_id=stmt_id,
            transactions=parsed["transactions"],
            dispositions={},
            envelope=FixtureEnvelope(
                currency=CURRENCY,
                period_start=date.fromisoformat(period_start),
                period_end=date.fromisoformat(period_end),
                opening_balance=opening,
                closing_balance=closing,
                rationale="The generated CSV header declares these source facts.",
            ),
        )
    return [(acc_id, stmt_id, parsed) for acc_id, stmt_id, parsed, _, _ in parsed_items]


@pytest.mark.e2e
@pytest.mark.journey
async def test_transfer_between_accounts_clears_through_processing(
    authenticated_page_unique: Page, record_property
) -> None:
    async with httpx.AsyncClient(
        headers=await auth_headers(authenticated_page_unique),
        verify=False,
        timeout=120.0,
    ) as client:
        await assert_pinned_via_client(client, record_property)
        pair_1 = await _run_transfer_pair(
            client,
            specs=[
                (
                    "Transfer Proof A",
                    "Transfer Proof Bank A",
                    "2026-03-10",
                    Decimal("1000.00"),
                    Decimal("500.00"),
                    "-500.00",
                    TRANSFER_DESCRIPTION,
                ),
                (
                    "Transfer Proof B",
                    "Transfer Proof Bank B",
                    "2026-03-11",
                    Decimal("200.00"),
                    Decimal("700.00"),
                    "500.00",
                    TRANSFER_DESCRIPTION,
                ),
            ],
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            expected_reconciliation={
                "matches_created": 2,
                "auto_accepted": 2,
                "pending_review": 0,
                "unmatched": 0,
            },
        )
        account_a, account_b = pair_1[0][0], pair_1[1][0]

        legs = [
            m
            for m in (await get_json(client, "/reconciliation/matches?limit=200"))[
                "items"
            ]
            if m["transaction"]["description"] == TRANSFER_DESCRIPTION
        ]
        by_kind = {
            next(iter(m["score_breakdown"])): m
            for m in legs
            if len(m["score_breakdown"]) == 1
        }
        assert len(legs) == 2 and set(by_kind) == {"transfer_out", "transfer_in"}
        out_leg, in_leg = by_kind["transfer_out"], by_kind["transfer_in"]
        assert (
            out_leg["status"] == in_leg["status"] == "auto_accepted"
            and out_leg["transaction"]["direction"] == "OUT"
            and in_leg["transaction"]["direction"] == "IN"
        )
        assert Decimal(out_leg["transaction"]["amount"]) == Decimal(
            "500.00"
        ) and Decimal(in_leg["transaction"]["amount"]) == Decimal("500.00")

        entries = (await get_json(client, "/journal-entries?limit=100"))["items"]
        by_id = {e["id"]: e for e in entries}
        out_entry, in_entry = (
            by_id[out_leg["journal_entry_ids"][0]],
            by_id[in_leg["journal_entry_ids"][0]],
        )
        out_lines, in_lines = (
            {ln["account_id"]: ln for ln in e["lines"]} for e in (out_entry, in_entry)
        )
        processing_ids = (set(out_lines) - {account_a}) & (set(in_lines) - {account_b})
        assert (
            account_a in out_lines
            and account_b in in_lines
            and len(processing_ids) == 1
        )
        processing_id = processing_ids.pop()
        assert (
            out_lines[account_a]["direction"] == "CREDIT"
            and out_lines[processing_id]["direction"] == "DEBIT"
            and in_lines[account_b]["direction"] == "DEBIT"
            and in_lines[processing_id]["direction"] == "CREDIT"
        )
        assert all(
            e["source_type"] == "system" and e["status"] in ("posted", "reconciled")
            for e in (out_entry, in_entry)
        )
        assert (
            sum(
                (
                    Decimal(ln["amount"])
                    if ln["direction"] == "DEBIT"
                    else -Decimal(ln["amount"])
                    for e in entries
                    for ln in e["lines"]
                    if ln["account_id"] == processing_id
                ),
                Decimal("0.00"),
            )
            == EXPECTED_PROCESSING_BALANCE
        )

        summary, pending = (
            await get_json(client, "/reconciliation/transfers/summary"),
            await get_json(client, "/reconciliation/transfers/pending"),
        )
        assert (
            Decimal(summary["current_balance"]) == EXPECTED_PROCESSING_BALANCE
            and summary["pending_count"] == 0
            and Decimal(summary["pending_total"]) == Decimal("0.00")
            and pending["items"] == []
            and pending["total"] == 0
        )
        balances = {
            acc["id"]: Decimal(acc["balance"])
            for acc in (await get_json(client, "/accounts?include_balance=true"))[
                "items"
            ]
        }
        assert balances[account_a] == Decimal("500.00") and balances[
            account_b
        ] == Decimal("700.00")
        income = await get_json(
            client,
            f"/reports/income-statement?start_date={PERIOD_START}&end_date={PERIOD_END}&currency={CURRENCY}",
        )
        assert (
            Decimal(income["net_income"]) == Decimal("0.00")
            and income["income"] == []
            and income["expenses"] == []
        )
        assert Decimal(
            (
                await get_json(
                    client,
                    f"/reports/balance-sheet?as_of_date={PERIOD_END}&currency={CURRENCY}",
                )
            )["total_assets"]
        ) == Decimal("1200.00")

        pair_2 = await _run_transfer_pair(
            client,
            specs=[
                (
                    "Transfer Review A",
                    "Transfer Review Bank A",
                    "2026-04-10",
                    Decimal("1000.00"),
                    Decimal("700.00"),
                    "-300.00",
                    "TRANSFER TO SAVINGS ACCOUNT",
                ),
                (
                    "Transfer Review B",
                    "Transfer Review Bank B",
                    "2026-04-11",
                    Decimal("200.00"),
                    Decimal("500.00"),
                    "300.00",
                    "TRANSFER FROM CURRENT ACCOUNT",
                ),
            ],
            period_start="2026-04-01",
            period_end="2026-04-30",
        )
        rev_txn_ids = {
            str(pair_2[0][2]["transactions"][0]["id"]),
            str(pair_2[1][2]["transactions"][0]["id"]),
        }
        pending_before = await get_json(client, "/reconciliation/transfers/pending")
        assert pending_before["total"] == 2 and len(pending_before["items"]) == 2
        checks = await post_json(
            client,
            "/reconciliation/consistency-checks/runs",
            json={"statement_id": pair_2[0][1]},
            expected_status=(200,),
        )
        transfer_check = next(
            (
                c
                for c in checks.get("items", [])
                if c.get("check_type") == "transfer_pair"
                and set(c.get("related_txn_ids") or []) == rev_txn_ids
            ),
            None,
        )
        assert transfer_check is not None, (
            f"expected transfer_pair check, got: {checks}"
        )
        await post_json(
            client,
            f"/reconciliation/consistency-checks/{transfer_check['id']}/resolutions",
            json={"action": "approve"},
            expected_status=(200,),
        )
        pending_after, summary_after = (
            await get_json(client, "/reconciliation/transfers/pending"),
            await get_json(client, "/reconciliation/transfers/summary"),
        )
        assert (
            pending_after["items"] == []
            and pending_after["total"] == 0
            and summary_after["pending_count"] == 0
            and Decimal(summary_after["current_balance"]) == EXPECTED_PROCESSING_BALANCE
            and Decimal(summary_after["pending_total"]) == Decimal("0.00")
        )
        checkpoint(record_property, "U7")
