"""AC4.3: Reconciliation API router tests for review queue and status management.

Tests all endpoints in src/routers/reconciliation.py covering:
- AC4.1: Matching core (POST /reconciliation/run)
- AC4.2: Group matching and batch operations
- AC4.3: Review queue and status management
- AC4.4: Performance optimization
- AC4.5: Anomaly detection

Endpoints:
- POST /reconciliation/run - Run reconciliation matching
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

from src.models import (
    BankStatement,
    BankStatementTransaction,
    BankStatementTransactionStatus,
    JournalEntry,
    ReconciliationMatch,
    ReconciliationStatus,
    User,
)
from src.schemas.reconciliation import ReconciliationStatusEnum


def create_test_statement(db, user: User, **kwargs):
    """Helper to create BankStatement with required fields."""
    from src.models.statement import BankStatementStatus as Status

    defaults = {
        "id": uuid4(),
        "user_id": user.id,
        "file_path": "statements/test.pdf",
        "file_hash": f"hash_{uuid4().hex[:8]}",
        "original_filename": "test.pdf",
        "institution": "Test Bank",
        "status": Status.PARSED,
    }
    defaults.update(kwargs)
    return BankStatement(**defaults)


def create_test_transaction(db, statement: BankStatement, **kwargs):
    """Helper to create BankStatementTransaction with required fields."""
    defaults = {
        "id": uuid4(),
        "statement_id": statement.id,
        "txn_date": date(2024, 1, 15),
        "description": "Test transaction",
        "amount": Decimal("100.00"),
        "direction": "DR",
        "status": BankStatementTransactionStatus.UNMATCHED,
    }
    defaults.update(kwargs)
    return BankStatementTransaction(**defaults)


def create_test_match(db, transaction: BankStatementTransaction, **kwargs):
    """Helper to create ReconciliationMatch with required fields."""
    defaults = {
        "id": str(uuid4()),
        "bank_txn_id": transaction.id,
        "status": ReconciliationStatus.PENDING_REVIEW,
        "match_score": 85,
        "journal_entry_ids": [],
    }
    defaults.update(kwargs)
    return ReconciliationMatch(**defaults)


class TestReconciliationEndpoints:
    """Test reconciliation API endpoints."""

    async def test_run_reconciliation_success(self, client: AsyncClient, db, test_user: User):
        """Test successful reconciliation run."""
        # GIVEN valid statement with transactions
        statement = create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        transaction = create_test_transaction(db, statement)
        db.add(transaction)
        await db.commit()

        # WHEN calling run endpoint
        payload = {"statement_id": str(statement.id)}
        response = await client.post("/reconciliation/run", json=payload)

        # THEN returns 200 with run results
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "matches_created" in data
        assert "auto_accepted" in data
        assert "pending_review" in data
        assert "unmatched" in data

    async def test_run_reconciliation_statement_not_found(self, client: AsyncClient, test_user: User):
        """Test reconciliation run with non-existent statement."""
        # GIVEN non-existent statement ID
        payload = {"statement_id": str(uuid4())}

        # WHEN calling run endpoint
        response = await client.post("/reconciliation/run", json=payload)

        # THEN returns 404 Not Found
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Statement" in response.json()["detail"]

    async def test_list_matches_success(self, client: AsyncClient, db, test_user: User):
        """Test listing reconciliation matches."""
        # GIVEN existing matches with proper hierarchy
        statement = create_test_statement(db, test_user)
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
        """Test listing matches with status filter."""
        # GIVEN matches with different statuses
        statement = create_test_statement(db, test_user)
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
        """Test listing pending review queue."""
        # GIVEN pending review matches
        statement = create_test_statement(db, test_user)
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
        """Test accepting a reconciliation match."""
        # GIVEN existing match
        statement = create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        transaction = create_test_transaction(db, statement)
        db.add(transaction)
        await db.commit()

        match = create_test_match(db, transaction)
        db.add(match)
        await db.commit()

        # WHEN calling accept endpoint
        response = await client.post(f"/reconciliation/matches/{match.id}/accept")

        # THEN returns 200 with updated match
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == ReconciliationStatusEnum.ACCEPTED.value

    async def test_accept_match_not_found(self, client: AsyncClient, test_user: User):
        """Test accepting non-existent match."""
        # GIVEN non-existent match ID
        non_existent_id = str(uuid4())

        # WHEN calling accept endpoint
        response = await client.post(f"/reconciliation/matches/{non_existent_id}/accept")

        # THEN returns 404 Not Found
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Match" in response.json()["detail"]

    async def test_reject_match_success(self, client: AsyncClient, db, test_user: User):
        """Test rejecting a reconciliation match."""
        # GIVEN existing match
        statement = create_test_statement(db, test_user)
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
        """Test rejecting non-existent match."""
        # GIVEN non-existent match ID
        non_existent_id = str(uuid4())

        # WHEN calling reject endpoint
        response = await client.post(f"/reconciliation/matches/{non_existent_id}/reject")

        # THEN returns 404 Not Found
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Match" in response.json()["detail"]

    async def test_batch_accept_success(self, client: AsyncClient, db, test_user: User):
        """Test batch accepting matches."""
        # GIVEN multiple matches
        statement = create_test_statement(db, test_user)
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

        # WHEN calling batch accept endpoint
        payload = {"match_ids": [match1.id, match2.id]}
        response = await client.post("/reconciliation/batch-accept", json=payload)

        # THEN returns 200 with accepted matches
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, dict)
        assert "items" in data
        assert "total" in data

    async def test_batch_accept_empty(self, client: AsyncClient):
        """Test batch accept with empty match IDs."""
        # WHEN calling batch accept endpoint with empty list
        payload = {"match_ids": []}
        response = await client.post("/reconciliation/batch-accept", json=payload)

        # THEN returns 200 with empty result
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_reconciliation_stats_success(self, client: AsyncClient, db, test_user: User):
        """Test getting reconciliation statistics."""
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
        """Test listing unmatched transactions."""
        # GIVEN unmatched transactions
        statement = create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        txn1 = create_test_transaction(db, statement, status=BankStatementTransactionStatus.UNMATCHED)
        txn2 = create_test_transaction(db, statement, status=BankStatementTransactionStatus.UNMATCHED)
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

    async def test_create_entry_from_unmatched_success(self, client: AsyncClient, db, test_user: User):
        """Test creating journal entry from unmatched transaction."""
        # GIVEN unmatched transaction
        statement = create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        transaction = create_test_transaction(
            db,
            statement,
            status=BankStatementTransactionStatus.UNMATCHED,
        )
        db.add(transaction)
        await db.commit()

        # WHEN calling create entry endpoint
        response = await client.post(f"/reconciliation/unmatched/{transaction.id}/create-entry")

        # THEN returns 200 with created entry
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "id" in data
        assert "entry_date" in data
        assert "memo" in data
        assert "status" in data
        assert "total_amount" in data

    async def test_create_entry_from_unmatched_not_found(self, client: AsyncClient, test_user: User):
        """Test creating entry from non-existent transaction."""
        # GIVEN non-existent transaction ID
        non_existent_id = str(uuid4())

        # WHEN calling create entry endpoint
        response = await client.post(f"/reconciliation/unmatched/{non_existent_id}/create-entry")

        # THEN returns 404 Not Found
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Transaction" in response.json()["detail"]

    async def test_list_anomalies_success(self, client: AsyncClient, db, test_user: User):
        """Test listing anomalies for a transaction."""
        # GIVEN transaction
        statement = create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        transaction = create_test_transaction(
            db,
            statement,
            status=BankStatementTransactionStatus.UNMATCHED,
        )
        db.add(transaction)
        await db.commit()

        # WHEN calling anomalies endpoint
        response = await client.get(f"/reconciliation/transactions/{transaction.id}/anomalies")

        # THEN returns 200 with anomalies list
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    async def test_list_anomalies_not_found(self, client: AsyncClient, test_user: User):
        """Test listing anomalies for non-existent transaction."""
        # GIVEN non-existent transaction ID
        non_existent_id = str(uuid4())

        # WHEN calling anomalies endpoint
        response = await client.get(f"/reconciliation/transactions/{non_existent_id}/anomalies")

        # THEN returns 404 Not Found
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Transaction" in response.json()["detail"]

    async def test_unauthenticated_access(self, public_client: AsyncClient, test_user: User):
        """Test that unauthenticated clients cannot access reconciliation endpoints."""
        # GIVEN unauthenticated client
        # WHEN calling any reconciliation endpoint
        response = await public_client.get("/reconciliation/stats")

        # THEN returns 401 Unauthorized
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_user_isolation(self, client: AsyncClient, db, test_user: User):
        """Test that users can only access their own reconciliation data."""
        # GIVEN statement belonging to different user
        other_user = User(email="other@example.com", hashed_password="hashed")
        db.add(other_user)
        await db.commit()

        other_statement = create_test_statement(db, other_user)
        db.add(other_statement)
        await db.commit()

        other_transaction = create_test_transaction(
            db,
            other_statement,
            status=BankStatementTransactionStatus.UNMATCHED,
        )
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
        """Test reconciliation run with statement_id filter."""
        # GIVEN statement with transactions
        statement = create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        txn1 = create_test_transaction(db, statement, status=BankStatementTransactionStatus.UNMATCHED)
        txn2 = create_test_transaction(db, statement, status=BankStatementTransactionStatus.UNMATCHED)
        db.add_all([txn1, txn2])
        await db.commit()

        # WHEN calling run endpoint with statement_id filter
        payload = {"statement_id": str(statement.id)}
        response = await client.post("/reconciliation/run", json=payload)

        # THEN returns 200 with filtered results
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "unmatched" in data
        assert data["unmatched"] >= 0

    async def test_list_matches_with_entry_summaries(self, client: AsyncClient, db, test_user: User):
        """Test listing matches with journal entry summaries."""
        from datetime import date
        from decimal import Decimal

        from src.models import Account, AccountType, JournalEntryStatus, JournalLine

        # GIVEN account for journal entry
        account = Account(
            id=uuid4(),
            user_id=test_user.id,
            name="Test Account",
            code="1000",
            type=AccountType.ASSET,
        )
        db.add(account)
        await db.commit()

        # GIVEN journal entry
        entry = JournalEntry(
            id=uuid4(),
            user_id=test_user.id,
            entry_date=date(2024, 1, 15),
            memo="Test entry",
            status=JournalEntryStatus.POSTED,
        )
        db.add(entry)
        await db.commit()

        # GIVEN journal lines
        from src.models import Direction

        line1 = JournalLine(
            id=uuid4(),
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=Direction.DEBIT,
            amount=Decimal("100.00"),
        )
        line2 = JournalLine(
            id=uuid4(),
            journal_entry_id=entry.id,
            account_id=account.id,
            direction=Direction.CREDIT,
            amount=Decimal("100.00"),
        )
        db.add_all([line1, line2])
        await db.commit()

        # GIVEN match with journal entry reference
        statement = create_test_statement(db, test_user)
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
        """Test listing matches with invalid journal entry UUID."""
        # GIVEN match with invalid UUID in journal_entry_ids
        statement = create_test_statement(db, test_user)
        db.add(statement)
        await db.commit()

        transaction = create_test_transaction(db, statement)
        db.add(transaction)
        await db.commit()

        match = create_test_match(
            db,
            transaction,
            journal_entry_ids=["invalid-uuid", "not-a-uuid"],
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
