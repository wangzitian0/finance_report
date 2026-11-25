import hashlib
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType, Money, canonical_json_digest, text_digest
from src.extraction import TransactionDirection
from src.extraction.base.validation import (
    bank_currency_balances,
    count_within_document_dedup_collapse,
    detect_balance_chain_break,
    evaluate_statement_balance,
    validate_balance_explicit,
    validate_balance_per_currency,
)
from src.extraction.extension.deduplication import DeduplicationService
from src.identity import User
from src.ledger import (
    Account,
    AccountType,
    Direction,
    Entry,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    create_transfer_in_entry,
    create_transfer_out_entry,
    find_transfer_pairs,
    get_processing_balance,
    post_entry,
)
from src.ledger.splits import calculate_reconciliation_adjustment
from src.pricing.orm.market_data import FxRate
from src.reporting import (
    EquationDiagnosticCategory,
    diagnose_equation_imbalance,
    generate_balance_sheet,
    generate_cash_flow,
    generate_income_statement,
)

@pytest.mark.no_db
def test_backend_domain_invariants() -> None:
    extracted = {
        "currency": "SGD",
        "opening_balance": "1000.00",
        "closing_balance": "1100.25",
        "transactions": [
            {"amount": "250.50", "direction": "IN"},
            {"amount": "50.25", "direction": "OUT"},
            {"amount": "100.00", "direction": "OUT"},
        ],
    }
    res = evaluate_statement_balance(
        opening=Decimal(extracted["opening_balance"]),
        closing=Decimal(extracted["closing_balance"]),
        currency=None,
        currency_balances=None,
        transactions=extracted["transactions"],
    )
    assert res["balance_valid"] is True
    assert res["expected_closing"] == "1100.25"
    assert res["difference"] == "0.00"

    explicit_mismatch = validate_balance_explicit(
        Decimal("1000.00"), Decimal("1200.00"), Decimal("100.25"), currency="SGD"
    )
    assert explicit_mismatch["balance_valid"] is False
    assert explicit_mismatch["expected_closing"] == "1100.25"
    assert explicit_mismatch["difference"] == "99.75"

    multi_ccy = {
        "balances": [
            {"currency": "HKD", "opening": "42580.00", "closing": "18364.12"},
            {"currency": "USD", "opening": "2150.00", "closing": "2841.35"},
        ],
        "transactions": [
            {"amount": "24215.88", "direction": "OUT", "currency": "HKD"},
            {"amount": "691.35", "direction": "IN", "currency": "USD"},
        ],
    }
    assert bank_currency_balances(multi_ccy) == [
        {"currency": "HKD", "opening": "42580.00", "closing": "18364.12"},
        {"currency": "USD", "opening": "2150.00", "closing": "2841.35"},
    ]
    assert validate_balance_per_currency(multi_ccy)["balance_valid"] is True

    u_id = uuid4()
    h1 = DeduplicationService.calculate_transaction_hash(
        user_id=u_id,
        txn_date=date(2026, 3, 15),
        amount=Decimal("128.50"),
        direction=TransactionDirection.OUT,
        description="SUPERMARKET GROCERIES",
        balance_after=Decimal("4500.00"),
        occurrence_index=0,
    )
    h2 = DeduplicationService.calculate_transaction_hash(
        user_id=u_id,
        txn_date=date(2026, 3, 15),
        amount=Decimal("128.50"),
        direction=TransactionDirection.OUT,
        description="SUPERMARKET GROCERIES",
        balance_after=Decimal("4500.00"),
        occurrence_index=0,
    )
    assert h1 == h2
    assert count_within_document_dedup_collapse([h1, h2, "h3"]) == 1

    mismatch_res = evaluate_statement_balance(
        opening=Decimal("5000.00"),
        closing=Decimal("4800.00"),
        currency="SGD",
        currency_balances=None,
        transactions=[{"amount": "100.00", "direction": "OUT"}],
    )
    assert mismatch_res["balance_valid"] is False
    assert mismatch_res["expected_closing"] == "4900.00"
    assert mismatch_res["difference"] == "100.00"

    chain_break = detect_balance_chain_break(
        [
            {"amount": "100.00", "direction": "OUT", "balance_after": "4900.00"},
            {"amount": "50.00", "direction": "OUT", "balance_after": "4750.00"},
        ],
        opening_balance=Decimal("5000.00"),
    )
    assert chain_break is not None
    assert chain_break.index == 1
    assert chain_break.expected_balance == Decimal("4850.00")
    assert chain_break.observed_balance == Decimal("4750.00")
    assert chain_break.delta == Decimal("-100.00")

    adj = calculate_reconciliation_adjustment(bank_balance=Decimal("500.04"), book_balance=Decimal("500.00"))
    assert adj.difference == Decimal("0.04")
    assert adj.is_gain is True

    assert diagnose_equation_imbalance(Decimal("0.00")).is_balanced is True
    unbalanced = diagnose_equation_imbalance(Decimal("150.00"), unposted_draft_count=1)
    assert unbalanced.is_balanced is False
    assert unbalanced.primary_category == EquationDiagnosticCategory.UNPOSTED_DRAFT

    csv_text = "date,account,amount,type\n2026-01-15,Checking,-150.00,EXPENSE\n"
    csv_digest = text_digest(csv_text)
    assert csv_digest == hashlib.sha256(csv_text.encode("utf-8")).hexdigest()
    manifest = {
        "framework": "US_GAAP_LIKE",
        "files": [
            {
                "path": "schedules/general_ledger.csv",
                "sha256": csv_digest,
                "bytes": len(csv_text.encode("utf-8")),
            }
        ],
    }
    manifest_digest = canonical_json_digest(manifest)
    reordered = {
        "files": [
            {
                "bytes": len(csv_text.encode("utf-8")),
                "sha256": csv_digest,
                "path": "schedules/general_ledger.csv",
            }
        ],
        "framework": "US_GAAP_LIKE",
    }
    assert canonical_json_digest(reordered) == manifest_digest
    tampered = {**manifest, "files": [{**manifest["files"][0], "bytes": 999}]}
    assert canonical_json_digest(tampered) != manifest_digest


async def test_uc_26_transfer_pairing(db: AsyncSession, test_user: User) -> None:
    user_id = test_user.id
    bank_a = Account(user_id=user_id, name="DBS Checking", code="1001", type=AccountType.ASSET, currency="SGD")
    bank_b = Account(user_id=user_id, name="OCBC Savings", code="1002", type=AccountType.ASSET, currency="SGD")
    equity = Account(
        user_id=user_id, name="Opening Balance Equity", code="3199", type=AccountType.EQUITY, currency="SGD"
    )
    db.add_all([bank_a, bank_b, equity])
    await db.flush()
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 1),
        memo="Opening balance DBS",
        entry=Entry.transfer(debit=bank_a.id, credit=equity.id, money=Money(Decimal("5000.00"), "SGD")),
        base_currency="SGD",
        operation="uc26-open-a",
    )
    out_entry = await create_transfer_out_entry(
        db,
        user_id=user_id,
        source_account_id=bank_a.id,
        amount=Decimal("1200.00"),
        txn_date=date(2026, 1, 10),
        description="FAST TRANSFER TO OCBC",
        currency="SGD",
    )
    in_entry = await create_transfer_in_entry(
        db,
        user_id=user_id,
        dest_account_id=bank_b.id,
        amount=Decimal("1200.00"),
        txn_date=date(2026, 1, 10),
        description="FAST TRANSFER FROM DBS",
        currency="SGD",
    )
    await db.commit()
    pairs = await find_transfer_pairs(db, user_id=user_id, currency="SGD", description_scorer=lambda _a, _b: 100.0)
    assert len(pairs) == 1
    assert pairs[0].out_entry.id == out_entry.id
    assert pairs[0].in_entry.id == in_entry.id
    assert await get_processing_balance(db, user_id, currency="SGD") == Decimal("0.00")
    bs = await generate_balance_sheet(db, user_id, as_of_date=date(2026, 1, 31), currency="SGD")
    assert bs["is_balanced"] is True
    assert bs["equation_delta"] == Decimal("0.00")
    assert bs["total_assets"] == Decimal("5000.00")
    assert bs["total_equity"] == Decimal("5000.00")
    cf = await generate_cash_flow(
        db,
        user_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        currency="SGD",
        cash_account_ids=frozenset([bank_a.id, bank_b.id]),
    )
    assert cf["summary"]["ending_cash"] == Decimal("5000.00")
    assert cf["cash_bridge"]["reconciles"] is True
    assert cf["cash_bridge"]["discrepancy"] == Decimal("0.00")


async def test_uc_29_fx_revaluation(db: AsyncSession, test_user: User) -> None:
    user_id = test_user.id
    date_t1, date_t2 = date(2026, 1, 15), date(2026, 1, 31)
    usd_cash = Account(user_id=user_id, name="USD Cash", code="1010", type=AccountType.ASSET, currency="USD")
    owner_eq = Account(user_id=user_id, name="Owner Capital", code="3000", type=AccountType.EQUITY, currency="SGD")
    db.add_all([usd_cash, owner_eq])
    db.add_all(
        [
            FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.32"), rate_date=date_t1, source="test"),
            FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.35"), rate_date=date_t2, source="test"),
        ]
    )
    await db.flush()
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date_t1,
        memo="Deposit 1000 USD at 1.32",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=usd_cash.id,
                direction=Direction.DEBIT,
                amount=Decimal("1000.00"),
                currency="USD",
                fx_rate=Decimal("1.32"),
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=owner_eq.id,
                direction=Direction.CREDIT,
                amount=Decimal("1320.00"),
                currency="SGD",
                fx_rate=Decimal("1.00"),
            ),
        ]
    )
    await db.commit()
    bs_t1 = await generate_balance_sheet(db, user_id, as_of_date=date_t1, currency="SGD")
    assert bs_t1["total_assets"] == Decimal("1320.00")
    assert bs_t1["unrealized_fx_gain_loss"] == Decimal("0.00")
    assert bs_t1["is_balanced"] is True
    assert bs_t1["equation_delta"] == Decimal("0.00")
    bs_t2 = await generate_balance_sheet(db, user_id, as_of_date=date_t2, currency="SGD")
    assert bs_t2["total_assets"] == Decimal("1350.00")
    assert bs_t2["unrealized_fx_gain_loss"] == Decimal("30.00")
    assert bs_t2["is_balanced"] is True
    assert bs_t2["equation_delta"] == Decimal("0.00")


async def test_uc_41_income_statement_aggregation(db: AsyncSession, test_user: User) -> None:
    user_id = test_user.id
    cash = Account(user_id=user_id, name="Checking", code="1000", type=AccountType.ASSET, currency="SGD")
    salary = Account(user_id=user_id, name="Salary", code="4000", type=AccountType.INCOME, currency="SGD")
    dividend = Account(user_id=user_id, name="Dividends", code="4010", type=AccountType.INCOME, currency="SGD")
    rent = Account(user_id=user_id, name="Rent Expense", code="5000", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([cash, salary, dividend, rent])
    await db.flush()
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 2, 5),
        memo="Monthly Salary",
        entry=Entry.transfer(debit=cash.id, credit=salary.id, money=Money(Decimal("8500.00"), "SGD")),
        base_currency="SGD",
        operation="uc41-salary",
    )
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 2, 12),
        memo="Dividend Payout",
        entry=Entry.transfer(debit=cash.id, credit=dividend.id, money=Money(Decimal("200.00"), "SGD")),
        base_currency="SGD",
        operation="uc41-dividend",
    )
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 2, 18),
        memo="Apartment Rent",
        entry=Entry.transfer(debit=rent.id, credit=cash.id, money=Money(Decimal("4200.00"), "SGD")),
        base_currency="SGD",
        operation="uc41-rent",
    )
    await db.commit()
    is_rep = await generate_income_statement(
        db, user_id, start_date=date(2026, 2, 1), end_date=date(2026, 2, 28), currency="SGD"
    )
    assert is_rep["total_income"] == Decimal("8700.00")
    assert is_rep["total_expenses"] == Decimal("4200.00")
    assert is_rep["net_income"] == Decimal("4500.00")


async def test_uc_39_balance_sheet_equation(db: AsyncSession, test_user: User) -> None:
    user_id = test_user.id
    cash = Account(user_id=user_id, name="Main Bank", code="1000", type=AccountType.ASSET, currency="SGD")
    card = Account(user_id=user_id, name="Credit Card", code="2000", type=AccountType.LIABILITY, currency="SGD")
    capital = Account(user_id=user_id, name="Owner Equity", code="3000", type=AccountType.EQUITY, currency="SGD")
    revenue = Account(user_id=user_id, name="Consulting Income", code="4000", type=AccountType.INCOME, currency="SGD")
    dining = Account(user_id=user_id, name="Dining Expense", code="5000", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([cash, card, capital, revenue, dining])
    await db.flush()
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 3, 1),
        memo="Capital Injection",
        entry=Entry.transfer(debit=cash.id, credit=capital.id, money=Money(Decimal("10000.00"), "SGD")),
        base_currency="SGD",
        operation="uc39-capital",
    )
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 3, 10),
        memo="Client Invoice",
        entry=Entry.transfer(debit=cash.id, credit=revenue.id, money=Money(Decimal("3000.00"), "SGD")),
        base_currency="SGD",
        operation="uc39-revenue",
    )
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 3, 15),
        memo="Card Dining Spend",
        entry=Entry.transfer(debit=dining.id, credit=card.id, money=Money(Decimal("450.00"), "SGD")),
        base_currency="SGD",
        operation="uc39-card-spend",
    )
    await db.commit()
    bs = await generate_balance_sheet(db, user_id, as_of_date=date(2026, 3, 31), currency="SGD")
    is_rep = await generate_income_statement(
        db, user_id, start_date=date(2026, 3, 1), end_date=date(2026, 3, 31), currency="SGD"
    )
    assert bs["is_balanced"] is True
    assert bs["equation_delta"] == Decimal("0.00")
    assert bs["total_assets"] == Decimal("13000.00")
    assert bs["total_liabilities"] == Decimal("450.00")
    assert bs["total_equity"] == Decimal("10000.00")
    assert bs["net_income"] == is_rep["net_income"] == Decimal("2550.00")
    assert bs["total_assets"] == bs["total_liabilities"] + bs["total_equity"] + bs["net_income"]


async def test_uc_47_chat_context_financial_summary(db: AsyncSession, test_user: User) -> None:
    user_id = test_user.id
    cash = Account(user_id=user_id, name="DBS Cash Account", code="1000", type=AccountType.ASSET, currency="SGD")
    equity = Account(user_id=user_id, name="Opening Equity", code="3199", type=AccountType.EQUITY, currency="SGD")
    income = Account(user_id=user_id, name="Advisory Fee", code="4000", type=AccountType.INCOME, currency="SGD")
    expense = Account(user_id=user_id, name="Cloud Hosting", code="5000", type=AccountType.EXPENSE, currency="SGD")
    db.add_all([cash, equity, income, expense])
    await db.flush()
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2025, 12, 31),
        memo="Prior Year Closing Cash",
        entry=Entry.transfer(debit=cash.id, credit=equity.id, money=Money(Decimal("20000.00"), "SGD")),
        base_currency="SGD",
        operation="uc47-open",
    )
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 10),
        memo="Advisory Retainer",
        entry=Entry.transfer(debit=cash.id, credit=income.id, money=Money(Decimal("5500.00"), "SGD")),
        base_currency="SGD",
        operation="uc47-income",
    )
    await post_entry(
        db,
        user_id=user_id,
        entry_date=date(2026, 1, 20),
        memo="Hosting Bill",
        entry=Entry.transfer(debit=expense.id, credit=cash.id, money=Money(Decimal("800.00"), "SGD")),
        base_currency="SGD",
        operation="uc47-expense",
    )
    await db.commit()
    bs = await generate_balance_sheet(db, user_id, as_of_date=date(2026, 1, 31), currency="SGD")
    is_rep = await generate_income_statement(
        db, user_id, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), currency="SGD"
    )
    cf = await generate_cash_flow(
        db,
        user_id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        currency="SGD",
        cash_account_ids=frozenset([cash.id]),
    )
    assert bs["is_balanced"] is True
    assert bs["net_income"] == is_rep["net_income"] == Decimal("4700.00")
    assert cf["summary"]["beginning_cash"] == Decimal("20000.00")
    assert cf["summary"]["net_cash_flow"] == Decimal("4700.00")
    assert cf["summary"]["ending_cash"] == bs["total_assets"] == Decimal("24700.00")
    assert cf["cash_bridge"]["reconciles"] is True
