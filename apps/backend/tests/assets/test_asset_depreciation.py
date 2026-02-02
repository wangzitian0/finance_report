"""Tests for asset depreciation calculations."""

from datetime import date
from decimal import Decimal

import pytest

from src.models.account import Account, AccountType
from src.models.layer3 import ManagedPosition, PositionStatus
from src.services.assets import AssetService, AssetServiceError


@pytest.mark.asyncio
class TestAssetDepreciation:
    """Tests for depreciation calculation methods."""

    async def test_calculate_depreciation_straight_line(self, db, test_user):
        """GIVEN: A managed position
        WHEN: Calculating straight-line depreciation
        THEN: Depreciation is spread evenly over useful life"""
        service = AssetService()

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
            asset_identifier="EQUIP-001",
            quantity=Decimal("1.0"),
            cost_basis=Decimal("10000.00"),
            acquisition_date=date(2024, 1, 1),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        db.add(position)
        await db.flush()

        result = service.calculate_depreciation(
            position=position,
            method="straight-line",
            useful_life_years=5,
            salvage_value=Decimal("0"),
            as_of_date=date(2026, 1, 1),
        )

        annual_depreciation = Decimal("10000.00") / 5
        expected_accumulated = annual_depreciation * 2
        expected_book_value = Decimal("10000.00") - expected_accumulated

        assert result.period_depreciation == pytest.approx(annual_depreciation, abs=Decimal("0.01"))
        assert result.accumulated_depreciation == pytest.approx(expected_accumulated, abs=Decimal("3.00"))
        assert result.book_value == pytest.approx(expected_book_value, abs=Decimal("3.00"))
        assert result.method == "straight-line"
        assert result.useful_life_years == 5

    async def test_calculate_depreciation_declining_balance(self, db, test_user):
        """GIVEN: A managed position
        WHEN: Calculating declining-balance depreciation
        THEN: Depreciation accelerates in early years"""
        service = AssetService()

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
            asset_identifier="EQUIP-002",
            quantity=Decimal("1.0"),
            cost_basis=Decimal("10000.00"),
            acquisition_date=date(2024, 1, 1),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        db.add(position)
        await db.flush()

        result = service.calculate_depreciation(
            position=position,
            method="declining-balance",
            useful_life_years=5,
            salvage_value=Decimal("0"),
            as_of_date=date(2025, 1, 1),
        )

        rate = Decimal("2") / 5
        year1_depreciation = Decimal("10000.00") * rate

        assert result.method == "declining-balance"
        assert result.accumulated_depreciation > Decimal("0")
        assert result.book_value < Decimal("10000.00")

    async def test_calculate_depreciation_with_salvage_value(self, db, test_user):
        """GIVEN: A position with salvage value
        WHEN: Calculating depreciation
        THEN: Depreciation stops at salvage value"""
        service = AssetService()

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
            asset_identifier="EQUIP-003",
            quantity=Decimal("1.0"),
            cost_basis=Decimal("10000.00"),
            acquisition_date=date(2024, 1, 1),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        db.add(position)
        await db.flush()

        salvage_value = Decimal("1000.00")
        result = service.calculate_depreciation(
            position=position,
            method="straight-line",
            useful_life_years=5,
            salvage_value=salvage_value,
            as_of_date=date(2029, 1, 1),
        )

        assert result.book_value == salvage_value
        assert result.salvage_value == salvage_value

    async def test_calculate_depreciation_disposed_position_error(self, db, test_user):
        """GIVEN: A disposed position
        WHEN: Attempting to calculate depreciation
        THEN: AssetServiceError is raised"""
        service = AssetService()

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
            asset_identifier="EQUIP-004",
            quantity=Decimal("0.0"),
            cost_basis=Decimal("0.00"),
            acquisition_date=date(2024, 1, 1),
            disposal_date=date(2024, 12, 31),
            status=PositionStatus.DISPOSED,
            currency="USD",
        )
        db.add(position)
        await db.flush()

        with pytest.raises(AssetServiceError, match="Cannot depreciate disposed position"):
            service.calculate_depreciation(
                position=position,
                method="straight-line",
                useful_life_years=5,
                salvage_value=Decimal("0"),
                as_of_date=date(2025, 1, 1),
            )

    async def test_calculate_depreciation_zero_useful_life_error(self, db, test_user):
        """GIVEN: A position with zero useful life
        WHEN: Attempting to calculate depreciation
        THEN: AssetServiceError is raised"""
        service = AssetService()

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
            asset_identifier="EQUIP-005",
            quantity=Decimal("1.0"),
            cost_basis=Decimal("10000.00"),
            acquisition_date=date(2024, 1, 1),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        db.add(position)
        await db.flush()

        with pytest.raises(AssetServiceError, match="Useful life must be positive"):
            service.calculate_depreciation(
                position=position,
                method="straight-line",
                useful_life_years=0,
                salvage_value=Decimal("0"),
                as_of_date=date(2025, 1, 1),
            )

    async def test_calculate_depreciation_future_date_error(self, db, test_user):
        """GIVEN: A position with as_of_date before acquisition
        WHEN: Attempting to calculate depreciation
        THEN: AssetServiceError is raised"""
        service = AssetService()

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
            asset_identifier="EQUIP-006",
            quantity=Decimal("1.0"),
            cost_basis=Decimal("10000.00"),
            acquisition_date=date(2024, 1, 1),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        db.add(position)
        await db.flush()

        with pytest.raises(AssetServiceError, match="as_of_date cannot be before acquisition_date"):
            service.calculate_depreciation(
                position=position,
                method="straight-line",
                useful_life_years=5,
                salvage_value=Decimal("0"),
                as_of_date=date(2023, 12, 31),
            )

    async def test_get_depreciation_schedule_not_found(self, db, test_user):
        """GIVEN: A non-existent position ID
        WHEN: Getting depreciation schedule
        THEN: AssetServiceError is raised"""
        from uuid import uuid4

        service = AssetService()

        with pytest.raises(AssetServiceError, match="Position not found"):
            await service.get_depreciation_schedule(
                db=db,
                user_id=test_user.id,
                position_id=uuid4(),
                method="straight-line",
                useful_life_years=5,
                salvage_value=Decimal("0"),
            )

    async def test_get_depreciation_schedule_success(self, db, test_user):
        """GIVEN: A valid position
        WHEN: Getting depreciation schedule
        THEN: Returns depreciation result"""
        service = AssetService()

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
            asset_identifier="EQUIP-007",
            quantity=Decimal("1.0"),
            cost_basis=Decimal("10000.00"),
            acquisition_date=date(2024, 1, 1),
            status=PositionStatus.ACTIVE,
            currency="USD",
        )
        db.add(position)
        await db.flush()

        result = await service.get_depreciation_schedule(
            db=db,
            user_id=test_user.id,
            position_id=position.id,
            method="straight-line",
            useful_life_years=5,
            salvage_value=Decimal("0"),
        )

        assert result.position_id == position.id
        assert result.asset_identifier == "EQUIP-007"
        assert result.period_depreciation > Decimal("0")
