"""Tests for deduplication service.

GIVEN: DeduplicationService for managing Layer 2 deduplicated records
WHEN: Creating/upserting atomic transactions and positions
THEN: Hash-based deduplication works correctly with source document tracking
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.models.layer1 import DocumentType
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.services.deduplication import DeduplicationService


class TestDeduplicationService:
    """Test suite for DeduplicationService."""

    def test_calculate_transaction_hash(self):
        """GIVEN: Transaction details with reference
        WHEN: Calculating transaction hash
        THEN: SHA256 hash is generated from canonical components"""
        user_id = uuid4()
        txn_date = date(2024, 1, 15)
        amount = Decimal("100.50")
        direction = TransactionDirection.IN
        description = "Test Transaction"
        reference = "REF123"

        service = DeduplicationService()
        hash_result = service.calculate_transaction_hash(user_id, txn_date, amount, direction, description, reference)

        # Verify hash format
        assert len(hash_result) == 64  # SHA256 produces 64-char hex
        assert all(c in "0123456789abcdef" for c in hash_result)

        # Verify deterministic - same inputs produce same hash
        hash_result2 = service.calculate_transaction_hash(user_id, txn_date, amount, direction, description, reference)
        assert hash_result == hash_result2

        # Verify components are normalized (case-insensitive description)
        hash_normalized = service.calculate_transaction_hash(
            user_id, txn_date, amount, direction, "TEST TRANSACTION", reference
        )
        assert hash_result == hash_normalized

    def test_calculate_transaction_hash_without_reference(self):
        """GIVEN: Transaction details without reference
        WHEN: Calculating transaction hash
        THEN: Hash is generated with empty string for reference"""
        user_id = uuid4()
        txn_date = date(2024, 1, 15)
        amount = Decimal("100.50")
        direction = TransactionDirection.IN
        description = "Test Transaction"

        service = DeduplicationService()
        hash_result = service.calculate_transaction_hash(
            user_id, txn_date, amount, direction, description, reference=None
        )

        # Verify hash is generated
        assert len(hash_result) == 64

        # Verify None reference and empty string produce same hash
        hash_empty_ref = service.calculate_transaction_hash(
            user_id, txn_date, amount, direction, description, reference=""
        )
        assert hash_result == hash_empty_ref

    def test_calculate_position_hash(self):
        """GIVEN: Position details with broker
        WHEN: Calculating position hash
        THEN: SHA256 hash is generated from canonical components (covers lines 54-61)"""
        user_id = uuid4()
        snapshot_date = date(2024, 1, 31)
        asset_identifier = "AAPL"
        broker = "Interactive Brokers"

        service = DeduplicationService()
        hash_result = service.calculate_position_hash(user_id, snapshot_date, asset_identifier, broker)

        # Verify hash format
        assert len(hash_result) == 64  # SHA256 produces 64-char hex
        assert all(c in "0123456789abcdef" for c in hash_result)

        # Verify deterministic
        hash_result2 = service.calculate_position_hash(user_id, snapshot_date, asset_identifier, broker)
        assert hash_result == hash_result2

        # Verify normalization (case-insensitive asset + broker)
        hash_normalized = service.calculate_position_hash(user_id, snapshot_date, "aapl", "INTERACTIVE BROKERS")
        assert hash_result == hash_normalized

    def test_calculate_position_hash_without_broker(self):
        """GIVEN: Position details without broker
        WHEN: Calculating position hash
        THEN: Hash is generated with empty string for broker (covers lines 54-61)"""
        user_id = uuid4()
        snapshot_date = date(2024, 1, 31)
        asset_identifier = "AAPL"

        service = DeduplicationService()
        hash_result = service.calculate_position_hash(user_id, snapshot_date, asset_identifier, broker=None)

        # Verify hash is generated
        assert len(hash_result) == 64

        # Verify None broker and empty string produce same hash
        hash_empty_broker = service.calculate_position_hash(user_id, snapshot_date, asset_identifier, broker="")
        assert hash_result == hash_empty_broker

    @pytest.mark.asyncio
    async def test_upsert_atomic_transaction_new_creates_record(self, db, test_user):
        """GIVEN: No existing atomic transaction with hash
        WHEN: Upserting atomic transaction
        THEN: New record is created with source document"""
        service = DeduplicationService()
        doc_id = uuid4()

        txn = await service.upsert_atomic_transaction(
            db=db,
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("100.50"),
            direction=TransactionDirection.IN,
            description="Test Transaction",
            currency="USD",
            source_doc_id=doc_id,
            source_doc_type=DocumentType.BANK_STATEMENT,
            reference="REF123",
        )

        # Verify new record created
        assert txn.id is not None
        assert txn.user_id == test_user.id
        assert txn.amount == Decimal("100.50")
        assert txn.direction == TransactionDirection.IN
        assert txn.description == "Test Transaction"
        assert txn.reference == "REF123"
        assert txn.currency == "USD"
        assert len(txn.dedup_hash) == 64

        # Verify source document
        assert len(txn.source_documents) == 1
        assert txn.source_documents[0]["doc_id"] == str(doc_id)
        assert txn.source_documents[0]["doc_type"] == DocumentType.BANK_STATEMENT.value

    @pytest.mark.asyncio
    async def test_upsert_atomic_transaction_duplicate_appends_source(self, db, test_user):
        """GIVEN: Existing atomic transaction with same hash
        WHEN: Upserting duplicate transaction with different source
        THEN: Source document is appended to existing record (covers lines 98, 100-105)"""
        service = DeduplicationService()
        doc1_id = uuid4()
        doc2_id = uuid4()

        # Create first transaction
        txn1 = await service.upsert_atomic_transaction(
            db=db,
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("100.50"),
            direction=TransactionDirection.IN,
            description="Test Transaction",
            currency="USD",
            source_doc_id=doc1_id,
            source_doc_type=DocumentType.BANK_STATEMENT,
            reference="REF123",
        )
        original_id = txn1.id

        # Upsert duplicate with different source
        txn2 = await service.upsert_atomic_transaction(
            db=db,
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("100.50"),
            direction=TransactionDirection.IN,
            description="Test Transaction",  # Same transaction
            currency="USD",
            source_doc_id=doc2_id,
            source_doc_type=DocumentType.BROKERAGE_STATEMENT,
            reference="REF123",
        )

        # Verify same record returned
        assert txn2.id == original_id

        # Verify both sources in array
        assert len(txn2.source_documents) == 2
        doc_ids = {doc["doc_id"] for doc in txn2.source_documents}
        assert str(doc1_id) in doc_ids
        assert str(doc2_id) in doc_ids

    @pytest.mark.asyncio
    async def test_upsert_atomic_transaction_duplicate_same_source_no_duplicate(self, db, test_user):
        """GIVEN: Existing atomic transaction with same hash and source
        WHEN: Upserting duplicate with same source document
        THEN: Source document is not duplicated in array (covers line 100)"""
        service = DeduplicationService()
        doc_id = uuid4()

        # Create first transaction
        txn1 = await service.upsert_atomic_transaction(
            db=db,
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("100.50"),
            direction=TransactionDirection.IN,
            description="Test Transaction",
            currency="USD",
            source_doc_id=doc_id,
            source_doc_type=DocumentType.BANK_STATEMENT,
            reference="REF123",
        )

        # Upsert duplicate with SAME source
        txn2 = await service.upsert_atomic_transaction(
            db=db,
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("100.50"),
            direction=TransactionDirection.IN,
            description="Test Transaction",
            currency="USD",
            source_doc_id=doc_id,  # Same source
            source_doc_type=DocumentType.BANK_STATEMENT,
            reference="REF123",
        )

        # Verify same record returned
        assert txn2.id == txn1.id

        # Verify source document NOT duplicated
        assert len(txn2.source_documents) == 1
        assert txn2.source_documents[0]["doc_id"] == str(doc_id)

    @pytest.mark.asyncio
    async def test_upsert_atomic_position_new_creates_record(self, db, test_user):
        """GIVEN: No existing atomic position with hash
        WHEN: Upserting atomic position
        THEN: New record is created with source document (covers lines 158-215)"""
        service = DeduplicationService()
        doc_id = uuid4()

        pos = await service.upsert_atomic_position(
            db=db,
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 31),
            asset_identifier="AAPL",
            quantity=Decimal("10.5"),
            market_value=Decimal("1850.50"),
            currency="USD",
            source_doc_id=doc_id,
            source_doc_type=DocumentType.BROKERAGE_STATEMENT,
            broker="Interactive Brokers",
        )

        # Verify new record created
        assert pos.id is not None
        assert pos.user_id == test_user.id
        assert pos.snapshot_date == date(2024, 1, 31)
        assert pos.asset_identifier == "AAPL"
        assert pos.broker == "Interactive Brokers"
        assert pos.quantity == Decimal("10.5")
        assert pos.market_value == Decimal("1850.50")
        assert pos.currency == "USD"
        assert len(pos.dedup_hash) == 64

        # Verify source document
        assert len(pos.source_documents) == 1
        assert pos.source_documents[0]["doc_id"] == str(doc_id)
        assert pos.source_documents[0]["doc_type"] == DocumentType.BROKERAGE_STATEMENT.value

    @pytest.mark.asyncio
    async def test_upsert_atomic_position_duplicate_appends_source(self, db, test_user):
        """GIVEN: Existing atomic position with same hash
        WHEN: Upserting duplicate position with different source
        THEN: Source document is appended to existing record (covers lines 177-178)"""
        service = DeduplicationService()
        doc1_id = uuid4()
        doc2_id = uuid4()

        # Create first position
        pos1 = await service.upsert_atomic_position(
            db=db,
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 31),
            asset_identifier="AAPL",
            quantity=Decimal("10.5"),
            market_value=Decimal("1850.50"),
            currency="USD",
            source_doc_id=doc1_id,
            source_doc_type=DocumentType.BROKERAGE_STATEMENT,
            broker="Interactive Brokers",
        )
        original_id = pos1.id

        # Upsert duplicate with different source
        pos2 = await service.upsert_atomic_position(
            db=db,
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 31),
            asset_identifier="AAPL",  # Same position
            quantity=Decimal("10.5"),
            market_value=Decimal("1850.50"),
            currency="USD",
            source_doc_id=doc2_id,
            source_doc_type=DocumentType.BANK_STATEMENT,
            broker="Interactive Brokers",
        )

        # Verify same record returned
        assert pos2.id == original_id

        # Verify both sources in array
        assert len(pos2.source_documents) == 2
        doc_ids = {doc["doc_id"] for doc in pos2.source_documents}
        assert str(doc1_id) in doc_ids
        assert str(doc2_id) in doc_ids

    @pytest.mark.asyncio
    async def test_upsert_atomic_position_duplicate_same_source_no_duplicate(self, db, test_user):
        """GIVEN: Existing atomic position with same hash and source
        WHEN: Upserting duplicate with same source document
        THEN: Source document is not duplicated in array (covers line 177)"""
        service = DeduplicationService()
        doc_id = uuid4()

        # Create first position
        pos1 = await service.upsert_atomic_position(
            db=db,
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 31),
            asset_identifier="AAPL",
            quantity=Decimal("10.5"),
            market_value=Decimal("1850.50"),
            currency="USD",
            source_doc_id=doc_id,
            source_doc_type=DocumentType.BROKERAGE_STATEMENT,
            broker="Interactive Brokers",
        )

        # Upsert duplicate with SAME source
        pos2 = await service.upsert_atomic_position(
            db=db,
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 31),
            asset_identifier="AAPL",
            quantity=Decimal("10.5"),
            market_value=Decimal("1850.50"),
            currency="USD",
            source_doc_id=doc_id,  # Same source
            source_doc_type=DocumentType.BROKERAGE_STATEMENT,
            broker="Interactive Brokers",
        )

        # Verify same record returned
        assert pos2.id == pos1.id

        # Verify source document NOT duplicated
        assert len(pos2.source_documents) == 1
        assert pos2.source_documents[0]["doc_id"] == str(doc_id)

    @pytest.mark.asyncio
    async def test_upsert_atomic_position_without_broker(self, db, test_user):
        """GIVEN: Position details without broker
        WHEN: Upserting atomic position
        THEN: Position is created with None broker (covers lines 158-215)"""
        service = DeduplicationService()
        doc_id = uuid4()

        pos = await service.upsert_atomic_position(
            db=db,
            user_id=test_user.id,
            snapshot_date=date(2024, 1, 31),
            asset_identifier="AAPL",
            quantity=Decimal("10.5"),
            market_value=Decimal("1850.50"),
            currency="USD",
            source_doc_id=doc_id,
            source_doc_type=DocumentType.BROKERAGE_STATEMENT,
            broker=None,
        )

        # Verify record created
        assert pos.id is not None
        assert pos.broker is None
        assert len(pos.dedup_hash) == 64

    @pytest.mark.asyncio
    async def test_different_users_have_different_hashes(self, db, test_user):
        """GIVEN: Two users with identical transaction details
        WHEN: Upserting transactions
        THEN: Different dedup hashes are generated (user_id is part of hash)"""
        service = DeduplicationService()
        user1_id = test_user.id
        user2_id = uuid4()
        doc_id = uuid4()

        # Create transaction for user 1
        txn1 = await service.upsert_atomic_transaction(
            db=db,
            user_id=user1_id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("100.50"),
            direction=TransactionDirection.IN,
            description="Test Transaction",
            currency="USD",
            source_doc_id=doc_id,
            source_doc_type=DocumentType.BANK_STATEMENT,
            reference="REF123",
        )

        # Create same transaction for user 2
        txn2 = await service.upsert_atomic_transaction(
            db=db,
            user_id=user2_id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("100.50"),
            direction=TransactionDirection.IN,
            description="Test Transaction",
            currency="USD",
            source_doc_id=doc_id,
            source_doc_type=DocumentType.BANK_STATEMENT,
            reference="REF123",
        )

        # Verify different records created
        assert txn1.id != txn2.id
        assert txn1.dedup_hash != txn2.dedup_hash

    @pytest.mark.asyncio
    async def test_concurrent_upsert_same_hash_no_duplicates(self, db_engine, test_user):
        """GIVEN: Two concurrent upserts with identical transaction data in separate sessions
        WHEN: Both execute simultaneously
        THEN: Database constraint prevents duplicate records (race condition protection)

        This test verifies database-level race condition protection.
        The service has a check-then-act pattern (lines 87-127 in deduplication.py)
        which is vulnerable to race conditions. Protection relies on the database
        unique constraint on (user_id, dedup_hash).

        NOTE: If this test fails with IntegrityError, it means the database constraint
        is working correctly. If it passes by creating one record, protection is working.
        If it creates two records, the race condition vulnerability is exposed.
        """
        import asyncio

        from sqlalchemy.ext.asyncio import AsyncSession

        service = DeduplicationService()
        doc1_id = uuid4()
        doc2_id = uuid4()

        # Create two separate sessions to simulate concurrent requests
        async def upsert_in_session(doc_id):
            async with AsyncSession(db_engine) as session:
                async with session.begin():
                    txn = await service.upsert_atomic_transaction(
                        db=session,
                        user_id=test_user.id,
                        txn_date=date(2024, 1, 15),
                        amount=Decimal("100.50"),
                        direction=TransactionDirection.IN,
                        description="Concurrent Test",
                        currency="USD",
                        source_doc_id=doc_id,
                        source_doc_type=DocumentType.BANK_STATEMENT,
                        reference="CONCURRENT",
                    )
                    # Extract data before session closes to avoid detached instance access
                    return {
                        "id": txn.id,
                        "dedup_hash": txn.dedup_hash,
                        "source_count": len(txn.source_documents),
                    }

        # Execute concurrent upserts with separate sessions
        results = await asyncio.gather(
            upsert_in_session(doc1_id),
            upsert_in_session(doc2_id),
            return_exceptions=True,  # Capture IntegrityError if constraint works
        )

        # Check if database constraint prevented race condition
        # Case 1: Constraint worked - one succeeds, one fails with IntegrityError
        from sqlalchemy.exc import IntegrityError

        has_integrity_error = any(isinstance(r, IntegrityError) for r in results)

        # Case 2: One transaction succeeded (check-then-act won the race)
        successful_results: list[dict] = [r for r in results if not isinstance(r, Exception)]  # type: ignore[misc]

        if has_integrity_error:
            # Database constraint prevented duplicate - this is expected behavior
            assert len(successful_results) == 1, "Constraint should allow exactly one record"
            # The successful record should have ONE source (the first to insert)
            assert successful_results[0]["source_count"] == 1
        else:
            # Both succeeded - verify they returned the same record ID
            assert len(successful_results) == 2, f"Expected 2 results, got {len(successful_results)}"
            assert successful_results[0]["id"] == successful_results[1]["id"], (
                "Race condition: different IDs mean duplicate records created"
            )

            # Verify database has only one record
            async with AsyncSession(db_engine) as session:
                result = await session.execute(
                    select(AtomicTransaction).where(AtomicTransaction.dedup_hash == successful_results[0]["dedup_hash"])
                )
                all_records = result.scalars().all()
                assert len(all_records) == 1, f"Race condition: {len(all_records)} duplicate records in database"
