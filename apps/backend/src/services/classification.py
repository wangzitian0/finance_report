"""Layer 3: Classification Service."""

import re
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

        # RuleType.ML_MODEL matching was retired (EPIC #1483 cleanup): it read AI
        # signals no producer ever wrote, and no rule CRUD exists. The model path
        # is the transaction classify node; ML_MODEL rows remain only as the
        # classification-policy anchors (is_active=False), which never match.

        return False

    def _confidence_score_for_rule(self, transaction: AtomicTransaction, rule: ClassificationRule) -> int:
        # Deterministic rules (keyword/regex) are user intent: full confidence.
        return 100

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
                existing_result = await db.execute(
                    select(TransactionClassification)
                    .where(TransactionClassification.atomic_txn_id == txn.id)
                    .where(TransactionClassification.rule_version_id == matched_rule.id)
                )
                existing_classification = existing_result.scalar_one_or_none()
                if existing_classification:
                    results.append(existing_classification)
                    continue

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
