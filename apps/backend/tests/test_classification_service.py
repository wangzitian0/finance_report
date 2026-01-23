"""Tests for Classification Service."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from src.models.account import Account, AccountType
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.layer3 import ClassificationRule, RuleType
from src.services.classification import ClassificationService


@pytest.mark.asyncio
class TestClassificationService:
    """Tests for classification logic."""

    async def test_apply_keyword_rule(self, db, test_user):
        """Test applying a keyword rule."""
        service = ClassificationService()

        # 1. Create Account
        account = Account(
            user_id=test_user.id,
            name="Groceries",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6000",
        )
        db.add(account)
        await db.flush()

        # 2. Create Rule
        rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="Grocery Rule",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": ["fairprice", "shengsiong"]},
            default_account_id=account.id,
            created_by=test_user.id,
        )
        db.add(rule)
        await db.flush()

        # 3. Create Transactions
        txn1 = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("50.00"),
            direction=TransactionDirection.OUT,
            description="NTUC FAIRPRICE",
            currency="SGD",
            dedup_hash="hash1",
            source_documents=[],
        )
        txn2 = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("100.00"),
            direction=TransactionDirection.OUT,
            description="Unknown Merchant",
            currency="SGD",
            dedup_hash="hash2",
            source_documents=[],
        )
        db.add_all([txn1, txn2])
        await db.flush()

        # 4. Apply Rules
        results = await service.apply_rules(db, test_user.id, [txn1, txn2])

        # 5. Verify
        assert len(results) == 1
        assert results[0].atomic_txn_id == txn1.id
        assert results[0].account_id == account.id
        assert results[0].rule_version_id == rule.id
