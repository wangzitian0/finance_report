"""Tests for deduplication service.

GIVEN: DeduplicationService for managing Layer 2 deduplicated records
WHEN: Creating/upserting atomic transactions and positions
THEN: Hash-based deduplication works correctly with source document tracking
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from src.extraction.extension.deduplication import DeduplicationService
from src.models.layer1 import DocumentType
from src.models.layer2 import AtomicTransaction, TransactionDirection
from tests.factories import UserFactory


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

    def test_running_balance_distinguishes_identical_transactions(self):
        """AC11.16.1: two otherwise-identical txns with different running balances hash differently;
        identical running balances (or none) collapse."""
        service = DeduplicationService()
        user_id = uuid4()
        txn_date = date(2024, 1, 1)
        amount = Decimal("50.00")
        direction = TransactionDirection.OUT
        description = "Batch Payment"

        def _hash(balance_after):
            return service.calculate_transaction_hash(
                user_id, txn_date, amount, direction, description, reference=None, balance_after=balance_after
            )

        # Different running balances -> distinct hashes (two real, separate payments).
        assert _hash(Decimal("950.00")) != _hash(Decimal("900.00"))
        # Same running balance -> same hash (a genuine duplicate extraction collapses).
        assert _hash(Decimal("950.00")) == _hash(Decimal("950.00"))
        # No running balance -> unchanged from the no-balance hash.
        assert _hash(None) == service.calculate_transaction_hash(
            user_id, txn_date, amount, direction, description, reference=None
        )
        # Scale differences are canonicalized: amount/balance differing only in scale hash identically.
        assert _hash(Decimal("950")) == _hash(Decimal("950.00")) == _hash(Decimal("950.000"))

    def test_occurrence_index_distinguishes_balanceless_repeats(self):
        """AC11.16.2: without a running balance, the per-document occurrence ordinal keeps
        genuinely-repeated identical rows distinct (recall first), while the first occurrence
        is unchanged and the running-balance path ignores the ordinal."""
        service = DeduplicationService()
        user_id = uuid4()
        txn_date = date(2024, 1, 1)
        amount = Decimal("5.00")
        direction = TransactionDirection.OUT
        description = "Coffee"

        def _hash(*, occurrence_index=0, balance_after=None):
            return service.calculate_transaction_hash(
                user_id,
                txn_date,
                amount,
                direction,
                description,
                reference=None,
                balance_after=balance_after,
                occurrence_index=occurrence_index,
            )

        # Two identical balance-less rows in one document -> distinct (two real coffees).
        assert _hash(occurrence_index=0) != _hash(occurrence_index=1)
        # First occurrence is the default; back-compat with the no-arg hash.
        assert _hash(occurrence_index=0) == service.calculate_transaction_hash(
            user_id, txn_date, amount, direction, description, reference=None
        )
        # AC13.22.1: the running balance is part of the disambiguator, but it is no longer the
        # *sole* key. The per-document occurrence ordinal is always folded in so two genuinely
        # distinct rows that happen to share a running balance (a page-boundary carried-forward /
        # brought-forward repeat) still hash differently.
        assert _hash(occurrence_index=0, balance_after=Decimal("100.00")) != _hash(
            occurrence_index=7, balance_after=Decimal("100.00")
        )
        # Same balance AND same ordinal -> same hash (a genuine cross-document duplicate collapses).
        assert _hash(occurrence_index=0, balance_after=Decimal("100.00")) == _hash(
            occurrence_index=0, balance_after=Decimal("100.00")
        )
        assert service.calculate_transaction_hash(
            user_id, txn_date, Decimal("50"), direction, description
        ) == service.calculate_transaction_hash(user_id, txn_date, Decimal("50.00"), direction, description)

    def test_AC13_22_1_same_balance_distinct_rows_do_not_collapse(self):
        """AC13.22.1: two genuinely-distinct same-date/same-amount/same-direction deposits that
        share one running ``balance_after`` (a page-boundary carried-forward / brought-forward
        repeat) must hash differently within one document, while a re-uploaded identical row still
        collapses across documents.

        This is the dedup-collapse root cause of #1254: before the fix, ``balance_after`` was the
        sole high-confidence disambiguator, so two real deposits printed against the same running
        balance hashed identically and the second was silently dropped at upsert."""
        service = DeduplicationService()
        user_id = uuid4()
        txn_date = date(2024, 3, 10)
        amount = Decimal("250.00")
        direction = TransactionDirection.IN
        description = "Incoming Transfer"
        balance = Decimal("1750.00")

        def _hash(occurrence_index):
            return service.calculate_transaction_hash(
                user_id,
                txn_date,
                amount,
                direction,
                description,
                reference=None,
                balance_after=balance,
                occurrence_index=occurrence_index,
            )

        # Within one parse: the two distinct deposits sit at ordinals 0 and 1 -> distinct hashes,
        # so both survive instead of the second collapsing into the first.
        first_deposit = _hash(occurrence_index=0)
        second_deposit = _hash(occurrence_index=1)
        assert first_deposit != second_deposit

        # Across documents: a re-uploaded statement reproduces the same ordered rows, so each row
        # keeps its (balance_after, occurrence_index) pair and the genuine duplicate still collapses.
        assert first_deposit == _hash(occurrence_index=0)
        assert second_deposit == _hash(occurrence_index=1)

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

    async def test_upsert_persists_balance_after(self, db, test_user):
        """AC4.6.8: upsert_atomic_transaction persists the extracted balance_after so the
        Stage-1 conflict guard can disambiguate distinct-but-identical transactions."""
        service = DeduplicationService()

        txn = await service.upsert_atomic_transaction(
            db=db,
            user_id=test_user.id,
            txn_date=date(2025, 6, 25),
            amount=Decimal("1033.50"),
            direction=TransactionDirection.OUT,
            description="Buy to Open NIO Inc NIO",
            currency="USD",
            source_doc_id=uuid4(),
            source_doc_type=DocumentType.BROKERAGE_STATEMENT,
            balance_after=Decimal("3966.50"),
        )
        assert txn.balance_after == Decimal("3966.50")

        # Reload from DB to confirm the value is persisted, not just set in memory.
        reloaded = (await db.execute(select(AtomicTransaction).where(AtomicTransaction.id == txn.id))).scalar_one()
        assert reloaded.balance_after == Decimal("3966.50")

    async def test_upsert_backfills_balance_after_on_legacy_null_row(self, db, test_user):
        """AC4.6.8: a legacy row whose dedup hash already encoded the running balance but left
        balance_after NULL (pre-migration) gets it backfilled when the same transaction is
        re-parsed, so previously-stuck statements benefit from the guard fix."""
        service = DeduplicationService()
        user_id = test_user.id
        balance = Decimal("3966.50")
        fields = dict(
            txn_date=date(2025, 6, 25),
            amount=Decimal("1033.50"),
            direction=TransactionDirection.OUT,
            description="Buy to Open NIO Inc NIO",
            reference=None,
        )
        # The hash always factored in balance_after; only the column was missing before the migration.
        dedup_hash = service.calculate_transaction_hash(user_id, balance_after=balance, **fields)
        legacy = AtomicTransaction(
            user_id=user_id,
            currency="USD",
            dedup_hash=dedup_hash,
            balance_after=None,
            source_documents=[{"doc_id": str(uuid4()), "doc_type": "brokerage_statement"}],
            **fields,
        )
        db.add(legacy)
        await db.flush()

        result = await service.upsert_atomic_transaction(
            db=db,
            user_id=user_id,
            currency="USD",
            source_doc_id=uuid4(),
            source_doc_type=DocumentType.BROKERAGE_STATEMENT,
            balance_after=balance,
            **fields,
        )

        assert result.id == legacy.id  # hit the existing branch, not a new insert
        assert result.balance_after == balance  # NULL was backfilled

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

    async def test_different_users_have_different_hashes(self, db, test_user):
        """GIVEN: Two users with identical transaction details
        WHEN: Upserting transactions
        THEN: Different dedup hashes are generated (user_id is part of hash)"""
        service = DeduplicationService()
        user1_id = test_user.id
        user2_id = (await UserFactory.create_async(db)).id
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

    async def test_upsert_atomic_transaction_handles_non_list_source_documents(self, db, test_user):
        """AC13.11.2: Dedup upsert sanitizes malformed source_documents payloads (transaction)."""
        service = DeduplicationService()
        doc1 = uuid4()
        doc2 = uuid4()

        txn = await service.upsert_atomic_transaction(
            db=db,
            user_id=test_user.id,
            txn_date=date(2024, 2, 1),
            amount=Decimal("12.00"),
            direction=TransactionDirection.OUT,
            description="Bad source docs",
            currency="SGD",
            source_doc_id=doc1,
            source_doc_type=DocumentType.BANK_STATEMENT,
        )
        txn.source_documents = {"bad": "shape"}
        await db.flush()

        txn2 = await service.upsert_atomic_transaction(
            db=db,
            user_id=test_user.id,
            txn_date=date(2024, 2, 1),
            amount=Decimal("12.00"),
            direction=TransactionDirection.OUT,
            description="Bad source docs",
            currency="SGD",
            source_doc_id=doc2,
            source_doc_type=DocumentType.BROKERAGE_STATEMENT,
        )
        assert isinstance(txn2.source_documents, list)
        assert len(txn2.source_documents) == 1

    async def test_upsert_atomic_position_handles_non_list_source_documents(self, db, test_user):
        """AC13.11.2: Dedup upsert sanitizes malformed source_documents payloads (position)."""
        service = DeduplicationService()
        doc1 = uuid4()
        doc2 = uuid4()

        pos = await service.upsert_atomic_position(
            db=db,
            user_id=test_user.id,
            snapshot_date=date(2024, 2, 1),
            asset_identifier="MSFT",
            quantity=Decimal("1"),
            market_value=Decimal("100"),
            currency="USD",
            source_doc_id=doc1,
            source_doc_type=DocumentType.BROKERAGE_STATEMENT,
            broker="IBKR",
        )
        pos.source_documents = {"bad": "shape"}
        await db.flush()

        pos2 = await service.upsert_atomic_position(
            db=db,
            user_id=test_user.id,
            snapshot_date=date(2024, 2, 1),
            asset_identifier="MSFT",
            quantity=Decimal("1"),
            market_value=Decimal("100"),
            currency="USD",
            source_doc_id=doc2,
            source_doc_type=DocumentType.BANK_STATEMENT,
            broker="IBKR",
        )
        assert isinstance(pos2.source_documents, list)
        assert len(pos2.source_documents) == 1
