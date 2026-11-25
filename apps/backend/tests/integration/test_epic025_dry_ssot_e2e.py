from datetime import date
from decimal import Decimal

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


async def test_reporting_calc_extraction_preserves_balance_sheet(client, test_user):
    bank = await client.post("/accounts", json={"name": "Bank", "type": "ASSET", "currency": "SGD"})
    equity = await client.post("/accounts", json={"name": "Opening Equity", "type": "EQUITY", "currency": "SGD"})
    assert (bank.status_code, equity.status_code) == (201, 201)
    entry = await client.post(
        "/journal-entries",
        json={
            "entry_date": date(2024, 6, 15).isoformat(),
            "memo": "opening balance",
            "lines": [
                {"account_id": bank.json()["id"], "direction": "DEBIT", "amount": "1000.00", "currency": "SGD"},
                {"account_id": equity.json()["id"], "direction": "CREDIT", "amount": "1000.00", "currency": "SGD"},
            ],
        },
    )
    assert entry.status_code == 201
    assert (await client.post(f"/journal-entries/{entry.json()['id']}/postings")).status_code == 200
    resp = await client.get("/reports/balance-sheet")
    assert resp.status_code == 200
    data = resp.json()
    assert (
        Decimal(str(data["total_assets"])),
        Decimal(str(data["total_liabilities"])),
        Decimal(str(data["total_equity"])),
        Decimal(str(data["equation_delta"])),
        data["is_balanced"],
    ) == (Decimal("1000.00"), Decimal("0.00"), Decimal("1000.00"), Decimal("0.00"), True)
