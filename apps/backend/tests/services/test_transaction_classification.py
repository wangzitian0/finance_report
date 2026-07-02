"""EPIC-018 AC18.15 (#1544 Construct): flag-gated transaction classify node + effective-dated policy.

The model proposes a category from a FIXED catalog with a confidence score; deterministic
code disposes (resolves category→account, writes the classification row). The model never
touches money. Construct-only: nothing in production consumes the node yet (#1545 migrates).
"""

from __future__ import annotations

import ast
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from src.models.account import Account, AccountType
from src.models.layer3 import (
    ClassificationRule,
    ClassificationStatus,
    RuleType,
    TransactionClassification,
)
from src.services.transaction_classification import (
    CategoryProposal,
    ClassificationPolicy,
    TransactionCategory,
    classify_transactions,
    policy_for,
)
from tests.factories import AtomicTransactionFactory

MODULE_PATH = Path("src/services/transaction_classification.py")


def _policy(**overrides) -> ClassificationPolicy:
    kwargs = dict(
        version=1,
        effective_from=date(2020, 1, 1),
        catalog=tuple(TransactionCategory),
        model_version="test-model",
        auto_apply_threshold=85,
        review_threshold=60,
    )
    kwargs.update(overrides)
    return ClassificationPolicy(**kwargs)


def _stub_proposer(proposals_by_description: dict[str, CategoryProposal | None]):
    """Deterministic proposer stub; records which descriptions it was asked about."""
    calls: list[str] = []

    async def proposer(transactions, policy):
        calls.append("call")
        return [proposals_by_description.get(t.description) for t in transactions]

    proposer.calls = calls
    return proposer


@pytest.fixture
def enabled_flag(monkeypatch):
    from src.config import settings

    monkeypatch.setattr(settings, "enable_ai_classification", True)


async def _count(db, model) -> int:
    return int((await db.execute(select(func.count()).select_from(model))).scalar_one())


# --- AC18.15.1: policy is versioned, effective-dated, immutable -----------------


def test_AC18_15_1_policy_is_effective_dated_and_immutable():
    """AC18.15.1: ClassificationPolicy is an effective-dated, immutable version."""
    v1 = _policy(version=1, effective_from=date(2020, 1, 1))
    v2 = _policy(version=2, effective_from=date(2026, 7, 1))
    registry = (v1, v2)

    # head-selection: the latest policy whose effective_from <= as_of wins
    assert policy_for(date(2026, 6, 30), registry=registry) is v1
    assert policy_for(date(2026, 7, 1), registry=registry) is v2
    assert policy_for(date(2030, 1, 1), registry=registry) is v2

    # immutable once constructed: a "change" must be a new version, never a mutation
    with pytest.raises(Exception):
        v1.auto_apply_threshold = 50  # type: ignore[misc]

    # the default registry head-selects too (v1 exists and covers today)
    assert policy_for(date.today()).version >= 1


# --- AC18.15.2: pure & reproducible ---------------------------------------------


@pytest.mark.asyncio
async def test_AC18_15_2_classify_is_reproducible_for_same_inputs(db, test_user, enabled_flag):
    """AC18.15.2: identical (transactions, policy, proposals) => identical outcomes."""
    txns = [
        await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description=f"COFFEE SHOP {i}")
        for i in range(3)
    ]
    proposer = _stub_proposer(
        {t.description: CategoryProposal(category=TransactionCategory.DINING.value, confidence=90) for t in txns}
    )
    policy = _policy()

    first = await classify_transactions(db, test_user.id, txns, policy=policy, proposer=proposer, commit_basis=False)
    second = await classify_transactions(db, test_user.id, txns, policy=policy, proposer=proposer, commit_basis=False)

    assert [o.model_dump() for o in first] == [o.model_dump() for o in second]
    assert all(o.policy_version == policy.version for o in first)


# --- AC18.15.3: output constrained to the catalog --------------------------------


@pytest.mark.asyncio
async def test_AC18_15_3_off_catalog_proposal_is_rejected_never_applied(db, test_user, enabled_flag):
    """AC18.15.3: a proposal outside the policy catalog is rejected, not posted."""
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="MYSTERY MERCHANT")
    proposer = _stub_proposer({txn.description: CategoryProposal(category="CRYPTO_YOLO", confidence=99)})

    outcomes = await classify_transactions(
        db, test_user.id, [txn], policy=_policy(), proposer=proposer, commit_basis=True
    )

    assert outcomes[0].disposition == "off_catalog"
    assert await _count(db, TransactionClassification) == 0


# --- AC18.15.4: confidence gate (Axiom B) ----------------------------------------


@pytest.mark.asyncio
async def test_AC18_15_4_confidence_gate_applies_reviews_or_tails(db, test_user, enabled_flag):
    """AC18.15.4: >=85 auto-APPLIED onto a real catalog account; 60-84 DRAFT for the
    ai_feedback review band; <60 stays in the genuine Uncategorized tail."""
    high = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    mid = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="NTUC FAIRPRICE")
    low = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="???")
    proposer = _stub_proposer(
        {
            high.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=92),
            mid.description: CategoryProposal(category=TransactionCategory.GROCERIES.value, confidence=70),
            low.description: CategoryProposal(category=TransactionCategory.OTHER_EXPENSE.value, confidence=30),
        }
    )

    outcomes = await classify_transactions(
        db, test_user.id, [high, mid, low], policy=_policy(), proposer=proposer, commit_basis=True
    )
    by_txn = {o.atomic_txn_id: o for o in outcomes}
    assert by_txn[high.id].disposition == "applied"
    assert by_txn[mid.id].disposition == "review"
    assert by_txn[low.id].disposition == "tail"

    rows = (await db.execute(select(TransactionClassification))).scalars().all()
    by_status = {r.atomic_txn_id: r for r in rows}
    assert set(by_status) == {high.id, mid.id}

    applied = by_status[high.id]
    assert applied.status == ClassificationStatus.APPLIED
    assert applied.confidence_score == 92
    account = (await db.execute(select(Account).where(Account.id == applied.account_id))).scalar_one()
    assert account.type == AccountType.INCOME  # deterministic category→account disposal

    draft = by_status[mid.id]
    assert draft.status == ClassificationStatus.DRAFT
    # exactly the existing ai_feedback review-band filter (DRAFT and 60 <= score < 85)
    assert draft.confidence_score is not None and 60 <= draft.confidence_score < 85


# --- AC18.15.5: red line — the model never touches money -------------------------


@pytest.mark.asyncio
async def test_AC18_15_5_model_never_touches_money(db, test_user, enabled_flag):
    """AC18.15.5: proposals carry no amounts; posting stays with deterministic code."""
    # schema red-line: a proposal cannot even express an amount
    assert not {"amount", "value", "total", "price"} & set(CategoryProposal.model_fields)

    # static red-line: the node never imports posting primitives
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert not {"JournalEntry", "JournalLine"} & imported

    # behavioral: the txn's Decimal amount is untouched by classification
    txn = await AtomicTransactionFactory.create_async(
        db, user_id=test_user.id, description="ACME PAYROLL", amount=Decimal("1234.56")
    )
    proposer = _stub_proposer(
        {txn.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)}
    )
    await classify_transactions(db, test_user.id, [txn], policy=_policy(), proposer=proposer, commit_basis=True)
    await db.refresh(txn)
    assert txn.amount == Decimal("1234.56") and isinstance(txn.amount, Decimal)


# --- AC18.15.6: pro-forma is side-effect-free ------------------------------------


@pytest.mark.asyncio
async def test_AC18_15_6_pro_forma_writes_nothing(db, test_user, enabled_flag):
    """AC18.15.6: commit_basis=False classifies under a candidate policy without
    writing the basis-of-record (no classifications, no policy rules, no accounts)."""
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    proposer = _stub_proposer(
        {txn.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)}
    )
    before = (
        await _count(db, TransactionClassification),
        await _count(db, ClassificationRule),
        await _count(db, Account),
    )

    outcomes = await classify_transactions(
        db, test_user.id, [txn], policy=_policy(version=99), proposer=proposer, commit_basis=False
    )

    assert outcomes[0].disposition == "applied"  # the *verdict* is computed...
    after = (
        await _count(db, TransactionClassification),
        await _count(db, ClassificationRule),
        await _count(db, Account),
    )
    assert after == before  # ...but nothing is committed


# --- AC18.15.7: deterministic rule pre-pass wins ----------------------------------


@pytest.mark.asyncio
async def test_AC18_15_7_user_rule_prepass_wins_over_model(db, test_user, enabled_flag):
    """AC18.15.7: a user's deterministic rule wins; the model is not consulted for it."""
    rule = ClassificationRule(
        user_id=test_user.id,
        created_by=test_user.id,
        rule_name="my-coffee-rule",
        version_number=1,
        effective_date=date(2020, 1, 1),
        is_active=True,
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["coffee"]},
        tag_mappings={"category": "user-coffee"},
    )
    db.add(rule)
    await db.flush()

    ruled = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="COFFEE SHOP")
    unruled = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    proposer = _stub_proposer(
        {
            ruled.description: CategoryProposal(category=TransactionCategory.DINING.value, confidence=95),
            unruled.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95),
        }
    )

    outcomes = await classify_transactions(
        db, test_user.id, [ruled, unruled], policy=_policy(), proposer=proposer, commit_basis=True
    )
    by_txn = {o.atomic_txn_id: o for o in outcomes}
    assert by_txn[ruled.id].disposition == "rule"
    assert by_txn[unruled.id].disposition == "applied"


@pytest.mark.asyncio
async def test_AC18_15_7_no_rules_is_a_noop_prepass_not_an_error(db, test_user, enabled_flag):
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    proposer = _stub_proposer(
        {txn.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)}
    )
    outcomes = await classify_transactions(
        db, test_user.id, [txn], policy=_policy(), proposer=proposer, commit_basis=True
    )
    assert outcomes[0].disposition == "applied"


# --- AC18.15.8: flag-gated; construct-only (nothing in production consumes it) ---


@pytest.mark.asyncio
async def test_AC18_15_8_flag_off_is_a_noop(db, test_user, monkeypatch):
    """AC18.15.8: with enable_ai_classification off (the default), the node is inert."""
    from src.config import settings

    monkeypatch.setattr(settings, "enable_ai_classification", False)
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    proposer = _stub_proposer(
        {txn.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)}
    )

    outcomes = await classify_transactions(
        db, test_user.id, [txn], policy=_policy(), proposer=proposer, commit_basis=True
    )

    assert outcomes == []
    assert proposer.calls == []
    assert await _count(db, TransactionClassification) == 0


def test_AC18_15_8_construct_only_no_production_consumer():
    """AC18.15.8: pre-Migrate, no production module imports the classify node —
    the exact 'wired' flip is #1545's job, asserted there in reverse."""
    src_root = Path("src")
    importers = []
    for path in src_root.rglob("*.py"):
        if path == MODULE_PATH:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "transaction_classification" in node.module:
                importers.append(str(path))
            elif isinstance(node, ast.Import) and any("transaction_classification" in a.name for a in node.names):
                importers.append(str(path))
    assert importers == []


# --- AC18.15.3 (LLM boundary contract): prompt-driven JSON, parsed + clamped by code ---


def _fake_stream(content: str):
    async def gen():
        yield content

    return gen()


@pytest.mark.asyncio
async def test_AC18_15_3_proposer_parses_and_clamps_model_json(monkeypatch):
    """AC18.15.3: the LLM boundary parses prompt-driven JSON and clamps confidence;
    code, not the model, owns the resulting values."""
    from src.config import settings
    from src.services import transaction_classification as tc

    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    txns = [
        AtomicTransactionFactory.build(user_id=None, description="ACME PAYROLL"),
        AtomicTransactionFactory.build(user_id=None, description="???"),
    ]
    content = json.dumps(
        [
            {"category": "SALARY", "confidence": 250, "reason": "payroll"},  # clamped to 100
            "not-a-dict",  # -> None
        ]
    )
    monkeypatch.setattr(tc, "stream_ai_json", lambda **kw: _fake_stream(content), raising=False)
    monkeypatch.setattr("src.services.ai_streaming.stream_ai_json", lambda **kw: _fake_stream(content))

    proposals = await tc.propose_categories(txns, policy_for(date.today()))

    assert proposals[0] is not None
    assert proposals[0].category == "SALARY"
    assert proposals[0].confidence == 100  # clamped by code
    assert proposals[1] is None


@pytest.mark.asyncio
async def test_AC18_15_3_proposer_fails_safe_to_none(monkeypatch):
    """AC18.15.3: malformed model output or a missing key degrades to None per txn."""
    from src.config import settings
    from src.services import transaction_classification as tc

    txns = [AtomicTransactionFactory.build(user_id=None, description="X")]

    # no API key -> no call, all None
    monkeypatch.setattr(settings, "ai_api_key", "")
    assert await tc.propose_categories(txns, policy_for(date.today())) == [None]

    # malformed JSON -> graceful None fallback
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr("src.services.ai_streaming.stream_ai_json", lambda **kw: _fake_stream("{nope"))
    assert await tc.propose_categories(txns, policy_for(date.today())) == [None]


@pytest.mark.asyncio
async def test_AC18_15_2_committed_rerun_is_idempotent_not_integrityerror(db, test_user, enabled_flag):
    """AC18.15.2: re-running the pass under the SAME policy is idempotent — the
    existing classification is kept (no duplicate (txn, policy-rule) row, no
    IntegrityError), because classification is a recomputable pass, not a one-shot."""
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    proposer = _stub_proposer(
        {txn.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)}
    )
    policy = _policy()

    first = await classify_transactions(db, test_user.id, [txn], policy=policy, proposer=proposer, commit_basis=True)
    second = await classify_transactions(db, test_user.id, [txn], policy=policy, proposer=proposer, commit_basis=True)

    assert first[0].disposition == "applied"
    assert second[0].disposition == "applied"  # same verdict, reported again
    rows = (
        (await db.execute(select(TransactionClassification).where(TransactionClassification.atomic_txn_id == txn.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1  # kept, not duplicated
