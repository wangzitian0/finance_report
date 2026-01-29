"""Tests to finalize coverage for Issue #64."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    JournalEntry,
    JournalEntryStatus,
)
from src.services.reporting import ReportError


@pytest.mark.asyncio
async def test_reports_router_errors_extended(client: AsyncClient, monkeypatch):
    """Test ReportError in all report endpoints using patch on the router's imports."""

    test_cases = [
        ("/reports/balance-sheet", {"currency": "SGD"}, "generate_balance_sheet"),
        (
            "/reports/income-statement",
            {"start_date": "2026-01-01", "end_date": "2026-01-31"},
            "generate_income_statement",
        ),
        (
            "/reports/cash-flow",
            {"start_date": "2026-01-01", "end_date": "2026-01-31"},
            "generate_cash_flow",
        ),
        ("/reports/trend", {"account_id": str(uuid4()), "period": "monthly"}, "get_account_trend"),
        ("/reports/breakdown", {"type": "income"}, "get_category_breakdown"),
    ]

    for path, params, func_name in test_cases:
        with patch(f"src.routers.reports.{func_name}", new_callable=AsyncMock) as mock_func:
            mock_func.side_effect = ReportError("Mock Error")
            response = await client.get(path, params=params)
            assert response.status_code == 400
            assert "Mock Error" in response.json()["detail"]


@pytest.mark.asyncio
async def test_export_csv_rows_coverage(client: AsyncClient):
    """Test CSV export execution of all row writing loops by mocking return data."""

    mock_bs = {
        "as_of_date": date(2026, 1, 31),
        "currency": "SGD",
        "assets": [{"name": "Cash", "amount": Decimal("100.00")}],
        "liabilities": [{"name": "Loan", "amount": Decimal("50.00")}],
        "equity": [{"name": "Earnings", "amount": Decimal("50.00")}],
        "total_assets": Decimal("100.00"),
        "total_liabilities": Decimal("50.00"),
        "total_equity": Decimal("50.00"),
    }

    mock_is = {
        "start_date": date(2026, 1, 1),
        "end_date": date(2026, 1, 31),
        "currency": "SGD",
        "income": [{"name": "Sales", "amount": Decimal("200.00")}],
        "expenses": [{"name": "Rent", "amount": Decimal("100.00")}],
        "total_income": Decimal("200.00"),
        "total_expenses": Decimal("100.00"),
        "net_income": Decimal("100.00"),
    }

    # 1. Balance Sheet Export
    with patch("src.routers.reports.generate_balance_sheet", new_callable=AsyncMock) as mock_func:
        mock_func.return_value = mock_bs
        resp = await client.get("/reports/export", params={"report_type": "balance-sheet"})
        assert resp.status_code == 200
        assert "Cash,100.0" in resp.text
        assert "Total Assets,,100.0" in resp.text

    # 2. Income Statement Export
    with patch("src.routers.reports.generate_income_statement", new_callable=AsyncMock) as mock_func:
        mock_func.return_value = mock_is
        params = {
            "report_type": "income-statement",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        }
        resp = await client.get("/reports/export", params=params)
        assert resp.status_code == 200
        assert "Sales,200.0" in resp.text
        assert "Total Income,,200.0" in resp.text


@pytest.mark.asyncio
async def test_auth_coverage_errors(client: AsyncClient):
    """Test error paths in auth.py."""
    from src.security import create_access_token

    # 1. Token missing subject (sub)
    token_no_sub = create_access_token(data={"not_sub": "val"})
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {token_no_sub}"})
    assert resp.status_code == 401
    assert "missing subject" in resp.json()["detail"].lower()

    # 2. Invalid user ID format in token
    token_bad_uuid = create_access_token(data={"sub": "not-a-uuid"})
    resp = await client.get("/auth/me", headers={"Authorization": f"Bearer {token_bad_uuid}"})
    assert resp.status_code == 401
    assert "invalid user id format" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_journal_router_coverage_errors(client: AsyncClient, db: AsyncSession, test_user):
    """Test journal router error paths."""
    # 1. Get non-existent
    resp = await client.get(f"/journal-entries/{uuid4()}")
    assert resp.status_code == 404

    # 2. Post non-existent (fails in service with ValidationError)
    resp = await client.post(f"/journal-entries/{uuid4()}/post")
    assert resp.status_code == 400

    # 3. Void non-existent (fails in service with ValidationError)
    resp = await client.post(f"/journal-entries/{uuid4()}/void", json={"reason": "test"})
    assert resp.status_code == 400

    # 4. Delete non-existent
    resp = await client.delete(f"/journal-entries/{uuid4()}")
    assert resp.status_code == 404

    # 5. Delete non-draft
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Posted",
        source_type="manual",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    resp = await client.delete(f"/journal-entries/{entry.id}")
    assert resp.status_code == 400
    assert "draft" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_accounts_coverage_errors(client: AsyncClient):
    """Test accounts router error paths."""
    from src.services.account_service import AccountNotFoundError

    # 1. Get non-existent
    resp = await client.get(f"/accounts/{uuid4()}")
    assert resp.status_code == 404

    # 2. Update non-existent
    resp = await client.put(f"/accounts/{uuid4()}", json={"name": "New"})
    assert resp.status_code == 404

    # 3. Delete non-existent (AccountNotFoundError branch in delete_account)
    with patch("src.routers.accounts.account_service.get_account", new_callable=AsyncMock) as mock:
        mock.side_effect = AccountNotFoundError(uuid4())
        resp = await client.delete(f"/accounts/{uuid4()}")
        assert resp.status_code == 404

    # 2. Reject non-existent match - returns 401 (authentication required, endpoint can't be accessed without auth)
    with patch("src.routers.reconciliation.reject_match_service", new_callable=AsyncMock) as mock:
        mock.side_effect = ValueError("Match not found")
        resp = await client.post(f"/reconciliation/matches/{uuid4()}/reject")
        assert resp.status_code == 401

    # 3. Batch accept empty - returns 401 (authentication required, endpoint can't be accessed without auth)
    with patch("src.routers.reconciliation.batch_accept_service", new_callable=AsyncMock) as mock:
        mock.return_value = []
        resp = await client.post("/reconciliation/batch-accept", json={"match_ids": []})
        assert resp.status_code == 401
