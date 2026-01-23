"""Tests for Asset Service."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition, PositionStatus
from src.services.assets import AssetService


@pytest.mark.asyncio
class TestAssetService:
    """Tests for asset reconciliation."""

    async def test_reconcile_creates_position(self, db, test_user):
        """Test that reconciling creates a new managed position."""
        service = AssetService()

        # 1. Create Atomic Position
        snap = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 15),
            asset_identifier="AAPL",
            broker="Moomoo",
            quantity=Decimal("10.0"),
            market_value=Decimal("1500.00"),
            currency="USD",
            dedup_hash="hash1",
            source_documents={},
        )
        db.add(snap)
        await db.flush()

        # 2. Reconcile
        await service.reconcile_positions(db, test_user.id)

        # 3. Verify Managed Position created
        positions = await service.get_positions(db, test_user.id)
        assert len(positions) == 1
        pos = positions[0]
        assert pos.asset_identifier == "AAPL"
        assert pos.quantity == Decimal("10.0")
        assert pos.status == PositionStatus.ACTIVE
        assert pos.account.name == "Moomoo"

    async def test_reconcile_updates_position(self, db, test_user):
        """Test that reconciling updates existing position quantity."""
        service = AssetService()

        # 1. Create Initial Atomic Position
        snap1 = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 15),
            asset_identifier="AAPL",
            broker="Moomoo",
            quantity=Decimal("10.0"),
            market_value=Decimal("1500.00"),
            currency="USD",
            dedup_hash="hash1",
            source_documents={},
        )
        db.add(snap1)
        await service.reconcile_positions(db, test_user.id)

        # 2. Create Newer Atomic Position (Quantity Change)
        snap2 = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 16),
            asset_identifier="AAPL",
            broker="Moomoo",
            quantity=Decimal("15.0"),
            market_value=Decimal("2250.00"),
            currency="USD",
            dedup_hash="hash2",
            source_documents={},
        )
        db.add(snap2)
        await db.flush()

        # 3. Reconcile Again
        await service.reconcile_positions(db, test_user.id)

        # 4. Verify Update
        positions = await service.get_positions(db, test_user.id)
        assert len(positions) == 1
        pos = positions[0]
        assert pos.quantity == Decimal("15.0")

    async def test_reconcile_disposes_position(self, db, test_user):
        """Test that 0 quantity marks position as disposed."""
        service = AssetService()

        # 1. Create Initial Atomic Position
        snap1 = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 15),
            asset_identifier="AAPL",
            broker="Moomoo",
            quantity=Decimal("10.0"),
            market_value=Decimal("1500.00"),
            currency="USD",
            dedup_hash="hash1",
            source_documents={},
        )
        db.add(snap1)
        await service.reconcile_positions(db, test_user.id)

        # 2. Create Disposal Snapshot
        snap2 = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 17),
            asset_identifier="AAPL",
            broker="Moomoo",
            quantity=Decimal("0.0"),
            market_value=Decimal("0.00"),
            currency="USD",
            dedup_hash="hash2",
            source_documents={},
        )
        db.add(snap2)
        await db.flush()

        # 3. Reconcile
        await service.reconcile_positions(db, test_user.id)

        # 4. Verify Disposed
        positions = await service.get_positions(db, test_user.id)
        assert len(positions) == 0  # get_positions filters ACTIVE

        # Check DB directly
        res = await db.execute(select(ManagedPosition).where(ManagedPosition.user_id == test_user.id))
        pos = res.scalar_one()
        assert pos.status == PositionStatus.DISPOSED
        assert pos.disposal_date == date(2024, 1, 17)
