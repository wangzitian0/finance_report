"""AC4.3: Reconciliation API router tests for review queue and status management.

Tests all endpoints in src/routers/reconciliation.py covering:
- AC4.1: Matching core (POST /reconciliation/runs)
- AC4.2: Group matching and batch operations
- AC4.3: Review queue and status management
- AC4.4: Performance optimization
- AC4.5: Anomaly detection

Endpoints:
- POST /reconciliation/runs - Run reconciliation matching
- GET /reconciliation/matches - List matches with status filter
- GET /reconciliation/pending - List pending review queue
- POST /reconciliation/matches/{match_id}/accept - Accept a match
- POST /reconciliation/matches/{match_id}/reject - Reject a match
- POST /reconciliation/batch-accept - Batch accept matches
- GET /reconciliation/stats - Get reconciliation statistics
- GET /reconciliation/unmatched - List unmatched transactions
- POST /reconciliation/unmatched/{txn_id}/create-entry - Create journal entry from unmatched transaction
- GET /reconciliation/transactions/{txn_id}/anomalies - List anomalies for a transaction
"""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select

from src.audit import STATEMENT_SOURCE_TYPES, JournalEntrySourceType
from src.extraction import DocumentType, UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction, TransactionDirection
from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import Account, AccountType, JournalEntry
from src.reconciliation import ReconciliationMatch, ReconciliationStatus
from src.schemas.reconciliation import ReconciliationStatusEnum
from tests.ledger._ledger_helpers import create_valid_posted_entry


async def create_test_statement(db, user: User, **kwargs) -> StatementSummary:
    """Create an UploadedDocument + StatementSummary conform envelope."""
    document = UploadedDocument(
        user_id=user.id,
        file_path="statements/test.pdf",
        file_hash=f"hash_{uuid4().hex[:8]}",
        original_filename="test.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(document)
    await db.flush()

    defaults = {
        "id": uuid4(),
        "user_id": user.id,
        "uploaded_document_id": document.id,
        "file_hash": document.file_hash,
        "institution": "Test Bank",
        "status": BankStatementStatus.PARSED,
    }
    defaults.update(kwargs)
    statement = StatementSummary(**defaults)
    db.add(statement)
    await db.flush()
    return statement


async def create_test_asset_account(db, user: User) -> Account:
    account = Account(
        user_id=user.id,
        name=f"Mapped Bank {uuid4().hex[:8]}",
        type=AccountType.ASSET,
        currency="SGD",
    )
    db.add(account)
    await db.flush()
    return account


def create_test_transaction(db, statement: StatementSummary, **kwargs) -> AtomicTransaction:
    """Build a Layer-2 AtomicTransaction linked to the statement's ODS document.

    Accepts and ignores a legacy ``status`` kwarg; per-transaction status no longer
    exists on AtomicTransaction (match status is the source of truth).
    """
    kwargs.pop("status", None)
    defaults = {
        "id": uuid4(),
        "user_id": statement.user_id,
        "txn_date": date(2024, 1, 15),
        "description": "Test transaction",
        "amount": Decimal("100.00"),
        "direction": TransactionDirection.OUT,
        "currency": "SGD",
        "dedup_hash": uuid4().hex + uuid4().hex,
        "source_documents": [
            {"doc_id": str(statement.uploaded_document_id), "doc_type": DocumentType.BANK_STATEMENT.value}
        ],
    }
    defaults.update(kwargs)
    return AtomicTransaction(**defaults)


def create_test_match(db, transaction: AtomicTransaction, **kwargs) -> ReconciliationMatch:
    """Helper to create ReconciliationMatch keyed on atomic_txn_id."""
    defaults = {
        "id": uuid4(),
        "atomic_txn_id": transaction.id,
        "status": ReconciliationStatus.PENDING_REVIEW,
        "match_score": 85,
        "journal_entry_ids": [],
    }
    defaults.update(kwargs)
    return ReconciliationMatch(**defaults)


class TestReconciliationEndpoints:
    """Test reconciliation API endpoints."""

    async def test_run_reconciliation_success(self, client: AsyncClient, db, test_user: User):
        """AC4.1.1: Test successful reconciliation run."""
        # GIVEN valid statement with transactions
        statement = await create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        transaction = create_test_transaction(db, statement)
        db.add(transaction)
        await db.commit()

        # WHEN calling run endpoint
        payload = {"statement_id": str(statement.id)}
        response = await client.post("/reconciliation/runs", json=payload)

        # THEN returns 200 with run results
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "matches_created" in data
        assert "auto_accepted" in data
        assert "pending_review" in data
        assert "unmatched" in data

    async def test_run_reconciliation_statement_not_found(self, client: AsyncClient, test_user: User):
        """AC4.1.2: Test reconciliation run with non-existent statement."""
        # GIVEN non-existent statement ID
        payload = {"statement_id": str(uuid4())}

        # WHEN calling run endpoint
        response = await client.post("/reconciliation/runs", json=payload)

        # THEN returns 404 Not Found
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Statement" in response.json()["detail"]

    async def test_list_matches_success(self, client: AsyncClient, db, test_user: User):
        """AC4.3.1: Test listing reconciliation matches."""
        # GIVEN existing matches with proper hierarchy
        statement = await create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        txn1 = create_test_transaction(db, statement)
        txn2 = create_test_transaction(db, statement)
        db.add_all([txn1, txn2])
        await db.commit()

        match1 = create_test_match(db, txn1, status=ReconciliationStatus.PENDING_REVIEW)
        match2 = create_test_match(db, txn2, status=ReconciliationStatus.AUTO_ACCEPTED)
        db.add_all([match1, match2])
        await db.commit()

        # WHEN calling matches endpoint
        response = await client.get("/reconciliation/matches")

        # THEN returns 200 with match list
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert "total" in data

    async def test_list_matches_with_status_filter(self, client: AsyncClient, db, test_user: User):
        """AC4.3.2: Test listing matches with status filter."""
        # GIVEN matches with different statuses
        statement = await create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        txn1 = create_test_transaction(db, statement)
        txn2 = create_test_transaction(db, statement)
        db.add_all([txn1, txn2])
        await db.commit()

        match1 = create_test_match(db, txn1, status=ReconciliationStatus.PENDING_REVIEW)
        match2 = create_test_match(db, txn2, status=ReconciliationStatus.AUTO_ACCEPTED)
        db.add_all([match1, match2])
        await db.commit()

        # WHEN calling matches endpoint with status filter
        response = await client.get("/reconciliation/matches?status=pending_review")

        # THEN returns 200 with filtered matches
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) == 1  # Only pending review matches

    async def test_list_pending_review_success(self, client: AsyncClient, db, test_user: User):
        """AC4.3.3: Test listing pending review queue."""
        # GIVEN pending review matches
        statement = await create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        txn1 = create_test_transaction(db, statement)
        txn2 = create_test_transaction(db, statement)
        db.add_all([txn1, txn2])
        await db.commit()

        match1 = create_test_match(db, txn1, status=ReconciliationStatus.PENDING_REVIEW)
        match2 = create_test_match(db, txn2, status=ReconciliationStatus.PENDING_REVIEW)
        db.add_all([match1, match2])
        await db.commit()

        # WHEN calling pending endpoint
        response = await client.get("/reconciliation/pending")

        # THEN returns 200 with pending matches
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert "total" in data

    async def test_accept_match_success(self, client: AsyncClient, db, test_user: User):
        """AC-reconciliation.review-queue.3: Accept a match against an existing entry."""
        # GIVEN an existing, balanced entry that the matcher has already selected
        from src.audit import JournalEntrySourceType
        from src.ledger import Direction, JournalEntryStatus, JournalLine

        account = await create_test_asset_account(db, test_user)
        statement = await create_test_statement(db, test_user, account_id=account.id, currency="SGD")
        db.add(statement)
        await db.commit()

        transaction = create_test_transaction(db, statement)
        db.add(transaction)
        await db.commit()

        counter_account = Account(
            user_id=test_user.id,
            name=f"Matched expense {uuid4().hex[:8]}",
            type=AccountType.EXPENSE,
            currency="SGD",
        )
        entry = JournalEntry(
            user_id=test_user.id,
            entry_date=transaction.txn_date,
            memo=transaction.description,
            source_type=JournalEntrySourceType.AUTO_MATCHED,
            source_id=transaction.id,
            status=JournalEntryStatus.POSTED,
        )
        db.add_all([counter_account, entry])
        await db.flush()
        db.add_all(
            [
                JournalLine(
                    journal_entry_id=entry.id,
                    account_id=counter_account.id,
                    direction=Direction.DEBIT,
                    amount=transaction.amount,
                    currency=transaction.currency,
                ),
                JournalLine(
                    journal_entry_id=entry.id,
                    account_id=account.id,
                    direction=Direction.CREDIT,
                    amount=transaction.amount,
                    currency=transaction.currency,
                ),
            ]
        )
        match = create_test_match(db, transaction, journal_entry_ids=[str(entry.id)])
        db.add(match)
        await db.commit()

        # WHEN calling accept endpoint
        response = await client.post(f"/reconciliation/matches/{match.id}/accept")

        # THEN returns 200 with updated match
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == ReconciliationStatusEnum.ACCEPTED.value

    async def test_accept_match_not_found(self, client: AsyncClient, test_user: User):
        """AC-reconciliation.review-queue.4: AC4.3.5: Test accepting non-existent match."""
        # GIVEN non-existent match ID
        non_existent_id = str(uuid4())

        # WHEN calling accept endpoint
        response = await client.post(f"/reconciliation/matches/{non_existent_id}/accept")

        # THEN returns 404 Not Found
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Match" in response.json()["detail"]

    async def test_reject_match_success(self, client: AsyncClient, db, test_user: User):
        """AC-reconciliation.review-queue.5: AC4.3.6: Test rejecting a reconciliation match."""
        # GIVEN existing match
        statement = await create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        transaction = create_test_transaction(db, statement)
        db.add(transaction)
        await db.commit()

        match = create_test_match(db, transaction)
        db.add(match)
        await db.commit()

        # WHEN calling reject endpoint
        response = await client.post(f"/reconciliation/matches/{match.id}/reject")

        # THEN returns 200 with updated match
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == ReconciliationStatusEnum.REJECTED.value

    async def test_reject_match_not_found(self, client: AsyncClient, test_user: User):
        """AC-reconciliation.review-queue.6: AC4.3.7: Test rejecting non-existent match."""
        # GIVEN non-existent match ID
        non_existent_id = str(uuid4())

        # WHEN calling reject endpoint
        response = await client.post(f"/reconciliation/matches/{non_existent_id}/reject")

        # THEN returns 404 Not Found
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Match" in response.json()["detail"]

    async def test_batch_accept_success(self, client: AsyncClient, db, test_user: User):
        """AC4.2.1: Test batch accepting matches."""
        # GIVEN multiple matches
        account = await create_test_asset_account(db, test_user)
        statement = await create_test_statement(db, test_user, account_id=account.id, currency="SGD")
        db.add(statement)
        await db.commit()

        txn1 = create_test_transaction(db, statement)
        txn2 = create_test_transaction(db, statement)
        db.add_all([txn1, txn2])
        await db.commit()

        entry1 = await create_valid_posted_entry(
            db,
            test_user.id,
            amount=txn1.amount,
            source_type=JournalEntrySourceType.AUTO_PARSED,
            source_id=txn1.id,
        )
        entry2 = await create_valid_posted_entry(
            db,
            test_user.id,
            amount=txn2.amount,
            source_type=JournalEntrySourceType.AUTO_PARSED,
            source_id=txn2.id,
        )
        match1 = create_test_match(
            db,
            txn1,
            status=ReconciliationStatus.PENDING_REVIEW,
            journal_entry_ids=[str(entry1.id)],
        )
        match2 = create_test_match(
            db,
            txn2,
            status=ReconciliationStatus.PENDING_REVIEW,
            journal_entry_ids=[str(entry2.id)],
        )
        db.add_all([match1, match2])
        await db.commit()

        # WHEN calling batch accept endpoint
        payload = {"match_ids": [str(match1.id), str(match2.id)]}
        response = await client.post("/reconciliation/batch-accept", json=payload)

        # THEN returns 200 with accepted matches
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert "total" in data

    async def test_batch_accept_empty(self, client: AsyncClient):
        """AC4.2.2: Test batch accept with empty match IDs."""
        # WHEN calling batch accept endpoint with empty list
        payload = {"match_ids": []}
        response = await client.post("/reconciliation/batch-accept", json=payload)

        # THEN returns 200 with empty result
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_reconciliation_stats_success(self, client: AsyncClient, db, test_user: User):
        """AC-reconciliation.review-queue.7: AC4.3.8: Test getting reconciliation statistics."""
        # GIVEN a user with transactions (setup handled by fixtures)

        # WHEN calling stats endpoint
        response = await client.get("/reconciliation/stats")

        # THEN returns 200 with stats
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, dict)
        assert "total_transactions" in data
        assert "matched_transactions" in data
        assert "unmatched_transactions" in data
        assert "pending_review" in data
        assert "auto_accepted" in data
        assert "match_rate" in data
        assert "score_distribution" in data

    async def test_list_unmatched_success(self, client: AsyncClient, db, test_user: User):
        """AC-reconciliation.review-queue.8: AC4.3.9: Test listing unmatched transactions."""
        # GIVEN unmatched transactions
        statement = await create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        txn1 = create_test_transaction(db, statement)
        txn2 = create_test_transaction(db, statement)
        db.add_all([txn1, txn2])
        await db.commit()

        # WHEN calling unmatched endpoint
        response = await client.get("/reconciliation/unmatched")

        # THEN returns 200 with unmatched transactions
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert "total" in data

    async def test_create_entry_from_unmatched_requires_economic_disposition(
        self, client: AsyncClient, db, test_user: User
    ):
        """AC-reconciliation.review-queue.9: unmatched facts cannot create a default entry."""
        account = await create_test_asset_account(db, test_user)
        statement = await create_test_statement(db, test_user, account_id=account.id, currency="SGD")
        db.add(statement)
        await db.commit()

        transaction = create_test_transaction(db, statement)
        db.add(transaction)
        await db.commit()

        # WHEN calling create entry without reviewed economic meaning
        response = await client.post(f"/reconciliation/unmatched/{transaction.id}/create-entry")

        # THEN it fails closed rather than posting an Uncategorized fallback.
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Authoritative economic disposition" in response.json()["detail"]

    async def test_create_entry_from_unmatched_not_found(self, client: AsyncClient, test_user: User):
        """AC-reconciliation.review-queue.10: AC4.3.11: Test creating entry from non-existent transaction."""
        # GIVEN non-existent transaction ID
        non_existent_id = uuid4()

        # WHEN calling create entry endpoint
        response = await client.post(f"/reconciliation/unmatched/{non_existent_id}/create-entry")

        # THEN returns 404 Not Found
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Transaction" in response.json()["detail"]

    async def test_create_entry_from_unmatched_rejection_is_zero_write(self, client: AsyncClient, db, test_user: User):
        """Repeating a denied create-entry request must not leave a partial journal entry."""
        account = await create_test_asset_account(db, test_user)
        statement = await create_test_statement(db, test_user, account_id=account.id, currency="SGD")
        db.add(statement)
        await db.commit()

        transaction = create_test_transaction(db, statement)
        db.add(transaction)
        await db.commit()

        first = await client.post(f"/reconciliation/unmatched/{transaction.id}/create-entry")
        second = await client.post(f"/reconciliation/unmatched/{transaction.id}/create-entry")

        assert first.status_code == status.HTTP_400_BAD_REQUEST
        assert second.status_code == status.HTTP_400_BAD_REQUEST

        entries_result = await db.execute(
            select(JournalEntry)
            .where(JournalEntry.user_id == test_user.id)
            .where(JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES))
            .where(JournalEntry.source_id == transaction.id)
        )
        entries = entries_result.scalars().all()
        assert entries == []

    async def test_batch_create_entries_requires_economic_disposition(self, client: AsyncClient, db, test_user: User):
        """AC-reconciliation.review-queue.13: batch creation cannot bypass review."""
        account = await create_test_asset_account(db, test_user)
        statement = await create_test_statement(db, test_user, account_id=account.id, currency="SGD")
        db.add(statement)
        await db.commit()

        txn1 = create_test_transaction(db, statement)
        txn2 = create_test_transaction(db, statement)
        db.add_all([txn1, txn2])
        await db.commit()

        response = await client.post("/reconciliation/unmatched/batch-create", json={"all": True})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Authoritative economic disposition" in response.json()["detail"]

        entries_result = await db.execute(select(JournalEntry).where(JournalEntry.source_id.in_([txn1.id, txn2.id])))
        entries = entries_result.scalars().all()
        assert entries == []

    async def test_batch_create_entries_requires_filter(self, client: AsyncClient):
        """AC-reconciliation.review-queue.14: AC4.3.15: Test batch create returns 400 without all/txn_ids filter."""
        response = await client.post("/reconciliation/unmatched/batch-create", json={})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "txn_ids" in response.json()["detail"]

    async def test_batch_create_entries_all_respects_max_limit(
        self, client: AsyncClient, db, test_user: User, monkeypatch
    ):
        """all=True batch create should reject oversized unmatched sets."""
        from src.routers import reconciliation as reconciliation_router

        with monkeypatch.context() as local_monkeypatch:
            local_monkeypatch.setattr(reconciliation_router, "MAX_BATCH_CREATE_ALL", 1)
            statement = await create_test_statement(db, test_user)
            db.add(statement)
            await db.commit()

            txn1 = create_test_transaction(db, statement)
            txn2 = create_test_transaction(db, statement)
            db.add_all([txn1, txn2])
            await db.commit()

            response = await client.post("/reconciliation/unmatched/batch-create", json={"all": True})

            assert response.status_code == status.HTTP_400_BAD_REQUEST
            assert "Too many unmatched transactions" in response.json()["detail"]

    async def test_list_anomalies_success(self, client: AsyncClient, db, test_user: User):
        """AC4.5.1: Test listing anomalies for a transaction."""
        # GIVEN transaction
        statement = await create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        transaction = create_test_transaction(db, statement)
        db.add(transaction)
        await db.commit()

        # WHEN calling anomalies endpoint
        response = await client.get(f"/reconciliation/transactions/{transaction.id}/anomalies")

        # THEN returns 200 with anomalies list
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    async def test_list_anomalies_not_found(self, client: AsyncClient, test_user: User):
        """AC-reconciliation.anomaly-detection.2: AC4.5.2: Test listing anomalies for non-existent transaction."""
        # GIVEN non-existent transaction ID
        non_existent_id = uuid4()

        # WHEN calling anomalies endpoint
        response = await client.get(f"/reconciliation/transactions/{non_existent_id}/anomalies")

        # THEN returns 404 Not Found
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Transaction" in response.json()["detail"]

    async def test_unauthenticated_access(self, public_client: AsyncClient, test_user: User):
        """AC-reconciliation.review-queue.11: AC4.3.12: Test that unauthenticated clients cannot access reconciliation endpoints."""
        # GIVEN unauthenticated client
        # WHEN calling any reconciliation endpoint
        response = await public_client.get("/reconciliation/stats")

        # THEN returns 401 Unauthorized
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_user_isolation(self, client: AsyncClient, db, test_user: User):
        """AC-reconciliation.review-queue.12: AC4.3.13: Test that users can only access their own reconciliation data."""
        # GIVEN statement belonging to different user
        other_user = User(email="other@example.com", hashed_password="hashed")
        db.add(other_user)
        await db.commit()

        other_statement = await create_test_statement(db, other_user)
        db.add(other_statement)
        await db.commit()

        other_transaction = create_test_transaction(db, other_statement)
        db.add(other_transaction)
        await db.commit()

        # WHEN calling unmatched endpoint
        response = await client.get("/reconciliation/unmatched")

        # THEN returns 200 but should not include other user's data
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        # Verify no transactions from other user are returned
        for item in data.get("items", []):
            assert str(item.get("id")) != str(other_transaction.id)

    async def test_run_reconciliation_with_statement_filter(self, client: AsyncClient, db, test_user: User):
        """AC4.1.3: Test reconciliation run with statement_id filter."""
        # GIVEN statement with transactions
        statement = await create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        txn1 = create_test_transaction(db, statement)
        txn2 = create_test_transaction(db, statement)
        db.add_all([txn1, txn2])
        await db.commit()

        # WHEN calling run endpoint with statement_id filter
        payload = {"statement_id": str(statement.id)}
        response = await client.post("/reconciliation/runs", json=payload)

        # THEN returns 200 with filtered results
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "unmatched" in data
        assert data["unmatched"] >= 0

    async def test_list_matches_with_entry_summaries(self, client: AsyncClient, db, test_user: User):
        """AC4.3.14: Test listing matches with journal entry summaries."""
        from src.ledger import Account, AccountType, JournalEntryStatus, JournalLine

        # GIVEN account for journal entry
        account = Account(
            id=uuid4(),
            user_id=test_user.id,
            name="Test Account",
            type=AccountType.ASSET,
            currency="SGD",
        )
        db.add(account)
        await db.commit()

        # GIVEN journal entry
        entry = JournalEntry(
            id=uuid4(),
            user_id=test_user.id,
            entry_date=date.today(),
            memo="Test entry",
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.flush()

        # GIVEN journal lines
        from src.ledger import Direction

        line1 = JournalLine(
            id=uuid4(),
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
            currency="SGD",
        )
        line2 = JournalLine(
            id=uuid4(),
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=Direction.CREDIT,
            amount=Decimal("100.00"),
            currency="SGD",
        )
        db.add_all([line1, line2])
        await db.commit()

        # GIVEN match with journal entry reference
        statement = await create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        transaction = create_test_transaction(db, statement)
        db.add(transaction)
        await db.commit()

        match = create_test_match(
            db,
            transaction,
            journal_entry_ids=[str(entry.id)],
        )
        db.add(match)
        await db.commit()

        # WHEN calling matches endpoint
        response = await client.get("/reconciliation/matches")

        # THEN returns 200 with entry summaries
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["items"]) >= 1
        match_data = data["items"][0]
        assert "entries" in match_data
        if match_data["entries"]:
            assert "id" in match_data["entries"][0]
            assert "total_amount" in match_data["entries"][0]

    async def test_list_matches_with_invalid_entry_id(self, client: AsyncClient, db, test_user: User):
        """AC4.3.15: Test listing matches with invalid journal entry UUID."""
        # GIVEN match with invalid UUID in journal_entry_ids
        statement = await create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        transaction = create_test_transaction(db, statement)
        db.add(transaction)
        await db.commit()

        match = create_test_match(
            db,
            transaction,
            journal_entry_ids=[str(uuid4())],
        )
        db.add(match)
        await db.commit()

        # WHEN calling matches endpoint
        response = await client.get("/reconciliation/matches")

        # THEN returns 200 and handles invalid UUIDs gracefully
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "items" in data
        # Invalid UUIDs should be skipped, entries should be empty
        match_data = data["items"][0]
        assert match_data["entries"] == []
