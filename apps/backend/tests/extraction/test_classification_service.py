"""Tests for Classification Service.

AC18.1.4 AC11.12.2: deterministic rule matching and priority coverage (ML matching retired, EPIC #1483 cleanup).
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import select

from src.extraction.extension.classification import ClassificationService
from src.ledger import Account, AccountType
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.layer3 import ClassificationRule, RuleType, TransactionClassification
from tests.factories import AtomicTransactionFactory


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
        with patch("src.extraction.extension.classification.logger") as mock_logger:
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

    async def test_apply_keyword_rule_empty_keywords(self, db, test_user):
        """Test that keyword rule with empty keywords list returns no matches."""
        service = ClassificationService()

        # 1. Create Account
        account = Account(
            user_id=test_user.id,
            name="Empty Keywords Test",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6700",
        )
        db.add(account)
        await db.flush()

        # 2. Create Keyword Rule with empty keywords list
        rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="Empty Keywords Rule",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": []},  # Empty keywords list
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
            description="NTUC FAIRPRICE",
            currency="SGD",
            dedup_hash="hash_empty_kw",
            source_documents=[],
        )
        db.add(txn)
        await db.flush()

        # 4. Apply Rules - should not match due to empty keywords
        results = await service.apply_rules(db, test_user.id, [txn])

        # 5. Verify - no matches
        assert len(results) == 0

    async def test_apply_no_active_rules(self, db, test_user):
        """Test that apply_rules returns empty list when no active rules exist."""
        service = ClassificationService()

        # 1. Create Transaction (but no rules)
        txn = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("50.00"),
            direction=TransactionDirection.OUT,
            description="Some Transaction",
            currency="SGD",
            dedup_hash="hash_no_rules",
            source_documents=[],
        )
        db.add(txn)
        await db.flush()

        # 2. Apply Rules - should return empty list since no rules exist
        results = await service.apply_rules(db, test_user.id, [txn])

        # 3. Verify - empty results
        assert len(results) == 0

    async def test_apply_no_matching_keywords(self, db, test_user):
        """Test that rules with non-matching keywords return no results."""
        service = ClassificationService()

        account = Account(
            user_id=test_user.id,
            name="No Match Test",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6800",
        )
        db.add(account)
        await db.flush()

        rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="Non-matching Rule",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": ["NONEXISTENT_KEYWORD_ZZZ"]},
            default_account_id=account.id,
            created_by=test_user.id,
        )
        db.add(rule)
        await db.flush()

        txn = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("50.00"),
            direction=TransactionDirection.OUT,
            description="Some Transaction UNKNOWN",
            currency="SGD",
            dedup_hash="hash_unknown",
            source_documents=[],
        )
        db.add(txn)
        await db.flush()

        results = await service.apply_rules(db, test_user.id, [txn])

        assert len(results) == 0

    async def test_classification_priority_keyword_over_regex(self, db, test_user):
        """AC-extraction.1801.2: AC18.1.4 AC11.12.2: Rule type priority: KEYWORD beats REGEX (ML tier retired)."""
        service = ClassificationService()

        keyword_account = Account(
            user_id=test_user.id,
            name="Keyword Account",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6812",
        )
        regex_account = Account(
            user_id=test_user.id,
            name="Regex Account",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6813",
        )
        db.add_all([keyword_account, regex_account])
        await db.flush()

        keyword_rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="Keyword Priority",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": ["food"]},
            default_account_id=keyword_account.id,
            created_by=test_user.id,
        )
        regex_rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="Regex Priority",
            rule_type=RuleType.REGEX_MATCH,
            rule_config={"pattern": r"food"},
            default_account_id=regex_account.id,
            created_by=test_user.id,
        )
        db.add_all([keyword_rule, regex_rule])
        await db.flush()

        txn = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 1, 15),
            amount=Decimal("30.00"),
            direction=TransactionDirection.OUT,
            description="food delivery",
            currency="SGD",
            dedup_hash="hash_priority",
            source_documents=[{"category_confidence": "0.95", "suggested_category": "Food & Dining"}],
        )
        db.add(txn)
        await db.flush()

        results = await service.apply_rules(db, test_user.id, [txn])

        assert len(results) == 1
        assert results[0].account_id == keyword_account.id

    async def test_same_type_rules_prefer_newer_version(self, db, test_user):
        """AC11.12.2: Same-type matches choose the newest rule version deterministically."""
        service = ClassificationService()

        old_account = Account(
            user_id=test_user.id,
            name="Old Grocery Account",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6817",
        )
        new_account = Account(
            user_id=test_user.id,
            name="New Grocery Account",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6818",
        )
        db.add_all([old_account, new_account])
        await db.flush()

        old_rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="Grocery Rule",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": ["grocery"]},
            default_account_id=old_account.id,
            created_by=test_user.id,
        )
        new_rule = ClassificationRule(
            user_id=test_user.id,
            version_number=2,
            effective_date=date(2024, 2, 1),
            rule_name="Grocery Rule",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": ["grocery"]},
            default_account_id=new_account.id,
            created_by=test_user.id,
        )
        db.add_all([old_rule, new_rule])
        await db.flush()

        txn = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 2, 15),
            amount=Decimal("42.00"),
            direction=TransactionDirection.OUT,
            description="Grocery store",
            currency="SGD",
            dedup_hash="hash_same_type_newer_version",
            source_documents=[],
        )
        db.add(txn)
        await db.flush()

        results = await service.apply_rules(db, test_user.id, [txn])

        assert len(results) == 1
        assert results[0].rule_version_id == new_rule.id
        assert results[0].account_id == new_account.id

    async def test_apply_rules_is_idempotent_for_existing_transaction_rule_version(self, db, test_user):
        """AC-extraction.212.1: Re-running the same rule does not duplicate Layer 3 classifications."""
        service = ClassificationService()

        account = Account(
            user_id=test_user.id,
            name="Idempotent Classification Account",
            type=AccountType.EXPENSE,
            currency="SGD",
            code="6819",
        )
        db.add(account)
        await db.flush()

        rule = ClassificationRule(
            user_id=test_user.id,
            version_number=1,
            effective_date=date(2024, 1, 1),
            rule_name="Idempotent Keyword Rule",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": ["subscription"]},
            default_account_id=account.id,
            created_by=test_user.id,
        )
        txn = AtomicTransaction(
            user_id=test_user.id,
            txn_date=date(2024, 3, 15),
            amount=Decimal("19.99"),
            direction=TransactionDirection.OUT,
            description="Software subscription",
            currency="SGD",
            dedup_hash="hash_classification_idempotency",
            source_documents=[],
        )
        db.add_all([rule, txn])
        await db.flush()

        first_results = await service.apply_rules(db, test_user.id, [txn])
        second_results = await service.apply_rules(db, test_user.id, [txn])

        assert len(first_results) == 1
        assert len(second_results) == 1
        assert second_results[0].id == first_results[0].id

        classification_result = await db.execute(
            select(TransactionClassification)
            .where(TransactionClassification.atomic_txn_id == txn.id)
            .where(TransactionClassification.rule_version_id == rule.id)
        )
        classifications = classification_result.scalars().all()
        assert len(classifications) == 1


async def test_AC18_1_3_ml_rule_matching_is_retired(db, test_user):
    """AC-extraction.1801.1: AC18.1.3: ML_MODEL rule matching is RETIRED (EPIC #1483 cleanup) — even an
    active ML_MODEL rule never matches (the model path is the classify node), and
    the dead AI-signal reader is gone from the service."""
    service = ClassificationService()
    assert not hasattr(service, "_extract_ai_signals")

    rule = ClassificationRule(
        user_id=test_user.id,
        version_number=1,
        effective_date=date(2024, 1, 1),
        rule_name="legacy-ml-rule",
        rule_type=RuleType.ML_MODEL,
        rule_config={"source": "extraction_ai", "confidence_threshold": "0.1"},
        created_by=test_user.id,
    )
    db.add(rule)
    await db.flush()
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="anything")

    assert await service.apply_rules(db, test_user.id, [txn]) == []
