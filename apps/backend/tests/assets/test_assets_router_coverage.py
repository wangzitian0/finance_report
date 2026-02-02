"""Coverage tests for assets router error paths and edge cases."""

from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.models.layer3 import ManagedPosition, PositionStatus
from src.services.assets import AssetServiceError


@pytest.mark.asyncio
class TestAssetsRouterCoverage:
    """Test assets router edge cases and error paths."""

    async def test_list_positions_with_account_names(self, client, db, test_user):
        """
        GIVEN positions exist with linked accounts
        WHEN listing positions
        THEN account names should be included in response
        """
        from src.models.account import Account, AccountType
        from src.models.layer3 import ManagedPosition, PositionStatus

        account = Account(
            user_id=test_user.id,
            name="Investment Account",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        position = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="AAPL",
            quantity=Decimal("10"),
            cost_basis=Decimal("1500.00"),
            status=PositionStatus.ACTIVE,
            acquisition_date=date(2024, 1, 1),
            currency="USD",
        )
        db.add(position)
        await db.commit()

        response = await client.get("/assets/positions")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
        position_with_account = next((p for p in data["items"] if p.get("account_name") == "Investment Account"), None)
        assert position_with_account is not None

    async def test_get_position_not_found(self, client, test_user):
        """
        GIVEN a non-existent position ID
        WHEN getting position details
        THEN it should return 404
        """
        fake_id = uuid4()
        response = await client.get(f"/assets/positions/{fake_id}")
        assert response.status_code == 404
        assert "Position" in response.json()["detail"]

    async def test_get_position_with_account_name(self, client, db, test_user):
        """
        GIVEN a position with linked account
        WHEN getting position details
        THEN account name should be included
        """
        from src.models.account import Account, AccountType
        from src.models.layer3 import ManagedPosition, PositionStatus

        account = Account(
            user_id=test_user.id,
            name="Brokerage Account",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        position = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="TSLA",
            quantity=Decimal("5"),
            cost_basis=Decimal("2000.00"),
            status=PositionStatus.ACTIVE,
            acquisition_date=date(2024, 1, 1),
            currency="USD",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        response = await client.get(f"/assets/positions/{position.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["account_name"] == "Brokerage Account"

    async def test_reconcile_positions_asset_service_error(self, client, db, test_user):
        """
        GIVEN reconciliation encounters AssetServiceError
        WHEN reconciling positions
        THEN it should return 500 and rollback
        """
        with patch("src.routers.assets._service.reconcile_positions") as mock_reconcile:
            mock_reconcile.side_effect = AssetServiceError("Test error")

            response = await client.post("/assets/reconcile")
            assert response.status_code == 500
            assert "Test error" in response.json()["detail"]

    async def test_reconcile_positions_unexpected_error(self, client, db, test_user):
        """
        GIVEN reconciliation encounters unexpected error
        WHEN reconciling positions
        THEN it should return 500 with generic message
        """
        with patch("src.routers.assets._service.reconcile_positions") as mock_reconcile:
            mock_reconcile.side_effect = RuntimeError("Unexpected error")

            response = await client.post("/assets/reconcile")
            assert response.status_code == 500
            assert "failed unexpectedly" in response.json()["detail"].lower()

    async def test_get_depreciation_asset_service_error(self, client, db, test_user):
        """
        GIVEN depreciation calculation fails with AssetServiceError
        WHEN calculating depreciation
        THEN it should return 400
        """
        from src.models.account import Account, AccountType
        from src.models.layer3 import ManagedPosition, PositionStatus

        account = Account(
            user_id=test_user.id,
            name="Real Estate",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        position = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="BUILDING",
            quantity=Decimal("1"),
            cost_basis=Decimal("500000.00"),
            status=PositionStatus.ACTIVE,
            acquisition_date=date(2020, 1, 1),
            currency="USD",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        with patch("src.routers.assets._service.get_depreciation_schedule") as mock_depreciation:
            mock_depreciation.side_effect = AssetServiceError("Invalid asset for depreciation")

            response = await client.get(
                f"/assets/positions/{position.id}/depreciation",
                params={"method": "straight-line", "useful_life_years": 10},
            )
            assert response.status_code == 400
            assert "Invalid asset for depreciation" in response.json()["detail"]

    async def test_reconcile_positions_success(self, client, db, test_user):
        """
        GIVEN reconciliation service returns success
        WHEN reconciling positions
        THEN it should return 200 with success message
        """
        from src.services.assets import ReconcileResult

        mock_result = ReconcileResult(
            created=2,
            updated=1,
            disposed=0,
            skipped=1,
            skipped_assets=["UNKNOWN"],
        )

        with patch("src.routers.assets._service.reconcile_positions") as mock_reconcile:
            mock_reconcile.return_value = mock_result

            response = await client.post("/assets/reconcile")
            assert response.status_code == 200
            data = response.json()
            assert data["created"] == 2
            assert data["updated"] == 1
            assert data["disposed"] == 0
            assert data["skipped"] == 1
            assert "UNKNOWN" in data["skipped_assets"]
            assert "successfully" in data["message"].lower()

    async def test_get_depreciation_success(self, client, db, test_user):
        """
        GIVEN depreciation calculation succeeds
        WHEN calculating depreciation
        THEN it should return 200 with depreciation schedule
        """
        from src.models.account import Account, AccountType
        from src.models.layer3 import ManagedPosition, PositionStatus
        from src.services.assets import DepreciationResult

        account = Account(
            user_id=test_user.id,
            name="Fixed Assets",
            type=AccountType.ASSET,
            currency="USD",
        )
        db.add(account)
        await db.flush()

        position = ManagedPosition(
            user_id=test_user.id,
            account_id=account.id,
            asset_identifier="EQUIPMENT",
            quantity=Decimal("1"),
            cost_basis=Decimal("10000.00"),
            status=PositionStatus.ACTIVE,
            acquisition_date=date(2023, 1, 1),
            currency="USD",
        )
        db.add(position)
        await db.commit()
        await db.refresh(position)

        mock_result = DepreciationResult(
            position_id=position.id,
            asset_identifier="EQUIPMENT",
            period_depreciation=Decimal("2000.00"),
            accumulated_depreciation=Decimal("2000.00"),
            book_value=Decimal("8000.00"),
            method="straight-line",
            useful_life_years=5,
            salvage_value=Decimal("0"),
        )

        with patch("src.routers.assets._service.get_depreciation_schedule") as mock_depreciation:
            mock_depreciation.return_value = mock_result

            response = await client.get(
                f"/assets/positions/{position.id}/depreciation",
                params={"method": "straight-line", "useful_life_years": 5},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["position_id"] == str(position.id)
            assert data["asset_identifier"] == "EQUIPMENT"
            assert data["method"] == "straight-line"
            assert data["useful_life_years"] == 5
