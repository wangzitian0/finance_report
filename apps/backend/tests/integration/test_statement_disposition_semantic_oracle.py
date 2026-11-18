from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from src.audit.orm.trace_record import TraceRecordRow
from src.config import settings
from src.extraction import DocumentSource, RuleType, StatementPostingStatus
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_posting import auto_create_posted_entries_for_statement
from src.extraction.extension.statement_validation import approve_statement_with_transactions
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.ledger import Account, AccountType, JournalLine
from src.reporting import generate_income_statement
from tests.statement_ingestion import classify_rows, parse_and_load_statement_projection, posting_dependencies

_SHA = "a" * 40
_CASES = (
    ("Salary payroll", "", "1000.00", "Income - Salary", AccountType.INCOME, {"category": "SALARY"}, "income", "disposition_authoritative"),
    ("Grocery market", "100.00", "", "Expense - Groceries", AccountType.EXPENSE, {"category": "GROCERIES"}, "expense", "disposition_authoritative"),
    ("Grocery refund", "", "20.00", "Expense - Groceries", AccountType.EXPENSE, {"category": "GROCERIES", "intent": "expense_refund"}, "expense_refund", "disposition_authoritative"),
    ("Cash dividend", "", "40.00", "Income - Dividends", AccountType.INCOME, {"category": "DIVIDEND"}, "income", "disposition_authoritative"),
    ("Broker fee", "10.00", "", "Expense - Broker Fees", AccountType.EXPENSE, {"category": "FEES"}, "expense", "disposition_authoritative"),
    ("Buy security", "250.00", "", "Asset - Securities", AccountType.ASSET, {"intent": "investment_purchase"}, "investment_purchase", "disposition_authoritative"),
    ("Sell security", "", "300.00", "Asset - Securities", AccountType.ASSET, {"intent": "investment_sale"}, "investment_sale", "disposition_authoritative"),
    ("Loan drawdown", "", "500.00", "Liability - Loan Payable", AccountType.LIABILITY, {"intent": "loan_principal"}, "loan_principal", "disposition_authoritative"),
    ("Loan repayment", "120.00", "", "Liability - Loan Payable", AccountType.LIABILITY, {"intent": "loan_principal"}, "loan_principal", "disposition_authoritative"),
    ("Loan interest", "5.00", "", "Expense - Loan Interest", AccountType.EXPENSE, {"category": "LOAN_INTEREST", "intent": "loan_interest"}, "loan_interest", "disposition_authoritative"),
    ("Card repayment", "80.00", "", "Liability - Card Payable", AccountType.LIABILITY, {"intent": "card_repayment"}, "card_repayment", "disposition_authoritative"),
    ("Own account transfer", "60.00", "", "Asset - Transfer Clearing", AccountType.ASSET, {"intent": "transfer"}, "transfer", "disposition_already_covered"),
)


async def test_reviewed_description_oracle_reaches_exact_report_lines(db, test_user, monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_ai_classification", False)
    monkeypatch.setattr(settings, "git_commit_sha", _SHA)
    bank = Account(user_id=test_user.id, name="DBS Cash", code="1001", type=AccountType.ASSET, currency="SGD")
    db.add(bank)
    await db.flush()
    accounts: dict[str, Account] = {}
    for desc, _d, _c, acc_name, acc_type, tags, *_ in _CASES:
        acc = accounts.get(acc_name) or Account(user_id=test_user.id, name=acc_name, type=acc_type, currency="SGD")
        if acc_name not in accounts:
            db.add(acc)
            accounts[acc_name] = acc
            await db.flush()
        db.add(ClassificationRule(user_id=test_user.id, created_by=test_user.id, version_number=1, effective_date=date(2026, 6, 1), rule_name=f"Reviewed: {desc}", rule_type=RuleType.KEYWORD_MATCH, rule_config={"keywords": [desc]}, tag_mappings=tags, default_account_id=acc.id))
    await db.flush()

    csv_bytes = ("Date,Description,Debit Amount,Credit Amount\n" + "\n".join(f"2026-06-{i:02d},{d},{deb},{cred}" for i, (d, deb, cred, *_) in enumerate(_CASES, 1)) + "\n").encode()
    _, statement, txns = await parse_and_load_statement_projection(ExtractionService(), db=db, source=DocumentSource.resolve(path=Path("economic-oracle.csv"), content=csv_bytes), institution="DBS", user_id=test_user.id, file_type="csv")
    statement.account_id, statement.currency, statement.period_start, statement.period_end, statement.opening_balance, statement.closing_balance = bank.id, bank.currency, date(2026, 6, 1), date(2026, 6, 30), Decimal("0.00"), Decimal("1235.00")
    for t in txns:
        t.currency, t.currency_unresolved, t.currency_resolved_by, t.currency_resolved_at = bank.currency, False, test_user.id, datetime.now(UTC)
    await db.flush()
    transfer_ids = {t.id for t in txns if t.description == "Own account transfer"}

    async def accepted_transfer_ids(_db, _ids):
        return transfer_ids

    await classify_rows(db, test_user.id, txns)
    approved, approved_txns = await approve_statement_with_transactions(db, statement.id, test_user.id)
    outcome = await auto_create_posted_entries_for_statement(db, approved, test_user.id, dependencies=replace(posting_dependencies(), transfer_exclusions=accepted_transfer_ids), transactions=approved_txns)
    classifications = list((await db.execute(select(TransactionClassification))).scalars())
    desc_by_id = {str(t.id): t.description for t in txns}
    assert (outcome.status, outcome.created_count, len(classifications)) == (StatementPostingStatus.POSTED, len(_CASES) - 1, len(_CASES))
    assert all(c.confidence_score == 100 for c in classifications)
    assert {desc_by_id[str(c.atomic_txn_id)]: c.tags for c in classifications} == {d: tags for d, _, _, _, _, tags, *_ in _CASES}

    report = await generate_income_statement(db, test_user.id, start_date=date(2026, 6, 1), end_date=date(2026, 6, 30), currency="SGD")
    inc_lines = {line["name"]: line["amount"] for line in report["income"]}
    exp_lines = {line["name"]: line["amount"] for line in report["expenses"]}
    assert (inc_lines, exp_lines, report["total_income"], report["total_expenses"]) == (
        {"Income - Dividends": Decimal("40.00"), "Income - Salary": Decimal("1000.00")},
        {"Expense - Broker Fees": Decimal("10.00"), "Expense - Groceries": Decimal("80.00"), "Expense - Loan Interest": Decimal("5.00")},
        Decimal("1040.00"),
        Decimal("95.00"),
    )
    non_pnl_ids = {accounts[n].id for n in ("Asset - Securities", "Liability - Loan Payable", "Liability - Card Payable")}
    posted_ids = set((await db.execute(select(JournalLine.account_id))).scalars())
    assert non_pnl_ids <= posted_ids and accounts["Asset - Transfer Clearing"].id not in posted_ids

    trace_rows = list((await db.execute(select(TraceRecordRow).where(TraceRecordRow.target_kind == "statement_transaction"))).scalars())
    cands = {r.target_id: r for r in trace_rows if r.assertion_kind == "economic_intent"}
    decs = {r.target_id: r for r in trace_rows if r.assertion_kind == "disposition"}
    expected_trace = {d: (intent, outcome_code) for d, _, _, _, _, _, intent, outcome_code in _CASES}
    assert set(desc_by_id) == set(cands) == set(decs)
    for tid, desc in desc_by_id.items():
        intent, outcome_code = expected_trace[desc]
        cand, dec = cands[tid], decs[tid]
        assert (cand.assertion_id, cand.authority_tier, cand.proof_kind, cand.provenance, dec.reason_code, dec.result.value) == (intent, "CODE-ONLY", "exact", "deterministic", outcome_code, "authoritative")
    assert {c.assertion_version for c in cands.values()} == {"v1|disposition-v1|enforce|machine:0.85|pnl:0.85|unknown:review|ambiguous:review|llm:0|git:" + _SHA}
