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
from src.llm import ModelCallFailed, ModelFailureKind
from tests._support.fake_llm import install_fake_model
from tests.extraction._statement_run_helpers import (
    _count,
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


def test_AC18_15_1_policy_is_effective_dated_and_immutable_and_static_boundaries():
    v1, v2 = _policy(version=1, effective_from=date(2020, 1, 1)), _policy(version=2, effective_from=date(2026, 7, 1))
    assert (
        policy_for(date(2026, 6, 30), registry=(v1, v2)),
        policy_for(date(2026, 7, 1), registry=(v1, v2)),
        policy_for(date(2030, 1, 1), registry=(v1, v2)),
    ) == (v1, v2, v2)
    with pytest.raises(Exception):
        v1.auto_apply_threshold = 50
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
    verify_no_classify_writer_uninvoked(_BACKEND_SRC, MODULE_PATH)
    inc_src = (_BACKEND_SRC / "reporting" / "extension" / "income_statement.py").read_text(encoding="utf-8")
    assert (
        "ClassificationStatus.APPLIED" in inc_src
        and "ClassificationStatus.DRAFT" not in inc_src
        and "ClassificationStatus.SUPERSEDED" not in inc_src
        and policy_for(date.today()).version >= 1
    )
    assert (
        [p.version for p in POLICY_VERSIONS] == [2]
        and set(POLICY_VERSIONS[0].catalog) == set(TransactionCategory)
        and {c.value for c in POLICY_VERSIONS[0].catalog} >= set(NON_PNL_NAMES)
    )
    assert all(policy_for(as_of).version == 2 for as_of in (date.min, date(2019, 1, 1), date(2026, 3, 1)))


async def test_AC18_15_5_model_never_touches_money(db, test_user, enabled_flag):
    imported = {
        alias.name
        for node in ast.walk(ast.parse(MODULE_PATH.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert not ({"amount", "value", "total", "price"} & set(CategoryProposal.model_fields)) and not (
        {"JournalEntry", "JournalLine"} & imported
    )
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
async def test_AC18_15_2_7_8_rule_prepass_flag_off_and_idempotent_rerun(db, test_user, monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    unruled = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    proposer = _stub_proposer(
        {
            unruled.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95),
            "COFFEE SHOP": CategoryProposal(category=TransactionCategory.DINING.value, confidence=95),
        }
    )
    asked: list[int] = []

    async def counting(transactions, policy_):
        asked.append(len(transactions))
        return await proposer(transactions, policy_)

    first = await classify_transactions(db, test_user.id, [unruled], policy=_policy(), proposer=counting)
    second = await classify_transactions(db, test_user.id, [unruled], policy=_policy(), proposer=counting)
    rows = (
        (
            await db.execute(
                select(TransactionClassification).where(TransactionClassification.atomic_txn_id == unruled.id)
            )
        )
        .scalars()
        .all()
    )
    assert (first[0].disposition, second[0].disposition, asked, len(rows)) == ("applied", "already_classified", [1], 1)

    proposer.calls.clear()
    db.add(_rule(test_user.id, name="reviewed-coffee-rule", category="DINING"))
    await db.flush()
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    ruled, unmatched = (
        await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="COFFEE SHOP"),
        await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="OTHER SHOP"),
    )
    by_off = {
        o.atomic_txn_id: o
        for o in await classify_transactions(db, test_user.id, [ruled, unmatched], policy=_policy(), proposer=proposer)
    }
    assert (
        by_off[ruled.id].disposition,
        by_off[unmatched.id].disposition,
        proposer.calls,
        await _count(db, TransactionClassification),
    ) == ("rule", "no_proposal", [], 2)


@pytest.mark.usefixtures("review_path")
async def test_AC_extraction_ai_classification_default_1_new_user_gets_model_proposals(db, test_user, monkeypatch):
    monkeypatch.delenv("ENABLE_AI_CLASSIFICATION", raising=False)
    monkeypatch.delenv("ENABLE_AI_RECONCILIATION", raising=False)
    defaults = Settings(_env_file=None)
    monkeypatch.setattr(settings, "enable_ai_classification", defaults.enable_ai_classification)
    assert (
        defaults.enable_ai_classification is True
        and defaults.enable_ai_reconciliation is True
        and not test_user.ai_settings
    )
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="ACME PAYROLL")
    p2 = _stub_proposer({txn.description: CategoryProposal(category=TransactionCategory.SALARY.value, confidence=95)})
    assert [
        o.disposition for o in await classify_transactions(db, test_user.id, [txn], policy=_policy(), proposer=p2)
    ] == ["applied"] and len(p2.calls) == 1


async def test_AC18_15_3_proposer_parsing_clamping_recovery_and_non_pnl_prompts(monkeypatch):
    cases = [
        (
            "test-key",
            json.dumps([{"index": 0, "category": "SALARY", "confidence": 250, "reason": "payroll"}, {"index": 1}]),
            [("SALARY", 100), None],
        ),
        ("", "[]", [None]),
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
    ]
    for api_key, raw, expected in cases:
        monkeypatch.setattr(settings, "ai_api_key", api_key)
        install_fake_model(monkeypatch, raw)
        txns = [
            AtomicTransactionFactory.build(user_id=None, description=d)
            for d in (["ACME PAYROLL", "???"] if len(expected) == 2 else ["ACME PAYROLL"])
        ]
        assert [
            None if p is None else (p.category, p.confidence)
            for p in await tc.propose_categories(txns, policy_for(date.today()))
        ] == expected

    # A reply that is no JSON array is a failed call (bad_reply), not an abstaining model: an abstaining model gives
    # a list whose items are null or left out, which the cases above show as None.
    for raw in ("{nope", "", '{"index": 0}', "[" + "1" * 5000 + "]"):
        monkeypatch.setattr(settings, "ai_api_key", "test-key")
        install_fake_model(monkeypatch, raw)
        with pytest.raises(ModelCallFailed) as failed:
            await tc.propose_categories(
                [AtomicTransactionFactory.build(user_id=None, description="ACME PAYROLL")], policy_for(date.today())
            )
        assert failed.value.kind is ModelFailureKind.BAD_REPLY, raw

    seen: list[str] = []

    def reply(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps([{"index": 0, "category": "TRANSFER", "confidence": 90, "reason": "own account"}])

    monkeypatch.setattr(settings, "ai_api_key", "test-key")
    install_fake_model(monkeypatch, reply)
    proposals = await propose_categories(
        [AtomicTransactionFactory.build(description="Funds transfer between own accounts")],
        policy_for(date(2026, 6, 1)),
    )
    assert [p.category for p in proposals if p] == ["TRANSFER"] and all(
        s in seen[0]
        for s in (
            *NON_PNL_NAMES,
            "Do NOT wrap it in markdown or code fences",
            "ONLY the raw JSON array",
            "between the user's own accounts",
            "OTHER_INCOME or OTHER_EXPENSE only",
        )
    )


@pytest.mark.parametrize("category", (*NON_PNL_NAMES, "OTHER_INCOME", "OTHER_EXPENSE"))
@pytest.mark.usefixtures("review_path")
async def test_AC_extraction_non_pnl_and_other_categories_stay_draft(db, test_user, enabled_flag, category):
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, description="MOVEMENT BETWEEN PRODUCTS")
    outcomes = await classify_transactions(
        db,
        test_user.id,
        [txn],
        policy=policy_for(date(2026, 6, 1)),
        proposer=_stub_proposer({txn.description: CategoryProposal(category=category, confidence=99)}),
    )
    rows = list((await db.execute(select(TransactionClassification))).scalars())
    if category in NON_PNL_NAMES:
        names = set((await db.execute(select(Account.name).where(Account.user_id == test_user.id))).scalars())
        assert (
            outcomes[0].disposition,
            outcomes[0].category,
            [(r.status, r.account_id, (r.tags or {}).get("category")) for r in rows],
        ) == ("non_pnl", category, [(ClassificationStatus.DRAFT, None, category)]) and not {
            n for n in names if n.startswith(("Income - ", "Expense - "))
        }
    else:
        assert (outcomes[0].disposition, [r.status for r in rows]) == ("review", [ClassificationStatus.DRAFT])


@pytest.mark.usefixtures("review_path")
async def test_AC_extraction_accept_ai_suggestions_4_reader_returns_latest_per_txn(db, test_user, enabled_flag):
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
    assert (
        set(found),
        found[txn_draft.id].account_id is not None,
        found[txn_draft.id].category,
        found[txn_draft.id].confidence,
        found[txn_draft.id].applied,
        found[txn_draft.id].non_pnl,
        found[txn_applied.id].category,
        found[txn_applied.id].confidence,
        found[txn_applied.id].applied,
        await classification_suggestions(db, []),
    ) == ({txn_draft.id, txn_applied.id}, True, "DINING", 75, False, False, "GROCERIES", 95, True, {})
