from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.models import BankStatement, BankStatementStatus, BankStatementTransaction
from src.models.consistency_check import CheckStatus, CheckType, ConsistencyCheck
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
def user_id():
    return uuid4()


@pytest.fixture
async def approved_statement(db, user_id):
    stmt = BankStatement(
        id=uuid4(),
        user_id=user_id,
        file_path="test.pdf",
        file_hash=str(uuid4()),
        original_filename="test.pdf",
        institution="Test Bank",
        currency="USD",
        status=BankStatementStatus.APPROVED,
    )
    db.add(stmt)
    await db.flush()
    return stmt


class TestDetectDuplicates:
    async def test_detect_duplicates(self, db, user_id, approved_statement):
        """AC2.1.1 Detect duplicate transactions within a single approved statement."""
        txn1 = BankStatementTransaction(
            id=uuid4(),
            statement_id=approved_statement.id,
            txn_date=date(2024, 1, 15),
            description="Starbucks",
            amount=Decimal("5.50"),
            direction="OUT",
            status="pending",
        )
        txn2 = BankStatementTransaction(
            id=uuid4(),
            statement_id=approved_statement.id,
            txn_date=date(2024, 1, 15),
            description="Starbucks",
            amount=Decimal("5.50"),
            direction="OUT",
            status="pending",
        )
        db.add_all([txn1, txn2])
        await db.flush()

        checks = await detect_duplicates(db, user_id, approved_statement.id)
        assert len(checks) == 1
        assert checks[0].check_type == CheckType.DUPLICATE
        assert len(checks[0].related_txn_ids) == 2


class TestDetectTransferPairs:
    async def test_detect_transfer_pairs(self, db, user_id):
        """AC2.2.1 Detect matching transfer pairs (OUT/IN) across different accounts."""
        # Create two accounts
        stmt1 = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="out.pdf",
            file_hash="hash_out",
            original_filename="out.pdf",
            institution="Bank A",
            status=BankStatementStatus.APPROVED,
        )
        stmt2 = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="in.pdf",
            file_hash="hash_in",
            original_filename="in.pdf",
            institution="Bank B",
            status=BankStatementStatus.APPROVED,
        )
        db.add_all([stmt1, stmt2])
        await db.flush()

        txn_out = BankStatementTransaction(
            id=uuid4(),
            statement_id=stmt1.id,
            txn_date=date(2024, 1, 15),
            description="Transfer to Bank B",
            amount=Decimal("100.00"),
            direction="OUT",
            status="pending",
        )
        txn_in = BankStatementTransaction(
            id=uuid4(),
            statement_id=stmt2.id,
            txn_date=date(2024, 1, 16),  # 1 day later
            description="Transfer from Bank A",
            amount=Decimal("100.00"),
            direction="IN",
            status="pending",
        )
        db.add_all([txn_out, txn_in])
        await db.flush()

        checks = await detect_transfer_pairs(db, user_id)
        assert len(checks) == 1
        assert checks[0].check_type == CheckType.TRANSFER_PAIR
        assert set(checks[0].related_txn_ids) == {str(txn_out.id), str(txn_in.id)}


class TestDetectAnomalies:
    async def test_detect_large_amount(self, db, user_id, approved_statement):
        """AC2.3.1 Detect large transaction amount anomalies."""
        # Create history
        for i in range(10):
            txn = BankStatementTransaction(
                id=uuid4(),
                statement_id=approved_statement.id,
                txn_date=date(2024, 1, i + 1),
                description="Regular",
                amount=Decimal("10.00"),
                direction="OUT",
                status="pending",
            )
            db.add(txn)
        await db.flush()

        large_txn = BankStatementTransaction(
            id=uuid4(),
            statement_id=approved_statement.id,
            txn_date=date(2024, 1, 15),
            description="Giant Buy",
            amount=Decimal("1000.00"),
            direction="OUT",
            status="pending",
        )
        db.add(large_txn)
        await db.flush()

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
        # Create duplicate pair
        txn1 = BankStatementTransaction(
            id=uuid4(),
            statement_id=approved_statement.id,
            txn_date=date(2024, 1, 15),
            description="Coffee",
            amount=Decimal("5.00"),
            direction="OUT",
            status="pending",
        )
        txn2 = BankStatementTransaction(
            id=uuid4(),
            statement_id=approved_statement.id,
            txn_date=date(2024, 1, 15),
            description="Coffee",
            amount=Decimal("5.00"),
            direction="OUT",
            status="pending",
        )
        db.add_all([txn1, txn2])
        await db.flush()

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
        txn1 = BankStatementTransaction(
            id=uuid4(),
            statement_id=approved_statement.id,
            txn_date=date(2024, 1, 15),
            description="Global dup",
            amount=Decimal("9.99"),
            direction="OUT",
            status="pending",
        )
        txn2 = BankStatementTransaction(
            id=uuid4(),
            statement_id=approved_statement.id,
            txn_date=date(2024, 1, 15),
            description="Global dup",
            amount=Decimal("9.99"),
            direction="OUT",
            status="pending",
        )
        db.add_all([txn1, txn2])
        await db.flush()

        checks = await detect_duplicates(db, user_id)
        assert len(checks) >= 1
        assert checks[0].check_type == CheckType.DUPLICATE

    async def test_idempotent_duplicate_detection(self, db, user_id, approved_statement):
        """AC16.4.2 detect_duplicates is idempotent - does not create duplicate checks."""
        txn1 = BankStatementTransaction(
            id=uuid4(),
            statement_id=approved_statement.id,
            txn_date=date(2024, 1, 20),
            description="Coffee Shop",
            amount=Decimal("4.50"),
            direction="OUT",
            status="pending",
        )
        txn2 = BankStatementTransaction(
            id=uuid4(),
            statement_id=approved_statement.id,
            txn_date=date(2024, 1, 20),
            description="Coffee Shop",
            amount=Decimal("4.50"),
            direction="OUT",
            status="pending",
        )
        db.add_all([txn1, txn2])
        await db.flush()

        checks1 = await detect_duplicates(db, user_id, approved_statement.id)
        assert len(checks1) == 1

        checks2 = await detect_duplicates(db, user_id, approved_statement.id)
        assert len(checks2) == 0

    async def test_no_duplicate_when_date_spread_exceeds_1_day(self, db, user_id, approved_statement):
        """detect_duplicates does not flag txns with >1 day apart as duplicates."""
        txn1 = BankStatementTransaction(
            id=uuid4(),
            statement_id=approved_statement.id,
            txn_date=date(2024, 1, 10),
            description="Grocery",
            amount=Decimal("25.00"),
            direction="OUT",
            status="pending",
        )
        txn2 = BankStatementTransaction(
            id=uuid4(),
            statement_id=approved_statement.id,
            txn_date=date(2024, 1, 15),
            description="Grocery",
            amount=Decimal("25.00"),
            direction="OUT",
            status="pending",
        )
        db.add_all([txn1, txn2])
        await db.flush()

        checks = await detect_duplicates(db, user_id, approved_statement.id)
        assert len(checks) == 0


class TestDetectTransferPairsEdgeCases:
    async def test_global_scan_no_statement_id(self, db, user_id):
        """AC16.4.3 detect_transfer_pairs runs global scan when no statement_id provided."""
        stmt1 = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="a.pdf",
            file_hash="hash_global_out",
            original_filename="a.pdf",
            institution="Bank A",
            status=BankStatementStatus.APPROVED,
        )
        stmt2 = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="b.pdf",
            file_hash="hash_global_in",
            original_filename="b.pdf",
            institution="Bank B",
            status=BankStatementStatus.APPROVED,
        )
        db.add_all([stmt1, stmt2])
        await db.flush()

        txn_out = BankStatementTransaction(
            id=uuid4(),
            statement_id=stmt1.id,
            txn_date=date(2024, 2, 1),
            description="Transfer out",
            amount=Decimal("200.00"),
            direction="OUT",
            status="pending",
        )
        txn_in = BankStatementTransaction(
            id=uuid4(),
            statement_id=stmt2.id,
            txn_date=date(2024, 2, 2),
            description="Transfer in",
            amount=Decimal("200.00"),
            direction="IN",
            status="pending",
        )
        db.add_all([txn_out, txn_in])
        await db.flush()

        checks = await detect_transfer_pairs(db, user_id)
        assert len(checks) >= 1
        assert checks[0].check_type == CheckType.TRANSFER_PAIR

    async def test_idempotent_transfer_pair_detection(self, db, user_id):
        """AC16.4.3 detect_transfer_pairs is idempotent."""
        stmt1 = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="c.pdf",
            file_hash="hash_idem_out",
            original_filename="c.pdf",
            institution="Bank C",
            status=BankStatementStatus.APPROVED,
        )
        stmt2 = BankStatement(
            id=uuid4(),
            user_id=user_id,
            file_path="d.pdf",
            file_hash="hash_idem_in",
            original_filename="d.pdf",
            institution="Bank D",
            status=BankStatementStatus.APPROVED,
        )
        db.add_all([stmt1, stmt2])
        await db.flush()

        txn_out = BankStatementTransaction(
            id=uuid4(),
            statement_id=stmt1.id,
            txn_date=date(2024, 2, 5),
            description="Idem transfer out",
            amount=Decimal("75.00"),
            direction="OUT",
            status="pending",
        )
        txn_in = BankStatementTransaction(
            id=uuid4(),
            statement_id=stmt2.id,
            txn_date=date(2024, 2, 6),
            description="Idem transfer in",
            amount=Decimal("75.00"),
            direction="IN",
            status="pending",
        )
        db.add_all([txn_out, txn_in])
        await db.flush()

        checks1 = await detect_transfer_pairs(db, user_id, stmt1.id)
        assert len(checks1) == 1

        checks2 = await detect_transfer_pairs(db, user_id, stmt1.id)
        assert len(checks2) == 0


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