"""Layer 3: Classification Service."""

import re
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.logger import get_logger
from src.models.layer2 import AtomicTransaction
from src.models.layer3 import (
    ClassificationRule,
    ClassificationStatus,
    RuleType,
    TransactionClassification,
)

logger = get_logger(__name__)


class ClassificationService:
    """Service for managing classification rules and applying them to transactions."""

    _RULE_PRIORITY: dict[RuleType, int] = {
        RuleType.KEYWORD_MATCH: 0,
        RuleType.REGEX_MATCH: 1,
        RuleType.ML_MODEL: 2,
    }

    async def get_active_rules(self, db: AsyncSession, user_id: UUID) -> list[ClassificationRule]:
        """Fetch active classification rules for a user."""
        query = (
            select(ClassificationRule)
            .where(ClassificationRule.user_id == user_id)
            .where(ClassificationRule.is_active == True)  # noqa: E712
            .order_by(ClassificationRule.version_number.desc())
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    def _match_rule(self, transaction: AtomicTransaction, rule: ClassificationRule) -> bool:
        """Check if a transaction matches a rule's criteria."""
        config = rule.rule_config

        if rule.rule_type == RuleType.KEYWORD_MATCH:
            keywords = config.get("keywords", [])
            if not keywords:
                return False
            desc = transaction.description.lower()
            return any(k.lower() in desc for k in keywords)

        elif rule.rule_type == RuleType.REGEX_MATCH:
            pattern = config.get("pattern", "")
            if not pattern:
                return False
            try:
                flags = re.IGNORECASE if config.get("case_insensitive", True) else 0
                return bool(re.search(pattern, transaction.description, flags))
            except re.error as e:
                logger.warning(f"Invalid regex pattern in rule {rule.id}: {e}")
                return False

        elif rule.rule_type == RuleType.ML_MODEL:
            source = str(config.get("source", "extraction_ai"))
            if source != "extraction_ai":
                return False

            confidence, category = self._extract_ai_signals(transaction)
            if confidence is None:
                return False

            threshold_raw = config.get("confidence_threshold", "0.70")
            try:
                confidence_threshold = Decimal(str(threshold_raw))
            except Exception:
                logger.warning(f"Invalid ML confidence threshold in rule {rule.id}: {threshold_raw}")
                return False

            expected_category = config.get("suggested_category")
            if expected_category and category:
                return (
                    category.strip().lower() == str(expected_category).strip().lower()
                    and confidence >= confidence_threshold
                )

            return confidence >= confidence_threshold

        return False

    def _extract_ai_signals(self, transaction: AtomicTransaction) -> tuple[Decimal | None, str | None]:
        sources = transaction.source_documents

        items: list[dict] = []
        if isinstance(sources, dict):
            items = [sources]
        elif isinstance(sources, list):
            items = [item for item in sources if isinstance(item, dict)]

        for item in items:
            confidence_raw = item.get("category_confidence")
            if confidence_raw is None:
                confidence_raw = item.get("ai_confidence")

            if confidence_raw is None:
                continue

            try:
                confidence = Decimal(str(confidence_raw))
            except Exception:
                continue

            category_raw = item.get("suggested_category")
            if category_raw is None:
                category_raw = item.get("category")

            category = str(category_raw) if category_raw is not None else None
            return confidence, category

        return None, None

    def _confidence_score_for_rule(self, transaction: AtomicTransaction, rule: ClassificationRule) -> int:
        if rule.rule_type != RuleType.ML_MODEL:
            return 100

        confidence, _ = self._extract_ai_signals(transaction)
        if confidence is None:
            return 70

        score = int((confidence * Decimal("100")).to_integral_value())
        return max(0, min(score, 100))

    def _sort_rules_by_priority(self, rules: list[ClassificationRule]) -> list[ClassificationRule]:
        return sorted(
            rules,
            key=lambda rule: (
                self._RULE_PRIORITY.get(rule.rule_type, 99),
                -rule.version_number,
            ),
        )

    async def apply_rules(
        self, db: AsyncSession, user_id: UUID, transactions: list[AtomicTransaction]
    ) -> list[TransactionClassification]:
        """Apply active rules to a list of transactions."""
        rules = await self.get_active_rules(db, user_id)
        if not rules:
            return []

        ordered_rules = self._sort_rules_by_priority(rules)

        results = []
        for txn in transactions:
            matched_rule = None
            for rule in ordered_rules:
                if self._match_rule(txn, rule):
                    matched_rule = rule
                    break

            if matched_rule:
                classification = TransactionClassification(
                    atomic_txn_id=txn.id,
                    rule_version_id=matched_rule.id,
                    account_id=matched_rule.default_account_id,
                    tags=matched_rule.tag_mappings,
                    confidence_score=self._confidence_score_for_rule(txn, matched_rule),
                    status=ClassificationStatus.APPLIED,
                )
                db.add(classification)
                results.append(classification)

        await db.flush()
        return results
