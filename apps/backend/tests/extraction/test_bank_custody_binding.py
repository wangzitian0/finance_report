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
    verify_concurrent_first_custody_imports,
    verify_historical_custody_adoption_case,
    verify_invalid_custody_evidence_case,
    verify_real_custody_migration,
)
from tests.factories import AccountFactory, UserFactory, seed_parsed_statement


async def test_rename_preserves_source_custody(db, test_user):
    first = await parse(db, test_user.id)
    assert (await parse(db, test_user.id)).account_id == first.account_id
    await update_account(
        first.account_id, AccountUpdate(name="Synthetic household savings"), RequestContext(db, test_user.id)
    )
    assert (await parse(db, test_user.id)).account_id == first.account_id and await db.scalar(
        select(func.count()).select_from(Account).where(Account.user_id == test_user.id)
    ) == 1


async def test_concurrent_first_imports_share_one_binding(db_engine):
    await verify_concurrent_first_custody_imports(db_engine)


async def test_custody_key_dimensions_remain_separate(db, test_user):
    other = await UserFactory.create_async(db, email=f"custody-other-{test_user.id}@example.invalid")
    await db.commit()
    ids = [
        (await parse(db, test_user.id)).account_id,
        (await parse(db, test_user.id, account_last4="0002")).account_id,
        (await parse(db, test_user.id, currency="USD")).account_id,
        (await parse(db, test_user.id, institution="DBS Alternate")).account_id,
        (await parse(db, other.id)).account_id,
    ]
    assert len(set(ids)) == 5


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
    account = AccountFactory.build(
        user_id=owner.id,
        currency="USD" if condition == "currency" else "SGD",
        type=AccountType.EXPENSE if condition == "type" else AccountType.ASSET,
        is_active=condition != "archived",
    )
    db.add(account)
    await db.commit()
    if condition == "conflict":
        await parse(db, test_user.id)
    with pytest.raises(ExtractionError, match="[Cc]ustody|[Aa]ccount"):
        await parse(db, test_user.id, account_id=account.id)


async def test_archived_binding_is_not_replaced(db, test_user):
    source = await parse(db, test_user.id)
    (await db.get(Account, source.account_id)).is_active = False
    await db.commit()
    with pytest.raises(ExtractionError, match="active|archived"):
        await parse(db, test_user.id)


async def test_rejected_parse_does_not_leave_orphan_custody(db, test_user):
    rejected = await parse(db, test_user.id, closing_balance="9999")
    assert (rejected.status, rejected.account_id) == (BankStatementStatus.REJECTED, None)
    assert (
        await db.scalar(select(func.count()).select_from(Account).where(Account.user_id == test_user.id)) == 0
        and await db.scalar(text("SELECT count(*) FROM bank_custody_bindings")) == 0
    )
    accepted = await parse(db, test_user.id)
    assert (await parse(db, test_user.id, closing_balance="9999")).status == BankStatementStatus.REJECTED
    assert (
        await db.get(Account, accepted.account_id) is not None
        and await db.scalar(text("SELECT count(*) FROM bank_custody_bindings")) == 1
    )


async def test_custody_allocation_rolls_back_with_failed_unit_of_work(db, test_user):
    with pytest.raises(RuntimeError, match="synthetic downstream failure"):
        async with db.begin_nested():
            await resolve_bank_custody(
                db, user_id=test_user.id, institution="DBS", account_last4="2468", currency="SGD"
            )
            raise RuntimeError("synthetic downstream failure")
    assert (
        await db.scalar(select(func.count()).select_from(Account).where(Account.user_id == test_user.id)) == 0
        and await db.scalar(text("SELECT count(*) FROM bank_custody_bindings")) == 0
    )


async def test_real_custody_migration_installs_unique_key(db, test_user):
    await verify_real_custody_migration(db, test_user)


@pytest.mark.parametrize("ambiguous", [False, True])
async def test_explicit_selection_resolves_only_unique_legacy_history(db, test_user, ambiguous):
    selected = None
    for _ in range(2 if ambiguous else 1):
        account = AccountFactory.build(user_id=test_user.id, name="Legacy retained custody", currency="SGD")
        db.add(account)
        await db.flush()
        source = await seed_parsed_statement(db, test_user.id)
        source.statement.account_id, source.statement.account_last4, source.statement.institution = (
            account.id,
            "2468",
            "DBS",
        )
        selected = account.id
    await db.commit()
    with pytest.raises(ExtractionError, match="Historical custody"):
        await parse(db, test_user.id)
    await db.rollback()
    if ambiguous:
        with pytest.raises(ExtractionError, match="Ambiguous historical"):
            await parse(db, test_user.id, account_id=selected)
    else:
        assert (await parse(db, test_user.id, account_id=selected)).account_id == selected


async def test_confirmed_create_reuses_and_mapped_posting_rejects_contradictory_custody(db, test_user):
    first = await parse(db, test_user.id)
    pending_create = await seed_parsed_statement(db, test_user.id)
    pending_create.statement.institution, pending_create.statement.account_last4 = "DBS", "2468"
    await db.commit()
    assert (
        await create_statement_account_from_confirmation(db, pending_create.statement, test_user.id)
    ).id == first.account_id and pending_create.statement.account_id == first.account_id

    other = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(other)
    await db.flush()
    pending_map = await seed_parsed_statement(db, test_user.id)
    pending_map.statement.institution, pending_map.statement.account_last4, pending_map.statement.account_id = (
        "DBS",
        "2468",
        other.id,
    )
    await db.commit()
    with pytest.raises(ValueError, match="contradicts"):
        await resolve_statement_posting_account(db, pending_map.statement, test_user.id)


@pytest.mark.parametrize("seam", ["create", "posting"])
async def test_brokerage_sources_do_not_allocate_bank_binding(db, test_user, seam):
    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    document = UploadedDocument(
        user_id=test_user.id,
        file_path="synthetic-broker.pdf",
        file_hash=f"b-{test_user.id.hex}",
        original_filename="synthetic-broker.pdf",
        document_type=DocumentType.BROKERAGE_STATEMENT,
    )
    db.add_all([account, document])
    await db.flush()
    statement = StatementSummary(
        user_id=test_user.id,
        uploaded_document_id=document.id,
        file_hash=document.file_hash,
        institution="IBKR",
        account_last4="2468",
        currency="SGD",
        account_id=account.id,
        status=BankStatementStatus.PARSED,
    )
    db.add(statement)
    await db.flush()
    resolver = create_statement_account_from_confirmation if seam == "create" else resolve_statement_posting_account
    assert (await resolver(db, statement, test_user.id)).id == account.id and await db.scalar(
        select(func.count()).select_from(BankCustodyBinding)
    ) == 0


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
    document = None if document_kind is None else SimpleNamespace(document_type=document_kind)
    assert is_bank_custody_source(source, document) is (
        typed == "bank" if typed is not None else document_kind is not DocumentType.BROKERAGE_STATEMENT
    )


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
    account = await AccountFactory.create_async(db, user_id=test_user.id, currency="SGD")
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
    assert payload()["institution"] == "DBS"
