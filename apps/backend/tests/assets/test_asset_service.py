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
        """AC11.1.1: Test that reconciling creates a new managed position."""
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
        positions, total = await service.get_positions(db, test_user.id)
        assert len(positions) == 1
        assert total == 1
        pos = positions[0]
        assert pos.asset_identifier == "AAPL"
        assert pos.quantity == Decimal("10.0")
        assert pos.status == PositionStatus.ACTIVE
        assert pos.account.name == "Moomoo"

    async def test_reconcile_updates_position(self, db, test_user):
        """AC11.1.2: Test that reconciling updates existing position quantity."""
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
        positions, _ = await service.get_positions(db, test_user.id)
        assert len(positions) == 1
        pos = positions[0]
        assert pos.quantity == Decimal("15.0")

    async def test_reconcile_disposes_position(self, db, test_user):
        """AC11.1.3: Test that 0 quantity marks position as disposed."""
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

        # 4. Verify Disposed - use ACTIVE filter to confirm it's not returned
        active_positions, active_count = await service.get_positions(
            db, test_user.id, status_filter=PositionStatus.ACTIVE
        )
        assert len(active_positions) == 0
        assert active_count == 0

        # Check DB directly
        res = await db.execute(select(ManagedPosition).where(ManagedPosition.user_id == test_user.id))
        pos = res.scalar_one()
        assert pos.status == PositionStatus.DISPOSED
        assert pos.disposal_date == date(2024, 1, 17)

    async def test_reconcile_cost_basis_uses_market_value(self, db, test_user):
        """AC11.1.4: Test that cost_basis is set from market_value."""
        service = AssetService()

        snap = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 15),
            asset_identifier="TSLA",
            broker="Interactive Brokers",
            quantity=Decimal("5.0"),
            market_value=Decimal("1250.00"),
            currency="USD",
            dedup_hash="hash_tsla",
            source_documents={},
        )
        db.add(snap)
        await db.flush()

        await service.reconcile_positions(db, test_user.id)

        positions, _ = await service.get_positions(db, test_user.id)
        assert len(positions) == 1
        assert positions[0].cost_basis == Decimal("1250.00")

    async def test_reconcile_multiple_assets(self, db, test_user):
        """AC11.1.5: Test reconciling multiple different assets."""
        service = AssetService()

        snap1 = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 15),
            asset_identifier="AAPL",
            broker="Moomoo",
            quantity=Decimal("10.0"),
            market_value=Decimal("1500.00"),
            currency="USD",
            dedup_hash="hash_aapl",
            source_documents={},
        )
        snap2 = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 15),
            asset_identifier="GOOGL",
            broker="Moomoo",
            quantity=Decimal("5.0"),
            market_value=Decimal("700.00"),
            currency="USD",
            dedup_hash="hash_googl",
            source_documents={},
        )
        db.add_all([snap1, snap2])
        await db.flush()

        await service.reconcile_positions(db, test_user.id)

        positions, _ = await service.get_positions(db, test_user.id)
        assert len(positions) == 2
        identifiers = {p.asset_identifier for p in positions}
        assert identifiers == {"AAPL", "GOOGL"}

    async def test_reconcile_multiple_brokers_same_asset(self, db, test_user):
        """AC11.1.6: Test same asset at different brokers creates separate positions."""
        service = AssetService()

        snap1 = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 15),
            asset_identifier="AAPL",
            broker="Moomoo",
            quantity=Decimal("10.0"),
            market_value=Decimal("1500.00"),
            currency="USD",
            dedup_hash="hash_moomoo",
            source_documents={},
        )
        snap2 = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 15),
            asset_identifier="AAPL",
            broker="Interactive Brokers",
            quantity=Decimal("20.0"),
            market_value=Decimal("3000.00"),
            currency="USD",
            dedup_hash="hash_ib",
            source_documents={},
        )
        db.add_all([snap1, snap2])
        await db.flush()

        await service.reconcile_positions(db, test_user.id)

        positions, _ = await service.get_positions(db, test_user.id)
        assert len(positions) == 2
        brokers = {p.account.name for p in positions}
        assert brokers == {"Moomoo", "Interactive Brokers"}

    async def test_reconcile_with_null_broker(self, db, test_user):
        """AC11.1.7: Test handling of null broker name."""
        service = AssetService()

        snap = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 15),
            asset_identifier="BTC",
            broker=None,
            quantity=Decimal("0.5"),
            market_value=Decimal("25000.00"),
            currency="USD",
            dedup_hash="hash_btc",
            source_documents={},
        )
        db.add(snap)
        await db.flush()

        await service.reconcile_positions(db, test_user.id)

        positions, _ = await service.get_positions(db, test_user.id)
        assert len(positions) == 1
        assert positions[0].account.name == "Unknown Broker"

    async def test_reconcile_reactivates_disposed_position(self, db, test_user):
        """AC11.1.8: Test that disposed position can be reactivated."""
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
            snapshot_date=date(2024, 1, 16),
            asset_identifier="AAPL",
            broker="Moomoo",
            quantity=Decimal("0.0"),
            market_value=Decimal("0.00"),
            currency="USD",
            dedup_hash="hash2",
            source_documents={},
        )
        db.add(snap2)
        await service.reconcile_positions(db, test_user.id)

        # 3. Create Newer Atomic Position
        snap3 = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 17),
            asset_identifier="AAPL",
            broker="Moomoo",
            quantity=Decimal("5.0"),
            market_value=Decimal("800.00"),
            currency="USD",
            dedup_hash="hash3",
            source_documents={},
        )
        db.add(snap3)
        await db.flush()

        await service.reconcile_positions(db, test_user.id)

        positions, _ = await service.get_positions(db, test_user.id)
        assert len(positions) == 1
        pos = positions[0]
        assert pos.status == PositionStatus.ACTIVE
        assert pos.quantity == Decimal("5.0")
        assert pos.disposal_date is None

    async def test_get_positions_empty(self, db, test_user):
        """AC11.1.9: Test get_positions returns empty list when no positions exist."""
        service = AssetService()

        positions, total = await service.get_positions(db, test_user.id)
        assert positions == []
        assert total == 0

    async def test_reconcile_no_snapshots(self, db, test_user):
        """AC11.1.10: Test reconcile with no atomic snapshots does nothing."""
        service = AssetService()

        await service.reconcile_positions(db, test_user.id)

        positions, total = await service.get_positions(db, test_user.id)
        assert positions == []
        assert total == 0

    async def test_reconcile_negative_quantity_short_position(self, db, test_user):
        """AC11.1.11: Test that negative quantities (short positions) are handled correctly."""
        service = AssetService()

        snap = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 15),
            asset_identifier="TSLA",
            broker="Moomoo",
            quantity=Decimal("-10.0"),
            market_value=Decimal("1500.00"),
            currency="USD",
            dedup_hash="hash_short",
            source_documents={},
        )
        db.add(snap)
        await db.flush()

        result = await service.reconcile_positions(db, test_user.id)

        assert result.created == 1
        positions, _ = await service.get_positions(db, test_user.id)
        assert len(positions) == 1
        pos = positions[0]
        assert pos.quantity == Decimal("-10.0")
        assert pos.status == PositionStatus.ACTIVE

    async def test_reconcile_result_counts_are_mutually_exclusive(self, db, test_user):
        """AC11.1.12: Test that updated and disposed counts don't double-count."""
        service = AssetService()

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

        snap2 = AtomicPosition(
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 16),
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

        result = await service.reconcile_positions(db, test_user.id)

        assert result.disposed == 1
        assert result.updated == 0
