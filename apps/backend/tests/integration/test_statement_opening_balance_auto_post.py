from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

from sqlalchemy import select
from src.config_app import set_base_currency
from src.extraction import BankStatementStatus, ClassificationStatus, DocumentSource, RuleType, StatementPostingOutcome, StatementPostingStatus
from src.extraction.extension import statement_posting as statement_posting_module
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_posting import try_auto_approve_high_confidence_statement, try_auto_post_statement_opening_balance
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.ledger import Account, AccountType, JournalEntry, JournalEntryStatus, JournalLine
from src.reporting import generate_income_statement
from tests.statement_ingestion import parse_and_load_statement_projection, posting_dependencies


def _drawdown_payload():
    return {
        "institution": "GXS",
        "account_last4": "7174",
        "currency": "SGD",
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
        "opening_balance": "51730.82",
        "closing_balance": "2953.14",
        "transactions": [
            {"date": "2026-06-05", "description": "Loan principal payment", "amount": "48800.00", "direction": "OUT", "currency": "SGD", "balance_after": "2930.82"},
            {"date": "2026-06-30", "description": "Interest", "amount": "22.32", "direction": "IN", "currency": "SGD", "balance_after": "2953.14"},
        ],
    }


def _followup_payload():
    return {
        "institution": "GXS",
        "account_last4": "7174",
        "currency": "SGD",
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
        "opening_balance": "2953.14",
        "closing_balance": "3053.14",
        "transactions": [{"date": "2026-07-15", "description": "Salary credit", "amount": "100.00", "direction": "IN", "currency": "SGD", "balance_after": "3053.14"}],
    }


async def _attach_dispositions(db, user_id, transactions) -> None:
    specs = {"Loan principal payment": ("Liability - Loan Principal", AccountType.LIABILITY, "loan_principal", None), "Interest": ("Income - Interest", AccountType.INCOME, None, "INTEREST"), "Salary credit": ("Income - Salary", AccountType.INCOME, None, "SALARY")}
    for txn in transactions:
        name, acc_type, intent, cat = specs[txn.description]
        counter = (await db.execute(select(Account).where(Account.user_id == user_id, Account.name == name))).scalar_one_or_none()
        if counter is None:
            counter = Account(user_id=user_id, name=name, code={AccountType.LIABILITY: "2101", AccountType.INCOME: "4102" if cat == "INTEREST" else "4101"}[acc_type], type=acc_type, currency=txn.currency)
            db.add(counter)
            await db.flush()
        tags = {k: v for k, v in (("intent", intent), ("category", cat)) if v is not None}
        rule = ClassificationRule(user_id=user_id, version_number=1, effective_date=txn.txn_date, rule_name=f"Reviewed {txn.id}", rule_type=RuleType.KEYWORD_MATCH, rule_config={"keywords": [txn.description]}, tag_mappings=tags, default_account_id=counter.id, created_by=user_id)
        db.add(rule)
        await db.flush()
        db.add(TransactionClassification(atomic_txn_id=txn.id, rule_version_id=rule.id, account_id=counter.id, tags=tags, confidence_score=100, status=ClassificationStatus.APPLIED))
    await db.flush()


async def _parse_and_auto_post(db, test_user, payload: dict, file_hash: str):
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=payload)
    _, statement, txns = await parse_and_load_statement_projection(service, db=db, source=DocumentSource.resolve(path=Path(f"{file_hash}.pdf"), content=f"%PDF-1.7\n%{file_hash}".encode()), institution=payload["institution"], user_id=test_user.id)
    await db.flush()
    assert statement.status == BankStatementStatus.APPROVED
    await _attach_dispositions(db, test_user.id, txns)
    assert await try_auto_approve_high_confidence_statement(db, statement.id, test_user.id, dependencies=posting_dependencies()) >= 1
    return statement


async def _account_balance(db, account_id) -> Decimal:
    lines = (await db.execute(select(JournalLine).join(JournalEntry).where(JournalLine.account_id == account_id, JournalEntry.status.in_([JournalEntryStatus.POSTED, JournalEntryStatus.RECONCILED])))).scalars().all()
    return sum((line.amount if line.direction.value == "DEBIT" else -line.amount for line in lines), Decimal("0"))


async def _opening_equity_count(db, user_id) -> int:
    equity = (await db.execute(select(Account).where(Account.user_id == user_id, Account.is_system.is_(True), Account.code == "3199"))).scalar_one_or_none()
    return 0 if equity is None else len((await db.execute(select(JournalLine).where(JournalLine.account_id == equity.id))).scalars().all())


async def test_auto_approve_posts_validated_opening_balance_and_skips_zero(db, test_user):
    stmt = await _parse_and_auto_post(db, test_user, _drawdown_payload(), "open-1")
    inc = await generate_income_statement(db, test_user.id, start_date=stmt.period_start, end_date=stmt.period_end, currency="SGD")
    assert stmt.account_id is not None and (await _account_balance(db, stmt.account_id), await _opening_equity_count(db, test_user.id), inc["total_income"], inc["total_expenses"]) == (
        Decimal("2953.14"), 1, Decimal("22.32"), Decimal("0.00")
    )
    second = await _parse_and_auto_post(db, test_user, _followup_payload(), "open-2")
    assert (second.account_id, await _opening_equity_count(db, test_user.id), await _account_balance(db, stmt.account_id)) == (stmt.account_id, 1, Decimal("3053.14"))


async def test_zero_opening_balance_posts_no_opening_entry(db, test_user):
    payload = _drawdown_payload()
    payload["opening_balance"], payload["closing_balance"] = "0.00", "-48777.68"
    payload["transactions"][0]["balance_after"], payload["transactions"][1]["balance_after"] = "-48800.00", "-48777.68"
    stmt = await _parse_and_auto_post(db, test_user, payload, "open-3")
    assert (await _opening_equity_count(db, test_user.id), await _account_balance(db, stmt.account_id)) == (0, Decimal("-48777.68"))


async def test_zero_created_count_still_posts_opening_balance_and_deduplicates_period_start(db, test_user, monkeypatch):
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=_drawdown_payload())
    _, stmt, _ = await parse_and_load_statement_projection(service, db=db, source=DocumentSource.resolve(path=Path("open-4.pdf"), content=b"%PDF-1.7"), institution="GXS", user_id=test_user.id)
    await db.flush()
    monkeypatch.setattr(statement_posting_module, "auto_create_posted_entries_for_statement", AsyncMock(return_value=StatementPostingOutcome(status=StatementPostingStatus.POSTED, created_count=0)))
    posted = await try_auto_approve_high_confidence_statement(db, stmt.id, test_user.id, dependencies=posting_dependencies())
    assert (posted, await _opening_equity_count(db, test_user.id), await _account_balance(db, stmt.account_id)) == (0, 1, Decimal("51730.82"))

    _, dup_stmt, _ = await parse_and_load_statement_projection(service, db=db, source=DocumentSource.resolve(path=Path("open-5b.pdf"), content=b"%PDF-1.7\n%dup"), institution="GXS", user_id=test_user.id, account_id=stmt.account_id)
    await db.flush()
    await try_auto_post_statement_opening_balance(db, dup_stmt, test_user.id, base_currency="SGD")
    assert await _opening_equity_count(db, test_user.id) == 1


async def test_statement_opening_balance_uses_persisted_usd_base(db, test_user) -> None:
    payload = _drawdown_payload()
    payload["currency"] = "USD"
    for txn in payload["transactions"]:
        txn["currency"] = "USD"
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=payload)
    _, stmt, txns = await parse_and_load_statement_projection(service, db=db, source=DocumentSource.resolve(path=Path("effective-usd-opening.pdf"), content=b"%PDF-1.7"), institution="GXS", user_id=test_user.id)
    await set_base_currency(db, "USD", user_id=test_user.id)
    await _attach_dispositions(db, test_user.id, txns)
    posted = await try_auto_approve_high_confidence_statement(db, stmt.id, test_user.id, dependencies=posting_dependencies())
    await db.commit()
    lines = (await db.execute(select(JournalLine).join(JournalEntry).where(JournalEntry.memo == "Opening balance (statement import)"))).scalars()
    assert posted >= 1 and {line.currency for line in lines} == {"USD"}
