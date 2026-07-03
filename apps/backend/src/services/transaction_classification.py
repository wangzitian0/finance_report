"""Transaction classify node (#1544 Construct, EPIC-018 AC18.15).

LLM-LED with a strong-code spine (vision Axiom D): the model *proposes* a category
from the FIXED catalog below with a confidence score; deterministic code *disposes* —
resolves category→account and writes the classification row. The model never touches
money: proposals cannot express amounts, and posting stays with the ledger path.

The classification basis is a first-class, effective-dated policy: a taxonomy/threshold
change is a NEW ``ClassificationPolicy`` version with an explicit ``effective_from``
cutoff (prospective by default). ``commit_basis=False`` runs the same pass pro-forma —
compute the verdicts under a candidate policy without writing the basis-of-record.

Construct-only: gated by ``settings.enable_ai_classification`` and consumed by nothing
in production yet. #1545 (Migrate) wires the import → income-statement path onto it.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from datetime import date
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.account import AccountType
from src.models.layer2 import AtomicTransaction
from src.models.layer3 import (
    ClassificationRule,
    ClassificationStatus,
    RuleType,
    TransactionClassification,
)
from src.observability import get_logger
from src.services.classification import ClassificationService

logger = get_logger(__name__)

POLICY_RULE_NAME = "llm-category-policy"


class TransactionCategory(str, Enum):
    """The fixed, closed category catalog (v1). The model may only propose these."""

    # income
    SALARY = "SALARY"
    INTEREST = "INTEREST"
    INVESTMENT_INCOME = "INVESTMENT_INCOME"
    REFUND = "REFUND"
    OTHER_INCOME = "OTHER_INCOME"
    # expense
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


# Deterministic category → (account name, account side). Code owns this mapping;
# the model only ever names a catalog member.
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


class ClassificationPolicy(BaseModel):
    """An effective-dated, immutable classification-basis version.

    A taxonomy/threshold change is a NEW version with its own ``effective_from``
    cutoff — prospective by default; already-effective versions are never mutated.
    """

    model_config = ConfigDict(frozen=True)

    version: int
    effective_from: date
    catalog: tuple[TransactionCategory, ...]
    model_version: str
    auto_apply_threshold: int = 85
    review_threshold: int = 60


#: Append-only registry of policy versions. A basis change appends a new version here
#: (or, post-#1545, to its persisted home) — it never edits an existing entry.
POLICY_VERSIONS: tuple[ClassificationPolicy, ...] = (
    ClassificationPolicy(
        version=1,
        # The INITIAL basis covers all prior history (pre-2020 statements are
        # normal); only later versions carry a meaningful cutover date.
        effective_from=date.min,
        catalog=tuple(TransactionCategory),
        model_version="v1",
    ),
)


def policy_for(as_of: date, *, registry: Sequence[ClassificationPolicy] | None = None) -> ClassificationPolicy:
    """Head-select the policy in effect on ``as_of`` (latest effective_from <= as_of).

    The default registry is resolved at call time so a newly published version is
    visible without rebinding call sites.
    """
    if registry is None:
        registry = POLICY_VERSIONS
    effective = [p for p in registry if p.effective_from <= as_of]
    if not effective:
        raise ValueError(f"no classification policy effective on {as_of.isoformat()}")
    return max(effective, key=lambda p: (p.effective_from, p.version))


class CategoryProposal(BaseModel):
    """What the model may say — a catalog category + confidence, nothing more.

    Deliberately cannot express an amount (red line: the model never touches money).
    """

    model_config = ConfigDict(frozen=True)

    category: str
    confidence: int
    reason: str = ""


Disposition = Literal["rule", "applied", "review", "tail", "off_catalog", "no_proposal"]


class ClassificationOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    atomic_txn_id: UUID
    disposition: Disposition
    category: str | None = None
    confidence: int | None = None
    policy_version: int


Proposer = Callable[
    [Sequence[AtomicTransaction], ClassificationPolicy],
    Awaitable[list[CategoryProposal | None]],
]


def _recover_json_array(content: str) -> list | None:
    """Best-effort recovery of a JSON array from a fenced/prose-wrapped response.

    Models occasionally wrap an otherwise-valid array in a markdown code fence or
    pad it with prose (seen live on staging: ``json.loads`` failed at char 0 and
    every transaction degraded to ``no_proposal``). Scan every top-level balanced
    ``[...]`` — tracking string literals so brackets inside values don't truncate
    one — and return the largest that parses. Deterministic; never invents data;
    returns ``None`` when nothing recoverable exists (the graceful-fallback path).
    The array twin of ``extraction/_coerce._repair_json_object``.
    """
    if not content:
        return None
    text = content.strip()
    candidates: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "[":
            i += 1
            continue
        depth, in_string, escaped, end = 0, False, False, None
        for j in range(i, n):
            char = text[j]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        if end is None:
            break
        candidates.append(text[i : end + 1])
        i = end + 1
    for candidate in sorted(candidates, key=len, reverse=True):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return parsed
    return None


async def propose_categories(
    transactions: Sequence[AtomicTransaction], policy: ClassificationPolicy
) -> list[CategoryProposal | None]:
    """The single LLM boundary: prompt-constrained JSON proposals onto the catalog.

    Mirrors ``reconciliation_scoring.ai_semantic_score``: prompt-driven JSON, parsed
    and clamped by code, graceful ``None`` fallback per transaction on any error.
    Only descriptions and directions are sent — never amounts.
    """
    from src.llm.extension.cassette import CassetteMode, current_mode
    from src.services.ai_streaming import AIStreamError, accumulate_stream, stream_ai_json

    if not settings.ai_api_key and current_mode() is CassetteMode.OFF:
        # Replay/record modes go through the cassette layer (zero key, zero
        # network in replay), so the key guard only applies in off mode.
        logger.debug("transaction classification skipped: no API key configured")
        return [None] * len(transactions)

    catalog = ", ".join(c.value for c in policy.catalog)
    lines = "\n".join(
        f'{i}. direction={t.direction.value} description="{t.description}"' for i, t in enumerate(transactions)
    )
    prompt = (
        "Classify each personal-finance transaction into EXACTLY ONE category from "
        f"this closed list: [{catalog}]. Respond with ONLY the raw JSON array — "
        "Do NOT wrap it in markdown or code fences and do not add prose. Item i "
        'must be {"category": "<one of the list>", "confidence": <0-100 integer>, '
        '"reason": "<short>"} for transaction i.\n\nTransactions:\n' + lines
    )

    try:
        stream = stream_ai_json(
            messages=[{"role": "user", "content": prompt}],
            model=settings.primary_model,
            timeout=60.0,
        )
        content = await accumulate_stream(stream)
        if not content or not content.strip():
            logger.warning("transaction classification proposal returned empty response")
            return [None] * len(transactions)
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = _recover_json_array(content)
        if not isinstance(parsed, list):
            # Redacted diagnostics only (descriptions are user data): enough to
            # distinguish fenced/prose/truncated shapes from the logs next time.
            logger.warning(
                "transaction classification proposal failed",
                error="unparseable model response",
                content_length=len(content),
                looks_fenced=content.lstrip().startswith("`"),
            )
            return [None] * len(transactions)
    except (AIStreamError, ValueError, TypeError) as e:
        logger.warning("transaction classification proposal failed", error=str(e))
        return [None] * len(transactions)

    proposals: list[CategoryProposal | None] = []
    for i in range(len(transactions)):
        item = parsed[i] if i < len(parsed) else None
        if not isinstance(item, dict):
            proposals.append(None)
            continue
        try:
            proposals.append(
                CategoryProposal(
                    category=str(item.get("category", "")),
                    confidence=max(0, min(100, int(item.get("confidence", 0)))),
                    reason=str(item.get("reason", ""))[:500],
                )
            )
        except (ValueError, TypeError):
            proposals.append(None)
    return proposals


async def _classification_enabled(db: AsyncSession, user_id: UUID) -> bool:
    """The EPIC-018 flag, with the per-user ``ai_settings`` override on top."""
    from src.identity import User

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    overrides = user.ai_settings if user is not None and isinstance(user.ai_settings, dict) else {}
    return bool(overrides.get("enable_ai_classification", settings.enable_ai_classification))


async def _ensure_policy_rule(db: AsyncSession, user_id: UUID, policy: ClassificationPolicy) -> ClassificationRule:
    """Materialize the policy version as its append-only ``ClassificationRule`` anchor.

    ``TransactionClassification.rule_version_id`` is NOT NULL, and the rule table
    already carries exactly the semantics a policy version needs (monotonic version,
    effective date, append-only supersession) — so the policy anchors there instead
    of a new table. One rule row per (user, policy version).
    """
    existing = (
        await db.execute(
            select(ClassificationRule)
            .where(ClassificationRule.user_id == user_id)
            .where(ClassificationRule.rule_name == POLICY_RULE_NAME)
            .where(ClassificationRule.version_number == policy.version)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    rule = ClassificationRule(
        user_id=user_id,
        created_by=user_id,
        rule_name=POLICY_RULE_NAME,
        version_number=policy.version,
        effective_date=policy.effective_from,
        # The policy anchor is not a matching rule: never let the deterministic
        # rules pre-pass pick it up as a user rule.
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
    return rule


async def _resolve_category_account(db: AsyncSession, user_id: UUID, category: TransactionCategory, currency: str):
    from src.services.review_queue import get_or_create_account

    name, account_type = CATEGORY_ACCOUNTS[category]
    return await get_or_create_account(db, name=name, account_type=account_type, currency=currency, user_id=user_id)


def summarize_outcomes(outcomes: Sequence[ClassificationOutcome]) -> dict:
    """Confidence/category distribution — the observe-then-tune surface (AC18.15.8)."""
    confidences = [o.confidence for o in outcomes if o.confidence is not None]
    return {
        "total": len(outcomes),
        "by_disposition": dict(Counter(o.disposition for o in outcomes)),
        "by_category": dict(Counter(o.category for o in outcomes if o.category)),
        "confidence_buckets": dict(Counter(f"{(c // 10) * 10}-{(c // 10) * 10 + 9}" for c in confidences)),
    }


async def classify_transactions(
    db: AsyncSession,
    user_id: UUID,
    transactions: Sequence[AtomicTransaction],
    *,
    policy: ClassificationPolicy,
    proposer: Proposer | None = None,
    commit_basis: bool = True,
) -> list[ClassificationOutcome]:
    """Classify ``transactions`` under ``policy``.

    Deterministic user rules win first; the model proposes for the rest; the
    confidence gate disposes: >= auto threshold => APPLIED onto a real catalog
    account; review band => DRAFT (the existing ai_feedback 60-84 queue); below =>
    the genuine Uncategorized tail. ``commit_basis=False`` is pro-forma: same
    verdicts, zero writes.
    """
    if not await _classification_enabled(db, user_id):
        return []
    if not transactions:
        return []

    propose = proposer or propose_categories
    outcomes: list[ClassificationOutcome] = []

    # 1) deterministic rules pre-pass (user intent wins; the model is not consulted)
    service = ClassificationService()
    rules = [r for r in await service.get_active_rules(db, user_id) if r.rule_name != POLICY_RULE_NAME]
    ruled: dict[UUID, AtomicTransaction] = {}
    if rules:
        for txn in transactions:
            if any(service._match_rule(txn, rule) for rule in rules):
                ruled[txn.id] = txn
        if ruled and commit_basis:
            await service.apply_rules(db, user_id, list(ruled.values()))

    remaining = [t for t in transactions if t.id not in ruled]

    # 2) the model proposes for the rest
    proposals = await propose(remaining, policy) if remaining else []

    # 3) deterministic disposal under the confidence gate
    policy_rule: ClassificationRule | None = None
    # Idempotent re-run: classification is a recomputable pass. A txn already
    # classified under THIS policy version keeps its row (no duplicate
    # (atomic_txn_id, rule_version_id) insert); superseding across policy
    # versions is #1545's migration seam.
    already_classified: set[UUID] = set()
    if commit_basis:
        existing_rule = (
            await db.execute(
                select(ClassificationRule.id)
                .where(ClassificationRule.user_id == user_id)
                .where(ClassificationRule.rule_name == POLICY_RULE_NAME)
                .where(ClassificationRule.version_number == policy.version)
            )
        ).scalar_one_or_none()
        if existing_rule is not None:
            already_classified = {
                row
                for row in (
                    await db.execute(
                        select(TransactionClassification.atomic_txn_id).where(
                            TransactionClassification.rule_version_id == existing_rule
                        )
                    )
                )
                .scalars()
                .all()
            }
    proposal_by_txn = dict(zip(remaining, proposals))
    for txn in transactions:
        if txn.id in ruled:
            outcomes.append(
                ClassificationOutcome(atomic_txn_id=txn.id, disposition="rule", policy_version=policy.version)
            )
            continue

        proposal = proposal_by_txn.get(txn)
        if proposal is None:
            outcomes.append(
                ClassificationOutcome(atomic_txn_id=txn.id, disposition="no_proposal", policy_version=policy.version)
            )
            continue

        try:
            category = TransactionCategory(proposal.category)
        except ValueError:
            category = None
        if category is None or category not in policy.catalog:
            outcomes.append(
                ClassificationOutcome(
                    atomic_txn_id=txn.id,
                    disposition="off_catalog",
                    category=proposal.category,
                    confidence=proposal.confidence,
                    policy_version=policy.version,
                )
            )
            continue

        if proposal.confidence >= policy.auto_apply_threshold:
            disposition: Disposition = "applied"
        elif proposal.confidence >= policy.review_threshold:
            disposition = "review"
        else:
            disposition = "tail"

        if commit_basis and disposition in ("applied", "review") and txn.id not in already_classified:
            if policy_rule is None:
                policy_rule = await _ensure_policy_rule(db, user_id, policy)
            account = await _resolve_category_account(db, user_id, category, txn.currency)
            db.add(
                TransactionClassification(
                    atomic_txn_id=txn.id,
                    rule_version_id=policy_rule.id,
                    account_id=account.id,
                    tags={"category": category.value, "reason": proposal.reason},
                    confidence_score=proposal.confidence,
                    status=(ClassificationStatus.APPLIED if disposition == "applied" else ClassificationStatus.DRAFT),
                )
            )

        outcomes.append(
            ClassificationOutcome(
                atomic_txn_id=txn.id,
                disposition=disposition,
                category=category.value,
                confidence=proposal.confidence,
                policy_version=policy.version,
            )
        )

    if commit_basis:
        await db.flush()

    logger.info(
        "transaction classification pass",
        policy_version=policy.version,
        commit_basis=commit_basis,
        **summarize_outcomes(outcomes),
    )
    return outcomes


async def backfill_classifications(db: AsyncSession, user_id: UUID) -> dict:
    """One-time (#1545) backfill: classify a user's not-yet-classified transactions
    under each transaction's OWN effective policy (``policy_for(txn_date)``).

    Append-only and duplicate-free by construction: transactions that already
    carry a classification row are never candidates again, so a re-run cannot
    rewrite or duplicate anything. Transactions still in the tail (low-confidence,
    no-proposal, off-catalog) get NO row and therefore ARE re-attempted on the
    next run — deliberately: the tail may resolve under a better model or a new
    policy version (the edit-tags → re-extract direction). Entry point: the
    /classifications/backfill router (#1546).
    """
    if not await _classification_enabled(db, user_id):
        return {"classified": 0, "candidates": 0}

    classified_txn_ids = select(TransactionClassification.atomic_txn_id)
    candidates = (
        (
            await db.execute(
                select(AtomicTransaction)
                .where(AtomicTransaction.user_id == user_id)
                .where(~AtomicTransaction.id.in_(classified_txn_ids))
                .order_by(AtomicTransaction.txn_date)
            )
        )
        .scalars()
        .all()
    )
    if not candidates:
        return {"classified": 0, "candidates": 0}

    # Effective-dated basis: group by the policy in effect on each txn's date, so a
    # later-published version never touches already-covered periods (prospective).
    by_version: dict[int, list[AtomicTransaction]] = {}
    policies: dict[int, ClassificationPolicy] = {}
    for txn in candidates:
        policy = policy_for(txn.txn_date)
        policies[policy.version] = policy
        by_version.setdefault(policy.version, []).append(txn)

    written = 0
    summaries = []
    for version, txns in sorted(by_version.items()):
        outcomes = await classify_transactions(db, user_id, txns, policy=policies[version])
        written += sum(1 for o in outcomes if o.disposition in ("applied", "review"))
        summaries.append({"policy_version": version, **summarize_outcomes(outcomes)})

    return {"classified": written, "candidates": len(candidates), "runs": summaries}


async def classify_by_effective_policy(
    db: AsyncSession,
    user_id: UUID,
    transactions: Sequence[AtomicTransaction],
) -> list[ClassificationOutcome]:
    """The production posting seam (#1545): classify each transaction under the
    policy in effect on its OWN txn_date.

    Contract (CR #1555): the flag gate comes FIRST — with classification disabled
    this returns immediately without evaluating any policy, so posting behaves
    exactly as before this EPIC. A transaction whose date no policy covers is
    SKIPPED (it stays in the Uncategorized tail) rather than crashing the posting
    path.
    """
    if not transactions or not await _classification_enabled(db, user_id):
        return []

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
        logger.warning(
            "transactions predate every classification policy; left unclassified",
            skipped=skipped,
        )

    outcomes: list[ClassificationOutcome] = []
    for version in sorted(by_version):
        outcomes.extend(await classify_transactions(db, user_id, by_version[version], policy=policies[version]))
    return outcomes
