"""Coverage boost tests for assets router — ensures shard-distributed coverage measurement."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.models.account import Account, AccountType
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition, PositionStatus
from src.services.assets import AssetServiceError


@pytest.mark.asyncio
class TestAssetsListCoverageBoost:
    async def test_list_positions_with_account(self, client, db, test_user):
        """
        GIVEN a position linked to an account
        WHEN GET /assets/positions
        THEN response includes account_name
        """
        account = Account(
            user_id=test_user.id,
            name="Boost Broker",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        position = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="BOOST_AAPL",
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
        assert data["items"][0]["account_name"] == "Boost Broker"


@pytest.mark.asyncio
class TestAssetsGetCoverageBoost:
    async def test_get_position_with_account(self, client, db, test_user):
        """
        GIVEN a position with a linked account
        WHEN GET /assets/positions/{id}
        THEN response includes account_name
        """
        account = Account(
            user_id=test_user.id,
            name="Boost Moomoo",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        position = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="BOOST_MSFT",
            quantity=Decimal("20.0"),
            cost_basis=Decimal("6000.00"),
            acquisition_date=date(2024, 3, 1),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        response = await client.get(f"/assets/positions/{position.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["account_name"] == "Boost Moomoo"

    async def test_get_nonexistent_position(self, client):
        """
        GIVEN a non-existent position ID
        WHEN GET /assets/positions/{id}
        THEN returns 404
        """
        response = await client.get(f"/assets/positions/{uuid4()}")
        assert response.status_code == 404


@pytest.mark.asyncio
class TestAssetsReconcileCoverageBoost:
    async def test_reconcile_creates_positions(self, client, db, test_user):
        """
        GIVEN atomic snapshots exist
        WHEN POST /assets/reconcile
        THEN positions are created from snapshots
        """
        snap = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 15),
            asset_identifier="BOOST_NVDA",
            broker="Interactive Brokers",
            quantity=Decimal("20.0"),
            market_value=Decimal("10000.00"),
            currency="USD",
            dedup_hash="boost_hash_nvda",
            source_documents={},
        )
        db.add(snap)
        await db.commit()

        response = await client.post("/assets/reconcile")
        assert response.status_code == 200
        data = response.json()
        assert data["created"] >= 1
        assert "successfully" in data["message"].lower()

    async def test_reconcile_handles_service_error(self, client):
        """
        GIVEN reconciliation service raises AssetServiceError
        WHEN POST /assets/reconcile
        THEN returns 500
        """
        with patch("src.routers.assets._service.reconcile_positions") as mock:
            mock.side_effect = AssetServiceError("Boost test error")
            response = await client.post("/assets/reconcile")
            assert response.status_code == 500

    async def test_reconcile_handles_unexpected_error(self, client):
        """
        GIVEN reconciliation service raises unexpected exception
        WHEN POST /assets/reconcile
        THEN returns 500 with generic message
        """
        with patch("src.routers.assets._service.reconcile_positions") as mock:
            mock.side_effect = RuntimeError("Boost unexpected")
            response = await client.post("/assets/reconcile")
            assert response.status_code == 500
            assert "unexpectedly" in response.json()["detail"].lower()


@pytest.mark.asyncio
class TestAssetsDepreciationCoverageBoost:
    async def test_depreciation_straight_line(self, client, db, test_user):
        """
        GIVEN an active position with cost basis
        WHEN GET /assets/positions/{id}/depreciation?method=straight-line
        THEN returns depreciation schedule
        """
        account = Account(
            user_id=test_user.id,
            name="Boost Fixed Assets",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        position = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="BOOST_EQUIP",
            quantity=Decimal("1.0"),
            cost_basis=Decimal("10000.00"),
            acquisition_date=date(2024, 1, 1),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        response = await client.get(
            f"/assets/positions/{position.id}/depreciation",
            params={"method": "straight-line", "useful_life_years": 5, "salvage_value": "100.00"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["position_id"] == str(position.id)
        assert data["method"] == "straight-line"

    async def test_depreciation_not_found(self, client):
        """
        GIVEN a non-existent position ID
        WHEN GET /assets/positions/{id}/depreciation
        THEN returns 400 (service raises AssetServiceError for not found)
        """
        response = await client.get(
            f"/assets/positions/{uuid4()}/depreciation",
            params={"method": "straight-line", "useful_life_years": 5},
        )
        assert response.status_code == 400
