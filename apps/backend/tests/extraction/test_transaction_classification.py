from __future__ import annotations

import ast
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from src.config import Settings, settings
from src.extraction import ClassificationStatus, RuleType
from src.extraction.extension import transaction_classification as tc
from src.extraction.extension.transaction_classification import (
    POLICY_VERSIONS,
    CategoryProposal,
    TransactionCategory,
    classification_suggestions,
    policy_for,
    propose_categories,
)
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.ledger import Account, AccountType
from tests.extraction._statement_run_helpers import (
    _count,
    fake_stream as _fake_stream,
    make_classification_policy as _policy,
    stub_proposer as _stub_proposer,
    verify_no_classify_writer_uninvoked,
)
from tests.factories import AtomicTransactionFactory
from tests.statement_ingestion import classify_transactions

_BACKEND_SRC = Path(__file__).resolve().parents[2] / "src"
MODULE_PATH = _BACKEND_SRC / "extraction" / "extension" / "transaction_classification.py"
NON_PNL_NAMES = ("TRANSFER", "CARD_REPAYMENT", "LOAN_PRINCIPAL", "INVESTMENT_TRADE")


@pytest.fixture
def enabled_flag(monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)


def _rule(user_id, *, name: str, category: str) -> ClassificationRule:
    return ClassificationRule(
        user_id=user_id,
        created_by=user_id,
        rule_name=name,
        version_number=1,
        effective_date=date(2020, 1, 1),
        is_active=True,
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["coffee"]},
        tag_mappings={"category": category},
    )


def test_AC18_15_1_policy_is_effective_dated_and_immutable():
    v1, v2 = _policy(version=1, effective_from=date(2020, 1, 1)), _policy(version=2, effective_from=date(2026, 7, 1))
    assert (
        policy_for(date(2026, 6, 30), registry=(v1, v2)),
        policy_for(date(2026, 7, 1), registry=(v1, v2)),
        policy_for(date(2030, 1, 1), registry=(v1, v2)),
    ) == (v1, v2, v2)
    with pytest.raises(Exception):
        v1.auto_apply_threshold = 50
    assert policy_for(date.today()).version >= 1
    importers = sorted(
        p.relative_to(_BACKEND_SRC.parent).as_posix()
        for p in _BACKEND_SRC.rglob("*.py")
        if p != MODULE_PATH and "transaction_classification" in (txt := p.read_text(encoding="utf-8"))
        for n in ast.walk(ast.parse(txt))
        if (isinstance(n, ast.ImportFrom) and n.module and "transaction_classification" in n.module)
        or (isinstance(n, ast.Import) and any("transaction_classification" in a.name for a in n.names))
    )
    assert importers == [
        "src/extraction/__init__.py",
        "src/extraction/extension/correction_service.py",
        "src/extraction/extension/statement_classification_run.py",
        "src/extraction/extension/statement_posting.py",
    ]


@pytest.mark.skip(
    reason="flaky under xdist: DB state pollution from co-scheduled tests; passes sequentially. See #3028 test isolation gap."
)
async def test_AC18_15_3_off_catalog_proposal_is_rejected_never_applied(db, test_user, enabled_flag):
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="MYSTERY MERCHANT")
    outcomes = await classify_transactions(
        db,
        test_user.id,
        [txn],
        policy=_policy(),
        proposer=_stub_proposer({txn.description: CategoryProposal(category="CRYPTO_YOLO", confidence=99)}),
    )
    assert outcomes[0].disposition == "off_catalog" and await _count(db, TransactionClassification) == 0


@pytest.mark.usefixtures("review_path")
@pytest.mark.skip(
    reason="flaky under xdist: DB state pollution from co-scheduled tests; passes sequentially. See #3028 test isolation gap."
)
async def test_AC18_15_4_confidence_gate_applies_reviews_or_tails(db, test_user, enabled_flag):
    high, mid, low = [
        await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description=d)
        for d in ("ACME PAYROLL", "NTUC FAIRPRICE", "???")
    ]
    proposer = _stub_proposer(
        {
            high.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=92),
            mid.description: CategoryProposal(category=TransactionCategory.GROCERIES.value, confidence=70),
            low.description: CategoryProposal(category=TransactionCategory.OTHER_EXPENSE.value, confidence=30),
        }
    )
    outcomes = await classify_transactions(db, test_user.id, [high, mid, low], policy=_policy(), proposer=proposer)
    by_txn = {o.atomic_txn_id: o for o in outcomes}
    assert (by_txn[high.id].disposition, by_txn[mid.id].disposition, by_txn[low.id].disposition) == (
        "applied",
        "review",
        "tail",
    )
    by_status = {r.atomic_txn_id: r for r in (await db.execute(select(TransactionClassification))).scalars().all()}
    assert set(by_status) == {high.id, mid.id}
    assert (by_status[high.id].status, by_status[high.id].confidence_score) == (ClassificationStatus.APPLIED, 92)
    assert (
        await db.execute(select(Account).where(Account.id == by_status[high.id].account_id))
    ).scalar_one().type == AccountType.INCOME
    assert (
        by_status[mid.id].status == ClassificationStatus.DRAFT
        and by_status[mid.id].confidence_score is not None
        and 60 <= by_status[mid.id].confidence_score < 85
    )


async def test_AC18_15_5_model_never_touches_money(db, test_user, enabled_flag):
    assert not {"amount", "value", "total", "price"} & set(CategoryProposal.model_fields)
    imported = {
        alias.name
        for node in ast.walk(ast.parse(MODULE_PATH.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert not {"JournalEntry", "JournalLine"} & imported
    txn = await AtomicTransactionFactory.create_async(
        db, user_id=test_user.id, description="ACME PAYROLL", amount=Decimal("1234.56")
    )
    await classify_transactions(
        db,
        test_user.id,
        [txn],
        policy=_policy(),
        proposer=_stub_proposer(
            {txn.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)}
        ),
    )
    await db.refresh(txn)
    assert txn.amount == Decimal("1234.56") and isinstance(txn.amount, Decimal)


@pytest.mark.usefixtures("review_path")
async def test_AC18_15_7_user_rule_prepass_wins_over_model_and_noop_without_rules(db, test_user, enabled_flag):
    unruled = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    proposer = _stub_proposer(
        {
            "COFFEE SHOP": CategoryProposal(category=TransactionCategory.DINING.value, confidence=95),
            unruled.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95),
        }
    )
    assert (await classify_transactions(db, test_user.id, [unruled], policy=_policy(), proposer=proposer))[
        0
    ].disposition == "applied"
    db.add(_rule(test_user.id, name="my-coffee-rule", category="user-coffee"))
    await db.flush()
    ruled = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="COFFEE SHOP")
    outcomes = await classify_transactions(db, test_user.id, [ruled, unruled], policy=_policy(), proposer=proposer)
    by_txn = {o.atomic_txn_id: o for o in outcomes}
    assert (by_txn[ruled.id].disposition, by_txn[unruled.id].disposition) == ("rule", "already_classified")


async def test_AC18_15_8_flag_off_skips_llm_not_deterministic_rules(db, test_user, monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    db.add(_rule(test_user.id, name="reviewed-coffee-rule", category="DINING"))
    await db.flush()
    ruled, unmatched = (
        await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="COFFEE SHOP"),
        await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL"),
    )
    proposer = _stub_proposer(
        {unmatched.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)}
    )
    by_txn = {
        o.atomic_txn_id: o
        for o in await classify_transactions(db, test_user.id, [ruled, unmatched], policy=_policy(), proposer=proposer)
    }
    assert (
        by_txn[ruled.id].disposition,
        by_txn[unmatched.id].disposition,
        proposer.calls,
        await _count(db, TransactionClassification),
    ) == ("rule", "no_proposal", [], 1)


def test_AC_extraction_ai_classification_default_1_code_default_is_on(monkeypatch):
    monkeypatch.delenv("ENABLE_AI_CLASSIFICATION", raising=False)
    monkeypatch.delenv("ENABLE_AI_RECONCILIATION", raising=False)
    defaults = Settings(_env_file=None)
    assert defaults.enable_ai_classification is True and defaults.enable_ai_reconciliation is True


@pytest.mark.usefixtures("review_path")
async def test_AC_extraction_ai_classification_default_1_new_user_gets_model_proposals(db, test_user, monkeypatch):
    monkeypatch.delenv("ENABLE_AI_CLASSIFICATION", raising=False)
    monkeypatch.setattr(settings, "enable_ai_classification", Settings(_env_file=None).enable_ai_classification)
    assert not test_user.ai_settings
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    proposer = _stub_proposer(
        {txn.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)}
    )
    assert [
        o.disposition for o in await classify_transactions(db, test_user.id, [txn], policy=_policy(), proposer=proposer)
    ] == ["applied"] and len(proposer.calls) == 1


@pytest.mark.parametrize(
    ("api_key", "raw", "expected"),
    [
        (
            "test-key",
            json.dumps([{"index": 0, "category": "SALARY", "confidence": 250, "reason": "payroll"}, {"index": 1}]),
            [("SALARY", 100), None],
        ),
        ("", "[]", [None]),
        ("test-key", "{nope", [None]),
        ("test-key", "", [None]),
        (
            "test-key",
            '```json\n[{"index": 0, "category": "SALARY", "confidence": 90, "reason": "payroll"}]\n```',
            [("SALARY", 90)],
        ),
        (
            "test-key",
            'Sure! Here is the classification:\n[{"index": 0, "category": "SALARY", "confidence": 88}]\nHope that helps.',
            [("SALARY", 88)],
        ),
    ],
)
async def test_AC18_15_3_proposer_parsing_clamping_recovery_and_fail_safe(monkeypatch, api_key, raw, expected):
    monkeypatch.setattr(settings, "ai_api_key", api_key)
    monkeypatch.setattr("src.llm.stream_ai_json", lambda **_kw: _fake_stream(raw))
    txns = [
        AtomicTransactionFactory.build(user_id=None, description=d)
        for d in (["ACME PAYROLL", "???"] if len(expected) == 2 else ["ACME PAYROLL"])
    ]
    proposals = await tc.propose_categories(txns, policy_for(date.today()))
    assert [None if p is None else (p.category, p.confidence) for p in proposals] == expected


async def test_AC18_15_3_prompt_forbids_markdown_fences(monkeypatch):
    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    captured: dict = {}
    monkeypatch.setattr(
        "src.llm.stream_ai_json", lambda **kw: (captured.update(messages=kw["messages"]), _fake_stream("[]"))[1]
    )
    await tc.propose_categories(
        [AtomicTransactionFactory.build(user_id=None, description="ACME PAYROLL")], policy_for(date.today())
    )
    prompt = captured["messages"][0]["content"]
    assert "Do NOT wrap it in markdown or code fences" in prompt and "ONLY the raw JSON array" in prompt


@pytest.mark.usefixtures("review_path")
async def test_AC18_15_2_committed_rerun_is_idempotent_not_integrityerror(db, test_user, enabled_flag):
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    proposer = _stub_proposer(
        {txn.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)}
    )
    asked: list[int] = []

    async def counting(transactions, policy_):
        asked.append(len(transactions))
        return await proposer(transactions, policy_)

    first, second = (
        await classify_transactions(db, test_user.id, [txn], policy=_policy(), proposer=counting),
        await classify_transactions(db, test_user.id, [txn], policy=_policy(), proposer=counting),
    )
    rows = (
        (await db.execute(select(TransactionClassification).where(TransactionClassification.atomic_txn_id == txn.id)))
        .scalars()
        .all()
    )
    assert (first[0].disposition, second[0].disposition, asked, len(rows)) == ("applied", "already_classified", [1], 1)


def test_AC18_17_1_no_classify_writer_is_defined_but_uninvoked():
    verify_no_classify_writer_uninvoked(_BACKEND_SRC, MODULE_PATH)


def test_AC18_17_3_reports_read_only_applied_classifications():
    src = (_BACKEND_SRC / "reporting" / "extension" / "income_statement.py").read_text(encoding="utf-8")
    assert (
        "ClassificationStatus.APPLIED" in src
        and "ClassificationStatus.DRAFT" not in src
        and "ClassificationStatus.SUPERSEDED" not in src
    )


@pytest.mark.parametrize("category", NON_PNL_NAMES)
@pytest.mark.usefixtures("review_path")
async def test_AC_extraction_non_pnl_categories_1_balance_sheet_class_is_never_applied(
    db, test_user, enabled_flag, category
):
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="MOVEMENT BETWEEN PRODUCTS")
    outcomes = await classify_transactions(
        db,
        test_user.id,
        [txn],
        policy=policy_for(date(2026, 6, 1)),
        proposer=_stub_proposer({txn.description: CategoryProposal(category=category, confidence=99)}),
    )
    rows = list((await db.execute(select(TransactionClassification))).scalars())
    names = set((await db.execute(select(Account.name).where(Account.user_id == test_user.id))).scalars())
    assert (outcomes[0].disposition, outcomes[0].category) == ("non_pnl", category)
    assert [(r.status, r.account_id, (r.tags or {}).get("category")) for r in rows] == [
        (ClassificationStatus.DRAFT, None, category)
    ]
    assert not {n for n in names if n.startswith(("Income - ", "Expense - "))}


@pytest.mark.parametrize("category", ("OTHER_INCOME", "OTHER_EXPENSE"))
@pytest.mark.usefixtures("review_path")
async def test_AC_extraction_non_pnl_categories_2_other_buckets_never_auto_apply(db, test_user, enabled_flag, category):
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="UNCLEAR PAYMENT")
    outcomes = await classify_transactions(
        db,
        test_user.id,
        [txn],
        policy=policy_for(date(2026, 6, 1)),
        proposer=_stub_proposer({txn.description: CategoryProposal(category=category, confidence=99)}),
    )
    assert outcomes[0].disposition == "review" and [
        r.status for r in (await db.execute(select(TransactionClassification))).scalars()
    ] == [ClassificationStatus.DRAFT]


def test_AC_extraction_non_pnl_categories_3_the_live_policy_holds_the_four_classes():
    assert [p.version for p in POLICY_VERSIONS] == [2] and set(POLICY_VERSIONS[0].catalog) == set(TransactionCategory)
    assert {c.value for c in POLICY_VERSIONS[0].catalog} >= set(NON_PNL_NAMES)
    assert all(policy_for(as_of).version == 2 for as_of in (date.min, date(2019, 1, 1), date(2026, 3, 1)))


async def test_AC_extraction_non_pnl_categories_4_prompt_names_the_new_classes(monkeypatch):
    seen: list[str] = []

    async def fake_stream(messages, model, **_kwargs):
        seen.append(messages[0]["content"])
        yield json.dumps([{"index": 0, "category": "TRANSFER", "confidence": 90, "reason": "own account"}])

    monkeypatch.setattr("src.llm.stream_ai_json", fake_stream)
    proposals = await propose_categories(
        [AtomicTransactionFactory.build(description="Funds transfer between own accounts")],
        policy_for(date(2026, 6, 1)),
    )
    assert [p.category for p in proposals if p] == ["TRANSFER"]
    assert (
        all(name in seen[0] for name in NON_PNL_NAMES)
        and "between the user's own accounts" in seen[0]
        and "OTHER_INCOME or OTHER_EXPENSE only" in seen[0]
    )


@pytest.mark.usefixtures("review_path")
async def test_AC_extraction_accept_ai_suggestions_4_reader_returns_the_latest_classification_per_transaction(
    db, test_user, enabled_flag
):
    txn_draft, txn_applied, txn_untagged = [
        await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description=d)
        for d in ("DRAFT ROW", "APPLIED ROW", "UNTAGGED ROW")
    ]
    await classify_transactions(
        db,
        test_user.id,
        [txn_draft, txn_applied],
        policy=policy_for(date(2026, 6, 1)),
        proposer=_stub_proposer(
            {
                txn_draft.description: CategoryProposal(category="DINING", confidence=75),
                txn_applied.description: CategoryProposal(category="GROCERIES", confidence=95),
            }
        ),
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
    assert set(found) == {txn_draft.id, txn_applied.id} and found[txn_draft.id].account_id is not None
    assert (
        found[txn_draft.id].category,
        found[txn_draft.id].confidence,
        found[txn_draft.id].applied,
        found[txn_draft.id].non_pnl,
    ) == ("DINING", 75, False, False)
    assert (found[txn_applied.id].category, found[txn_applied.id].confidence, found[txn_applied.id].applied) == (
        "GROCERIES",
        95,
        True,
    )
    assert await classification_suggestions(db, []) == {}
