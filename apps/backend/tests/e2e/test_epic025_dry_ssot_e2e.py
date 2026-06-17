"""Product E2E owner test for EPIC-025 (DRY/SSOT simplification).

EPIC-025 is a behavior-preserving refactor; this Tier-1 API E2E proves the
refactored reporting path still produces correct numbers end to end
(request → router → reporting → reporting_calc → DB → response), so the
extraction cannot silently change financial output.
"""

from datetime import date
from decimal import Decimal

import pytest

TEST_DATE = date(2024, 6, 15)


async def _create_account(client, name, acct_type, currency="SGD"):
    resp = await client.post("/accounts", json={"name": name, "type": acct_type, "currency": currency})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _post_balanced_entry(client, *, debit_id, credit_id, amount, currency="SGD"):
    create = await client.post(
        "/journal-entries",
        json={
            "entry_date": TEST_DATE.isoformat(),
            "memo": "EPIC-025 opening balance",
            "lines": [
                {"account_id": debit_id, "direction": "DEBIT", "amount": amount, "currency": currency},
                {"account_id": credit_id, "direction": "CREDIT", "amount": amount, "currency": currency},
            ],
        },
    )
    assert create.status_code == 201, create.text
    entry_id = create.json()["id"]
    posted = await client.post(f"/journal-entries/{entry_id}/postings")
    assert posted.status_code == 200, posted.text
    return entry_id


@pytest.mark.e2e
async def test_epic025_reporting_calc_extraction_preserves_balance_sheet(client, test_user):
    """EPIC-025 / AC25.1.1: the balance-sheet report still computes correct totals
    end to end after the pure reporting math moved into ``services.reporting_calc``.

    GIVEN a balanced opening entry (Bank 1000 ← Opening Equity 1000)
    WHEN requesting the balance sheet via the API
    THEN the accounting equation holds with the exact numbers — proving the
    extraction is behavior-preserving across the real request stack.
    """
    bank_id = await _create_account(client, "Bank", "ASSET")
    equity_id = await _create_account(client, "Opening Equity", "EQUITY")
    await _post_balanced_entry(client, debit_id=bank_id, credit_id=equity_id, amount="1000.00")

    resp = await client.get("/reports/balance-sheet")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert Decimal(str(data["total_assets"])) == Decimal("1000.00")
    assert Decimal(str(data["total_liabilities"])) == Decimal("0.00")
    assert Decimal(str(data["total_equity"])) == Decimal("1000.00")
    assert Decimal(str(data["equation_delta"])) == Decimal("0.00")
    assert data["is_balanced"] is True
