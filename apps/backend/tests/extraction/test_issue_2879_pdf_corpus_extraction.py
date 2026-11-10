"""AC-extraction.source-routing.2: Tests for Issue #2879 brokerage cash-ledger classification, multi-currency posting, and credit-card sign normalization."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from src.extraction import (
    BankStatementStatus,
    DocumentSource,
    EconomicIntent,
    StatementEvidenceType,
    StatementSourceType,
)
from src.extraction.base.validation import (
    bank_currency_balances,
    normalize_statement_balance_payload,
    validate_balance,
    validate_balance_per_currency,
)
from src.extraction.extension.brokerage_positions import parse_brokerage_positions
from src.extraction.extension.prompts.statement import get_parsing_prompt
from src.extraction.extension.result_contract import statement_evidence_type
from src.extraction.extension.review_queue import _plan_entry_command
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_parsing import route_brokerage_for_review_if_present
from src.extraction.extension.statement_posting import try_auto_post_statement_opening_balance
from src.extraction.extension.statement_validation import validate_balance_chain
from src.ledger import Account, AccountType, list_opening_positions
from src.schemas.review import BalanceValidationResult
from tests.statement_ingestion import (
    parse_and_load_statement_projection,
    posting_dependencies,
    reviewed_posting_inputs,
)


def test_brokerage_prompt_includes_opening_and_closing_balances_and_cash_rules():
    """AC-extraction.source-routing.2: BROKERAGE_POSITIONS_PROMPT includes opening_balance, closing_balance, and cash-only instructions."""
    prompt = get_parsing_prompt("Moomoo", document_kind="brokerage")
    assert '"opening_balance"' in prompt
    assert '"closing_balance"' in prompt
    assert '"balance_after"' in prompt
    assert "omit `positions` or return an empty `positions` array" in prompt.lower()


def test_statement_evidence_type_classifies_cash_only_brokerage_as_transaction_ledger():
    """AC-extraction.source-routing.2: Empty positions=[] with non-empty transactions classifies as TRANSACTION_LEDGER."""
    cash_only_payload = {
        "institution": "Moomoo Financial Singapore Pte. Ltd.",
        "account_last4": "7742",
        "currency": "SGD",
        "period_start": "2025-05-01",
        "period_end": "2025-05-31",
        "positions": [],
        "transactions": [
            {
                "date": "2025-05-02",
                "description": "FAST DEPOSIT - DBS BANK REF 99281736",
                "amount": "5000.00",
                "direction": "IN",
                "balance_after": "15000.00",
                "currency": "SGD",
            },
            {
                "date": "2025-05-20",
                "description": "MONEY MARKET FUND YIELD DISTRIBUTION",
                "amount": "28.45",
                "direction": "IN",
                "balance_after": "15028.45",
                "currency": "SGD",
            },
        ],
    }
    positions = parse_brokerage_positions(
        cash_only_payload,
        filename="moomoo_statement_fixture.pdf",
        institution="Moomoo Financial Singapore Pte. Ltd.",
    )
    assert positions == []

    evidence = statement_evidence_type(
        is_brokerage=True,
        provider_payload=cash_only_payload,
        positions=positions,
    )
    assert evidence is StatementEvidenceType.TRANSACTION_LEDGER

    futu_positions = parse_brokerage_positions(
        {
            **cash_only_payload,
            "institution": "Futu Securities International (Hong Kong) Limited",
            "currency": "HKD",
        },
        filename="futu_statement_fixture.pdf",
        institution="Futu Securities International (Hong Kong) Limited",
    )
    assert futu_positions == []


async def test_cash_only_brokerage_derives_balances_binds_custody_and_auto_approves(db, test_user, monkeypatch):
    """AC-extraction.source-routing.2: Cash-only brokerage payload derives missing balances, binds custody, and auto-approves."""
    service = ExtractionService()
    raw_payload = {
        "institution": "Futu Securities",
        "account_last4": "8821",
        "currency": "HKD",
        "period_start": "2025-05-01",
        "period_end": "2025-05-31",
        "opening_balance": None,
        "closing_balance": None,
        "positions": [],
        "transactions": [
            {
                "date": "2025-05-03",
                "description": "EDDA DEPOSIT - HSBC HK",
                "amount": "20000.00",
                "direction": "IN",
                "balance_after": "70000.00",
                "currency": "HKD",
            },
            {
                "date": "2025-05-12",
                "description": "DIVIDEND - 00700 TENCENT",
                "amount": "680.00",
                "direction": "IN",
                "balance_after": "70680.00",
                "currency": "HKD",
            },
            {
                "date": "2025-05-19",
                "description": "PLATFORM USAGE FEE",
                "amount": "15.00",
                "direction": "OUT",
                "balance_after": "70665.00",
                "currency": "HKD",
            },
            {
                "date": "2025-05-27",
                "description": "FPS WITHDRAWAL TO BANK ACCOUNT",
                "amount": "8000.00",
                "direction": "OUT",
                "balance_after": "62665.00",
                "currency": "HKD",
            },
        ],
    }
    service._extract_vision_source = AsyncMock(return_value=raw_payload)
    monkeypatch.setattr(
        "src.extraction.extension.service.read_pdf_text_layer",
        lambda *_args, **_kwargs: "Opening Balance 50,000.00 Closing Balance 62,665.00",
    )

    source = DocumentSource.resolve(
        path=Path("futu_statement_fixture.pdf"),
        content=b"%PDF-1.4 futu fixture",
    )
    result, statement, txns = await parse_and_load_statement_projection(
        service,
        db=db,
        user_id=test_user.id,
        institution="Futu Securities",
        source=source,
    )
    assert result.source_type is StatementSourceType.BROKERAGE
    assert result.evidence_type is StatementEvidenceType.TRANSACTION_LEDGER
    assert result.missing_required_facts == ()
    assert statement.opening_balance == Decimal("50000.00")
    assert statement.closing_balance == Decimal("62665.00")
    assert statement.account_id is not None
    assert statement.balance_validated is True
    assert statement.status == BankStatementStatus.APPROVED
    assert len(txns) == 4

    await route_brokerage_for_review_if_present(
        summary=statement,
        db=db,
        user_id=test_user.id,
        filename="futu_statement_fixture.pdf",
        institution="Futu Securities",
        payload=raw_payload,
    )
    assert statement.validation_error is None


def test_multicurrency_running_balance_synthesis_and_top_level_backfill():
    """AC-extraction.source-routing.2: Multi-currency transactions without balances array synthesize per-currency balances."""
    payload = {
        "institution": "Silk Road Bank",
        "account_last4": "6355",
        "currency": "HKD",
        "period_start": "2025-06-01",
        "period_end": "2025-06-30",
        "opening_balance": None,
        "closing_balance": None,
        "transactions": [
            {
                "date": "2025-06-05",
                "description": "FPS TRANSFER IN",
                "amount": "5000.00",
                "direction": "IN",
                "balance_after": "25000.00",
                "currency": "HKD",
            },
            {
                "date": "2025-06-12",
                "description": "UTILITY BILL PAYMENT",
                "amount": "800.00",
                "direction": "OUT",
                "balance_after": "24200.00",
                "currency": "HKD",
            },
            {
                "date": "2025-06-08",
                "description": "USD WIRE DEPOSIT",
                "amount": "1000.00",
                "direction": "IN",
                "balance_after": "3500.00",
                "currency": "USD",
            },
            {
                "date": "2025-06-18",
                "description": "USD CARD SETTLEMENT",
                "amount": "200.00",
                "direction": "OUT",
                "balance_after": "3300.00",
                "currency": "USD",
            },
        ],
    }
    normalized = normalize_statement_balance_payload(payload)
    assert normalized["opening_balance"] == "20000.00"
    assert normalized["closing_balance"] == "24200.00"
    assert normalized["balances"] == [
        {"currency": "HKD", "opening": "20000.00", "closing": "24200.00"},
        {"currency": "USD", "opening": "2500.00", "closing": "3300.00"},
    ]

    derived_buckets = bank_currency_balances(payload)
    assert derived_buckets == [
        {"currency": "HKD", "opening": "20000.00", "closing": "24200.00"},
        {"currency": "USD", "opening": "2500.00", "closing": "3300.00"},
    ]
    per_ccy = validate_balance_per_currency(normalized)
    assert per_ccy["balance_valid"] is True


def test_balance_validation_result_allows_none_opening_balance():
    """AC-extraction.source-routing.2: BalanceValidationResult accepts opening_balance=None without raising ValidationError."""
    model = BalanceValidationResult(
        opening_balance=None,
        closing_balance=None,
        calculated_closing="100.00",
        opening_delta="0",
        closing_delta="100.00",
        opening_match=False,
        closing_match=False,
        validated_at="2025-06-30T00:00:00Z",
    )
    assert model.opening_balance is None


async def test_multicurrency_statement_posts_per_currency_custody_accounts_and_opening_balances(db, test_user):
    """AC-extraction.source-routing.2: Multi-currency statement resolves per-currency custody accounts and posts opening balances for each."""
    service = ExtractionService()
    payload = {
        "institution": "Silk Road Bank",
        "account_last4": "6355",
        "currency": "HKD",
        "period_start": "2025-06-01",
        "period_end": "2025-06-30",
        "opening_balance": None,
        "closing_balance": None,
        "transactions": [
            {
                "date": "2025-06-05",
                "description": "HKD DEPOSIT",
                "amount": "5000.00",
                "direction": "IN",
                "balance_after": "25000.00",
                "currency": "HKD",
            },
            {
                "date": "2025-06-10",
                "description": "USD DEPOSIT",
                "amount": "1000.00",
                "direction": "IN",
                "balance_after": "3500.00",
                "currency": "USD",
            },
        ],
    }
    service._extract_vision_source = AsyncMock(return_value=payload)
    source = DocumentSource.resolve(
        path=Path("bsb_004_silk_road.pdf"),
        content=uuid4().bytes,
    )
    _, statement, txns = await parse_and_load_statement_projection(
        service,
        db=db,
        user_id=test_user.id,
        institution="Silk Road Bank",
        source=source,
    )
    assert statement.status == BankStatementStatus.APPROVED
    assert len(statement.typed_currency_balances()) == 2

    hkd_txn = next(t for t in txns if t.currency == "HKD")
    usd_txn = next(t for t in txns if t.currency == "USD")

    fx_provider = AsyncMock(return_value=Decimal("1.35"))
    hkd_decision, hkd_counter = await reviewed_posting_inputs(
        db,
        user_id=test_user.id,
        transaction=hkd_txn,
        intent=EconomicIntent.INCOME,
    )
    usd_decision, usd_counter = await reviewed_posting_inputs(
        db,
        user_id=test_user.id,
        transaction=usd_txn,
        intent=EconomicIntent.INCOME,
    )
    hkd_account = await db.get(Account, statement.account_id)
    assert hkd_account is not None
    assert hkd_account.currency == "HKD"

    hkd_plan = await _plan_entry_command(
        db,
        hkd_txn,
        user_id=test_user.id,
        base_currency="SGD",
        auto_post=True,
        preloaded_statement=statement,
        preloaded_bank_account=hkd_account,
        fx_rate_provider=fx_provider,
        disposition=hkd_decision,
        counter_account=hkd_counter,
    )
    usd_plan = await _plan_entry_command(
        db,
        usd_txn,
        user_id=test_user.id,
        base_currency="SGD",
        auto_post=True,
        preloaded_statement=statement,
        preloaded_bank_account=hkd_account,
        fx_rate_provider=fx_provider,
        disposition=usd_decision,
        counter_account=usd_counter,
    )
    hkd_debit_account_id = hkd_plan.lines_data[0]["account_id"]
    usd_debit_account_id = usd_plan.lines_data[0]["account_id"]
    assert hkd_debit_account_id == hkd_account.id
    assert usd_debit_account_id != hkd_account.id

    usd_account = await db.get(Account, usd_debit_account_id)
    assert usd_account is not None
    assert usd_account.currency == "USD"
    assert usd_account.type == AccountType.ASSET

    deps = posting_dependencies()
    deps_with_fx = replace(deps, fx_rate_provider=fx_provider)
    changed = await try_auto_post_statement_opening_balance(
        db,
        statement,
        test_user.id,
        dependencies=deps_with_fx,
    )
    assert changed is True

    positions = await list_opening_positions(db, user_id=test_user.id, as_of=date(2025, 12, 31))
    by_account = {p.account_id: p for p in positions}
    assert hkd_account.id in by_account
    assert usd_account.id in by_account
    assert by_account[hkd_account.id].amount == Decimal("20000.00")
    assert by_account[usd_account.id].amount == Decimal("2500.00")


async def test_credit_card_positive_balance_owed_sign_normalization(db, test_user):
    """AC-extraction.source-routing.2: Credit-card statement with positive balance-owed convention normalizes to negative liability balances."""
    cc_payload = {
        "institution": "Liberty National Credit Card",
        "account_last4": "4102",
        "currency": "USD",
        "period_start": "2025-03-01",
        "period_end": "2025-03-31",
        "opening_balance": "1847.32",
        "closing_balance": "9532.91",
        "transactions": [
            {
                "date": "2025-03-05",
                "description": "AUTOPAY PAYMENT - THANK YOU",
                "amount": "13.84",
                "direction": "IN",
                "balance_after": "1833.48",
                "currency": "USD",
            },
            {
                "date": "2025-03-14",
                "description": "FLIGHT & HOTEL PURCHASE",
                "amount": "7699.43",
                "direction": "OUT",
                "balance_after": "9532.91",
                "currency": "USD",
            },
        ],
    }
    normalized = normalize_statement_balance_payload(cc_payload)
    assert normalized["opening_balance"] == "-1847.32"
    assert normalized["closing_balance"] == "-9532.91"
    assert normalized["transactions"][0]["balance_after"] == "-1833.48"
    assert normalized["transactions"][1]["balance_after"] == "-9532.91"

    verdict = validate_balance(cc_payload)
    assert verdict["balance_valid"] is True
    assert verdict["expected_closing"] == "-9532.91"
    assert verdict["actual_closing"] == "-9532.91"

    service = ExtractionService()
    service._extract_vision_source = AsyncMock(return_value=cc_payload)
    source = DocumentSource.resolve(
        path=Path("bsb_002_liberty_national.pdf"),
        content=uuid4().bytes,
    )
    _, statement, txns = await parse_and_load_statement_projection(
        service,
        db=db,
        user_id=test_user.id,
        institution="Liberty National Credit Card",
        source=source,
    )
    assert statement.opening_balance == Decimal("-1847.32")
    assert statement.closing_balance == Decimal("-9532.91")
    assert statement.balance_validated is True

    # Also verify validate_balance_chain normalizes a pre-existing positive-balance-owed statement in place.
    statement.opening_balance = Decimal("1847.32")
    statement.closing_balance = Decimal("9532.91")
    for t in txns:
        if t.balance_after is not None:
            t.balance_after = abs(t.balance_after)
    chain_result = await validate_balance_chain(
        db,
        statement.id,
        statement=statement,
        transactions=txns,
    )
    assert chain_result["balance_valid"] is True
    assert chain_result["opening_balance"] == "-1847.32"
    assert chain_result["closing_balance"] == "-9532.91"
    assert statement.opening_balance == Decimal("-1847.32")
    assert statement.closing_balance == Decimal("-9532.91")
    assert all(t.balance_after < Decimal("0") for t in txns if t.balance_after is not None)


def test_normalize_statement_balance_payload_edge_cases():
    """AC-extraction.source-routing.2: Edge cases in balance derivation and normalization fail closed without corrupting payload."""
    from src.extraction.base.validation import _derive_running_balance_endpoints, _safe_parse_decimal

    assert _safe_parse_decimal("") is None
    assert _safe_parse_decimal("not-a-number") is None
    assert _safe_parse_decimal(True) is None
    assert normalize_statement_balance_payload("not-a-dict") == "not-a-dict"  # type: ignore[arg-type]

    # Chain break in running balance returns None
    broken_chain = [
        {"amount": "100.00", "direction": "IN", "balance_after": "1100.00", "currency": "USD"},
        {"amount": "50.00", "direction": "OUT", "balance_after": "900.00", "currency": "USD"},
    ]
    assert _derive_running_balance_endpoints(broken_chain, currency="USD") is None

    # Explicit closing balance mismatch with running balance returns None
    valid_chain = [
        {"amount": "100.00", "direction": "IN", "balance_after": "1100.00", "currency": "USD"},
        {"amount": "50.00", "direction": "OUT", "balance_after": "1050.00", "currency": "USD"},
    ]
    assert (
        _derive_running_balance_endpoints(
            valid_chain,
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("9999.00"),
            currency="USD",
        )
        is None
    )

    # Multi-currency where one currency bucket has broken chain does not synthesize balances
    mc_broken = {
        "currency": "USD",
        "transactions": [
            {"amount": "100.00", "direction": "IN", "balance_after": "1100.00", "currency": "USD"},
            {"amount": "50.00", "direction": "OUT", "balance_after": "900.00", "currency": "EUR"},
            {"amount": "10.00", "direction": "OUT", "balance_after": "700.00", "currency": "EUR"},
        ],
    }
    res = normalize_statement_balance_payload(mc_broken)
    assert "balances" not in res

    # Single-currency with missing top-level currency backfills currency from transaction
    single_no_header_ccy = {
        "currency": None,
        "opening_balance": None,
        "closing_balance": None,
        "transactions": valid_chain,
    }
    res_single = normalize_statement_balance_payload(single_no_header_ccy)
    assert res_single["currency"] == "USD"
    assert res_single["opening_balance"] == "1000.00"
    assert res_single["closing_balance"] == "1050.00"


async def test_multicurrency_fallback_account_without_last4_and_custody_source_guard(db, test_user):
    """AC-extraction.source-routing.2: Multi-currency statement without account_last4 falls back to get_or_create_account and custody guard rejects position snapshot."""
    from types import SimpleNamespace

    from src.extraction.extension.custody_binding import is_bank_custody_source

    holdings_source = SimpleNamespace(
        source_type=StatementSourceType.BROKERAGE,
        evidence_type=StatementEvidenceType.POSITION_SNAPSHOT,
        positions=("pos1",),
    )
    assert is_bank_custody_source(holdings_source, None) is False  # type: ignore[arg-type]

    service = ExtractionService()
    payload = {
        "institution": "NoLast4 MultiCcy Bank",
        "account_last4": None,
        "currency": "HKD",
        "period_start": "2025-07-01",
        "period_end": "2025-07-31",
        "opening_balance": None,
        "closing_balance": None,
        "transactions": [
            {
                "date": "2025-07-05",
                "description": "HKD DEPOSIT",
                "amount": "1000.00",
                "direction": "IN",
                "balance_after": "6000.00",
                "currency": "HKD",
            },
            {
                "date": "2025-07-10",
                "description": "USD DEPOSIT",
                "amount": "500.00",
                "direction": "IN",
                "balance_after": "1500.00",
                "currency": "USD",
            },
        ],
    }
    service._extract_vision_source = AsyncMock(return_value=payload)
    source = DocumentSource.resolve(
        path=Path("no_last4_multiccy.pdf"),
        content=uuid4().bytes,
    )
    _, statement, txns = await parse_and_load_statement_projection(
        service,
        db=db,
        user_id=test_user.id,
        institution="NoLast4 MultiCcy Bank",
        source=source,
    )
    hkd_account = Account(
        user_id=test_user.id,
        name="NoLast4 MultiCcy Bank (HKD)",
        type=AccountType.ASSET,
        currency="HKD",
    )
    db.add(hkd_account)
    await db.flush()
    statement.account_id = hkd_account.id

    usd_txn = next(t for t in txns if t.currency == "USD")
    fx_provider = AsyncMock(return_value=Decimal("1.35"))
    usd_decision, usd_counter = await reviewed_posting_inputs(
        db,
        user_id=test_user.id,
        transaction=usd_txn,
        intent=EconomicIntent.INCOME,
    )
    usd_plan = await _plan_entry_command(
        db,
        usd_txn,
        user_id=test_user.id,
        base_currency="SGD",
        auto_post=True,
        preloaded_statement=statement,
        preloaded_bank_account=hkd_account,
        fx_rate_provider=fx_provider,
        disposition=usd_decision,
        counter_account=usd_counter,
    )
    assert usd_plan.lines_data[0]["account_id"] != hkd_account.id

    deps_with_fx = replace(posting_dependencies(), fx_rate_provider=fx_provider)
    changed = await try_auto_post_statement_opening_balance(
        db,
        statement,
        test_user.id,
        dependencies=deps_with_fx,
    )
    assert changed is True


async def test_persist_conform_statement_summary_preserves_currency_balances_on_existing_parsing_row(db, test_user):
    """AC-extraction.source-routing.2: Pre-created StatementSummary (status=PARSING) receives currency_balances during conform persistence."""
    import hashlib

    from src.extraction.orm.statement_summary import StatementSummary

    pdf_bytes = b"%PDF-1.4 silk road precreated"
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()
    precreated = StatementSummary(
        user_id=test_user.id,
        file_hash=file_hash,
        institution="Silk Road Banking",
        status=BankStatementStatus.PARSING,
        currency_balances=None,
    )
    db.add(precreated)
    await db.flush()

    service = ExtractionService()
    payload = {
        "institution": "Silk Road Banking",
        "account_last4": "7323",
        "currency": "HKD",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "42580.00",
        "closing_balance": "18364.12",
        "balances": [
            {"currency": "HKD", "opening": "42580.00", "closing": "18364.12"},
            {"currency": "USD", "opening": "150000.00", "closing": "170150.85"},
        ],
        "transactions": [
            {
                "date": "2025-01-10",
                "description": "HKD RENT PAYMENT",
                "amount": "24215.88",
                "direction": "OUT",
                "balance_after": "18364.12",
                "currency": "HKD",
            },
            {
                "date": "2025-01-15",
                "description": "USD TRADE SETTLEMENT",
                "amount": "20150.85",
                "direction": "IN",
                "balance_after": "170150.85",
                "currency": "USD",
            },
        ],
    }
    service._extract_vision_source = AsyncMock(return_value=payload)
    source = DocumentSource.resolve(
        path=Path("bsb_004_silk_road.pdf"),
        content=pdf_bytes,
    )
    _, persisted_summary, _ = await parse_and_load_statement_projection(
        service,
        db=db,
        user_id=test_user.id,
        institution="Silk Road Banking",
        source=source,
    )
    assert persisted_summary.id == precreated.id
    assert precreated.currency_balances is not None
    by_ccy = {b.currency.code: b for b in precreated.typed_currency_balances()}
    assert "HKD" in by_ccy
    assert "USD" in by_ccy
    assert by_ccy["HKD"].opening.amount == Decimal("42580.00")
    assert by_ccy["HKD"].closing.amount == Decimal("18364.12")
    assert by_ccy["USD"].opening.amount == Decimal("150000.00")
    assert by_ccy["USD"].closing.amount == Decimal("170150.85")


async def test_coverage_bank_custody_and_package_contribution_include_transaction_ledger_brokerage(
    db, test_user, monkeypatch
):
    """AC-extraction.source-routing.2: coverage_bank_custody_account_ids and _is_bank_statement_contribution include TRANSACTION_LEDGER brokerage statements."""
    from types import SimpleNamespace

    from src.extraction.extension.custody_binding import coverage_bank_custody_account_ids
    from src.extraction.extension.reviewed_statement_envelope import persist_statement_extraction_result
    from src.reporting.extension.package_document import _is_bank_statement_contribution

    service = ExtractionService()
    raw_payload = {
        "institution": "Moomoo Financial Singapore",
        "account_last4": "7742",
        "currency": "SGD",
        "period_start": "2025-05-01",
        "period_end": "2025-05-31",
        "opening_balance": "10000.00",
        "closing_balance": "15028.45",
        "positions": [],
        "transactions": [
            {
                "date": "2025-05-02",
                "description": "FAST DEPOSIT",
                "amount": "5028.45",
                "direction": "IN",
                "balance_after": "15028.45",
                "currency": "SGD",
            }
        ],
    }
    service._extract_vision_source = AsyncMock(return_value=raw_payload)
    monkeypatch.setattr(
        "src.extraction.extension.service.read_pdf_text_layer",
        lambda *_args, **_kwargs: "Opening Balance 10,000.00 Closing Balance 15,028.45",
    )
    source = DocumentSource.resolve(
        path=Path("moomoo_statement_fixture.pdf"),
        content=uuid4().bytes,
    )
    result, statement, _ = await parse_and_load_statement_projection(
        service,
        db=db,
        user_id=test_user.id,
        institution="Moomoo Financial Singapore",
        source=source,
    )
    assert result.source_type is StatementSourceType.BROKERAGE
    assert result.evidence_type is StatementEvidenceType.TRANSACTION_LEDGER
    assert statement.account_id is not None

    await persist_statement_extraction_result(
        db,
        statement=statement,
        result=result,
        source_trace_record_id=uuid4(),
    )

    custody_ids = await coverage_bank_custody_account_ids(
        db,
        user_id=test_user.id,
        as_of=date(2025, 5, 31),
    )
    assert statement.account_id in custody_ids

    brokerage_ledger_contrib = SimpleNamespace(
        contribution_type="statement_source",
        payload=SimpleNamespace(source_result=result),
    )
    assert _is_bank_statement_contribution(brokerage_ledger_contrib) is True

    brokerage_holdings_contrib = SimpleNamespace(
        contribution_type="statement_source",
        payload=SimpleNamespace(
            source_result=SimpleNamespace(
                source_type=StatementSourceType.BROKERAGE,
                evidence_type=StatementEvidenceType.POSITION_SNAPSHOT,
            )
        ),
    )
    assert _is_bank_statement_contribution(brokerage_holdings_contrib) is False
    assert _is_bank_statement_contribution(SimpleNamespace(contribution_type="valuation")) is False
