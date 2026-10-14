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

from src.extraction import ClassificationStatus, RuleType
from src.extraction.extension.transaction_classification import (
    CategoryProposal,
    ClassificationPolicy,
    TransactionCategory,
    classify_transactions,
    policy_for,
)
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.ledger import Account, AccountType
from tests.factories import AtomicTransactionFactory

_BACKEND_SRC = Path(__file__).resolve().parents[2] / "src"
MODULE_PATH = _BACKEND_SRC / "extraction" / "extension" / "transaction_classification.py"


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
    """AC-extraction.1815.1: AC18.15.1: ClassificationPolicy is an effective-dated, immutable version."""
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
    """AC-extraction.1815.2: AC18.15.2: identical (transactions, policy, proposals) => identical outcomes."""
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
    """AC-extraction.1815.3: AC18.15.3: a proposal outside the policy catalog is rejected, not posted."""
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="MYSTERY MERCHANT")
    proposer = _stub_proposer({txn.description: CategoryProposal(category="CRYPTO_YOLO", confidence=99)})

    outcomes = await classify_transactions(
        db, test_user.id, [txn], policy=_policy(), proposer=proposer, commit_basis=True
    )

    assert outcomes[0].disposition == "off_catalog"
    assert await _count(db, TransactionClassification) == 0


# --- AC18.15.4: confidence gate (Axiom B) ----------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("review_path")
async def test_AC18_15_4_confidence_gate_applies_reviews_or_tails(db, test_user, enabled_flag):
    """AC-extraction.1815.4: AC18.15.4: >=85 auto-APPLIED onto a real catalog account; 60-84 DRAFT for the
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
    """AC-extraction.1815.5: AC18.15.5: proposals carry no amounts; posting stays with deterministic code."""
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
@pytest.mark.usefixtures("review_path")
async def test_AC18_15_6_pro_forma_writes_nothing(db, test_user, enabled_flag):
    """AC-extraction.1815.6: AC18.15.6: commit_basis=False classifies under a candidate policy without
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
@pytest.mark.usefixtures("review_path")
async def test_AC18_15_7_user_rule_prepass_wins_over_model(db, test_user, enabled_flag):
    """AC-extraction.1815.7: AC18.15.7: a user's deterministic rule wins; the model is not consulted for it."""
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
@pytest.mark.usefixtures("review_path")
async def test_AC18_15_7_no_rules_is_a_noop_prepass_not_an_error(db, test_user, enabled_flag):
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    proposer = _stub_proposer(
        {txn.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)}
    )
    outcomes = await classify_transactions(
        db, test_user.id, [txn], policy=_policy(), proposer=proposer, commit_basis=True
    )
    assert outcomes[0].disposition == "applied"


# --- AC18.15.8: LLM toggle controls only model proposals ---------------------------


@pytest.mark.asyncio
async def test_AC18_15_8_flag_off_skips_llm_not_deterministic_rules(db, test_user, monkeypatch):
    """AC-extraction.1815.8: the LLM toggle cannot disable a reviewed rule."""
    from src.config import settings

    monkeypatch.setattr(settings, "enable_ai_classification", False)
    db.add(
        ClassificationRule(
            user_id=test_user.id,
            created_by=test_user.id,
            rule_name="reviewed-coffee-rule",
            version_number=1,
            effective_date=date(2020, 1, 1),
            is_active=True,
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": ["coffee"]},
            tag_mappings={"category": "DINING"},
        )
    )
    await db.flush()
    ruled = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="COFFEE SHOP")
    unmatched = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    proposer = _stub_proposer(
        {unmatched.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)}
    )

    outcomes = await classify_transactions(
        db, test_user.id, [ruled, unmatched], policy=_policy(), proposer=proposer, commit_basis=True
    )

    by_txn = {outcome.atomic_txn_id: outcome for outcome in outcomes}
    assert by_txn[ruled.id].disposition == "rule"
    assert by_txn[unmatched.id].disposition == "no_proposal"
    assert proposer.calls == []
    assert await _count(db, TransactionClassification) == 1


def test_AC_extraction_ai_classification_default_1_code_default_is_on(monkeypatch):
    """AC-extraction.ai-classification-default.1: the code default is on; reconciliation stays opt-in."""
    from src.config import Settings

    monkeypatch.delenv("ENABLE_AI_CLASSIFICATION", raising=False)
    monkeypatch.delenv("ENABLE_AI_RECONCILIATION", raising=False)

    defaults = Settings(_env_file=None)

    assert defaults.enable_ai_classification is True
    assert defaults.enable_ai_reconciliation is False


@pytest.mark.asyncio
@pytest.mark.usefixtures("review_path")
async def test_AC_extraction_ai_classification_default_1_new_user_gets_model_proposals(db, test_user, monkeypatch):
    """AC-extraction.ai-classification-default.1: a user with no override reaches the model proposer."""
    from src.config import Settings, settings

    monkeypatch.delenv("ENABLE_AI_CLASSIFICATION", raising=False)
    monkeypatch.setattr(settings, "enable_ai_classification", Settings(_env_file=None).enable_ai_classification)
    assert not test_user.ai_settings, "the new user must carry no settings override"
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    proposer = _stub_proposer(
        {txn.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)}
    )

    outcomes = await classify_transactions(
        db, test_user.id, [txn], policy=_policy(), proposer=proposer, commit_basis=True
    )

    assert [outcome.disposition for outcome in outcomes] == ["applied"]
    assert len(proposer.calls) == 1


def test_AC18_15_8_production_consumers_are_the_declared_seams():
    """AC18.15.8: the classify node's production consumers are EXACTLY the two
    declared seams — the posting path (#1545) and the extraction package root
    (#1546's backfill entry point, published for the router per #1677: routers
    import only src.<pkg>, so the router-facing seam is the root re-export).
    No other module may grow a side-door into classification."""
    src_root = _BACKEND_SRC
    importers = []
    for path in src_root.rglob("*.py"):
        if path == MODULE_PATH:
            continue
        text = path.read_text(encoding="utf-8")
        if "transaction_classification" not in text:
            continue
        tree = ast.parse(text)
        rel_path = path.relative_to(_BACKEND_SRC.parent).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "transaction_classification" in node.module:
                importers.append(rel_path)
            elif isinstance(node, ast.Import) and any("transaction_classification" in a.name for a in node.names):
                importers.append(rel_path)
    assert sorted(importers) == [
        "src/extraction/__init__.py",
        "src/extraction/extension/statement_posting.py",
    ]


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
    from src.extraction.extension import transaction_classification as tc

    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    txns = [
        AtomicTransactionFactory.build(user_id=None, description="ACME PAYROLL"),
        AtomicTransactionFactory.build(user_id=None, description="???"),
    ]
    content = json.dumps(
        [
            {"index": 0, "category": "SALARY", "confidence": 250, "reason": "payroll"},  # clamped to 100
            "not-a-dict",  # -> None
        ]
    )
    monkeypatch.setattr(tc, "stream_ai_json", lambda **kw: _fake_stream(content), raising=False)
    monkeypatch.setattr("src.llm.stream_ai_json", lambda **kw: _fake_stream(content))

    proposals = await tc.propose_categories(txns, policy_for(date.today()))

    assert proposals[0] is not None
    assert proposals[0].category == "SALARY"
    assert proposals[0].confidence == 100  # clamped by code
    assert proposals[1] is None


@pytest.mark.asyncio
async def test_AC18_15_3_proposer_fails_safe_to_none(monkeypatch):
    """AC18.15.3: malformed model output or a missing key degrades to None per txn."""
    from src.config import settings
    from src.extraction.extension import transaction_classification as tc

    txns = [AtomicTransactionFactory.build(user_id=None, description="X")]

    # no API key -> no call, all None
    monkeypatch.setattr(settings, "ai_api_key", "")
    assert await tc.propose_categories(txns, policy_for(date.today())) == [None]

    # malformed JSON -> graceful None fallback
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    monkeypatch.setattr("src.llm.stream_ai_json", lambda **kw: _fake_stream("{nope"))
    assert await tc.propose_categories(txns, policy_for(date.today())) == [None]


@pytest.mark.asyncio
@pytest.mark.usefixtures("review_path")
async def test_AC18_15_2_committed_rerun_is_idempotent_not_integrityerror(db, test_user, enabled_flag):
    """AC18.15.2: re-running the pass under the SAME policy is idempotent — the
    existing classification is kept (no duplicate (txn, policy-rule) row, no
    IntegrityError), because classification is a recomputable pass, not a one-shot."""
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    proposer = _stub_proposer(
        {txn.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)}
    )
    policy = _policy()

    asked: list[int] = []

    async def counting_proposer(transactions, policy_):
        asked.append(len(transactions))
        return await proposer(transactions, policy_)

    first = await classify_transactions(
        db, test_user.id, [txn], policy=policy, proposer=counting_proposer, commit_basis=True
    )
    second = await classify_transactions(
        db, test_user.id, [txn], policy=policy, proposer=counting_proposer, commit_basis=True
    )

    assert first[0].disposition == "applied"
    assert second[0].disposition == "already_classified"  # the row stays, and the model is not asked again (#2405)
    assert asked == [1]
    rows = (
        (await db.execute(select(TransactionClassification).where(TransactionClassification.atomic_txn_id == txn.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1  # kept, not duplicated


# --- AC18.15.3 (staging observe fix): fenced/prose-wrapped model arrays are recovered ---


@pytest.mark.asyncio
async def test_AC18_15_3_proposer_recovers_fenced_or_prose_wrapped_arrays(monkeypatch):
    """AC18.15.3: models wrap JSON in markdown fences or prose (seen live on
    staging: json.loads failed at char 0 => every txn degraded to no_proposal).
    The boundary recovers the balanced top-level array instead of giving up."""
    from src.config import settings
    from src.extraction.extension import transaction_classification as tc

    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    txns = [AtomicTransactionFactory.build(user_id=None, description="ACME PAYROLL")]
    policy = policy_for(date.today())

    fenced = '```json\n[{"index": 0, "category": "SALARY", "confidence": 90, "reason": "payroll"}]\n```'
    prose = (
        'Sure! Here is the classification:\n[{"index": 0, "category": "SALARY", "confidence": 88}]\nHope that helps.'
    )
    for content in (fenced, prose):
        monkeypatch.setattr("src.llm.stream_ai_json", lambda **kw: _fake_stream(content))
        proposals = await tc.propose_categories(txns, policy)
        assert proposals[0] is not None, content
        assert proposals[0].category == "SALARY"

    # empty response stays a graceful per-txn None (distinct from a parse failure)
    monkeypatch.setattr("src.llm.stream_ai_json", lambda **kw: _fake_stream(""))
    assert await tc.propose_categories(txns, policy) == [None]


@pytest.mark.asyncio
async def test_AC18_15_3_prompt_forbids_markdown_fences(monkeypatch):
    """AC18.15.3: the ACTUAL prompt sent to the model carries the no-fence
    instruction the statement prompts use, so recovery is the fallback, not the
    norm. Asserted on the captured request, not on module source (CR #1560)."""
    from src.config import settings
    from src.extraction.extension import transaction_classification as tc

    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    captured: dict = {}

    def capture_stream(**kwargs):
        captured["messages"] = kwargs["messages"]
        return _fake_stream("[]")

    monkeypatch.setattr("src.llm.stream_ai_json", capture_stream)
    txns = [AtomicTransactionFactory.build(user_id=None, description="ACME PAYROLL")]
    await tc.propose_categories(txns, policy_for(date.today()))

    prompt = captured["messages"][0]["content"]
    assert "Do NOT wrap it in markdown or code fences" in prompt
    assert "ONLY the raw JSON array" in prompt


# --- AC18.17 (#1546 Cleanup): governance locks -----------------------------------


def test_AC18_17_1_no_classify_writer_is_defined_but_uninvoked():
    """AC-extraction.1817.1: AC18.17.1: every classification writer has a production call site — the
    #1279 'closed-but-not-wired' failure mode (orphaned scaffolding) can never
    recur silently. This is the lock that caught backfill_classifications."""
    # Entry seams must be invoked from production code OUTSIDE the module; the
    # core pass (classify_transactions) must be invoked by those live seams.
    # Alias-aware (CR #1572): a seam imported as `... import X as Y` counts via Y,
    # and attribute calls count only through an import of THIS module — unrelated
    # same-named attributes elsewhere do not satisfy the gate.
    seam_module = "src.extraction.extension.transaction_classification"
    # The package root re-exports the router-facing seam (#1677: routers import
    # only src.<pkg>), so a root import is the same seam, not a side-door.
    seam_import_paths = (seam_module, "src.extraction")
    entry_seams = ("classify_by_effective_policy", "backfill_classifications")

    def seam_calls(tree: ast.AST) -> set[str]:
        alias_to_seam: dict[str, str] = {}
        module_aliases: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in seam_import_paths:
                for alias in node.names:
                    if alias.name in entry_seams:
                        alias_to_seam[alias.asname or alias.name] = alias.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == seam_module:
                        module_aliases.add((alias.asname or alias.name).split(".")[0])
        called: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in alias_to_seam:
                called.add(alias_to_seam[fn.id])
            elif (
                isinstance(fn, ast.Attribute)
                and fn.attr in entry_seams
                and isinstance(fn.value, ast.Name)
                and fn.value.id in module_aliases
            ):
                called.add(fn.attr)
        return called

    external_calls: set[str] = set()
    for path in _BACKEND_SRC.rglob("*.py"):
        if path == MODULE_PATH:
            continue
        text = path.read_text(encoding="utf-8")
        if not any(seam in text for seam in entry_seams):
            continue
        external_calls |= seam_calls(ast.parse(text))
    orphaned = [w for w in entry_seams if w not in external_calls]
    assert not orphaned, f"classify entry seam(s) defined but never invoked in production: {orphaned}"

    module_src = MODULE_PATH.read_text(encoding="utf-8")
    module_calls = {
        node.func.id
        for node in ast.walk(ast.parse(module_src))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "classify_transactions" in module_calls, "the core pass is not wired to any live entry seam"


def test_AC18_17_3_reports_read_only_applied_classifications():
    """AC-extraction.1817.3: AC18.17.3: reports consume exactly ONE classification source and only
    APPLIED rows — the DRAFT review band never leaks into as-reported figures."""
    src = (_BACKEND_SRC / "reporting" / "extension" / "income_statement.py").read_text(encoding="utf-8")
    assert "ClassificationStatus.APPLIED" in src
    assert "ClassificationStatus.DRAFT" not in src and "ClassificationStatus.SUPERSEDED" not in src


# --- AC-extraction.non-pnl-categories: the model can name a movement that is not income or expense (#2411) ---

NON_PNL_NAMES = ("TRANSFER", "CARD_REPAYMENT", "LOAN_PRINCIPAL", "INVESTMENT_TRADE")


def _pnl_account_names(accounts) -> set[str]:
    return {name for name in accounts if name.startswith(("Income - ", "Expense - "))}


@pytest.mark.asyncio
@pytest.mark.parametrize("category", NON_PNL_NAMES)
@pytest.mark.usefixtures("review_path")
async def test_AC_extraction_non_pnl_categories_1_balance_sheet_class_is_never_applied(
    db, test_user, enabled_flag, category
):
    """AC-extraction.non-pnl-categories.1: a balance-sheet class never becomes profit or loss, at any confidence."""
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="MOVEMENT BETWEEN PRODUCTS")
    proposer = _stub_proposer({txn.description: CategoryProposal(category=category, confidence=99)})

    outcomes = await classify_transactions(
        db, test_user.id, [txn], policy=policy_for(date(2026, 6, 1)), proposer=proposer, commit_basis=True
    )

    assert [outcome.disposition for outcome in outcomes] == ["non_pnl"]
    assert outcomes[0].category == category
    # Posting reads applied rows only. The draft row has no account and records what the AI named.
    rows = list((await db.execute(select(TransactionClassification))).scalars())
    assert [(row.status, row.account_id, (row.tags or {}).get("category")) for row in rows] == [
        (ClassificationStatus.DRAFT, None, category)
    ]
    names = set((await db.execute(select(Account.name).where(Account.user_id == test_user.id))).scalars())
    assert _pnl_account_names(names) == set(), "a balance-sheet class must not create an income or expense account"


@pytest.mark.asyncio
@pytest.mark.parametrize("category", ("OTHER_INCOME", "OTHER_EXPENSE"))
@pytest.mark.usefixtures("review_path")
async def test_AC_extraction_non_pnl_categories_2_other_buckets_never_auto_apply(db, test_user, enabled_flag, category):
    """AC-extraction.non-pnl-categories.2: 'Other' means 'does not fit', so it always waits for a person."""
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="UNCLEAR PAYMENT")
    proposer = _stub_proposer({txn.description: CategoryProposal(category=category, confidence=99)})

    outcomes = await classify_transactions(
        db, test_user.id, [txn], policy=policy_for(date(2026, 6, 1)), proposer=proposer, commit_basis=True
    )

    assert [outcome.disposition for outcome in outcomes] == ["review"]
    rows = list((await db.execute(select(TransactionClassification))).scalars())
    assert [row.status for row in rows] == [ClassificationStatus.DRAFT]


def test_AC_extraction_non_pnl_categories_3_policy_v1_stays_frozen_and_v2_adds_the_four_classes():
    """AC-extraction.non-pnl-categories.3: a taxonomy change is a new policy version, never an edit."""
    from src.extraction.extension.transaction_classification import POLICY_VERSIONS

    by_version = {policy.version: policy for policy in POLICY_VERSIONS}
    assert set(by_version) == {1, 2}
    assert len(by_version[1].catalog) == 18
    assert not {c.value for c in by_version[1].catalog} & set(NON_PNL_NAMES)
    assert {c.value for c in by_version[2].catalog} >= set(NON_PNL_NAMES)
    assert set(by_version[2].catalog) == set(TransactionCategory)
    # v2 applies to every date, so a statement of any period can use the new classes.
    for as_of in (date.min, date(2019, 1, 1), date(2026, 3, 1)):
        assert policy_for(as_of).version == 2


@pytest.mark.asyncio
async def test_AC_extraction_non_pnl_categories_4_prompt_names_the_new_classes(monkeypatch):
    """AC-extraction.non-pnl-categories.4: the model sees the four classes and when to use each."""
    import src.llm
    from src.extraction.extension.transaction_classification import propose_categories

    seen: list[str] = []

    async def fake_stream(messages, model, **_kwargs):
        seen.append(messages[0]["content"])
        yield json.dumps([{"index": 0, "category": "TRANSFER", "confidence": 90, "reason": "own account"}])

    monkeypatch.setattr(src.llm, "stream_ai_json", fake_stream)
    txn = AtomicTransactionFactory.build(description="Funds transfer between own accounts")

    proposals = await propose_categories([txn], policy_for(date(2026, 6, 1)))

    assert [p.category for p in proposals if p] == ["TRANSFER"]
    prompt = seen[0]
    for name in NON_PNL_NAMES:
        assert name in prompt
    assert "between the user's own accounts" in prompt
    assert "OTHER_INCOME or OTHER_EXPENSE only" in prompt


@pytest.mark.asyncio
@pytest.mark.usefixtures("review_path")
async def test_AC_extraction_accept_ai_suggestions_4_reader_returns_the_latest_classification_per_transaction(
    db, test_user, enabled_flag
):
    """AC-extraction.accept-ai-suggestions.4: the reader sees applied and draft rows and skips untagged rows."""
    from src.extraction.extension.transaction_classification import classification_suggestions

    txn_draft = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="DRAFT ROW")
    txn_applied = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="APPLIED ROW")
    txn_untagged = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="UNTAGGED ROW")
    proposer = _stub_proposer(
        {
            txn_draft.description: CategoryProposal(category="DINING", confidence=75),
            txn_applied.description: CategoryProposal(category="GROCERIES", confidence=95),
        }
    )
    await classify_transactions(
        db,
        test_user.id,
        [txn_draft, txn_applied],
        policy=policy_for(date(2026, 6, 1)),
        proposer=proposer,
        commit_basis=True,
    )
    rule = (await db.execute(select(ClassificationRule))).scalars().first()
    db.add(
        TransactionClassification(
            atomic_txn_id=txn_untagged.id,
            rule_version_id=rule.id,
            account_id=None,
            tags={"reason": "no category"},
            confidence_score=70,
            status=ClassificationStatus.DRAFT,
        )
    )
    await db.flush()

    found = await classification_suggestions(db, [txn_draft.id, txn_applied.id, txn_untagged.id])

    assert set(found) == {txn_draft.id, txn_applied.id}
    draft = found[txn_draft.id]
    assert (draft.category, draft.confidence, draft.applied, draft.non_pnl) == ("DINING", 75, False, False)
    assert draft.account_id is not None
    applied = found[txn_applied.id]
    assert (applied.category, applied.confidence, applied.applied) == ("GROCERIES", 95, True)
    assert await classification_suggestions(db, []) == {}
