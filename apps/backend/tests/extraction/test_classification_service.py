"""Tests for Classification Service."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

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

    async def test_apply_regex_rule_basic_match(self, db, test_user):
        """Test applying a regex rule with basic pattern matching."""
        service = ClassificationService()

        # 1. Create Account
        account = Account(
            user_id=test_user.id,
            name="Transport",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6100",
        )
        db.add(account)
        await db.flush()

        # 2. Create Regex Rule - match transactions starting with "GRAB"
        rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="Grab Transport Rule",
            rule_type=RuleType.REGEX_MATCH,
            rule_config={"pattern": r"^GRAB\s+\w+"},
            default_account_id=account.id,
            created_by=test_user.id,
        )
        db.add(rule)
        await db.flush()

        # 3. Create Transactions
        txn_match = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("15.00"),
            direction=TransactionDirection.OUT,
            description="GRAB RIDE payment",
            currency="SGD",
            dedup_hash="hash_regex1",
            source_documents=[],
        )
        txn_no_match = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("25.00"),
            direction=TransactionDirection.OUT,
            description="GOJEK RIDE payment",
            currency="SGD",
            dedup_hash="hash_regex2",
            source_documents=[],
        )
        db.add_all([txn_match, txn_no_match])
        await db.flush()

        # 4. Apply Rules
        results = await service.apply_rules(db, test_user.id, [txn_match, txn_no_match])

        # 5. Verify - only the GRAB transaction should match
        assert len(results) == 1
        assert results[0].atomic_txn_id == txn_match.id
        assert results[0].account_id == account.id

    async def test_apply_regex_rule_empty_pattern(self, db, test_user):
        """Test that regex rule with empty pattern returns False."""
        service = ClassificationService()

        # 1. Create Account
        account = Account(
            user_id=test_user.id,
            name="Misc",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6200",
        )
        db.add(account)
        await db.flush()

        # 2. Create Regex Rule with empty pattern
        rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="Empty Pattern Rule",
            rule_type=RuleType.REGEX_MATCH,
            rule_config={"pattern": ""},  # Empty pattern
            default_account_id=account.id,
            created_by=test_user.id,
        )
        db.add(rule)
        await db.flush()

        # 3. Create Transaction
        txn = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("50.00"),
            direction=TransactionDirection.OUT,
            description="Some Transaction",
            currency="SGD",
            dedup_hash="hash_empty",
            source_documents=[],
        )
        db.add(txn)
        await db.flush()

        # 4. Apply Rules - should not match due to empty pattern
        results = await service.apply_rules(db, test_user.id, [txn])

        # 5. Verify - no matches
        assert len(results) == 0

    async def test_apply_regex_rule_case_insensitive(self, db, test_user):
        """Test regex rule with case_insensitive flag."""
        service = ClassificationService()

        # 1. Create Account
        account = Account(
            user_id=test_user.id,
            name="Dining",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6300",
        )
        db.add(account)
        await db.flush()

        # 2. Create Regex Rule with case_insensitive=True (default)
        rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="Restaurant Rule",
            rule_type=RuleType.REGEX_MATCH,
            rule_config={"pattern": r"restaurant", "case_insensitive": True},
            default_account_id=account.id,
            created_by=test_user.id,
        )
        db.add(rule)
        await db.flush()

        # 3. Create Transactions with different cases
        txn_upper = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("30.00"),
            direction=TransactionDirection.OUT,
            description="RESTAURANT XYZ",
            currency="SGD",
            dedup_hash="hash_case1",
            source_documents=[],
        )
        txn_lower = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("40.00"),
            direction=TransactionDirection.OUT,
            description="the restaurant abc",
            currency="SGD",
            dedup_hash="hash_case2",
            source_documents=[],
        )
        db.add_all([txn_upper, txn_lower])
        await db.flush()

        # 4. Apply Rules - both should match due to case insensitivity
        results = await service.apply_rules(db, test_user.id, [txn_upper, txn_lower])

        # 5. Verify - both transactions should match
        assert len(results) == 2

    async def test_apply_regex_rule_case_sensitive(self, db, test_user):
        """Test regex rule with case_insensitive=False."""
        service = ClassificationService()

        # 1. Create Account
        account = Account(
            user_id=test_user.id,
            name="Shopping",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6400",
        )
        db.add(account)
        await db.flush()

        # 2. Create Regex Rule with case_insensitive=False
        rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="Case Sensitive Rule",
            rule_type=RuleType.REGEX_MATCH,
            rule_config={"pattern": r"AMAZON", "case_insensitive": False},
            default_account_id=account.id,
            created_by=test_user.id,
        )
        db.add(rule)
        await db.flush()

        # 3. Create Transactions
        txn_upper = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("100.00"),
            direction=TransactionDirection.OUT,
            description="AMAZON Purchase",
            currency="SGD",
            dedup_hash="hash_sens1",
            source_documents=[],
        )
        txn_lower = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("50.00"),
            direction=TransactionDirection.OUT,
            description="amazon purchase",
            currency="SGD",
            dedup_hash="hash_sens2",
            source_documents=[],
        )
        db.add_all([txn_upper, txn_lower])
        await db.flush()

        # 4. Apply Rules - only uppercase should match
        results = await service.apply_rules(db, test_user.id, [txn_upper, txn_lower])

        # 5. Verify - only one match (case sensitive)
        assert len(results) == 1
        assert results[0].atomic_txn_id == txn_upper.id

    async def test_apply_regex_rule_invalid_pattern(self, db, test_user):
        """Test that invalid regex pattern logs warning and returns False."""
        service = ClassificationService()

        # 1. Create Account
        account = Account(
            user_id=test_user.id,
            name="Invalid Test",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6500",
        )
        db.add(account)
        await db.flush()

        # 2. Create Regex Rule with invalid pattern (unclosed group)
        rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="Invalid Regex Rule",
            rule_type=RuleType.REGEX_MATCH,
            rule_config={"pattern": r"(unclosed[group"},  # Invalid regex
            default_account_id=account.id,
            created_by=test_user.id,
        )
        db.add(rule)
        await db.flush()

        # 3. Create Transaction
        txn = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("75.00"),
            direction=TransactionDirection.OUT,
            description="Some Transaction",
            currency="SGD",
            dedup_hash="hash_invalid",
            source_documents=[],
        )
        db.add(txn)
        await db.flush()

        # 4. Apply Rules - should handle invalid regex gracefully
        with patch("src.services.classification.logger") as mock_logger:
            results = await service.apply_rules(db, test_user.id, [txn])

            # 5. Verify - no match and warning was logged
            assert len(results) == 0
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args[0][0]
            assert "Invalid regex pattern" in call_args

    async def test_apply_regex_rule_missing_pattern_key(self, db, test_user):
        """Test that regex rule with missing pattern key returns False."""
        service = ClassificationService()

        # 1. Create Account
        account = Account(
            user_id=test_user.id,
            name="Missing Key Test",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6600",
        )
        db.add(account)
        await db.flush()

        # 2. Create Regex Rule without pattern key
        rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="No Pattern Rule",
            rule_type=RuleType.REGEX_MATCH,
            rule_config={},  # No pattern key
            default_account_id=account.id,
            created_by=test_user.id,
        )
        db.add(rule)
        await db.flush()

        # 3. Create Transaction
        txn = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("60.00"),
            direction=TransactionDirection.OUT,
            description="Some Transaction",
            currency="SGD",
            dedup_hash="hash_nokey",
            source_documents=[],
        )
        db.add(txn)
        await db.flush()

        # 4. Apply Rules - should not match due to missing pattern
        results = await service.apply_rules(db, test_user.id, [txn])

        # 5. Verify - no matches
        assert len(results) == 0
