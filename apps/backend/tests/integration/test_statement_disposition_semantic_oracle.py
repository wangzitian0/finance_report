"""Independent reviewed-description oracle for statement economic disposition (#1483)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from src.audit.orm.trace_record import TraceRecordRow
from src.config import settings
from src.extraction import DocumentSource, StatementPostingStatus
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_posting import auto_create_posted_entries_for_statement
from src.extraction.extension.statement_validation import approve_statement
from src.extraction.orm.layer3 import ClassificationRule, RuleType, TransactionClassification
from src.ledger import Account, AccountType, JournalLine
from src.reporting import generate_income_statement
from tests.statement_ingestion import parse_and_load_statement_projection, posting_dependencies

_SHA = "a" * 40

# This fixture is deliberately independent of the implementation's category map.
# It names the economic result expected from each recorded description.
_CASES = (
    ("Salary payroll", "", "1000.00", "Income - Salary", AccountType.INCOME, {"category": "SALARY"}),
    ("Grocery market", "100.00", "", "Expense - Groceries", AccountType.EXPENSE, {"category": "GROCERIES"}),
    (
        "Grocery refund",
        "",
        "20.00",
        "Expense - Groceries",
        AccountType.EXPENSE,
        {"category": "GROCERIES", "intent": "expense_refund"},
    ),
    ("Cash dividend", "", "40.00", "Income - Dividends", AccountType.INCOME, {"category": "DIVIDEND"}),
    ("Broker fee", "10.00", "", "Expense - Broker Fees", AccountType.EXPENSE, {"category": "FEES"}),
    (
        "Buy security",
        "250.00",
        "",
        "Asset - Securities",
        AccountType.ASSET,
        {"intent": "investment_purchase"},
    ),
    (
        "Sell security",
        "",
        "300.00",
        "Asset - Securities",
        AccountType.ASSET,
        {"intent": "investment_sale"},
    ),
    (
        "Loan drawdown",
        "",
        "500.00",
        "Liability - Loan Payable",
        AccountType.LIABILITY,
        {"intent": "loan_principal"},
    ),
    (
        "Loan repayment",
        "120.00",
        "",
        "Liability - Loan Payable",
        AccountType.LIABILITY,
        {"intent": "loan_principal"},
    ),
    (
        "Loan interest",
        "5.00",
        "",
        "Expense - Loan Interest",
        AccountType.EXPENSE,
        {"category": "LOAN_INTEREST", "intent": "loan_interest"},
    ),
    (
        "Card repayment",
        "80.00",
        "",
        "Liability - Card Payable",
        AccountType.LIABILITY,
        {"intent": "card_repayment"},
    ),
    (
        "Own account transfer",
        "60.00",
        "",
        "Asset - Transfer Clearing",
        AccountType.ASSET,
        {"intent": "transfer"},
    ),
)

_EXPECTED_TRACE = {
    "Salary payroll": ("income", "CODE-ONLY", "exact", "disposition_authoritative"),
    "Grocery market": ("expense", "CODE-ONLY", "exact", "disposition_authoritative"),
    "Grocery refund": ("expense_refund", "CODE-ONLY", "exact", "disposition_authoritative"),
    "Cash dividend": ("income", "CODE-ONLY", "exact", "disposition_authoritative"),
    "Broker fee": ("expense", "CODE-ONLY", "exact", "disposition_authoritative"),
    "Buy security": ("investment_purchase", "CODE-ONLY", "exact", "disposition_authoritative"),
    "Sell security": ("investment_sale", "CODE-ONLY", "exact", "disposition_authoritative"),
    "Loan drawdown": ("loan_principal", "CODE-ONLY", "exact", "disposition_authoritative"),
    "Loan repayment": ("loan_principal", "CODE-ONLY", "exact", "disposition_authoritative"),
    "Loan interest": ("loan_interest", "CODE-ONLY", "exact", "disposition_authoritative"),
    "Card repayment": ("card_repayment", "CODE-ONLY", "exact", "disposition_authoritative"),
    "Own account transfer": ("transfer", "CODE-ONLY", "exact", "disposition_already_covered"),
}


def _csv() -> bytes:
    rows = ["Date,Description,Debit Amount,Credit Amount"]
    for index, (description, debit, credit, *_rest) in enumerate(_CASES, start=1):
        rows.append(f"2026-06-{index:02d},{description},{debit},{credit}")
    return ("\n".join(rows) + "\n").encode()


async def _reviewed_rules(db, *, user_id) -> dict[str, Account]:
    accounts: dict[str, Account] = {}
    for description, _debit, _credit, account_name, account_type, tags in _CASES:
        account = accounts.get(account_name)
        if account is None:
            account = Account(user_id=user_id, name=account_name, type=account_type, currency="SGD")
            db.add(account)
            accounts[account_name] = account
            await db.flush()
        db.add(
            ClassificationRule(
                user_id=user_id,
                created_by=user_id,
                version_number=1,
                effective_date=date(2026, 6, 1),
                rule_name=f"Reviewed disposition: {description}",
                rule_type=RuleType.KEYWORD_MATCH,
                rule_config={"keywords": [description]},
                tag_mappings=tags,
                default_account_id=account.id,
            )
        )
    await db.flush()
    return accounts


@pytest.mark.asyncio
async def test_AC_extraction_disposition_3_reviewed_description_oracle_reaches_exact_report_lines(
    db,
    test_user,
    monkeypatch,
) -> None:
    """AC-extraction.disposition.3: reviewed descriptions determine report semantics without live AI."""
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    monkeypatch.setattr(settings, "git_commit_sha", _SHA)

    bank = Account(user_id=test_user.id, name="DBS Cash", code="1001", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.flush()
    accounts = await _reviewed_rules(db, user_id=test_user.id)

    _result, statement, transactions = await parse_and_load_statement_projection(
        ExtractionService(),
        db=db,
        source=DocumentSource.resolve(path=Path("economic-oracle.csv"), content=_csv()),
        institution="DBS",
        user_id=test_user.id,
        file_type="csv",
    )
    statement.account_id = bank.id
    statement.currency = bank.currency
    statement.period_start = date(2026, 6, 1)
    statement.period_end = date(2026, 6, 30)
    statement.opening_balance = Decimal("0.00")
    statement.closing_balance = Decimal("1235.00")
    for transaction in transactions:
        transaction.currency = bank.currency
        transaction.currency_unresolved = False
        transaction.currency_resolved_by = test_user.id
        transaction.currency_resolved_at = datetime.now(UTC)
    await db.flush()

    transfer_ids = {transaction.id for transaction in transactions if transaction.description == "Own account transfer"}

    async def accepted_transfer_ids(_db, _transaction_ids):
        return transfer_ids

    approved = await approve_statement(db, statement.id, test_user.id)
    outcome = await auto_create_posted_entries_for_statement(
        db,
        approved,
        test_user.id,
        dependencies=replace(posting_dependencies(), transfer_exclusions=accepted_transfer_ids),
    )

    assert outcome.status is StatementPostingStatus.POSTED
    assert outcome.created_count == len(_CASES) - 1
    classifications = list((await db.execute(select(TransactionClassification))).scalars())
    assert len(classifications) == len(_CASES)
    assert all(classification.confidence_score == 100 for classification in classifications)
    descriptions_by_transaction_id = {str(transaction.id): transaction.description for transaction in transactions}
    expected_tags = {description: tags for description, _debit, _credit, _name, _type, tags in _CASES}
    assert {
        descriptions_by_transaction_id[str(classification.atomic_txn_id)]: classification.tags
        for classification in classifications
    } == expected_tags

    report = await generate_income_statement(
        db,
        test_user.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        currency="SGD",
    )
    income_lines = {line["name"]: line["amount"] for line in report["income"]}
    expense_lines = {line["name"]: line["amount"] for line in report["expenses"]}
    assert income_lines == {
        "Income - Dividends": Decimal("40.00"),
        "Income - Salary": Decimal("1000.00"),
    }
    assert expense_lines == {
        "Expense - Broker Fees": Decimal("10.00"),
        "Expense - Groceries": Decimal("80.00"),
        "Expense - Loan Interest": Decimal("5.00"),
    }
    assert report["total_income"] == Decimal("1040.00")
    assert report["total_expenses"] == Decimal("95.00")

    pnl_account_ids = {accounts[name].id for name in income_lines | expense_lines}
    non_pnl_account_ids = {
        accounts["Asset - Securities"].id,
        accounts["Liability - Loan Payable"].id,
        accounts["Liability - Card Payable"].id,
    }
    posted_counter_account_ids = {
        account_id
        for account_id in (await db.execute(select(JournalLine.account_id))).scalars()
        if account_id in pnl_account_ids | non_pnl_account_ids
    }
    assert non_pnl_account_ids <= posted_counter_account_ids
    assert accounts["Asset - Transfer Clearing"].id not in posted_counter_account_ids

    trace_rows = list(
        (await db.execute(select(TraceRecordRow).where(TraceRecordRow.target_kind == "statement_transaction")))
        .scalars()
        .all()
    )
    candidates = {row.target_id: row for row in trace_rows if row.assertion_kind == "economic_intent"}
    decisions = {row.target_id: row for row in trace_rows if row.assertion_kind == "disposition"}
    assert set(descriptions_by_transaction_id) == set(candidates) == set(decisions)
    for transaction_id, description in descriptions_by_transaction_id.items():
        intent, tier, proof_kind, outcome = _EXPECTED_TRACE[description]
        candidate = candidates[transaction_id]
        decision = decisions[transaction_id]
        assert (candidate.assertion_id, candidate.authority_tier, candidate.proof_kind) == (
            intent,
            tier,
            proof_kind,
        )
        assert candidate.provenance == "deterministic"
        assert decision.reason_code == outcome
        assert decision.result.value == "authoritative"

    trace_versions = {candidate.assertion_version for candidate in candidates.values()}
    assert trace_versions == {
        "v1|disposition-v1|enforce|machine:0.85|pnl:0.85|unknown:review|ambiguous:review|llm:0|git:" + _SHA
    }
