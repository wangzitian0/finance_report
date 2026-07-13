"""Business-value correctness through the real journey, not just reachability (#1505).

Prior e2e/smoke gates proved reachability (HTTP 200, page-loaded, a boolean
"healthy" flag) but never that a computed business value is *right* — three
production bugs (#1486, #1481, #1397) all returned 200 and "looked fine". This
is the Tier-1 (pre-merge, no-LLM) half of #1505's proof: the CSV upload here
needs no provider call, so a regression in this journey fails CI at PR time,
not staging. The deployed-environment half (same journey/assertions, against a
live app, wired into deploy.yml's staging gate) is
``tests/e2e/test_business_value_correctness_gate.py`` at the repo root.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

_INSTITUTION = "Business Value Gate Bank"
_SALARY = Decimal("3000.00")
_RENT = Decimal("500.00")
_OPENING_BALANCE = Decimal("1000.00")
_PARSE_TIMEOUT_S = 15.0


async def _wait_for_parsed(client, stmt_id: str) -> dict:
    """Poll a just-uploaded statement until CSV parsing (async, but LLM-free and
    fast) lands it in a terminal status. Matches the established polling
    contract in tests/e2e/test_four_asset_net_worth_golden_path.py, sized down
    for a deterministic no-LLM CSV parse."""
    deadline = asyncio.get_running_loop().time() + _PARSE_TIMEOUT_S
    last_payload: dict | None = None
    while asyncio.get_running_loop().time() < deadline:
        resp = await client.get(f"/statements/{stmt_id}")
        assert resp.status_code == 200, resp.text
        last_payload = resp.json()
        if last_payload["status"] in ("parsed", "rejected"):
            return last_payload
        await asyncio.sleep(0.1)
    pytest.fail(f"statement {stmt_id} did not reach a terminal status within {_PARSE_TIMEOUT_S}s: {last_payload}")


def _asset_line(balance_sheet: dict, name_token: str) -> dict:
    matches = [line for line in balance_sheet["assets"] if name_token in line.get("name", "")]
    assert matches, f"expected a balance-sheet line containing {name_token!r}; assets={balance_sheet['assets']}"
    return matches[0]


@pytest.mark.e2e
async def test_AC_reporting_business_value_gate_1_total_matches_transactions_and_open_bal_missing_degrades_tier(
    client, test_user
) -> None:
    """EPIC-005 EPIC-008.

    AC-reporting.business-value-gate.1 AC-audit.global-invariant.2: a
    CSV-sourced statement's balance-sheet total equals the known net of its
    transactions (a real business VALUE, not just HTTP 200) AND — because the
    CSV source carried no opening balance — the aggregate confidence tier
    reads LOW with an explicit missing_opening_balance warning (#1481's
    invariant), never silently HIGH, even though every posted line is
    USER_CONFIRMED.

    AC-audit.global-invariant.2 (#1429): this is also the cross-package anchor
    for "the extraction source->fact balance chain reconciles to posted ledger
    entries" — the source CSV's transactions flow through
    parse -> review-approve -> post, and the ledger-derived balance-sheet line
    equals the known net of the source transactions end to end."""
    csv_content = f"Date,Description,Amount\n2026-03-01,Salary,{_SALARY}\n2026-03-05,Rent,-{_RENT}\n"
    upload_resp = await client.post(
        "/statements/upload",
        files={"file": ("business_gate.csv", csv_content.encode(), "text/csv")},
        data={"institution": _INSTITUTION},
    )
    assert upload_resp.status_code == 202, upload_resp.text
    stmt_id = upload_resp.json()["id"]
    parsed = await _wait_for_parsed(client, stmt_id)
    assert parsed["status"] == "parsed", parsed

    approve_resp = await client.post(
        f"/statements/{stmt_id}/review/approve",
        json={"create_account_if_missing": True},
    )
    assert approve_resp.status_code == 200, approve_resp.text

    recon_resp = await client.post("/reconciliation/runs", json={"statement_id": stmt_id})
    assert recon_resp.status_code == 200, recon_resp.text

    bs_resp = await client.get("/reports/balance-sheet")
    assert bs_resp.status_code == 200, bs_resp.text
    balance_sheet = bs_resp.json()

    bank_line = _asset_line(balance_sheet, _INSTITUTION)
    net_flow = _SALARY - _RENT
    assert Decimal(str(bank_line["amount"])) == net_flow

    # #1481: no opening balance was ever supplied by this source. The aggregate
    # must NOT read as trusted/HIGH just because the posted lines are all
    # USER_CONFIRMED — that would be exactly the "confidently wrong" failure
    # mode the axioms forbid (a total missing its starting position, stamped
    # as if it were complete).
    assert balance_sheet["confidence_tier"] == "LOW", balance_sheet
    assert any(w.get("type") == "missing_opening_balance" for w in balance_sheet["opening_balance_warnings"]), (
        balance_sheet["opening_balance_warnings"]
    )


@pytest.mark.e2e
async def test_AC_reporting_business_value_gate_2_recording_opening_balance_clears_warning_and_updates_total(
    client, test_user
) -> None:
    """EPIC-005 EPIC-008.

    AC-reporting.business-value-gate.2: once an opening balance is recorded for
    the same account, the warning clears, the tier is no longer degraded by it,
    and the total correctly includes the opening balance — proving the gate
    responds to real state in both directions rather than being permanently
    stuck LOW (a vacuous gate that never clears is not a real signal either)."""
    csv_content = f"Date,Description,Amount\n2026-03-01,Salary,{_SALARY}\n"
    upload_resp = await client.post(
        "/statements/upload",
        files={"file": ("business_gate_2.csv", csv_content.encode(), "text/csv")},
        data={"institution": _INSTITUTION},
    )
    assert upload_resp.status_code == 202, upload_resp.text
    stmt_id = upload_resp.json()["id"]
    parsed = await _wait_for_parsed(client, stmt_id)
    assert parsed["status"] == "parsed", parsed

    approve_resp = await client.post(
        f"/statements/{stmt_id}/review/approve",
        json={"create_account_if_missing": True},
    )
    assert approve_resp.status_code == 200, approve_resp.text

    accounts_resp = await client.get("/accounts", params={"account_type": "ASSET"})
    assert accounts_resp.status_code == 200, accounts_resp.text
    account = next(
        (a for a in accounts_resp.json()["items"] if a["name"] == _INSTITUTION),
        None,
    )
    assert account is not None, f"expected an auto-created account named {_INSTITUTION!r}"

    opening_resp = await client.post(
        "/accounts/opening-balances",
        json={
            "entry_date": "2026-01-01",
            "balances": {account["id"]: str(_OPENING_BALANCE)},
            "currency": "SGD",
        },
    )
    assert opening_resp.status_code == 201, opening_resp.text

    bs_resp = await client.get("/reports/balance-sheet")
    assert bs_resp.status_code == 200, bs_resp.text
    balance_sheet = bs_resp.json()

    assert balance_sheet["opening_balance_warnings"] == [], balance_sheet["opening_balance_warnings"]
    bank_line = _asset_line(balance_sheet, _INSTITUTION)
    assert Decimal(str(bank_line["amount"])) == _OPENING_BALANCE + _SALARY
