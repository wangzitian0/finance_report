from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.models.account import Account, AccountType
from src.models.consistency_check import CheckStatus, CheckType, ConsistencyCheck
from src.models.layer1 import DocumentType, UploadedDocument
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement_enums import BankStatementStatus
from src.models.statement_summary import StatementSummary
from src.services.consistency_checks import (
    detect_anomalies_batch,
    detect_duplicates,
    detect_transfer_pairs,
    get_pending_checks,
    has_unresolved_checks,
    resolve_check,
    run_all_consistency_checks,
)


@pytest.fixture
def user_id(test_user):
    return test_user.id


async def _make_statement(db, user_id, *, file_hash: str) -> StatementSummary:
    """Create an ODS document + linked StatementSummary conform envelope."""
    account = Account(
        user_id=user_id,
        name=f"Consistency Account {uuid4()}",
        type=AccountType.ASSET,
        currency="USD",
    )
    doc = UploadedDocument(
        id=uuid4(),
        user_id=user_id,
        file_path=f"statements/{file_hash}.pdf",
        file_hash=file_hash,
        original_filename="test.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add_all([account, doc])
    await db.flush()

    statement = StatementSummary(
        id=uuid4(),
        user_id=user_id,
        uploaded_document_id=doc.id,
        file_hash=file_hash,
        account_id=account.id,
        institution="Test Bank",
        currency="USD",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 1, 31),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
        status=BankStatementStatus.APPROVED,
    )
    db.add(statement)
    await db.flush()
    return statement


async def _add_txn(
    db,
    user_id,
    *,
    amount: Decimal,
    direction: TransactionDirection,
    txn_date: date,
    description: str,
    source_doc_id=None,
) -> AtomicTransaction:
    txn = AtomicTransaction(
        id=uuid4(),
        user_id=user_id,
        txn_date=txn_date,
        description=description,
        amount=amount,
        direction=direction,
        currency="USD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[
            {
                "doc_id": str(source_doc_id or uuid4()),
                "doc_type": DocumentType.BANK_STATEMENT.value,
            }
        ],
    )
    db.add(txn)
    await db.flush()
    return txn


@pytest.fixture
async def approved_statement(db, user_id):
    return await _make_statement(db, user_id, file_hash=str(uuid4()))


class TestDetectDuplicates:
    async def test_detect_duplicates(self, db, user_id, approved_statement):
        """AC2.1.1 AC16.2.1 Detect duplicate transactions for a user."""
        await _add_txn(
            db,
            user_id,
            amount=Decimal("5.50"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 15),
            description="Starbucks",
        )
        await _add_txn(
            db,
            user_id,
            amount=Decimal("5.50"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 15),
            description="Starbucks",
        )

        checks = await detect_duplicates(db, user_id, approved_statement.id)
        assert len(checks) == 1
        assert checks[0].check_type == CheckType.DUPLICATE
        assert len(checks[0].related_txn_ids) == 2


class TestDetectTransferPairs:
    async def test_detect_transfer_pairs(self, db, user_id):
        """AC2.2.1 AC16.2.2 Detect matching transfer pairs (OUT/IN)."""
        txn_out = await _add_txn(
            db,
            user_id,
            amount=Decimal("100.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 15),
            description="Transfer to Bank B",
        )
        txn_in = await _add_txn(
            db,
            user_id,
            amount=Decimal("100.00"),
            direction=TransactionDirection.IN,
            txn_date=date(2024, 1, 16),
            description="Transfer from Bank A",
        )

        checks = await detect_transfer_pairs(db, user_id)
        assert len(checks) == 1
        assert checks[0].check_type == CheckType.TRANSFER_PAIR
        assert set(checks[0].related_txn_ids) == {str(txn_out.id), str(txn_in.id)}


class TestDetectAnomalies:
    async def test_detect_large_amount(self, db, user_id, approved_statement):
        """AC2.3.1 Detect large transaction amount anomalies."""
        for i in range(10):
            await _add_txn(
                db,
                user_id,
                amount=Decimal("10.00"),
                direction=TransactionDirection.OUT,
                txn_date=date(2024, 1, i + 1),
                description="Regular",
            )

        await _add_txn(
            db,
            user_id,
            amount=Decimal("1000.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 15),
            description="Giant Buy",
        )

        checks = await detect_anomalies_batch(db, user_id, approved_statement.id)
        # Should detect at least LARGE_AMOUNT and NEW_MERCHANT
        assert len(checks) >= 1
        types = [c.check_type for c in checks]
        assert CheckType.ANOMALY in types


class TestResolveCheck:
    async def test_resolve_check(self, db, user_id):
        """AC2.4.1 Resolve a consistency check and update status."""
        check = ConsistencyCheck(
            id=uuid4(),
            user_id=user_id,
            check_type=CheckType.DUPLICATE,
            status=CheckStatus.PENDING,
            related_txn_ids=["txn1"],
            details={},
        )
        db.add(check)
        await db.flush()

        assert await has_unresolved_checks(db, user_id) is True

        resolved = await resolve_check(db, check.id, "approve", user_id, "All good")
        assert resolved.status == CheckStatus.APPROVED
        assert resolved.resolution_note == "All good"
        assert resolved.resolved_at is not None

        assert await has_unresolved_checks(db, user_id) is False


class TestRunAllConsistencyChecks:
    async def test_run_all_aggregates_results(self, db, user_id, approved_statement):
        """AC2.5.1 run_all_consistency_checks aggregates results from all detectors."""
        await _add_txn(
            db,
            user_id,
            amount=Decimal("5.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 15),
            description="Coffee",
        )
        await _add_txn(
            db,
            user_id,
            amount=Decimal("5.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 15),
            description="Coffee",
        )

        checks = await run_all_consistency_checks(db, user_id, approved_statement.id)
        # Should include at least the duplicate check
        assert len(checks) >= 1
        types = {c.check_type for c in checks}
        assert CheckType.DUPLICATE in types

    async def test_run_all_empty_statement(self, db, user_id, approved_statement):
        """AC2.5.2 run_all_consistency_checks returns empty for clean statement."""
        # No transactions -> no checks
        checks = await run_all_consistency_checks(db, user_id, approved_statement.id)
        assert checks == []


class TestGetPendingChecks:
    async def test_get_pending_returns_only_pending(self, db, user_id):
        """AC2.6.1 get_pending_checks returns only PENDING checks."""
        pending = ConsistencyCheck(
            id=uuid4(),
            user_id=user_id,
            check_type=CheckType.DUPLICATE,
            status=CheckStatus.PENDING,
            related_txn_ids=["txn1"],
            details={},
        )
        resolved = ConsistencyCheck(
            id=uuid4(),
            user_id=user_id,
            check_type=CheckType.ANOMALY,
            status=CheckStatus.APPROVED,
            related_txn_ids=["txn2"],
            details={},
        )
        db.add_all([pending, resolved])
        await db.flush()

        result = await get_pending_checks(db, user_id)
        assert len(result) == 1
        assert result[0].id == pending.id
        assert result[0].status == CheckStatus.PENDING

    async def test_get_pending_filters_by_type(self, db, user_id):
        """AC2.6.2 get_pending_checks filters by check_type."""
        dup = ConsistencyCheck(
            id=uuid4(),
            user_id=user_id,
            check_type=CheckType.DUPLICATE,
            status=CheckStatus.PENDING,
            related_txn_ids=["txn1"],
            details={},
        )
        anomaly = ConsistencyCheck(
            id=uuid4(),
            user_id=user_id,
            check_type=CheckType.ANOMALY,
            status=CheckStatus.PENDING,
            related_txn_ids=["txn2"],
            details={},
        )
        db.add_all([dup, anomaly])
        await db.flush()

        result = await get_pending_checks(db, user_id, check_type=CheckType.DUPLICATE)
        assert len(result) == 1
        assert result[0].check_type == CheckType.DUPLICATE

    async def test_get_pending_empty(self, db, user_id):
        """AC2.6.3 get_pending_checks returns empty when no pending checks."""
        result = await get_pending_checks(db, user_id)
        assert result == []


class TestDetectDuplicatesEdgeCases:
    async def test_global_scan_no_statement_id(self, db, user_id, approved_statement):
        """AC16.4.1 detect_duplicates runs global scan when no statement_id provided."""
        await _add_txn(
            db,
            user_id,
            amount=Decimal("9.99"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 15),
            description="Global dup",
        )
        await _add_txn(
            db,
            user_id,
            amount=Decimal("9.99"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 15),
            description="Global dup",
        )

        checks = await detect_duplicates(db, user_id)
        assert len(checks) >= 1
        assert checks[0].check_type == CheckType.DUPLICATE

    async def test_idempotent_duplicate_detection(self, db, user_id, approved_statement):
        """AC16.4.2 detect_duplicates is idempotent - does not create duplicate checks."""
        await _add_txn(
            db,
            user_id,
            amount=Decimal("4.50"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 20),
            description="Coffee Shop",
        )
        await _add_txn(
            db,
            user_id,
            amount=Decimal("4.50"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 20),
            description="Coffee Shop",
        )

        checks1 = await detect_duplicates(db, user_id, approved_statement.id)
        assert len(checks1) == 1

        checks2 = await detect_duplicates(db, user_id, approved_statement.id)
        assert len(checks2) == 0

    async def test_no_duplicate_when_date_spread_exceeds_1_day(self, db, user_id, approved_statement):
        """detect_duplicates does not flag txns with >1 day apart as duplicates."""
        await _add_txn(
            db,
            user_id,
            amount=Decimal("25.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 10),
            description="Grocery",
        )
        await _add_txn(
            db,
            user_id,
            amount=Decimal("25.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 15),
            description="Grocery",
        )

        checks = await detect_duplicates(db, user_id, approved_statement.id)
        assert len(checks) == 0

    async def test_global_scan_detects_duplicates_across_statements(self, db, user_id):
        """detect_duplicates scans all user transactions regardless of source statement."""
        anchor_stmt = await _make_statement(db, user_id, file_hash="hash_anchor")
        other_stmt = await _make_statement(db, user_id, file_hash="hash_other")

        await _add_txn(
            db,
            user_id,
            amount=Decimal("11.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 5),
            description="Anchor Unique",
            source_doc_id=anchor_stmt.uploaded_document_id,
        )
        await _add_txn(
            db,
            user_id,
            amount=Decimal("20.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 8),
            description="Outside Anchor Dup",
            source_doc_id=other_stmt.uploaded_document_id,
        )
        await _add_txn(
            db,
            user_id,
            amount=Decimal("20.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 1, 8),
            description="Outside Anchor Dup",
            source_doc_id=other_stmt.uploaded_document_id,
        )

        checks = await detect_duplicates(db, user_id, anchor_stmt.id)
        assert len(checks) == 1
        assert checks[0].check_type == CheckType.DUPLICATE


class TestDetectTransferPairsEdgeCases:
    async def test_global_scan_no_statement_id(self, db, user_id):
        """AC16.4.3 detect_transfer_pairs runs global scan when no statement_id provided."""
        await _add_txn(
            db,
            user_id,
            amount=Decimal("200.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 2, 1),
            description="Transfer out",
        )
        await _add_txn(
            db,
            user_id,
            amount=Decimal("200.00"),
            direction=TransactionDirection.IN,
            txn_date=date(2024, 2, 2),
            description="Transfer in",
        )

        checks = await detect_transfer_pairs(db, user_id)
        assert len(checks) >= 1
        assert checks[0].check_type == CheckType.TRANSFER_PAIR

    async def test_idempotent_transfer_pair_detection(self, db, user_id):
        """AC16.4.3 detect_transfer_pairs is idempotent."""
        out_txn = await _add_txn(
            db,
            user_id,
            amount=Decimal("75.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 2, 5),
            description="Idem transfer out",
        )
        await _add_txn(
            db,
            user_id,
            amount=Decimal("75.00"),
            direction=TransactionDirection.IN,
            txn_date=date(2024, 2, 6),
            description="Idem transfer in",
        )

        checks1 = await detect_transfer_pairs(db, user_id, out_txn.id)
        assert len(checks1) == 1

        checks2 = await detect_transfer_pairs(db, user_id, out_txn.id)
        assert len(checks2) == 0

    async def test_transfer_pair_matching_skips_already_used_in_candidate(self, db, user_id):
        await _add_txn(
            db,
            user_id,
            amount=Decimal("100.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 3, 1),
            description="Transfer out 1",
        )
        await _add_txn(
            db,
            user_id,
            amount=Decimal("100.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 3, 2),
            description="Transfer out 2",
        )
        await _add_txn(
            db,
            user_id,
            amount=Decimal("100.00"),
            direction=TransactionDirection.IN,
            txn_date=date(2024, 3, 1),
            description="Transfer in 1",
        )
        await _add_txn(
            db,
            user_id,
            amount=Decimal("100.00"),
            direction=TransactionDirection.IN,
            txn_date=date(2024, 3, 2),
            description="Transfer in 2",
        )

        checks = await detect_transfer_pairs(db, user_id)
        assert len(checks) == 2


class TestResolveCheckEdgeCases:
    async def test_resolve_check_invalid_action_raises(self, db, user_id):
        """AC16.4.4 resolve_check raises ValueError on invalid action."""
        check = ConsistencyCheck(
            id=uuid4(),
            user_id=user_id,
            check_type=CheckType.DUPLICATE,
            status=CheckStatus.PENDING,
            related_txn_ids=["txn_x"],
            details={},
        )
        db.add(check)
        await db.flush()

        with pytest.raises(ValueError, match="Invalid action"):
            await resolve_check(db, check.id, "unknown_action", user_id)

    async def test_resolve_check_not_found_raises(self, db, user_id):
        """AC16.4.5 resolve_check raises ValueError when check not found."""
        non_existent_id = uuid4()
        with pytest.raises(ValueError, match="Check not found or access denied"):
            await resolve_check(db, non_existent_id, "approve", user_id)

    async def test_resolve_check_wrong_user_raises(self, db, user_id):
        """AC16.4.5 resolve_check raises ValueError when called with wrong user_id."""
        check = ConsistencyCheck(
            id=uuid4(),
            user_id=user_id,
            check_type=CheckType.ANOMALY,
            status=CheckStatus.PENDING,
            related_txn_ids=["txn_y"],
            details={},
        )
        db.add(check)
        await db.flush()

        wrong_user_id = uuid4()
        with pytest.raises(ValueError, match="Check not found or access denied"):
            await resolve_check(db, check.id, "approve", wrong_user_id)

    async def test_resolve_check_sets_flagged(self, db, user_id):
        """AC16.4.6 resolve_check sets FLAGGED status when action=flag."""
        check = ConsistencyCheck(
            id=uuid4(),
            user_id=user_id,
            check_type=CheckType.DUPLICATE,
            status=CheckStatus.PENDING,
            related_txn_ids=["txn_z"],
            details={},
        )
        db.add(check)
        await db.flush()

        resolved = await resolve_check(db, check.id, "flag", user_id, "Suspicious")
        assert resolved.status == CheckStatus.FLAGGED
        assert resolved.resolution_note == "Suspicious"

    async def test_resolve_check_sets_rejected(self, db, user_id):
        """resolve_check sets REJECTED status when action=reject."""
        check = ConsistencyCheck(
            id=uuid4(),
            user_id=user_id,
            check_type=CheckType.TRANSFER_PAIR,
            status=CheckStatus.PENDING,
            related_txn_ids=["txn_r"],
            details={},
        )
        db.add(check)
        await db.flush()

        resolved = await resolve_check(db, check.id, "reject", user_id)
        assert resolved.status == CheckStatus.REJECTED


class TestDetectAnomaliesEdgeCases:
    async def test_detect_anomalies_batch_skips_existing_same_anomaly_type(self, db, user_id, approved_statement):
        txn = await _add_txn(
            db,
            user_id,
            amount=Decimal("33.00"),
            direction=TransactionDirection.OUT,
            txn_date=date(2024, 4, 1),
            description="Recurring Charge",
        )

        db.add(
            ConsistencyCheck(
                id=uuid4(),
                user_id=user_id,
                check_type=CheckType.ANOMALY,
                status=CheckStatus.PENDING,
                related_txn_ids=[str(txn.id)],
                details={"anomaly_type": "REPEATED_DESCRIPTION"},
            )
        )
        await db.flush()

        with patch(
            "src.services.consistency_checks.detect_anomalies",
            new=AsyncMock(
                return_value=[SimpleNamespace(anomaly_type="REPEATED_DESCRIPTION", message="x", severity="low")]
            ),
        ):
            checks = await detect_anomalies_batch(db, user_id, approved_statement.id)

        assert checks == []


class TestGetPendingChecksEdgeCases:
    async def test_get_pending_filters_by_severity(self, db, user_id):
        """AC16.4.7 get_pending_checks filters by severity."""
        high_check = ConsistencyCheck(
            id=uuid4(),
            user_id=user_id,
            check_type=CheckType.DUPLICATE,
            status=CheckStatus.PENDING,
            related_txn_ids=["txn_high"],
            details={},
            severity="high",
        )
        medium_check = ConsistencyCheck(
            id=uuid4(),
            user_id=user_id,
            check_type=CheckType.TRANSFER_PAIR,
            status=CheckStatus.PENDING,
            related_txn_ids=["txn_med"],
            details={},
            severity="medium",
        )
        db.add_all([high_check, medium_check])
        await db.flush()

        result = await get_pending_checks(db, user_id, severity="high")
        assert len(result) == 1
        assert result[0].id == high_check.id
