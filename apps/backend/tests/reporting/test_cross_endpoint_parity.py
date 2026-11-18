"""Real HTTP cross-endpoint parity & staggered coverage invariant tests (#3128)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import SqlTraceRecordRepository, TraceEmitter
from src.audit.money import Money
from src.extraction import (
    BankStatementStatus,
    ExtractedTransactionFact,
    ExtractionMethod,
    SourceProvenance,
    StatementBalanceFact,
    StatementEvidenceType,
    StatementExtractionResult,
    StatementSourceType,
    StatementSummary,
    extraction_trace_policy_registry,
    persist_statement_extraction_result,
)
from src.extraction.extension.custody_binding import resolve_bank_custody_account
from src.extraction.extension.extraction_trace import build_extraction_trace_records
from src.extraction.extension.review_queue import resolve_secondary_currency_custody_account
from src.ledger import Account, AccountType, Entry, initialize_opening_positions, post_entry
from tests.reporting._report_fixtures import seed_accounts, seed_fx_rates


async def _authoritative_bank_statement(
    db: AsyncSession,
    *,
    user_id,
    primary_account: Account,
    institution: str,
    account_last4: str,
    primary_currency: str,
    period_start: date,
    period_end: date,
    balances: tuple[StatementBalanceFact, ...],
    transactions: tuple[ExtractedTransactionFact, ...],
) -> StatementSummary:
    stmt = StatementSummary(
        user_id=user_id,
        file_hash=sha256(f"{user_id}:{institution}:{account_last4}:{period_start}:{period_end}".encode()).hexdigest(),
        institution=institution,
        account_last4=account_last4,
        account_id=primary_account.id,
        currency=primary_currency,
        period_start=period_start,
        period_end=period_end,
        opening_balance=balances[0].opening,
        closing_balance=balances[0].closing,
        currency_balances=[
            {"currency": b.currency, "opening": str(b.opening), "closing": str(b.closing)} for b in balances
        ],
        status=BankStatementStatus.APPROVED,
        confidence_score=98,
        balance_validated=True,
    )
    db.add(stmt)
    await db.flush()

    src_res = StatementExtractionResult.create(
        producer_version="parity-test@1",
        source_content_digest=sha256(f"raw:{stmt.id}".encode()).hexdigest(),
        source_type=StatementSourceType.BANK,
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        institution=institution,
        account_last4=account_last4,
        period_start=period_start,
        period_end=period_end,
        balances=balances,
        transactions=transactions,
        positions=(),
        confidence=Decimal("0.98"),
        balance_validated=True,
        warnings=(),
        review_reasons=(),
        provenance=SourceProvenance(
            intake_mode="pdf", method=ExtractionMethod.LIVE_LLM, provider="test", model="test@1"
        ),
        statement_currency=primary_currency,
    )
    traces = build_extraction_trace_records(
        src_res, user_id=user_id, execution_id=f"parity:{stmt.id}", occurred_at=datetime.now(UTC)
    )
    await TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())).emit_many(traces)
    await persist_statement_extraction_result(
        db, statement=stmt, result=src_res, source_trace_record_id=traces[0].record_id
    )
    return stmt


async def test_multicurrency_secondary_custody_in_cash_flow_and_package_parity(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    """Secondary-currency derived custody account appears in Cash Flow and Package CTA/Net Income stay aligned."""
    uid = test_user.id
    test_user.base_currency = "SGD"
    await seed_fx_rates(
        db,
        ("HKD", "SGD", "0.171000", date(2025, 1, 1)),
        ("HKD", "SGD", "0.168500", date(2025, 6, 15)),
        ("HKD", "SGD", "0.166000", date(2025, 12, 31)),
        ("USD", "SGD", "1.351000", date(2025, 1, 1)),
        ("USD", "SGD", "1.337000", date(2025, 6, 15)),
        ("USD", "SGD", "1.319000", date(2025, 12, 31)),
        commit=False,
    )
    hkd_bank = await resolve_bank_custody_account(
        db, user_id=uid, institution="Silk Road Banking", account_last4="0838", currency="HKD", create_if_missing=True
    )
    stmt = await _authoritative_bank_statement(
        db,
        user_id=uid,
        primary_account=hkd_bank,
        institution="Silk Road Banking",
        account_last4="0838",
        primary_currency="HKD",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        balances=(
            StatementBalanceFact(currency="HKD", opening=Decimal("10000.00"), closing=Decimal("12500.00")),
            StatementBalanceFact(currency="USD", opening=Decimal("5000.00"), closing=Decimal("6111.11")),
        ),
        transactions=(
            ExtractedTransactionFact(
                fact_id="t-hkd-in",
                transaction_date=date(2025, 6, 15),
                description="HKD Retainer",
                amount=Decimal("2500.00"),
                direction="IN",
                currency="HKD",
                balance_after=Decimal("12500.00"),
                confidence=Decimal("0.99"),
            ),
            ExtractedTransactionFact(
                fact_id="t-usd-in",
                transaction_date=date(2025, 6, 15),
                description="USD Advisory Fee",
                amount=Decimal("1234.56"),
                direction="IN",
                currency="USD",
                balance_after=Decimal("6234.56"),
                confidence=Decimal("0.99"),
            ),
            ExtractedTransactionFact(
                fact_id="t-usd-out",
                transaction_date=date(2025, 6, 20),
                description="USD Cloud Subscription",
                amount=Decimal("123.45"),
                direction="OUT",
                currency="USD",
                balance_after=Decimal("6111.11"),
                confidence=Decimal("0.99"),
            ),
        ),
    )
    usd_bank = await resolve_secondary_currency_custody_account(db, statement=stmt, user_id=uid, currency="USD")
    hkd_inc, usd_inc, usd_exp = await seed_accounts(
        db,
        uid,
        ("Consulting HKD", AccountType.INCOME, "HKD"),
        ("Advisory USD", AccountType.INCOME, "USD"),
        ("Software USD", AccountType.EXPENSE, "USD"),
    )
    await initialize_opening_positions(
        db,
        uid,
        entry_date=date(2025, 1, 1),
        balances={hkd_bank.id: Decimal("10000.00")},
        currency="HKD",
        base_currency="SGD",
        fx_rates={"HKD": Decimal("0.171000")},
    )
    await initialize_opening_positions(
        db,
        uid,
        entry_date=date(2025, 1, 1),
        balances={usd_bank.id: Decimal("5000.00")},
        currency="USD",
        base_currency="SGD",
        fx_rates={"USD": Decimal("1.351000")},
    )
    for debit, credit, amt, ccy, fx in (
        (hkd_bank, hkd_inc, "2500.00", "HKD", Decimal("0.168500")),
        (usd_bank, usd_inc, "1234.56", "USD", Decimal("1.337000")),
        (usd_exp, usd_bank, "123.45", "USD", Decimal("1.337000")),
    ):
        await post_entry(
            db,
            user_id=uid,
            entry_date=date(2025, 6, 15),
            memo=f"Parity {ccy}",
            entry=Entry.transfer(debit=debit.id, credit=credit.id, money=Money(Decimal(amt), ccy), fx_rate=fx),
            base_currency="SGD",
        )
    await db.commit()

    bs_resp = await client.get("/reports/balance-sheet", params={"as_of_date": "2025-12-31", "currency": "SGD"})
    cf_resp = await client.get(
        "/reports/cash-flow", params={"start_date": "2025-01-01", "end_date": "2025-12-31", "currency": "SGD"}
    )
    pkg_resp = await client.get(
        "/reports/package",
        params={"start_date": "2025-01-01", "end_date": "2025-12-31", "as_of_date": "2025-12-31", "currency": "SGD"},
    )
    assert bs_resp.status_code == 200, bs_resp.text
    assert cf_resp.status_code == 200, cf_resp.text
    assert pkg_resp.status_code == 200, pkg_resp.text

    bs = bs_resp.json()
    cf = cf_resp.json()
    pkg = pkg_resp.json()

    expected_cash = sum((Decimal(line["amount"]) for line in bs["assets"]), Decimal("0.00"))
    assert Decimal(cf["summary"]["ending_cash"]) == expected_cash
    assert bs["is_balanced"] is True
    assert pkg["sections"]["balance_sheet"]["is_balanced"] is True
    assert Decimal(pkg["sections"]["balance_sheet"]["cta_adjustment"]) == Decimal(bs["cta_adjustment"])
    assert Decimal(pkg["sections"]["cash_flow"]["summary"]["ending_cash"]) == expected_cash

    blocker_codes = {b["code"] for b in pkg["readiness"]["blockers"]}
    assert "balance_sheet_equation_failed" not in blocker_codes
    assert "statement_net_income_mismatch" not in blocker_codes
    assert "cash_identity_missing" not in blocker_codes


async def test_staggered_multi_account_coverage_and_all_period_cash_flow(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    """Staggered accounts preserve earliest_start for All while keeping simultaneous coverage_start for 1Y."""
    uid = test_user.id
    test_user.base_currency = "SGD"
    acct_a = await resolve_bank_custody_account(
        db, user_id=uid, institution="Alpha Bank", account_last4="1111", currency="SGD", create_if_missing=True
    )
    acct_b = await resolve_bank_custody_account(
        db, user_id=uid, institution="Beta Bank", account_last4="2222", currency="SGD", create_if_missing=True
    )
    [salary] = await seed_accounts(db, uid, ("Salary", AccountType.INCOME, "SGD"))

    await _authoritative_bank_statement(
        db,
        user_id=uid,
        primary_account=acct_a,
        institution="Alpha Bank",
        account_last4="1111",
        primary_currency="SGD",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 5, 31),
        balances=(StatementBalanceFact(currency="SGD", opening=Decimal("1000.00"), closing=Decimal("1500.00")),),
        transactions=(
            ExtractedTransactionFact(
                fact_id="alpha-1",
                transaction_date=date(2025, 3, 10),
                description="Q1 Salary",
                amount=Decimal("500.00"),
                direction="IN",
                currency="SGD",
                balance_after=Decimal("1500.00"),
                confidence=Decimal("0.99"),
            ),
        ),
    )
    await _authoritative_bank_statement(
        db,
        user_id=uid,
        primary_account=acct_b,
        institution="Beta Bank",
        account_last4="2222",
        primary_currency="SGD",
        period_start=date(2025, 9, 1),
        period_end=date(2025, 12, 31),
        balances=(StatementBalanceFact(currency="SGD", opening=Decimal("2000.00"), closing=Decimal("2300.00")),),
        transactions=(
            ExtractedTransactionFact(
                fact_id="beta-1",
                transaction_date=date(2025, 10, 10),
                description="Q4 Bonus",
                amount=Decimal("300.00"),
                direction="IN",
                currency="SGD",
                balance_after=Decimal("2300.00"),
                confidence=Decimal("0.99"),
            ),
        ),
    )
    await initialize_opening_positions(
        db,
        uid,
        entry_date=date(2025, 1, 1),
        balances={acct_a.id: Decimal("1000.00")},
        currency="SGD",
        base_currency="SGD",
    )
    await initialize_opening_positions(
        db,
        uid,
        entry_date=date(2025, 9, 1),
        balances={acct_b.id: Decimal("2000.00")},
        currency="SGD",
        base_currency="SGD",
    )
    await post_entry(
        db,
        user_id=uid,
        entry_date=date(2025, 3, 10),
        memo="Alpha Salary",
        entry=Entry.transfer(debit=acct_a.id, credit=salary.id, money=Money(Decimal("500.00"), "SGD")),
        base_currency="SGD",
    )
    await post_entry(
        db,
        user_id=uid,
        entry_date=date(2025, 10, 10),
        memo="Beta Bonus",
        entry=Entry.transfer(debit=acct_b.id, credit=salary.id, money=Money(Decimal("300.00"), "SGD")),
        base_currency="SGD",
    )
    await db.commit()

    cov_resp = await client.get("/reports/coverage", params={"as_of_date": "2025-12-31"})
    assert cov_resp.status_code == 200, cov_resp.text
    cov = cov_resp.json()
    assert cov["coverage_start"] == "2025-09-01"
    assert cov["earliest_start"] == "2025-01-01"

    cf_resp = await client.get(
        "/reports/cash-flow", params={"start_date": "2025-01-01", "end_date": "2025-12-31", "currency": "SGD"}
    )
    assert cf_resp.status_code == 200, cf_resp.text
    cf = cf_resp.json()
    assert cf["proof_state"] == "proven"
    assert "opening_coverage_starts_after_period" not in cf["proof_reasons"]
    assert Decimal(cf["summary"]["beginning_cash"]) == Decimal("1000.00")
    assert Decimal(cf["summary"]["net_cash_flow"]) == Decimal("800.00")
    assert Decimal(cf["cash_bridge"]["opening_stock_adjustment"]) == Decimal("2000.00")
    assert Decimal(cf["summary"]["ending_cash"]) == Decimal("3800.00")
