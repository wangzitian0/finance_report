import pytest
from decimal import Decimal
from datetime import date, timedelta
from uuid import uuid4

from src.models import BankStatement, BankStatementStatus, BankStatementTransaction
from src.models.consistency_check import CheckStatus, CheckType, ConsistencyCheck
from src.services.consistency_checks import (
    detect_duplicates,
    detect_transfer_pairs,
    detect_anomalies_batch,
    resolve_check,
    has_unresolved_checks,
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
            txn_date=date(2024, 1, 16), # 1 day later
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
        # Create history
        for i in range(10):
            txn = BankStatementTransaction(
                id=uuid4(),
                statement_id=approved_statement.id,
                txn_date=date(2024, 1, i+1),
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
