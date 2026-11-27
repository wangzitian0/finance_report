from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select, text

from src.extraction import (
    BankStatementStatus,
    DocumentType,
    StatementEvidenceType,
    StatementSourceType,
    create_statement_account_from_confirmation,
    is_bank_custody_source,
    resolve_cash_flow_custody_ids,
    resolve_statement_posting_account,
)
from src.extraction.extension.custody_binding import resolve_bank_custody
from src.extraction.extension.service import ExtractionError
from src.extraction.orm.bank_custody_binding import BankCustodyBinding
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType
from src.request_context import RequestContext
from src.routers.accounts import update_account
from src.schemas.account import AccountUpdate
from tests.extraction._statement_run_helpers import (
    custody_parse as parse,
    custody_payload as payload,
    make_account,
    verify_concurrent_first_custody_imports,
    verify_historical_custody_adoption_case,
    verify_invalid_custody_evidence_case,
    verify_real_custody_migration,
)
from tests.factories import UserFactory, seed_parsed_statement


async def test_rename_preserves_source_custody_and_key_dimensions(db, test_user):
    first = await parse(db, test_user.id)
    assert (await parse(db, test_user.id)).account_id == first.account_id
    await update_account(
        first.account_id, AccountUpdate(name="Synthetic household savings"), RequestContext(db, test_user.id)
    )
    assert (await parse(db, test_user.id)).account_id == first.account_id and await db.scalar(
        select(func.count()).select_from(Account).where(Account.user_id == test_user.id)
    ) == 1

    other = await UserFactory.create_async(db, email=f"custody-other-{test_user.id}@example.invalid")
    await db.commit()
    ids = [
        (await parse(db, test_user.id)).account_id,
        (await parse(db, test_user.id, account_last4="0002")).account_id,
        (await parse(db, test_user.id, currency="USD")).account_id,
        (await parse(db, test_user.id, institution="DBS Alternate")).account_id,
        (await parse(db, other.id)).account_id,
    ]
    assert len(set(ids)) == 5 and payload()["institution"] == "DBS"


async def test_concurrent_first_imports_and_real_migration(db, db_engine, test_user):
    await verify_concurrent_first_custody_imports(db_engine)
    await verify_real_custody_migration(db, test_user)


@pytest.mark.parametrize("condition", ["unique", "ambiguous", "foreign", "source_mismatch", "source_original"])
async def test_historical_custody_adoption(db, test_user, condition):
    await verify_historical_custody_adoption_case(db, test_user, condition)


@pytest.mark.parametrize("condition", ["foreign", "currency", "archived", "type", "conflict"])
async def test_explicit_account_cannot_bypass_custody(db, test_user, condition):
    owner = (
        await UserFactory.create_async(db, email=f"explicit-foreign-{test_user.id}@example.invalid")
        if condition == "foreign"
        else test_user
    )
    account = await make_account(
        db,
        owner.id,
        name="Explicit Bank",
        currency="USD" if condition == "currency" else "SGD",
        type=AccountType.EXPENSE if condition == "type" else AccountType.ASSET,
    )
    account.is_active = condition != "archived"
    await db.commit()
    if condition == "conflict":
        await parse(db, test_user.id)
    with pytest.raises(ExtractionError, match="[Cc]ustody|[Aa]ccount"):
        await parse(db, test_user.id, account_id=account.id)


async def test_archived_binding_rejected_parse_and_rollback_safety(db, test_user):
    rejected = await parse(db, test_user.id, closing_balance="9999")
    assert (
        rejected.status,
        rejected.account_id,
        await db.scalar(select(func.count()).select_from(Account).where(Account.user_id == test_user.id)),
        await db.scalar(text("SELECT count(*) FROM bank_custody_bindings")),
    ) == (BankStatementStatus.REJECTED, None, 0, 0)

    with pytest.raises(RuntimeError, match="synthetic downstream failure"):
        async with db.begin_nested():
            await resolve_bank_custody(
                db, user_id=test_user.id, institution="DBS", account_last4="2468", currency="SGD"
            )
            raise RuntimeError("synthetic downstream failure")
    assert (
        await db.scalar(select(func.count()).select_from(Account).where(Account.user_id == test_user.id)),
        await db.scalar(text("SELECT count(*) FROM bank_custody_bindings")),
    ) == (0, 0)

    accepted = await parse(db, test_user.id)
    assert (
        (await parse(db, test_user.id, closing_balance="9999")).status,
        await db.get(Account, accepted.account_id) is not None,
        await db.scalar(text("SELECT count(*) FROM bank_custody_bindings")),
    ) == (BankStatementStatus.REJECTED, True, 1)

    (await db.get(Account, accepted.account_id)).is_active = False
    await db.commit()
    with pytest.raises(ExtractionError, match="active|archived"):
        await parse(db, test_user.id)


@pytest.mark.parametrize("ambiguous", [False, True])
async def test_explicit_selection_resolves_only_unique_legacy_history(db, test_user, ambiguous):
    uid, selected = test_user.id, None
    for _ in range(2 if ambiguous else 1):
        account = await make_account(db, uid, name="Legacy retained custody")
        source = await seed_parsed_statement(db, uid)
        source.statement.account_id, source.statement.account_last4, source.statement.institution = (
            account.id,
            "2468",
            "DBS",
        )
        selected = account.id
    await db.commit()
    with pytest.raises(ExtractionError, match="Historical custody"):
        await parse(db, uid)
    await db.rollback()
    if ambiguous:
        with pytest.raises(ExtractionError, match="Ambiguous historical"):
            await parse(db, uid, account_id=selected)
    else:
        assert (await parse(db, uid, account_id=selected)).account_id == selected


async def test_confirmed_create_reuses_and_mapped_posting_rejects_contradictory_custody(db, test_user):
    first = await parse(db, test_user.id)
    pending_create, pending_map, other = (
        await seed_parsed_statement(db, test_user.id),
        await seed_parsed_statement(db, test_user.id),
        await make_account(db, test_user.id, name="Other Bank"),
    )
    pending_create.statement.institution, pending_create.statement.account_last4 = "DBS", "2468"
    pending_map.statement.institution, pending_map.statement.account_last4, pending_map.statement.account_id = (
        "DBS",
        "2468",
        other.id,
    )
    await db.commit()
    assert (
        await create_statement_account_from_confirmation(db, pending_create.statement, test_user.id)
    ).id == first.account_id and pending_create.statement.account_id == first.account_id
    with pytest.raises(ValueError, match="contradicts"):
        await resolve_statement_posting_account(db, pending_map.statement, test_user.id)


@pytest.mark.parametrize("seam", ["create", "posting"])
async def test_brokerage_sources_do_not_allocate_bank_binding(db, test_user, seam):
    account = await make_account(db, test_user.id, name="Broker Cash")
    doc = UploadedDocument(
        user_id=test_user.id,
        file_path="synthetic-broker.pdf",
        file_hash=f"b-{test_user.id.hex}",
        original_filename="synthetic-broker.pdf",
        document_type=DocumentType.BROKERAGE_STATEMENT,
    )
    db.add(doc)
    await db.flush()
    stmt = StatementSummary(
        user_id=test_user.id,
        uploaded_document_id=doc.id,
        file_hash=doc.file_hash,
        institution="IBKR",
        account_last4="2468",
        currency="SGD",
        account_id=account.id,
        status=BankStatementStatus.PARSED,
    )
    db.add(stmt)
    await db.flush()
    assert (
        await (create_statement_account_from_confirmation if seam == "create" else resolve_statement_posting_account)(
            db, stmt, test_user.id
        )
    ).id == account.id and await db.scalar(select(func.count()).select_from(BankCustodyBinding)) == 0


@pytest.mark.parametrize("typed", [None, "bank", "brokerage"])
@pytest.mark.parametrize("document_kind", [None, DocumentType.BANK_STATEMENT, DocumentType.BROKERAGE_STATEMENT])
def test_bank_source_classification_is_shared(typed, document_kind):
    source = (
        None
        if typed is None
        else SimpleNamespace(
            source_type=StatementSourceType.BANK if typed == "bank" else StatementSourceType.BROKERAGE,
            evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        )
    )
    assert is_bank_custody_source(
        source, None if document_kind is None else SimpleNamespace(document_type=document_kind)
    ) is (typed == "bank" if typed is not None else document_kind is not DocumentType.BROKERAGE_STATEMENT)


@pytest.mark.parametrize(
    "failure",
    [
        "missing_document",
        "brokerage_document",
        "invalid_payload",
        "source_digest",
        "payload_digest",
        "archived_account",
        "missing_identity",
        "explicit_conflict",
    ],
)
async def test_historical_custody_rejects_invalid_evidence(db, test_user, failure):
    await verify_invalid_custody_evidence_case(db, test_user, failure)


@pytest.mark.parametrize(("active", "last4"), [(True, "9999"), (False, "8888")])
async def test_parse_fallback_custody_when_last4_is_missing(db, test_user, active, last4):
    account = await make_account(db, test_user.id, name=f"Fallback {last4}")
    account.is_active = active
    db.add(
        BankCustodyBinding(
            user_id=test_user.id, account_id=account.id, institution="DBS", account_last4=last4, currency="SGD"
        )
    )
    await db.commit()
    if active:
        stmt = await parse(db, test_user.id, account_id=None, account_last4=None)
        assert (stmt.account_id, stmt.account_last4) == (account.id, last4)
    else:
        with pytest.raises(ExtractionError, match="Custody account is archived"):
            await parse(db, test_user.id, account_id=None, account_last4=None)


async def test_credit_card_statement_allocates_liability_custody_and_validates_explicit_liability(db, test_user):
    stmt = await parse(
        db,
        test_user.id,
        institution="Liberty National Credit Card",
        account_last4="8899",
        currency="SGD",
        opening_balance="-1000.00",
        closing_balance="-1250.00",
        transactions=[
            {
                "date": "2026-01-10",
                "description": "Dining charge",
                "amount": "250.00",
                "direction": "OUT",
                "currency": "SGD",
                "balance_after": "-1250.00",
            }
        ],
    )
    assert stmt.account_id is not None
    account = await db.get(Account, stmt.account_id)
    assert account is not None
    assert account.type is AccountType.LIABILITY
    assert account.code == "AUTO-CARD"

    re_parsed = await parse(
        db,
        test_user.id,
        institution="Liberty National Credit Card",
        account_last4="8899",
        currency="SGD",
        account_id=account.id,
        opening_balance="-1250.00",
        closing_balance="-1000.00",
        transactions=[
            {
                "date": "2026-02-05",
                "description": "Card payment",
                "amount": "250.00",
                "direction": "IN",
                "currency": "SGD",
                "balance_after": "-1000.00",
            }
        ],
    )
    assert re_parsed.account_id == account.id


async def test_resolve_cash_flow_custody_ids_distinguishes_empty_liability_and_brokerage_cash(db, test_user):
    """Zero statements returns None; card-only returns empty set; brokerage ledger includes non-system ASSET."""
    from datetime import UTC, datetime
    from decimal import Decimal
    from hashlib import sha256
    from uuid import uuid4

    from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
    from tests.factories import UserFactory

    assert await resolve_cash_flow_custody_ids(db, user_id=test_user.id, as_of=date(2026, 3, 31)) is None

    card_stmt = await parse(
        db,
        test_user.id,
        institution="Card Bank",
        account_last4="9911",
        currency="SGD",
        opening_balance="-100.00",
        closing_balance="-120.00",
        transactions=[
            {
                "date": "2026-01-10",
                "description": "Spend",
                "amount": "20.00",
                "direction": "OUT",
                "currency": "SGD",
                "balance_after": "-120.00",
            }
        ],
    )
    card_stmt.status = BankStatementStatus.APPROVED
    await db.flush()
    assert await resolve_cash_flow_custody_ids(db, user_id=test_user.id, as_of=date(2026, 3, 31)) == frozenset()

    pos_user = await UserFactory.create_async(db)
    pos_acct = await make_account(db, pos_user.id, name="Broker Positions")
    pos_doc = UploadedDocument(
        user_id=pos_user.id,
        file_path="pos.pdf",
        file_hash=f"pos-{pos_user.id.hex}",
        original_filename="pos.pdf",
        document_type=DocumentType.BROKERAGE_STATEMENT,
    )
    db.add(pos_doc)
    await db.flush()
    pos_stmt = StatementSummary(
        user_id=pos_user.id,
        uploaded_document_id=pos_doc.id,
        file_hash=pos_doc.file_hash,
        institution="IBKR",
        account_id=pos_acct.id,
        currency="SGD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("1000.00"),
        status=BankStatementStatus.APPROVED,
    )
    db.add(pos_stmt)
    await db.flush()
    pos_rec = StatementExtractionResultRecord(
        user_id=pos_user.id,
        statement_id=pos_stmt.id,
        content_digest=sha256(f"pos:{pos_stmt.id}".encode()).hexdigest(),
        source_content_digest=sha256(f"pos-src:{pos_stmt.id}".encode()).hexdigest(),
        schema_version="2",
        producer_version="test",
        payload={
            "source_type": StatementSourceType.BROKERAGE.value,
            "evidence_type": StatementEvidenceType.POSITION_SNAPSHOT.value,
            "period_start": "2026-01-01",
        },
        source_trace_record_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    db.add(pos_rec)
    await db.flush()
    pos_stmt.current_extraction_result_id = pos_rec.id
    await db.flush()
    assert await resolve_cash_flow_custody_ids(db, user_id=pos_user.id, as_of=date(2026, 3, 31)) == frozenset()

    cash_acct = await make_account(db, pos_user.id, name="IBKR Cash")
    cash_doc = UploadedDocument(
        user_id=pos_user.id,
        file_path="cash.pdf",
        file_hash=f"cash-{pos_user.id.hex}",
        original_filename="cash.pdf",
        document_type=DocumentType.BROKERAGE_STATEMENT,
    )
    db.add(cash_doc)
    await db.flush()
    cash_stmt = StatementSummary(
        user_id=pos_user.id,
        uploaded_document_id=cash_doc.id,
        file_hash=cash_doc.file_hash,
        institution="IBKR",
        account_id=cash_acct.id,
        currency="SGD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("200.00"),
        status=BankStatementStatus.APPROVED,
    )
    db.add(cash_stmt)
    await db.flush()
    cash_rec = StatementExtractionResultRecord(
        user_id=pos_user.id,
        statement_id=cash_stmt.id,
        content_digest=sha256(f"cash:{cash_stmt.id}".encode()).hexdigest(),
        source_content_digest=sha256(f"cash-src:{cash_stmt.id}".encode()).hexdigest(),
        schema_version="2",
        producer_version="test",
        payload={
            "source_type": StatementSourceType.BROKERAGE.value,
            "evidence_type": StatementEvidenceType.TRANSACTION_LEDGER.value,
            "period_start": "2026-01-01",
        },
        source_trace_record_id=uuid4(),
        created_at=datetime.now(UTC),
    )
    db.add(cash_rec)
    await db.flush()
    cash_stmt.current_extraction_result_id = cash_rec.id
    await db.flush()
    assert await resolve_cash_flow_custody_ids(db, user_id=pos_user.id, as_of=date(2026, 3, 31)) == frozenset(
        {cash_acct.id}
    )
