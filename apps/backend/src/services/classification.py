"""Layer 3: Classification Service."""

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

    async def get_active_rules(self, db: AsyncSession, user_id: UUID) -> list[ClassificationRule]:
        """Fetch active classification rules for a user."""
        query = (
            select(ClassificationRule)
            .where(ClassificationRule.user_id == user_id)
            .where(ClassificationRule.is_active == True)  # noqa: E712
            .order_by(ClassificationRule.version_number.desc())
        )
        result = await db.execute(query)
        return result.scalars().all()

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
            # TODO: Implement regex matching
            pass

        return False

    async def apply_rules(
        self, db: AsyncSession, user_id: UUID, transactions: list[AtomicTransaction]
    ) -> list[TransactionClassification]:
        """Apply active rules to a list of transactions."""
        rules = await self.get_active_rules(db, user_id)
        if not rules:
            return []

        results = []
        for txn in transactions:
            matched_rule = None
            # Apply rules in priority order (assuming retrieved order implies priority?)
            # Actually, we might need a priority field. For now, first match wins.
            for rule in rules:
                if self._match_rule(txn, rule):
                    matched_rule = rule
                    break

            if matched_rule:
                classification = TransactionClassification(
                    atomic_txn_id=txn.id,
                    rule_version_id=matched_rule.id,
                    account_id=matched_rule.default_account_id,
                    tags=matched_rule.tag_mappings,
                    confidence_score=100,  # Keyword match is high confidence
                    status=ClassificationStatus.APPLIED,
                )
                db.add(classification)
                results.append(classification)

        await db.flush()
        return results
