"""Transaction classify node (#1544 Construct, EPIC-018 AC18.15)."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import cast, func, or_, select, update
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

import src.config
from src.audit import canonical_json_digest
from src.extraction.base.decoding import JSON_MAX_TOKENS
from src.extraction.base.disposition import EconomicIntent
from src.extraction.base.source_vocabulary import ClassificationStatus, RuleType, TransactionDirection
from src.extraction.base.types import RunHints
from src.extraction.extension._coerce import scan_balanced_json_candidates
from src.extraction.extension.ai_settings import auto_accept_enabled, classification_enabled
from src.extraction.extension.classification import ClassificationService
from src.extraction.extension.prompts import classification as templates
from src.extraction.extension.prompts.hints import hints_block
from src.extraction.orm.ai_feedback import AiFeedback
from src.extraction.orm.correction import CorrectionLog
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.extraction.orm.statement_run import StatementRun
from src.ledger import Account, AccountType
from src.observability import get_logger
from src.platform import ConflictError, ValidationFailedError

logger = get_logger(__name__)
settings = src.config.settings

POLICY_RULE_NAME = "llm-category-policy"
UNCLASSIFIED = "UNCLASSIFIED"
SUSPENSE_TAG = "suspense"
CLASSIFICATION_BATCH_SIZE = 50
CLASSIFICATION_PARALLEL_BATCHES = 4
CLASSIFICATION_PHASE_DEADLINE_SECONDS = 180.0
_PLAIN_NUMBER = re.compile(r"\d+(\.\d+)?")


class TransactionCategory(str, Enum):
    """The fixed, closed category catalog (v1). The model may only propose these."""

    SALARY = "SALARY"
    INTEREST = "INTEREST"
    INVESTMENT_INCOME = "INVESTMENT_INCOME"
    REFUND = "REFUND"
    OTHER_INCOME = "OTHER_INCOME"
    DINING = "DINING"
    GROCERIES = "GROCERIES"
    TRANSPORT = "TRANSPORT"
    HOUSING = "HOUSING"
    UTILITIES = "UTILITIES"
    SHOPPING = "SHOPPING"
    HEALTHCARE = "HEALTHCARE"
    ENTERTAINMENT = "ENTERTAINMENT"
    TRAVEL = "TRAVEL"
    EDUCATION = "EDUCATION"
    INSURANCE = "INSURANCE"
    FEES = "FEES"
    OTHER_EXPENSE = "OTHER_EXPENSE"
    TRANSFER = "TRANSFER"
    CARD_REPAYMENT = "CARD_REPAYMENT"
    LOAN_PRINCIPAL = "LOAN_PRINCIPAL"
    INVESTMENT_TRADE = "INVESTMENT_TRADE"


NON_PNL_CATEGORIES = frozenset(
    {
        TransactionCategory.TRANSFER,
        TransactionCategory.CARD_REPAYMENT,
        TransactionCategory.LOAN_PRINCIPAL,
        TransactionCategory.INVESTMENT_TRADE,
    }
)
PROCESSING_LEG_CATEGORIES = frozenset({TransactionCategory.TRANSFER, TransactionCategory.CARD_REPAYMENT})
REVIEW_ONLY_CATEGORIES = frozenset({TransactionCategory.OTHER_INCOME, TransactionCategory.OTHER_EXPENSE})

BALANCE_SHEET_ACCOUNTS: dict[TransactionCategory, tuple[str, AccountType]] = {
    TransactionCategory.LOAN_PRINCIPAL: ("Loans Payable ({currency})", AccountType.LIABILITY),
    TransactionCategory.INVESTMENT_TRADE: ("Investments ({currency})", AccountType.ASSET),
}

NON_PNL_GUIDANCE = {
    TransactionCategory.TRANSFER: "TRANSFER is money moved between the user's own accounts.",
    TransactionCategory.CARD_REPAYMENT: "CARD_REPAYMENT is a payment toward the user's own credit card.",
    TransactionCategory.LOAN_PRINCIPAL: "LOAN_PRINCIPAL is a loan drawdown or a repayment of loan principal.",
    TransactionCategory.INVESTMENT_TRADE: "INVESTMENT_TRADE is a purchase or a sale of an investment.",
}

CATEGORY_ACCOUNTS: dict[TransactionCategory, tuple[str, AccountType]] = {
    TransactionCategory.SALARY: ("Income - Salary", AccountType.INCOME),
    TransactionCategory.INTEREST: ("Income - Interest", AccountType.INCOME),
    TransactionCategory.INVESTMENT_INCOME: ("Income - Investment", AccountType.INCOME),
    TransactionCategory.REFUND: ("Income - Refunds", AccountType.INCOME),
    TransactionCategory.OTHER_INCOME: ("Income - Other", AccountType.INCOME),
    TransactionCategory.DINING: ("Expense - Dining", AccountType.EXPENSE),
    TransactionCategory.GROCERIES: ("Expense - Groceries", AccountType.EXPENSE),
    TransactionCategory.TRANSPORT: ("Expense - Transport", AccountType.EXPENSE),
    TransactionCategory.HOUSING: ("Expense - Housing", AccountType.EXPENSE),
    TransactionCategory.UTILITIES: ("Expense - Utilities", AccountType.EXPENSE),
    TransactionCategory.SHOPPING: ("Expense - Shopping", AccountType.EXPENSE),
    TransactionCategory.HEALTHCARE: ("Expense - Healthcare", AccountType.EXPENSE),
    TransactionCategory.ENTERTAINMENT: ("Expense - Entertainment", AccountType.EXPENSE),
    TransactionCategory.TRAVEL: ("Expense - Travel", AccountType.EXPENSE),
    TransactionCategory.EDUCATION: ("Expense - Education", AccountType.EXPENSE),
    TransactionCategory.INSURANCE: ("Expense - Insurance", AccountType.EXPENSE),
    TransactionCategory.FEES: ("Expense - Fees", AccountType.EXPENSE),
    TransactionCategory.OTHER_EXPENSE: ("Expense - Other", AccountType.EXPENSE),
}


def general_account_name(account_type: AccountType, currency: str) -> str:
    return f"General {account_type.value.capitalize()} ({currency})"


def balance_sheet_intent(category: TransactionCategory, direction: TransactionDirection) -> EconomicIntent:
    if category is TransactionCategory.LOAN_PRINCIPAL:
        return EconomicIntent.LOAN_PRINCIPAL
    return (
        EconomicIntent.INVESTMENT_PURCHASE if direction is TransactionDirection.OUT else EconomicIntent.INVESTMENT_SALE
    )


def balance_sheet_booking(
    category: str, direction: TransactionDirection, currency: str
) -> tuple[EconomicIntent, AccountType, str] | None:
    try:
        known = TransactionCategory(category)
    except ValueError:
        return None
    if known not in BALANCE_SHEET_ACCOUNTS:
        return None
    template, account_type = BALANCE_SHEET_ACCOUNTS[known]
    return balance_sheet_intent(known, direction), account_type, template.format(currency=currency)


class ClassificationPolicy(BaseModel):
    """Effective-dated immutable classification-basis version."""

    model_config = ConfigDict(frozen=True)

    version: int
    effective_from: date
    catalog: tuple[TransactionCategory, ...]
    model_version: str
    auto_apply_threshold: int = 85
    review_threshold: int = 60


POLICY_VERSIONS: tuple[ClassificationPolicy, ...] = (
    ClassificationPolicy(
        version=2,
        effective_from=date.min,
        catalog=tuple(TransactionCategory),
        model_version="v2",
    ),
)


def policy_for(as_of: date, *, registry: Sequence[ClassificationPolicy] | None = None) -> ClassificationPolicy:
    if registry is None:
        registry = POLICY_VERSIONS
    effective = [p for p in registry if p.effective_from <= as_of]
    if not effective:
        raise ValueError(f"no classification policy effective on {as_of.isoformat()}")
    return max(effective, key=lambda p: (p.effective_from, p.version))


class CategoryProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: str
    confidence: int
    reason: str = ""


Disposition = Literal[
    "rule", "applied", "review", "tail", "off_catalog", "no_proposal", "non_pnl", "fallback", "already_classified"
]


class ClassificationOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    atomic_txn_id: UUID
    disposition: Disposition
    category: str | None = None
    confidence: int | None = None
    policy_version: int | None
    wrote_row: bool = False


def _recover_json_array(content: str) -> list | None:
    """Recover the largest valid JSON array from a fenced or prose-wrapped response."""
    for candidate in sorted(scan_balanced_json_candidates(content, "[", "]"), key=len, reverse=True):
        try:
            parsed = json.loads(candidate)
        except (ValueError, RecursionError):  # not JSON, a number of more than 4300 digits, or nesting too deep
            continue
        if isinstance(parsed, list):
            return parsed
    return None


def _item_index(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isascii() and value.isdigit():
        return int(value)
    return None


def _align_indexed_items(parsed: object, count: int) -> list[dict | None]:
    none: list[dict | None] = [None] * count
    if not isinstance(parsed, list) or len(parsed) != count:
        return none
    by_index: dict[int, dict] = {}
    for item in parsed:
        if not isinstance(item, dict) or "index" not in item:
            return none
        index = _item_index(item["index"])
        if index is None or not 0 <= index < count or index in by_index:
            return none
        by_index[index] = item
    return [by_index.get(i) for i in range(count)]


def _item_category(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return re.sub(r"[\s\-]+", "_", value.strip()).upper()


def _read_number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        text = value.strip().rstrip("%").strip()
        return float(text) if _PLAIN_NUMBER.fullmatch(text) else None
    return None


def _item_score(value: object) -> int | None:
    number = _read_number(value)
    if number is None:
        return None
    if isinstance(number, int):
        return None if number < 0 else min(100, number)
    if not math.isfinite(number) or number < 0:
        return None
    return min(100, math.floor(number))


def _is_fraction(number: int | float | None) -> bool:
    return isinstance(number, float) and math.isfinite(number) and 0 < number < 1


def _normalize_scale(items: Sequence[object]) -> list[object]:
    numbers = [_read_number(item.get("confidence")) if isinstance(item, dict) else None for item in items]
    fractional = [_is_fraction(number) for number in numbers]
    if not any(fractional):
        return list(items)
    if all(number <= 1 for number in numbers if number is not None):
        logger.warning("transaction classification scale from 0 to 1 read", rows=len(items))
        return [
            {**item, "confidence": math.floor(Decimal(str(number)) * 100)}
            if isinstance(item, dict) and number is not None
            else item
            for item, number in zip(items, numbers, strict=True)
        ]
    logger.warning("transaction classification fractions dropped", rows=len(items), dropped=sum(fractional))
    return [None if is_fraction else item for item, is_fraction in zip(items, fractional, strict=True)]


def _proposal_from_item(item: object) -> CategoryProposal | None:
    if not isinstance(item, dict):
        return None
    category = _item_category(item.get("category"))
    confidence = _item_score(item.get("confidence"))
    if category is None or confidence is None:
        return None
    return CategoryProposal(category=category, confidence=confidence, reason=str(item.get("reason", ""))[:500])


def model_batches(rows: Sequence[AtomicTransaction]) -> list[Sequence[AtomicTransaction]]:
    """Split rows into the groups that one model call answers."""
    return [rows[start : start + CLASSIFICATION_BATCH_SIZE] for start in range(0, len(rows), CLASSIFICATION_BATCH_SIZE)]


async def propose_categories(
    transactions: Sequence[AtomicTransaction],
    policy: ClassificationPolicy,
    *,
    hints: RunHints | None = None,
    few_shot_examples: Sequence[Mapping[str, object]] = (),
) -> list[CategoryProposal | None]:
    """Prompt-constrained JSON proposals for one batch of rows (never sends amounts). The run splits the batches."""
    if not transactions:
        return []
    return await _propose_batch(
        transactions,
        policy,
        hints=hints,
        few_shot_examples=few_shot_examples,
    )


def build_classification_prompt(
    transactions: Sequence[AtomicTransaction],
    policy: ClassificationPolicy,
    *,
    hints: RunHints | None = None,
    few_shot_examples: Sequence[Mapping[str, object]] = (),
) -> str:
    """Return the prompt of one batch. The reviewer guidance of the run, if any, is the last block (never amounts)."""
    guidance = " ".join(NON_PNL_GUIDANCE[c] for c in policy.catalog if c in NON_PNL_GUIDANCE)
    if guidance:
        guidance += templates.OTHER_BUCKET_GUIDANCE
    lines = "\n".join(
        json.dumps({"index": i, "direction": t.direction.value, "description": t.description}, ensure_ascii=False)
        for i, t in enumerate(transactions)
    )
    catalog = ", ".join(c.value for c in policy.catalog)
    prompt = templates.INDEXED_PROMPT.format(catalog=catalog, guidance=guidance, lines=lines)
    return prompt + templates.few_shot_examples_block(few_shot_examples) + hints_block(hints, templates.HINTS_PURPOSE)


def classification_template_fingerprint() -> str:
    """Return one SHA-256 over every text part of the classification prompt, built for fixed rows and hints.

    The template, every guidance line, the catalog and the hints block are all in it. A test pins it to the version.
    """
    rows = [AtomicTransaction(direction=TransactionDirection.OUT, description='FIXED "ROW"')]
    hints = RunHints(keywords=["keyword"], note="note")
    examples = (
        {"description": "FIXED COFFEE 1234", "original_category": "OTHER_EXPENSE", "corrected_category": "DINING"},
    )
    return canonical_json_digest(
        {
            f"v{policy.version}": build_classification_prompt(rows, policy, hints=hints, few_shot_examples=examples)
            for policy in POLICY_VERSIONS
        }
    )


async def ask_model(
    rows: Sequence[AtomicTransaction],
    policy: ClassificationPolicy | None,
    *,
    hints: RunHints | None = None,
    few_shot_examples: Sequence[Mapping[str, object]] = (),
) -> list[CategoryProposal | None]:
    """Ask the model for one group of rows. The caller passes no session (#3028), and the call reads no user setting:
    the provider is the one of the deployment. A failed call raises `ModelCallFailed`."""
    assert policy is not None, "the model is off: no plan asks it"
    extra: dict[str, Any] = {}
    if hints is not None and not hints.is_empty:
        extra["hints"] = hints
    if few_shot_examples:
        extra["few_shot_examples"] = few_shot_examples
    return await propose_categories(rows, policy, **extra)


async def _propose_batch(
    transactions: Sequence[AtomicTransaction],
    policy: ClassificationPolicy,
    *,
    hints: RunHints | None = None,
    few_shot_examples: Sequence[Mapping[str, object]] = (),
) -> list[CategoryProposal | None]:
    from infra2_sdk.llm import DecodingSpec

    from src.llm import ModelFailureKind
    from src.llm.extension.agent import CallSite, complete_text, model_call_failed

    prompt = build_classification_prompt(transactions, policy, hints=hints, few_shot_examples=few_shot_examples)

    # A failed call raises ModelCallFailed (counted and logged at the entry point). The run decides what a failed
    # batch means; a bug in this code is not caught here.
    content = await complete_text(
        CallSite.CLASSIFICATION_PROPOSE,
        "small",
        prompt,
        decoding=DecodingSpec(
            decoding_version="extraction.classification.v1",
            thinking=False,
            temperature=0.0,
            max_tokens=JSON_MAX_TOKENS,
            timeout=60.0,
        ),
        extra_body={"do_sample": False},
        # Two attempts of 60 s stay inside the deadline of the run (180 s); the SDK default of three do not.
        max_attempts=2,
    )
    try:
        parsed = json.loads(content)
    except (ValueError, RecursionError):
        parsed = _recover_json_array(content)
    if not isinstance(parsed, list):
        # No answer at all is a failed call, not an abstaining model: an abstaining model returns a list whose
        # items are null or omit rows (those rows stay None below).
        raise model_call_failed(
            CallSite.CLASSIFICATION_PROPOSE,
            ModelFailureKind.BAD_REPLY,
            f"the reply is not a JSON array ({len(content)} characters, fenced={content.lstrip().startswith('`')})",
        )

    items = _align_indexed_items(parsed, len(transactions))
    if not any(items):
        logger.warning("transaction classification answer dropped", rows=len(transactions), items=len(parsed))
    return [_proposal_from_item(item) for item in _normalize_scale(items)]


async def _lock_policy_rule(db: AsyncSession, user_id: UUID, policy: ClassificationPolicy) -> None:
    lock_key = f"policy_rule:{user_id}:{POLICY_RULE_NAME}:{policy.version}"
    await db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))


async def _ensure_policy_rule(db: AsyncSession, user_id: UUID, policy: ClassificationPolicy) -> ClassificationRule:
    cache = db.info.setdefault("_policy_rule_cache", {})
    cache_key = (user_id, policy.version)
    cached = cache.get(cache_key)
    if cached is not None and cached in db:
        return cached

    await _lock_policy_rule(db, user_id, policy)
    existing = (
        await db.execute(
            select(ClassificationRule)
            .where(ClassificationRule.user_id == user_id)
            .where(ClassificationRule.rule_name == POLICY_RULE_NAME)
            .where(ClassificationRule.version_number == policy.version)
            .order_by(ClassificationRule.created_at, ClassificationRule.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        cache[cache_key] = existing
        return existing

    rule = ClassificationRule(
        user_id=user_id,
        created_by=user_id,
        rule_name=POLICY_RULE_NAME,
        version_number=policy.version,
        effective_date=policy.effective_from,
        is_active=False,
        rule_type=RuleType.ML_MODEL,
        rule_config={
            "policy_version": policy.version,
            "model_version": policy.model_version,
            "catalog": [c.value for c in policy.catalog],
            "auto_apply_threshold": policy.auto_apply_threshold,
            "review_threshold": policy.review_threshold,
        },
    )
    db.add(rule)
    await db.flush()
    cache[cache_key] = rule
    return rule


async def _get_default_account(db: AsyncSession, user_id: UUID, name: str, account_type: AccountType, currency: str):
    from src.extraction.extension.review_queue import get_or_create_account

    return await get_or_create_account(db, name=name, account_type=account_type, currency=currency, user_id=user_id)


async def _resolve_category_account(db: AsyncSession, user_id: UUID, category: TransactionCategory, currency: str):
    name, account_type = CATEGORY_ACCOUNTS[category]
    return await _get_default_account(db, user_id, name, account_type, currency)


async def _general_account(db: AsyncSession, user_id: UUID, txn: AtomicTransaction) -> Account:
    account_type = AccountType.EXPENSE if txn.direction is TransactionDirection.OUT else AccountType.INCOME
    return await _get_default_account(
        db, user_id, general_account_name(account_type, txn.currency), account_type, txn.currency
    )


async def _balance_sheet_account(
    db: AsyncSession, user_id: UUID, category: TransactionCategory, currency: str
) -> Account:
    template, account_type = BALANCE_SHEET_ACCOUNTS[category]
    return await _get_default_account(db, user_id, template.format(currency=currency), account_type, currency)


async def _promote_drafts(
    db: AsyncSession, user_id: UUID, policy: ClassificationPolicy, transactions: Sequence[AtomicTransaction]
) -> None:
    """Promote eligible review drafts to APPLIED when auto-accept is enabled."""
    by_id = {txn.id: txn for txn in transactions}
    if not by_id:
        return
    drafts = (
        (
            await db.execute(
                select(TransactionClassification)
                .join(ClassificationRule, TransactionClassification.rule_version_id == ClassificationRule.id)
                .where(ClassificationRule.user_id == user_id)
                .where(ClassificationRule.rule_name == POLICY_RULE_NAME)
                .where(ClassificationRule.version_number == policy.version)
                .where(TransactionClassification.atomic_txn_id.in_(list(by_id)))
                .where(TransactionClassification.status == ClassificationStatus.DRAFT)
            )
        )
        .scalars()
        .all()
    )
    for draft in drafts:
        txn = by_id[draft.atomic_txn_id]
        tags = dict(draft.tags) if isinstance(draft.tags, dict) else {}
        corrected = tags.get("corrected_by_user") is True
        if tags.get(SUSPENSE_TAG) is True:
            continue
        try:
            category = TransactionCategory(str(tags.get("category")))
        except ValueError:
            continue
        if category in BALANCE_SHEET_ACCOUNTS:
            draft.account_id = (await _balance_sheet_account(db, user_id, category, txn.currency)).id
            tags["intent"] = balance_sheet_intent(category, txn.direction).value
        elif category in NON_PNL_CATEGORIES:
            continue
        elif draft.account_id is None or not category_fits_direction(category, txn.direction):
            if corrected:
                continue
            draft.account_id = (await _general_account(db, user_id, txn)).id
            tags["original_category"] = tags.get("original_category", category.value)
            tags["category"] = UNCLASSIFIED
            draft.confidence_score = 0
        if not corrected:
            tags["auto_accepted"] = True
        draft.tags = tags
        draft.status = ClassificationStatus.APPLIED
    await db.flush()


_CATALOG_KEYS = frozenset({category.value for category in TransactionCategory} | {UNCLASSIFIED})


def summarize_outcomes(outcomes: Sequence[ClassificationOutcome]) -> dict:
    confidences = [o.confidence for o in outcomes if o.confidence is not None]
    return {
        "total": len(outcomes),
        "by_disposition": dict(Counter(o.disposition for o in outcomes)),
        # Keys come from the closed catalog. An answer outside it can echo a row description: it counts as "other".
        "by_category": dict(
            Counter(o.category if o.category in _CATALOG_KEYS else "other" for o in outcomes if o.category)
        ),
        "confidence_buckets": dict(Counter(f"{(c // 10) * 10}-{(c // 10) * 10 + 9}" for c in confidences)),
    }


async def _supersede_older_model_rows(
    db: AsyncSession, user_id: UUID, txn_ids: Sequence[UUID], current_version: int
) -> None:
    if not txn_ids:
        return
    newer = aliased(TransactionClassification)
    newer_rule = aliased(ClassificationRule)
    successor = (
        select(newer.id)
        .join(newer_rule, newer.rule_version_id == newer_rule.id)
        .where(newer.atomic_txn_id == TransactionClassification.atomic_txn_id)
        .where(newer_rule.user_id == user_id)
        .where(newer_rule.rule_name == POLICY_RULE_NAME)
        .where(newer_rule.version_number == current_version)
        .where(newer.status.in_((ClassificationStatus.APPLIED, ClassificationStatus.DRAFT)))
        .limit(1)
        .scalar_subquery()
    )
    older_rules = (
        select(ClassificationRule.id)
        .where(ClassificationRule.user_id == user_id)
        .where(ClassificationRule.rule_name == POLICY_RULE_NAME)
        .where(ClassificationRule.version_number < current_version)
    )
    await db.execute(
        update(TransactionClassification)
        .where(TransactionClassification.atomic_txn_id.in_(list(txn_ids)))
        .where(TransactionClassification.rule_version_id.in_(older_rules))
        .where(TransactionClassification.status.in_((ClassificationStatus.APPLIED, ClassificationStatus.DRAFT)))
        .where(func.coalesce(TransactionClassification.tags["corrected_by_user"].astext, "false") != "true")
        .where(successor.is_not(None))
        .values(status=ClassificationStatus.SUPERSEDED, superseded_by_id=successor)
        .execution_options(synchronize_session="fetch")
    )


# The tags that record a decision of the user. A row with one of them is never asked again.
DECISION_MARKERS = ("corrected_by_user", "rejected_by_user", "accepted_by_user")
LIVE_STATUSES = (ClassificationStatus.DRAFT, ClassificationStatus.APPLIED)


async def _user_decided_txn_ids(db: AsyncSession, user_id: UUID, txn_ids: Sequence[UUID]) -> set[UUID]:
    if not txn_ids:
        return set()
    decided = or_(*(TransactionClassification.tags[marker].astext == "true" for marker in DECISION_MARKERS))
    rows = await db.execute(
        select(TransactionClassification.atomic_txn_id)
        .join(ClassificationRule, TransactionClassification.rule_version_id == ClassificationRule.id)
        .where(ClassificationRule.user_id == user_id)
        .where(ClassificationRule.rule_name == POLICY_RULE_NAME)
        .where(TransactionClassification.atomic_txn_id.in_(list(txn_ids)))
        .where(decided)
    )
    return set(rows.scalars().all())


async def _already_classified_ids(
    db: AsyncSession, user_id: UUID, policy_version: int, txn_ids: Sequence[UUID]
) -> set[UUID]:
    if not txn_ids:
        return set()
    current_rules = (
        select(ClassificationRule.id)
        .where(ClassificationRule.user_id == user_id)
        .where(ClassificationRule.rule_name == POLICY_RULE_NAME)
        .where(ClassificationRule.version_number == policy_version)
    )
    classified = set(
        (
            await db.execute(
                select(TransactionClassification.atomic_txn_id)
                .where(TransactionClassification.atomic_txn_id.in_(list(txn_ids)))
                .where(TransactionClassification.rule_version_id.in_(current_rules))
                .where(TransactionClassification.status.in_(LIVE_STATUSES))
            )
        )
        .scalars()
        .all()
    )
    return classified | await _user_decided_txn_ids(db, user_id, txn_ids)


CoverageCheck = Callable[[AsyncSession, Sequence[UUID]], Awaitable[set[UUID]]]


@dataclass(frozen=True)
class RunAsk:
    """What a classify run tells the phases about itself (#2994)."""

    run_id: UUID
    statement_id: UUID
    prompt_digest: str | None
    reask: bool  # a user run with hints asks again for every row that has a model answer
    covered_by: CoverageCheck  # the rows that the ledger covers: a run never writes an answer for them


async def _same_digest_ids(
    db: AsyncSession, user_id: UUID, policy: ClassificationPolicy, txn_ids, run: RunAsk
) -> set[UUID]:
    """The rows whose live answer came from a run of this statement with the same prompt digest: same inputs, no new answer."""
    rows = await db.execute(
        select(TransactionClassification.atomic_txn_id)
        .join(ClassificationRule, TransactionClassification.rule_version_id == ClassificationRule.id)
        .join(
            StatementRun, StatementRun.id == cast(TransactionClassification.tags["run_id"].astext, PGUUID(as_uuid=True))
        )
        .where(ClassificationRule.user_id == user_id, ClassificationRule.rule_name == POLICY_RULE_NAME)
        .where(ClassificationRule.version_number == policy.version)
        .where(TransactionClassification.status.in_(LIVE_STATUSES))
        .where(TransactionClassification.atomic_txn_id.in_(list(txn_ids)))
        .where(StatementRun.statement_id == run.statement_id, StatementRun.prompt_digest == run.prompt_digest)
    )
    return set(rows.scalars())


async def _answered_ids(
    db: AsyncSession, user_id: UUID, policy: ClassificationPolicy, txn_ids: Sequence[UUID], run: RunAsk | None
) -> set[UUID]:
    """The rows that the model is not asked for: any answer for an automatic pass. A re-ask skips a decision of the
    user and a row that an earlier run of this statement answered with the same prompt digest."""
    if run is None or not run.reask:
        return await _already_classified_ids(db, user_id, policy.version, txn_ids)
    return await _user_decided_txn_ids(db, user_id, txn_ids) | await _same_digest_ids(db, user_id, policy, txn_ids, run)


async def _policy_rows(
    db: AsyncSession, user_id: UUID, txn_ids: Sequence[UUID]
) -> list[tuple[TransactionClassification, int]]:
    """The answers of every policy version for these rows, locked in id order. Call it after the policy-rule lock."""
    result = await db.execute(
        select(TransactionClassification, ClassificationRule.version_number)
        .join(ClassificationRule, TransactionClassification.rule_version_id == ClassificationRule.id)
        .where(ClassificationRule.user_id == user_id, ClassificationRule.rule_name == POLICY_RULE_NAME)
        .where(TransactionClassification.atomic_txn_id.in_(list(txn_ids)))
        .order_by(TransactionClassification.id)
        .with_for_update(of=TransactionClassification)
        .execution_options(populate_existing=True)
    )
    return [(row, version) for row, version in result.all()]


@dataclass(frozen=True)
class ClassificationPlan:
    """What the reads of one policy bucket found (#3028). It holds no session, so a model call needs no connection."""

    user_id: UUID
    policy: ClassificationPolicy | None  # None: the model is off for this user
    rows: Sequence[AtomicTransaction]
    ruled: dict[UUID, int]  # row id -> version number of the keyword rule that matches the row
    already: frozenset[UUID]  # row ids with an answer under this policy version, or a decision of the user
    to_propose: list[AtomicTransaction]  # the rows that the model answers
    auto_accept: bool
    run: RunAsk | None = None  # the run whose answers these are: its id goes into the tags of each answer it writes

    @property
    def reask(self) -> bool:
        return self.run is not None and self.run.reask

    @property
    def run_id(self) -> UUID | None:
        return self.run.run_id if self.run is not None else None

    @property
    def version(self) -> int | None:
        return self.policy.version if self.policy is not None else None

    def base_outcomes(self) -> list[ClassificationOutcome]:
        """The outcomes of the rows that no model call answers: a keyword rule, an earlier answer, or the model off."""
        asked = {txn.id for txn in self.to_propose}
        rest: Disposition = "already_classified" if self.policy is not None else "no_proposal"
        return [
            ClassificationOutcome(
                atomic_txn_id=txn.id,
                disposition="rule",
                policy_version=self.ruled[txn.id],
                wrote_row=True,
            )
            if txn.id in self.ruled
            else ClassificationOutcome(atomic_txn_id=txn.id, disposition=rest, policy_version=self.version)
            for txn in self.rows
            if txn.id not in asked
        ]


async def plan_classification(
    db: AsyncSession,
    user_id: UUID,
    rows: Sequence[AtomicTransaction],
    policy: ClassificationPolicy | None,
    *,
    run: RunAsk | None = None,
) -> ClassificationPlan:
    """Read what one policy bucket needs: the keyword rules and matches, the two flags, the rows with an answer.

    An automatic pass skips every row that has an answer. A re-ask skips the rows that the user decided.
    """
    service = ClassificationService()
    rules = [r for r in await service.get_active_rules(db, user_id) if r.rule_name != POLICY_RULE_NAME]
    ruled: dict[UUID, int] = {}
    for txn in rows:
        matched_rule = next((rule for rule in rules if service._match_rule(txn, rule)), None)
        if matched_rule is not None:
            ruled[txn.id] = matched_rule.version_number
    enabled = await classification_enabled(db, user_id)
    if enabled and policy is None:
        raise ValueError("classification policy is required when LLM proposals are enabled")
    policy = policy if enabled else None
    already: frozenset[UUID] = frozenset()
    if policy is not None:
        already = frozenset(await _answered_ids(db, user_id, policy, [txn.id for txn in rows], run))
    to_propose = [txn for txn in rows if policy is not None and txn.id not in ruled and txn.id not in already]
    auto_accept = policy is not None and await auto_accept_enabled(db, user_id)
    return ClassificationPlan(user_id, policy, rows, ruled, already, to_propose, auto_accept, run)


async def write_rule_answers(db: AsyncSession, plan: ClassificationPlan) -> None:
    """Write the answers of the keyword rules. They need no model call."""
    if plan.ruled:
        rows = [txn for txn in plan.rows if txn.id in plan.ruled]
        await ClassificationService().apply_rules(db, plan.user_id, rows, run_id=plan.run_id)


async def settle_drafts(db: AsyncSession, plan: ClassificationPlan) -> None:
    """Promote the drafts of the plan, then sweep the older versions of the rows that already have an answer."""
    if plan.policy is not None:
        if plan.auto_accept:
            await _promote_drafts(db, plan.user_id, plan.policy, plan.rows)
        await _supersede_older_model_rows(db, plan.user_id, sorted(plan.already), plan.policy.version)


async def write_answers(
    db: AsyncSession,
    plan: ClassificationPlan,
    rows: Sequence[AtomicTransaction],
    proposals: Sequence[CategoryProposal | None],
) -> list[ClassificationOutcome]:
    """Decide and write the answer of each row: the one write phase. Rows answered since the plan are skipped."""
    policy, user_id, auto_accept = plan.policy, plan.user_id, plan.auto_accept
    assert policy is not None, "the model is off: no plan asks it"
    tags: dict[str, Any]
    apply_threshold = policy.review_threshold if auto_accept else policy.auto_apply_threshold
    proposal_by_txn = dict(zip(rows, proposals))
    late: set[UUID] = set()
    existing: dict[UUID, TransactionClassification] = {}
    if any(proposal is not None for proposal in proposals):
        await _lock_policy_rule(db, user_id, policy)
        ids = [txn.id for txn in rows]
        if plan.reask:  # the decisions and the live answers come from the rows that this transaction locks
            locked = await _policy_rows(db, user_id, ids)
            late = {r.atomic_txn_id for r, _ in locked if any((r.tags or {}).get(m) is True for m in DECISION_MARKERS)}
            existing = {
                r.atomic_txn_id: r
                for r, version in locked
                if version == policy.version and r.status in LIVE_STATUSES and r.atomic_txn_id not in late
            }
        else:
            late = await _already_classified_ids(db, user_id, policy.version, ids)
        if plan.run is not None:  # a row can be posted while the model runs, also from another statement
            late |= await plan.run.covered_by(db, ids)

    policy_rule: ClassificationRule | None = None
    category_account_cache: dict[tuple[TransactionCategory, str], Account] = {}
    new_rows: list[TransactionClassification] = []
    outcomes: list[ClassificationOutcome] = []

    async def add(
        txn: AtomicTransaction, account_id: UUID | None, tags: dict, score: int, status: ClassificationStatus
    ):
        nonlocal policy_rule
        if plan.run_id is not None:
            tags = {**tags, "run_id": str(plan.run_id)}
        if policy_rule is None:
            policy_rule = await _ensure_policy_rule(db, user_id, policy)
        new_rows.append(
            TransactionClassification(
                atomic_txn_id=txn.id,
                rule_version_id=policy_rule.id,
                account_id=account_id,
                tags=tags,
                confidence_score=score,
                status=status,
            )
        )

    def outcome(txn: AtomicTransaction, disposition: Disposition, proposal: CategoryProposal | None = None):
        return ClassificationOutcome(
            atomic_txn_id=txn.id,
            disposition=disposition,
            category=proposal.category if proposal else None,
            confidence=proposal.confidence if proposal else None,
            policy_version=policy.version,
        )

    for txn in rows:
        proposal = proposal_by_txn.get(txn)
        if txn.id in late or proposal is None:
            outcomes.append(outcome(txn, "already_classified" if txn.id in late else "no_proposal"))
            continue

        try:
            category = TransactionCategory(proposal.category)
        except ValueError:
            category = None
        if category is None or category not in policy.catalog:
            outcomes.append(outcome(txn, "off_catalog", proposal))
            continue

        if category in NON_PNL_CATEGORIES and auto_accept and proposal.confidence <= 0:
            outcomes.append(outcome(txn, "no_proposal", proposal))
            continue

        if category in BALANCE_SHEET_ACCOUNTS and auto_accept and proposal.confidence >= policy.review_threshold:
            account = await _balance_sheet_account(db, user_id, category, txn.currency)
            tags = {
                "category": category.value,
                "reason": proposal.reason,
                "intent": balance_sheet_intent(category, txn.direction).value,
                "auto_accepted": True,
            }
            await add(txn, account.id, tags, proposal.confidence, ClassificationStatus.APPLIED)
            outcomes.append(outcome(txn, "applied", proposal))
            continue

        if category in NON_PNL_CATEGORIES:
            writes_draft = auto_accept or proposal.confidence >= policy.review_threshold
            suspense = auto_accept and category in BALANCE_SHEET_ACCOUNTS
            if writes_draft:
                tags = {
                    "category": category.value,
                    "reason": proposal.reason,
                    **({SUSPENSE_TAG: True} if suspense else {}),
                }
                await add(txn, None, tags, proposal.confidence, ClassificationStatus.DRAFT)
            outcomes.append(outcome(txn, "non_pnl", proposal))
            continue

        usable = category_fits_direction(category, txn.direction)
        if auto_accept and (not usable or proposal.confidence < policy.review_threshold):
            account = await _general_account(db, user_id, txn)
            tags = {
                "category": UNCLASSIFIED,
                "reason": ("the suggestion does not fit the direction" if not usable else "low confidence")[:200],
                "auto_accepted": True,
                "original_category": proposal.category,
                "original_confidence": proposal.confidence,
            }
            await add(txn, account.id, tags, 0, ClassificationStatus.APPLIED)
            outcomes.append(outcome(txn, "fallback", proposal))
            continue

        if proposal.confidence >= apply_threshold and (auto_accept or category not in REVIEW_ONLY_CATEGORIES):
            disposition: Disposition = "applied"
        elif proposal.confidence >= policy.review_threshold:
            disposition = "review"
        else:
            disposition = "tail"

        if disposition in ("applied", "review"):
            acc_key = (category, txn.currency)
            if acc_key not in category_account_cache:
                category_account_cache[acc_key] = await _resolve_category_account(db, user_id, category, txn.currency)
            tags = {"category": category.value, "reason": proposal.reason}
            if auto_accept and (
                proposal.confidence < policy.auto_apply_threshold or category in REVIEW_ONLY_CATEGORIES
            ):
                tags["auto_accepted"] = True
            status = ClassificationStatus.APPLIED if disposition == "applied" else ClassificationStatus.DRAFT
            await add(txn, category_account_cache[acc_key].id, tags, proposal.confidence, status)

        outcomes.append(outcome(txn, disposition, proposal))

    replaced = {txn_id: existing[txn_id] for txn_id in {row.atomic_txn_id for row in new_rows} & existing.keys()}
    for old_row in replaced.values():  # a re-ask appends: the old answer stays as history, not as a live row
        old_row.status = ClassificationStatus.SUPERSEDED
    await db.flush()  # frees the live key before the new rows take it
    db.add_all(new_rows)
    await db.flush()
    for row in new_rows:
        if row.atomic_txn_id in replaced:
            replaced[row.atomic_txn_id].superseded_by_id = row.id
    wrote = {row.atomic_txn_id for row in new_rows}
    await _supersede_older_model_rows(db, user_id, sorted(wrote | late), policy.version)
    await db.flush()
    return [o.model_copy(update={"wrote_row": True}) if o.atomic_txn_id in wrote else o for o in outcomes]


class ClassificationSuggestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    atomic_txn_id: UUID
    category: str
    confidence: int
    account_id: UUID | None
    applied: bool
    corrected: bool = False
    classification_id: UUID | None = None
    suspense: bool = False

    @property
    def non_pnl(self) -> bool:
        return self.category in {c.value for c in NON_PNL_CATEGORIES}

    @property
    def booking(self) -> Literal["processing_leg", "loan_principal", "investment_trade"] | None:
        if self.suspense or self.category in {c.value for c in PROCESSING_LEG_CATEGORIES}:
            return "processing_leg"
        if self.category == TransactionCategory.LOAN_PRINCIPAL.value:
            return "loan_principal"
        if self.category == TransactionCategory.INVESTMENT_TRADE.value:
            return "investment_trade"
        return None


async def classification_suggestions(db: AsyncSession, txn_ids: Sequence[UUID]) -> dict[UUID, ClassificationSuggestion]:
    if not txn_ids:
        return {}
    rows = (
        await db.execute(
            select(TransactionClassification)
            .where(TransactionClassification.atomic_txn_id.in_(list(txn_ids)))
            .where(TransactionClassification.status.in_((ClassificationStatus.APPLIED, ClassificationStatus.DRAFT)))
            .order_by(TransactionClassification.created_at.desc())
        )
    ).scalars()
    suggestions: dict[UUID, ClassificationSuggestion] = {}
    for row in rows:
        tags = row.tags if isinstance(row.tags, dict) else {}
        category = tags.get("category")
        if row.atomic_txn_id in suggestions or not isinstance(category, str) or not category:
            continue
        suggestions[row.atomic_txn_id] = ClassificationSuggestion(
            atomic_txn_id=row.atomic_txn_id,
            category=category,
            confidence=row.confidence_score or 0,
            account_id=row.account_id,
            applied=row.status is ClassificationStatus.APPLIED,
            corrected=tags.get("corrected_by_user") is True,
            classification_id=row.id,
            suspense=tags.get(SUSPENSE_TAG) is True,
        )
    return suggestions


def category_fits_direction(category: TransactionCategory, direction: TransactionDirection) -> bool:
    spec = CATEGORY_ACCOUNTS.get(category)
    if spec is None:
        return True
    side = spec[1]
    return (side is AccountType.INCOME and direction is TransactionDirection.IN) or (
        side is AccountType.EXPENSE and direction is TransactionDirection.OUT
    )


class SuggestionCorrectionError(ValidationFailedError):
    """Raised when a user correction cannot be applied to a classification."""


def parse_corrected_category(corrected_value: dict | None) -> TransactionCategory:
    raw = None
    if isinstance(corrected_value, dict):
        for key in ("category", "value"):
            candidate = corrected_value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                raw = candidate.strip()
                break
    allowed = ", ".join(c.value for c in TransactionCategory)
    if raw is None:
        raise SuggestionCorrectionError(f"A corrected category is required. Use one of: {allowed}")
    try:
        return TransactionCategory(re.sub(r"[\s\-]+", "_", raw).upper())
    except ValueError:
        pass
    by_account_name = {name.casefold(): category for category, (name, _side) in CATEGORY_ACCOUNTS.items()}
    category = by_account_name.get(raw.casefold())
    if category is None:
        raise SuggestionCorrectionError(f"The corrected value is not a category. Use one of: {allowed}")
    return category


def _validate_corrected_category(value: dict | None, txn: AtomicTransaction) -> TransactionCategory:
    category = parse_corrected_category(value)
    if not category_fits_direction(category, txn.direction):
        raise SuggestionCorrectionError(
            f"{category.value} does not fit a transaction with direction {txn.direction.value}"
        )
    return category


FeedbackEffect = Literal["accepted", "rejected", "corrected", "recorded"]


async def _retire_model_rows(db: AsyncSession, user_id: UUID, txn_id: UUID, *, keep: UUID) -> None:
    policy_rules = (
        select(ClassificationRule.id)
        .where(ClassificationRule.user_id == user_id)
        .where(ClassificationRule.rule_name == POLICY_RULE_NAME)
    )
    await db.execute(
        update(TransactionClassification)
        .where(TransactionClassification.atomic_txn_id == txn_id)
        .where(TransactionClassification.id != keep)
        .where(TransactionClassification.rule_version_id.in_(policy_rules))
        .where(TransactionClassification.status.in_((ClassificationStatus.APPLIED, ClassificationStatus.DRAFT)))
        .values(status=ClassificationStatus.SUPERSEDED)
        .execution_options(synchronize_session="fetch")
    )


async def _raise_if_superseded_by_rerun(db: AsyncSession, user_id: UUID, suggestion_id: UUID) -> None:
    """Raise ConflictError with live_suggestion_id when a draft was superseded by a newer suggestion."""
    row = (
        await db.execute(
            select(TransactionClassification)
            .join(AtomicTransaction, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
            .where(TransactionClassification.id == suggestion_id)
            .where(AtomicTransaction.user_id == user_id)
        )
    ).scalar_one_or_none()
    if row is None or row.status is not ClassificationStatus.SUPERSEDED or row.superseded_by_id is None:
        return
    direct_successor = row.superseded_by_id
    current_id: UUID = direct_successor
    seen: set[UUID] = {row.id}
    for _ in range(25):
        if current_id in seen:
            break
        seen.add(current_id)
        nxt = await db.get(TransactionClassification, current_id)
        if nxt is None or nxt.status is not ClassificationStatus.SUPERSEDED or nxt.superseded_by_id is None:
            break
        current_id = nxt.superseded_by_id
    raise ConflictError(
        "Classification suggestion was superseded by a newer suggestion.",
        detail_payload={
            "message": "Classification suggestion was superseded by a newer suggestion.",
            "superseded_by_id": str(direct_successor),
            "live_suggestion_id": str(current_id),
        },
    )


async def apply_suggestion_feedback(
    db: AsyncSession,
    user_id: UUID,
    suggestion_id: UUID,
    action: str,
    corrected_value: dict | None,
) -> FeedbackEffect:
    pending = (
        select(TransactionClassification, AtomicTransaction)
        .join(AtomicTransaction, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
        .where(TransactionClassification.id == suggestion_id)
        .where(AtomicTransaction.user_id == user_id)
        .where(TransactionClassification.status == ClassificationStatus.DRAFT)
    )
    row = (await db.execute(pending)).first()
    if row is None:
        await _raise_if_superseded_by_rerun(db, user_id, suggestion_id)
        return "recorded"
    # The lock order of a correction and of a re-ask: the policy-rule lock, then the row (#2994).
    await _lock_policy_rule(db, user_id, policy_for(row[1].txn_date))
    row = (await db.execute(pending.with_for_update(of=TransactionClassification))).first()
    if row is None:
        await _raise_if_superseded_by_rerun(db, user_id, suggestion_id)
        return "recorded"
    classification, txn = row
    previous = classification.tags if isinstance(classification.tags, dict) else {}
    if action == "reject":
        classification.tags = {**previous, "rejected_by_user": True}
        classification.status = ClassificationStatus.SUPERSEDED
        await _retire_model_rows(db, user_id, txn.id, keep=classification.id)
        await db.flush()
        return "rejected"
    if action != "edit_accept":
        classification.tags = {**previous, "accepted_by_user": True}
        await db.flush()
        return "accepted"

    category = _validate_corrected_category(corrected_value, txn)
    account_id = (
        (await _resolve_category_account(db, user_id, category, txn.currency)).id
        if category in CATEGORY_ACCOUNTS
        else None
    )
    if previous.get("category") != category.value:
        db.add(
            CorrectionLog(
                user_id=user_id,
                transaction_id=txn.id,
                original_category=previous.get("category"),
                corrected_category=category.value,
                original_account_id=classification.account_id,
                corrected_account_id=account_id,
                transaction_description=txn.description,
            )
        )
    classification.tags = {
        **{key: value for key, value in previous.items() if key != SUSPENSE_TAG},
        "category": category.value,
        "original_category": previous.get("original_category", previous.get("category")),
        "corrected_by_user": True,
    }
    classification.account_id = account_id
    await db.flush()
    return "corrected"


async def record_classification_feedback(
    db: AsyncSession,
    *,
    user_id: UUID,
    suggestion_id: UUID,
    action: str,
    corrected_value: dict[str, Any] | None,
) -> tuple[AiFeedback, FeedbackEffect] | None:
    """Persist AI feedback for an owned classification suggestion and apply its effect."""
    owned = await db.scalar(
        select(TransactionClassification.id)
        .join(AtomicTransaction, TransactionClassification.atomic_txn_id == AtomicTransaction.id)
        .where(TransactionClassification.id == suggestion_id)
        .where(AtomicTransaction.user_id == user_id)
        .limit(1)
    )
    if owned is None:
        return None
    effect = await apply_suggestion_feedback(db, user_id, suggestion_id, action, corrected_value)
    feedback = AiFeedback(
        suggestion_id=suggestion_id,
        user_id=user_id,
        action=action,
        corrected_value=corrected_value,
    )
    db.add(feedback)
    return feedback, effect


async def apply_user_transaction_correction(
    db: AsyncSession,
    *,
    user_id: UUID,
    txn: AtomicTransaction,
    corrected_category: str,
    corrected_account_id: UUID | None = None,
) -> tuple[str | None, UUID | None]:
    category = _validate_corrected_category({"value": corrected_category}, txn)
    rule = await _ensure_policy_rule(db, user_id, policy_for(txn.txn_date))
    prior = (await classification_suggestions(db, [txn.id])).get(txn.id)
    original_category = prior.category if prior is not None else None

    classification = (
        await db.execute(
            select(TransactionClassification)
            .where(TransactionClassification.atomic_txn_id == txn.id)
            .where(TransactionClassification.rule_version_id == rule.id)
            .order_by(
                TransactionClassification.status.in_(LIVE_STATUSES).desc(), TransactionClassification.created_at.desc()
            )
            .limit(1)  # a re-ask leaves history rows: take the live answer, else the latest
            .with_for_update(of=TransactionClassification)
        )
    ).scalar_one_or_none()

    account_id = corrected_account_id
    if account_id is None:
        if category in CATEGORY_ACCOUNTS:
            account_id = (await _resolve_category_account(db, user_id, category, txn.currency)).id
        elif category in BALANCE_SHEET_ACCOUNTS:
            account_id = (await _balance_sheet_account(db, user_id, category, txn.currency)).id

    target_status = (
        ClassificationStatus.DRAFT
        if category in PROCESSING_LEG_CATEGORIES and corrected_account_id is None
        else ClassificationStatus.APPLIED
    )
    previous_tags = (
        dict(classification.tags) if classification is not None and isinstance(classification.tags, dict) else {}
    )
    tags: dict[str, object] = {
        **{
            key: value
            for key, value in previous_tags.items()
            if key not in (SUSPENSE_TAG, "rejected_by_user", "auto_accepted")
        },
        "category": category.value,
        "corrected_by_user": True,
    }
    if original_category and "original_category" not in tags:
        tags["original_category"] = original_category
    if category in BALANCE_SHEET_ACCOUNTS:
        tags["intent"] = balance_sheet_intent(category, txn.direction).value
    else:
        tags.pop("intent", None)

    if classification is None:
        classification = TransactionClassification(
            atomic_txn_id=txn.id,
            rule_version_id=rule.id,
            account_id=account_id,
            tags=tags,
            confidence_score=100,
            status=target_status,
        )
        db.add(classification)
    else:
        classification.account_id = account_id
        classification.tags = tags
        classification.status = target_status
        classification.confidence_score = 100
    await db.flush()
    await _retire_model_rows(db, user_id, txn.id, keep=classification.id)
    await db.flush()
    return original_category, account_id


async def settle_drafts_after_posting(
    db: AsyncSession, txn_id: UUID, *, accepted_id: UUID | None, accepted_by: Literal["user", "system"] = "user"
) -> None:
    drafts = (
        (
            await db.execute(
                select(TransactionClassification)
                .where(TransactionClassification.atomic_txn_id == txn_id)
                .where(TransactionClassification.status == ClassificationStatus.DRAFT)
                .with_for_update(of=TransactionClassification)  # read the draft again if a re-ask held it
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    for draft in drafts:
        if draft.id == accepted_id:
            draft.status = ClassificationStatus.APPLIED
            mark = "accepted_by_user" if accepted_by == "user" else "auto_accepted"
            draft.tags = {**(draft.tags if isinstance(draft.tags, dict) else {}), mark: True}
        else:
            draft.status = ClassificationStatus.SUPERSEDED
    if drafts:
        await db.flush()


async def policy_buckets(
    db: AsyncSession, user_id: UUID, transactions: Sequence[AtomicTransaction]
) -> list[tuple[ClassificationPolicy | None, list[AtomicTransaction]]]:
    """Group transactions by effective policy date. With the model off there is one bucket and no policy."""
    if not await classification_enabled(db, user_id):
        return [(None, list(transactions))]

    by_version: dict[int, list[AtomicTransaction]] = {}
    policies: dict[int, ClassificationPolicy] = {}
    skipped = 0
    for txn in transactions:
        try:
            policy = policy_for(txn.txn_date)
        except ValueError:
            skipped += 1
            continue
        policies[policy.version] = policy
        by_version.setdefault(policy.version, []).append(txn)
    if skipped:
        logger.warning("transactions predate every classification policy; left unclassified", skipped=skipped)

    return [(policies[version], by_version[version]) for version in sorted(by_version)]
