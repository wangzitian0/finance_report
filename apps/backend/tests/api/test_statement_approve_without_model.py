"""Approve of a statement whose rows have no model answer (#2994, slice S3 precondition tests)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from src.config import settings
from src.extraction import BankStatementStatus, RuleType, StatementSummary, TransactionDirection
from src.extraction.extension import transaction_classification
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.ledger import Account, AccountType, JournalEntry
from tests.factories import seed_parsed_statement
from tests.statement_ingestion import classify_statement

ROWS = [
    {
        "description": "Salary Jan",
        "amount": Decimal("2500.00"),
        "direction": TransactionDirection.IN,
        "date": date(2026, 1, 5),
    },
    {
        "description": "Coffee Jan",
        "amount": Decimal("12.50"),
        "direction": TransactionDirection.OUT,
        "date": date(2026, 1, 6),
    },
]


class ForbiddenProposer:
    calls = 0

    async def __call__(self, transactions, _policy):
        self.calls += 1
        raise AssertionError("the model was asked")


@pytest.fixture
def model_off(monkeypatch):
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    proposer = ForbiddenProposer()
    monkeypatch.setattr(transaction_classification, "propose_categories", proposer)
    return proposer


async def _seed(db, user):
    seeded = await seed_parsed_statement(
        db,
        user.id,
        institution="DBS",
        original_filename="precondition.pdf",
        opening_balance=Decimal("1000.00"),
        transactions=ROWS,
    )
    seeded.statement.period_start, seeded.statement.period_end = ROWS[0]["date"], ROWS[-1]["date"]
    await db.commit()
    return seeded


async def _count(db, model) -> int:
    return int(await db.scalar(select(func.count()).select_from(model)) or 0)


async def test_AC_extraction_2994_100_approve_of_rows_without_an_answer_goes_to_economic_review(
    client, db, test_user, model_off
):
    seeded = await _seed(db, test_user)
    resp = await client.post(f"/statements/{seeded.id}/approvals", json={"create_account_if_missing": True})
    refreshed = await db.scalar(
        select(StatementSummary).where(StatementSummary.id == seeded.id).execution_options(populate_existing=True)
    )
    assert resp.status_code == 409 and resp.json()["detail"].startswith("Economic review required:")
    assert (
        model_off.calls,
        await _count(db, JournalEntry),
        await _count(db, TransactionClassification),
        refreshed.status,
    ) == (0, 0, 0, BankStatementStatus.PARSED)


async def test_AC_extraction_2994_100_the_classify_run_applies_the_keyword_rules_and_approve_posts_them_without_a_model_call(
    client, db, test_user, model_off
):
    seeded = await _seed(db, test_user)
    exp = Account(user_id=test_user.id, name="Expense - Reviewed", type=AccountType.EXPENSE, currency="SGD")
    inc = Account(user_id=test_user.id, name="Income - Reviewed", type=AccountType.INCOME, currency="SGD")
    db.add_all([exp, inc])
    await db.flush()
    db.add_all(
        [
            ClassificationRule(
                user_id=test_user.id,
                created_by=test_user.id,
                version_number=1,
                effective_date=date(2020, 1, 1),
                is_active=True,
                rule_name=f"{name} rule",
                rule_type=RuleType.KEYWORD_MATCH,
                rule_config={"keywords": [kw]},
                tag_mappings={"category": name.upper()},
                default_account_id=target.id,
            )
            for name, kw, target in (("expense", "Coffee", exp), ("income", "Salary", inc))
        ]
    )
    await db.commit()

    before = await client.post(f"/statements/{seeded.id}/approvals", json={"create_account_if_missing": True})
    await classify_statement(db, seeded.id)
    after = await client.post(f"/statements/{seeded.id}/approvals", json={"create_account_if_missing": True})
    assert before.status_code == 409 and before.json()["detail"].startswith("Economic review required:")
    assert after.status_code == 200 and (
        after.json()["journal_entries_created"],
        model_off.calls,
        await _count(db, TransactionClassification),
    ) == (len(ROWS), 0, len(ROWS))
