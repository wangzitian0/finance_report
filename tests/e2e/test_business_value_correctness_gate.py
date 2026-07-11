"""
EPIC-005 EPIC-008.

Tier 2/3 deploy-gate: business-value correctness through the real journey
(``AC-reporting.business-value-gate.1``/``.2``, ``common/reporting/contract.py``,
#1505).

Runs against a live deployed environment (staging, via ``deploy.yml``'s
``staging_e2e_tests`` step — the same non-llm selection ``tools/tier2_http_e2e.py``
already uses; no new workflow wiring needed) and, being audited/dependency-free,
also the PR-preview in-runner stack. Prior gates at this stage proved
reachability (HTTP 200, page loads) but never that a computed business value
is *right* — #1486, #1481, and #1397 all returned 200 and "looked fine". CSV
parsing needs no provider call, so this fails the deploy on a real regression,
not just a PR.

Backend-only twin (same journey/assertions, in-process, no live server needed
— iterates fast pre-merge): ``apps/backend/tests/e2e/test_business_value_correctness_gate.py``.
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import httpx
import pytest
from playwright.async_api import Page, expect

APP_URL: str = os.getenv("APP_URL", "http://localhost:3000")
_INSTITUTION = "Business Value Gate Bank"
_SALARY = Decimal("3000.00")
_RENT = Decimal("500.00")
_OPENING_BALANCE = Decimal("1000.00")
_PARSE_TIMEOUT_S = 60.0


def _api_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}/api{path}"


def _get_url(path: str) -> str:
    return f"{APP_URL.rstrip('/')}{path}"


def _dashboard_amount(amount: Decimal) -> str:
    return f"{int(amount):,}"


async def _auth_headers(page: Page) -> dict[str, str]:
    cookies = await page.context.cookies(APP_URL)
    auth_cookie = next(
        (c for c in cookies if c["name"] == "finance_access_token"), None
    )
    assert auth_cookie, "authenticated Playwright context is missing auth cookie"
    return {"Cookie": f"finance_access_token={auth_cookie['value']}"}


async def _wait_for_parsed(client: httpx.AsyncClient, stmt_id: str) -> dict:
    deadline = asyncio.get_running_loop().time() + _PARSE_TIMEOUT_S
    last_payload: dict | None = None
    while asyncio.get_running_loop().time() < deadline:
        resp = await client.get(_api_url(f"/statements/{stmt_id}"))
        assert resp.status_code == 200, resp.text
        last_payload = resp.json()
        if last_payload["status"] in ("parsed", "rejected"):
            return last_payload
        await asyncio.sleep(1)
    pytest.fail(
        f"statement {stmt_id} did not reach a terminal status within {_PARSE_TIMEOUT_S}s: {last_payload}"
    )


def _asset_line(balance_sheet: dict, name_token: str) -> dict:
    matches = [
        line for line in balance_sheet["assets"] if name_token in line.get("name", "")
    ]
    assert matches, (
        f"expected a balance-sheet line containing {name_token!r}; assets={balance_sheet['assets']}"
    )
    return matches[0]


@pytest.mark.e2e
@pytest.mark.critical
async def test_business_value_gate_totals_correct_and_open_bal_missing_degrades_tier(
    authenticated_page_unique: Page,
) -> None:
    """EPIC-005 EPIC-008.

    A deployed statement's balance-sheet AND dashboard total equal the known
    net of its transactions (a real business VALUE, not just HTTP 200) AND —
    because the CSV source carried no opening balance — the aggregate
    confidence tier reads LOW with an explicit missing_opening_balance
    warning (#1481's invariant), read through the surface the user actually
    sees, on a live deployed environment."""
    page = authenticated_page_unique
    headers = await _auth_headers(page)

    async with httpx.AsyncClient(headers=headers, verify=False, timeout=60.0) as client:
        csv_content = (
            "Date,Description,Amount\n"
            f"2026-03-01,Salary,{_SALARY}\n"
            f"2026-03-05,Rent,-{_RENT}\n"
        )
        upload_resp = await client.post(
            _api_url("/statements/upload"),
            data={"institution": _INSTITUTION},
            files={"file": ("business_gate.csv", csv_content.encode(), "text/csv")},
        )
        assert upload_resp.status_code == 202, upload_resp.text
        stmt_id = upload_resp.json()["id"]
        parsed = await _wait_for_parsed(client, stmt_id)
        assert parsed["status"] == "parsed", parsed

        approve_resp = await client.post(
            _api_url(f"/statements/{stmt_id}/review/approve"),
            json={"create_account_if_missing": True},
        )
        assert approve_resp.status_code == 200, approve_resp.text

        recon_resp = await client.post(
            _api_url("/reconciliation/runs"), json={"statement_id": stmt_id}
        )
        assert recon_resp.status_code == 200, recon_resp.text

        bs_resp = await client.get(_api_url("/reports/balance-sheet"))
        assert bs_resp.status_code == 200, bs_resp.text
        balance_sheet = bs_resp.json()

    net_flow = _SALARY - _RENT
    bank_line = _asset_line(balance_sheet, _INSTITUTION)
    assert Decimal(str(bank_line["amount"])) == net_flow

    # #1481 through the deployed API: no opening balance was ever supplied, so
    # the aggregate must not read as trusted/HIGH even though every posted
    # line is USER_CONFIRMED.
    assert balance_sheet["confidence_tier"] == "LOW", balance_sheet
    assert any(
        w.get("type") == "missing_opening_balance"
        for w in balance_sheet["opening_balance_warnings"]
    ), balance_sheet["opening_balance_warnings"]

    # Same invariant through the surface the user actually reads: the
    # dashboard net-worth card must reflect the real (LOW-confidence, net-flow
    # only) total, not a silently-inflated or mislabeled one.
    await page.goto(_get_url("/dashboard"))
    await page.wait_for_load_state("domcontentloaded")
    await expect(
        page.locator(".card")
        .filter(has_text="Total Assets")
        .filter(has_text=_dashboard_amount(net_flow))
    ).to_be_visible(timeout=15_000)


@pytest.mark.e2e
@pytest.mark.critical
async def test_business_value_gate_recording_opening_balance_clears_warning_and_updates_total(
    authenticated_page_unique: Page,
) -> None:
    """EPIC-005 EPIC-008.

    Once an opening balance is recorded for the same deployed account, the
    missing_opening_balance warning clears, the confidence tier is no longer
    degraded by it, and the dashboard/balance-sheet total correctly includes
    the opening balance — proving the deployed gate responds to real state in
    both directions rather than being permanently stuck LOW/warning (a gate
    that can never turn green on real deployed data is exactly as vacuous as
    one that never turns red)."""
    page = authenticated_page_unique
    headers = await _auth_headers(page)

    async with httpx.AsyncClient(headers=headers, verify=False, timeout=60.0) as client:
        csv_content = f"Date,Description,Amount\n2026-03-01,Salary,{_SALARY}\n"
        upload_resp = await client.post(
            _api_url("/statements/upload"),
            data={"institution": _INSTITUTION},
            files={"file": ("business_gate_2.csv", csv_content.encode(), "text/csv")},
        )
        assert upload_resp.status_code == 202, upload_resp.text
        stmt_id = upload_resp.json()["id"]
        parsed = await _wait_for_parsed(client, stmt_id)
        assert parsed["status"] == "parsed", parsed

        approve_resp = await client.post(
            _api_url(f"/statements/{stmt_id}/review/approve"),
            json={"create_account_if_missing": True},
        )
        assert approve_resp.status_code == 200, approve_resp.text

        accounts_resp = await client.get(
            _api_url("/accounts"), params={"account_type": "ASSET"}
        )
        assert accounts_resp.status_code == 200, accounts_resp.text
        account = next(
            (a for a in accounts_resp.json()["items"] if a["name"] == _INSTITUTION),
            None,
        )
        assert account is not None, (
            f"expected an auto-created account named {_INSTITUTION!r}"
        )

        opening_resp = await client.post(
            _api_url("/accounts/opening-balances"),
            json={
                "entry_date": "2026-01-01",
                "balances": {account["id"]: str(_OPENING_BALANCE)},
                "currency": "SGD",
            },
        )
        assert opening_resp.status_code == 201, opening_resp.text

        bs_resp = await client.get(_api_url("/reports/balance-sheet"))
        assert bs_resp.status_code == 200, bs_resp.text
        balance_sheet = bs_resp.json()

    assert balance_sheet["opening_balance_warnings"] == [], balance_sheet[
        "opening_balance_warnings"
    ]
    expected_total = _OPENING_BALANCE + _SALARY
    bank_line = _asset_line(balance_sheet, _INSTITUTION)
    assert Decimal(str(bank_line["amount"])) == expected_total

    await page.goto(_get_url("/dashboard"))
    await page.wait_for_load_state("domcontentloaded")
    await expect(
        page.locator(".card")
        .filter(has_text="Total Assets")
        .filter(has_text=_dashboard_amount(expected_total))
    ).to_be_visible(timeout=15_000)
