"""Approve of a statement whose rows have no model answer (#2994, slice S3 precondition tests).

The first test passed on main before the change (the approve then called the classification): a row without an
answer ends in the "Economic review required" 409. The second test posted a keyword-rule row at the approve
on main. Slice S3 moves the keyword rule step from the approve to the classify run and keeps both results.
"""

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
    """A model that must not be asked. The calls are recorded so that the test can show it."""

    def __init__(self) -> None:
        self.calls = 0

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
    """AC-extraction.2994.100: With the model off and no stored answer, approve gives the 409 and posts nothing."""
    seeded = await _seed(db, test_user)

    response = await client.post(f"/statements/{seeded.id}/review/approve", json={"create_account_if_missing": True})

    assert response.status_code == 409, response.text
    assert response.json()["detail"].startswith("Economic review required:"), response.text
    assert model_off.calls == 0
    assert await _count(db, JournalEntry) == 0, "nothing is posted"
    assert await _count(db, TransactionClassification) == 0, "no answer is invented"
    refreshed = await db.scalar(
        select(StatementSummary).where(StatementSummary.id == seeded.id).execution_options(populate_existing=True)
    )
    assert refreshed.status is BankStatementStatus.PARSED


async def _add_keyword_rule(db, user, keyword: str) -> None:
    account = Account(user_id=user.id, name=f"Expense - {keyword}", type=AccountType.EXPENSE, currency="SGD")
    income = Account(user_id=user.id, name=f"Income - {keyword}", type=AccountType.INCOME, currency="SGD")
    db.add_all([account, income])
    await db.flush()
    for name, kw, target in (("expense", "Coffee", account), ("income", "Salary", income)):
        db.add(
            ClassificationRule(
                user_id=user.id,
                created_by=user.id,
                version_number=1,
                effective_date=date(2020, 1, 1),
                is_active=True,
                rule_name=f"{name} rule",
                rule_type=RuleType.KEYWORD_MATCH,
                rule_config={"keywords": [kw]},
                tag_mappings={"category": name.upper()},
                default_account_id=target.id,
            )
        )
    await db.commit()


async def test_AC_extraction_2994_100_the_classify_run_applies_the_keyword_rules_and_approve_posts_them_without_a_model_call(
    client, db, test_user, model_off
):
    """AC-extraction.2994.100: The rule step moved from the approve to the classify run. The model stays off."""
    seeded = await _seed(db, test_user)
    await _add_keyword_rule(db, test_user, "Reviewed")

    before_the_run = await client.post(
        f"/statements/{seeded.id}/review/approve", json={"create_account_if_missing": True}
    )
    await classify_statement(db, seeded.id)
    response = await client.post(f"/statements/{seeded.id}/review/approve", json={"create_account_if_missing": True})

    assert before_the_run.status_code == 409, "the approve alone applies no rule any more"
    assert before_the_run.json()["detail"].startswith("Economic review required:")
    assert response.status_code == 200, response.text
    assert response.json()["journal_entries_created"] == len(ROWS)
    assert model_off.calls == 0
    assert await _count(db, TransactionClassification) == len(ROWS), "each row has its answer from the rule"
