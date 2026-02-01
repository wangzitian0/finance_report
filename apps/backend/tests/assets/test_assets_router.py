"""Integration tests for Assets API router."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.models.account import Account, AccountType
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition, PositionStatus


@pytest.mark.asyncio
class TestAssetsRouter:
    """Tests for /api/assets endpoints."""

    async def test_list_positions_empty(self, client):
        """GET /assets/positions returns empty list when no positions."""
        response = await client.get("/assets/positions")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_positions_with_data(self, client, db, test_user):
        """GET /assets/positions returns positions."""
        account = Account(
            user_id=test_user.id,
            name="Test Broker",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        position = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="AAPL",
            quantity=Decimal("10.0"),
            cost_basis=Decimal("1500.00"),
            acquisition_date=date(2024, 1, 15),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        db.add(position)
        await db.commit()

        response = await client.get("/assets/positions")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["asset_identifier"] == "AAPL"
        assert data["items"][0]["quantity"] == "10.000000"
        assert data["items"][0]["account_name"] == "Test Broker"

    async def test_list_positions_filter_by_status(self, client, db, test_user):
        """GET /assets/positions?status_filter=active filters correctly."""
        account = Account(
            user_id=test_user.id,
            name="Test Broker",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        active_pos = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="AAPL",
            quantity=Decimal("10.0"),
            cost_basis=Decimal("1500.00"),
            acquisition_date=date(2024, 1, 15),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        disposed_pos = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="GOOGL",
            quantity=Decimal("0.0"),
            cost_basis=Decimal("0.00"),
            acquisition_date=date(2024, 1, 10),
            disposal_date=date(2024, 1, 14),
            status=PositionStatus.DISPOSED,
            currency="USD",
        )
        db.add_all([active_pos, disposed_pos])
        await db.commit()

        response = await client.get("/assets/positions?status_filter=active")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["asset_identifier"] == "AAPL"

        response = await client.get("/assets/positions?status_filter=disposed")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["asset_identifier"] == "GOOGL"

    async def test_get_position_success(self, client, db, test_user):
        """GET /assets/positions/{id} returns position details."""
        account = Account(
            user_id=test_user.id,
            name="Moomoo",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        position = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="TSLA",
            quantity=Decimal("5.0"),
            cost_basis=Decimal("800.00"),
            acquisition_date=date(2024, 2, 1),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        response = await client.get(f"/assets/positions/{position.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["asset_identifier"] == "TSLA"
        assert data["quantity"] == "5.000000"
        assert data["account_name"] == "Moomoo"

    async def test_get_position_not_found(self, client):
        """GET /assets/positions/{id} returns 404 for non-existent position."""
        fake_id = uuid4()
        response = await client.get(f"/assets/positions/{fake_id}")
        assert response.status_code == 404

    async def test_get_position_wrong_user(self, client, db):
        """GET /assets/positions/{id} returns 404 for other user's position."""
        other_user_id = uuid4()
        account = Account(
            user_id=other_user_id,
            name="Other Broker",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        position = ManagedPosition(
            user_id=other_user_id,
            account_id=account.id,
            asset_identifier="AAPL",
            quantity=Decimal("10.0"),
            cost_basis=Decimal("1500.00"),
            acquisition_date=date(2024, 1, 15),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        response = await client.get(f"/assets/positions/{position.id}")
        assert response.status_code == 404

    async def test_reconcile_positions_success(self, client, db, test_user):
        """POST /assets/reconcile creates positions from snapshots."""
        snap = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 15),
            asset_identifier="NVDA",
            broker="Interactive Brokers",
            quantity=Decimal("20.0"),
            market_value=Decimal("10000.00"),
            currency="USD",
            dedup_hash="hash_nvda",
            source_documents={},
        )
        db.add(snap)
        await db.commit()

        response = await client.post("/assets/reconcile")
        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Positions reconciled successfully"
        assert data["created"] == 1
        assert data["updated"] == 0
        assert data["disposed"] == 0

        positions_response = await client.get("/assets/positions")
        positions = positions_response.json()
        assert positions["total"] == 1
        assert positions["items"][0]["asset_identifier"] == "NVDA"

    async def test_reconcile_positions_empty(self, client):
        """POST /assets/reconcile with no snapshots returns 0 counts."""
        response = await client.post("/assets/reconcile")
        assert response.status_code == 200
        data = response.json()
        assert data["created"] == 0
        assert data["updated"] == 0
        assert data["disposed"] == 0
        assert data["skipped"] == 0
        assert data["skipped_assets"] == []

    async def test_list_positions_requires_auth(self, public_client):
        """GET /assets/positions requires authentication."""
        response = await public_client.get("/assets/positions")
        assert response.status_code == 401

    async def test_get_position_requires_auth(self, public_client):
        """GET /assets/positions/{id} requires authentication."""
        response = await public_client.get(f"/assets/positions/{uuid4()}")
        assert response.status_code == 401

    async def test_reconcile_requires_auth(self, public_client):
        """POST /assets/reconcile requires authentication."""
        response = await public_client.post("/assets/reconcile")
        assert response.status_code == 401

    async def test_get_position_depreciation_success(self, client, db, test_user):
        """GET /assets/positions/{id}/depreciation returns depreciation schedule."""
        account = Account(
            user_id=test_user.id,
            name="Test Broker",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        position = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="AAPL",
            quantity=Decimal("10.0"),
            cost_basis=Decimal("1000.00"),
            acquisition_date=date(2024, 1, 1),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        response = await client.get(
            f"/assets/positions/{position.id}/depreciation",
            params={
                "method": "straight-line",
                "useful_life_years": 5,
                "salvage_value": "100.00",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["position_id"] == str(position.id)
        assert data["asset_identifier"] == "AAPL"
        assert data["method"] == "straight-line"
        assert data["useful_life_years"] == 5

    async def test_get_position_depreciation_not_found(self, client):
        """GET /assets/positions/{id}/depreciation returns 400 for non-existent position."""
        fake_id = uuid4()
        response = await client.get(
            f"/assets/positions/{fake_id}/depreciation",
            params={"method": "straight-line", "useful_life_years": 5},
        )
        assert response.status_code == 400
        assert "not found" in response.json()["detail"].lower()

    async def test_get_position_depreciation_disposed_position(self, client, db, test_user):
        """GET /assets/positions/{id}/depreciation returns 400 for disposed position."""
        account = Account(
            user_id=test_user.id,
            name="Test Broker",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        position = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="AAPL",
            quantity=Decimal("0.0"),
            cost_basis=Decimal("0.00"),
            acquisition_date=date(2024, 1, 1),
            disposal_date=date(2024, 6, 1),
            status=PositionStatus.DISPOSED,
            currency="USD",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        response = await client.get(
            f"/assets/positions/{position.id}/depreciation",
            params={"method": "straight-line", "useful_life_years": 5},
        )
        assert response.status_code == 400
        assert "disposed" in response.json()["detail"].lower()

    async def test_get_position_depreciation_invalid_params(self, client, db, test_user):
        """GET /assets/positions/{id}/depreciation returns 400 for invalid params."""
        account = Account(
            user_id=test_user.id,
            name="Test Broker",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        position = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="AAPL",
            quantity=Decimal("10.0"),
            cost_basis=Decimal("1000.00"),
            acquisition_date=date(2024, 1, 1),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        response = await client.get(
            f"/assets/positions/{position.id}/depreciation",
            params={
                "method": "straight-line",
                "useful_life_years": 0,  # Invalid: must be >= 1
            },
        )
        assert response.status_code == 422
