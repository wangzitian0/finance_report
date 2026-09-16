"""Persistent custody identity regressions: generated sources, actual PostgreSQL."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.extraction import BankStatementStatus, DocumentSource, DocumentType
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType
from src.routers.accounts import update_account
from src.schemas.account import AccountUpdate
from tests.extraction.test_source_ingestion_integrity import _store_result
from tests.factories import AccountFactory, UserFactory
from tests.statement_ingestion import parse_and_load_statement_projection


def payload(**changes):
    return {
        "institution": "DBS",
        "account_last4": "2468",
        "currency": "SGD",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "opening_balance": "1000",
        "closing_balance": "1100",
        "transactions": [
            {
                "date": "2026-01-10",
                "description": "Synthetic receipt",
                "amount": "100",
                "direction": "IN",
                "currency": changes.get("currency", "SGD"),
                "balance_after": "1100",
            }
        ],
        **changes,
    }


async def parse(db, uid, *, account_id=None, **changes):
    service = ExtractionService()
    service._extract_vision_source = AsyncMock(return_value=payload(**changes))
    source = DocumentSource.resolve(path=Path("synthetic-custody.pdf"), content=uuid4().bytes)
    _, statement, _ = await parse_and_load_statement_projection(
        service, db=db, user_id=uid, institution=None, source=source, account_id=account_id
    )
    await db.commit()
    return statement


async def history(db, uid, account, *, corrupt=False):
    source = DocumentSource.resolve(path=Path("synthetic-history.pdf"), content=uuid4().bytes)
    service = ExtractionService()
    service._extract_vision_source = AsyncMock(return_value=payload())
    result = await service.parse_document(source, user_id=uid, account_id=account.id)
    document = UploadedDocument(
        user_id=uid,
        file_path=str(source.path),
        file_hash=source.content_hash,
        original_filename=source.filename,
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(document)
    await db.flush()
    summary = StatementSummary(
        user_id=uid,
        uploaded_document_id=document.id,
        file_hash=document.file_hash,
        account_id=account.id,
        institution="DBS",
        account_last4="2468",
        currency="SGD",
        status=BankStatementStatus.PARSED,
    )
    db.add(summary)
    await db.flush()
    await _store_result(db, summary, result)
    if corrupt:
        summary.account_last4 = "9999"
    await db.commit()
    return summary


async def test_rename_preserves_source_custody(db, test_user):
    """AC-extraction.custody-binding.1: names never identify physical custody."""
    first = await parse(db, test_user.id)
    control = await parse(db, test_user.id)
    assert control.account_id == first.account_id
    await update_account(first.account_id, AccountUpdate(name="Synthetic household savings"), db, test_user.id)
    later = await parse(db, test_user.id)
    assert later.account_id == first.account_id
    assert await db.scalar(select(func.count()).select_from(Account).where(Account.user_id == test_user.id)) == 1


async def test_concurrent_first_imports_share_one_binding(db_engine):
    """AC-extraction.custody-binding.2: independent transactions cannot win twice."""
    sessions = async_sessionmaker(db_engine, expire_on_commit=False)
    async with sessions() as db:
        user = await UserFactory.create_async(db, email=f"custody-race-{uuid4()}@example.invalid")
        uid = user.id
        # Widen a valid real-DB interleaving; no SELECT results are mocked.
        await db.execute(
            text(
                "CREATE FUNCTION custody_test_delay() RETURNS trigger AS $$ BEGIN PERFORM pg_sleep(0.1); RETURN NEW; END; $$ LANGUAGE plpgsql"
            )
        )
        await db.execute(
            text(
                "CREATE TRIGGER custody_test_delay BEFORE INSERT ON accounts FOR EACH ROW EXECUTE FUNCTION custody_test_delay()"
            )
        )
        await db.commit()

    async def first():
        async with sessions() as db:
            return (await parse(db, uid)).account_id

    try:
        ids = await asyncio.gather(first(), first())
        assert ids[0] == ids[1]
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Account).where(Account.user_id == uid)) == 1
            from src.extraction.orm.bank_custody_binding import BankCustodyBinding

            with pytest.raises(IntegrityError):
                async with db.begin_nested():
                    db.add(
                        BankCustodyBinding(
                            user_id=uid, institution="DBS", account_last4="2468", currency="SGD", account_id=ids[0]
                        )
                    )
                    await db.flush()
    finally:
        async with sessions() as db:
            await db.execute(text("DROP TRIGGER custody_test_delay ON accounts"))
            await db.execute(text("DROP FUNCTION custody_test_delay()"))
            await db.commit()


async def test_custody_key_dimensions_remain_separate(db, test_user):
    """AC-extraction.custody-binding.3: no fuzzy institution or cross-tenant collapse."""
    other = await UserFactory.create_async(db, email=f"custody-other-{uuid4()}@example.invalid")
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
    """AC-extraction.custody-binding.4: immutable source identity qualifies adoption."""
    owner = test_user
    if condition == "foreign":
        owner = await UserFactory.create_async(db, email=f"custody-foreign-{uuid4()}@example.invalid")
    account = AccountFactory.build(user_id=owner.id, name="Renamed historical account", currency="SGD")
    db.add(account)
    await db.flush()
    if condition == "foreign":
        with pytest.raises(IntegrityError, match="cross-user account"):
            async with db.begin_nested():
                await history(db, test_user.id, account)
        return
    await history(db, test_user.id, account, corrupt=condition in {"source_mismatch", "source_original"})
    if condition == "ambiguous":
        second = AccountFactory.build(user_id=test_user.id, currency="SGD")
        db.add(second)
        await db.flush()
        await history(db, test_user.id, second)
    if condition == "unique":
        assert (await parse(db, test_user.id)).account_id == account.id
    else:
        with pytest.raises(ExtractionError, match="[Hh]istorical|[Aa]mbiguous"):
            await parse(db, test_user.id, account_last4="9999" if condition == "source_mismatch" else "2468")


@pytest.mark.parametrize("condition", ["foreign", "currency", "archived", "type", "conflict"])
async def test_explicit_account_cannot_bypass_custody(db, test_user, condition):
    """AC-extraction.custody-binding.5: explicit UUIDs do not waive source safeguards."""
    owner = test_user
    if condition == "foreign":
        owner = await UserFactory.create_async(db, email=f"explicit-foreign-{uuid4()}@example.invalid")
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
    """AC-extraction.custody-binding.5: archival is an explicit review condition."""
    source = await parse(db, test_user.id)
    account = await db.get(Account, source.account_id)
    account.is_active = False
    await db.commit()
    with pytest.raises(ExtractionError, match="active|archived"):
        await parse(db, test_user.id)


async def test_rejected_parse_does_not_leave_orphan_custody(db, test_user):
    """AC-extraction.custody-binding.6: rejection cleans only its new allocation."""
    rejected = await parse(db, test_user.id, closing_balance="9999")
    assert rejected.status == BankStatementStatus.REJECTED
    assert rejected.account_id is None
    assert await db.scalar(select(func.count()).select_from(Account).where(Account.user_id == test_user.id)) == 0
    assert await db.scalar(text("SELECT count(*) FROM bank_custody_bindings")) == 0
    accepted = await parse(db, test_user.id)
    rejected_again = await parse(db, test_user.id, closing_balance="9999")
    assert rejected_again.status == BankStatementStatus.REJECTED
    assert await db.get(Account, accepted.account_id) is not None
    assert await db.scalar(text("SELECT count(*) FROM bank_custody_bindings")) == 1


async def test_custody_allocation_rolls_back_with_failed_unit_of_work(db, test_user):
    """AC-extraction.custody-binding.6: failure after allocation retains neither row."""
    from src.extraction.extension.custody_binding import resolve_bank_custody

    with pytest.raises(RuntimeError, match="synthetic downstream failure"):
        async with db.begin_nested():
            await resolve_bank_custody(
                db, user_id=test_user.id, institution="DBS", account_last4="2468", currency="SGD"
            )
            raise RuntimeError("synthetic downstream failure")
    assert await db.scalar(select(func.count()).select_from(Account).where(Account.user_id == test_user.id)) == 0
    assert await db.scalar(text("SELECT count(*) FROM bank_custody_bindings")) == 0


async def test_real_custody_migration_installs_unique_key(db, test_user):
    """AC-extraction.custody-binding.7: the real additive migration enforces uniqueness."""
    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from src.extraction.extension.custody_binding import resolve_bank_custody
    from src.extraction.orm.bank_custody_binding import BankCustodyBinding

    await db.execute(text("DROP TABLE bank_custody_bindings"))
    spec = importlib.util.spec_from_file_location(
        "custody_migration", Path(__file__).resolve().parents[2] / "migrations/versions/0062_bank_custody.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def upgrade(session):
        migration.op = Operations(MigrationContext.configure(session.connection()))
        migration.upgrade()

    await db.run_sync(upgrade)
    allocation = await resolve_bank_custody(
        db, user_id=test_user.id, institution="DBS", account_last4="2468", currency="SGD"
    )
    await db.commit()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                BankCustodyBinding(
                    user_id=test_user.id,
                    institution="DBS",
                    account_last4="2468",
                    currency="SGD",
                    account_id=allocation.account.id,
                )
            )
            await db.flush()
    for statement, target_id in (
        ("DELETE FROM accounts WHERE id = :id", allocation.account.id),
        ("DELETE FROM users WHERE id = :id", test_user.id),
    ):
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.execute(text(statement), {"id": target_id})
    assert await db.scalar(text("SELECT count(*) FROM bank_custody_bindings")) == 1
    with pytest.raises(RuntimeError, match="verified pre-upgrade backup"):
        migration.downgrade()


@pytest.mark.parametrize("ambiguous", [False, True])
async def test_explicit_selection_resolves_only_unique_legacy_history(db, test_user, ambiguous):
    """AC-extraction.custody-binding.4: legacy users have a deliberate selection path."""
    from tests.factories import seed_parsed_statement

    uid = test_user.id
    selected = None
    for _ in range(2 if ambiguous else 1):
        account = AccountFactory.build(user_id=uid, name="Legacy retained custody", currency="SGD")
        db.add(account)
        await db.flush()
        source = await seed_parsed_statement(db, uid)
        source.statement.account_id = account.id
        source.statement.account_last4 = "2468"
        source.statement.institution = "DBS"
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


async def test_confirmed_create_reuses_existing_custody_key(db, test_user):
    """AC-extraction.custody-binding.5: explicit create cannot fork an existing identity."""
    from src.routers.statements import _create_statement_account_from_confirmation
    from tests.factories import seed_parsed_statement

    first = await parse(db, test_user.id)
    pending = await seed_parsed_statement(db, test_user.id)
    pending.statement.institution = "DBS"
    pending.statement.account_last4 = "2468"
    await db.commit()
    account = await _create_statement_account_from_confirmation(db, pending.statement, test_user.id)
    assert account.id == first.account_id
    assert pending.statement.account_id == first.account_id


async def test_mapped_posting_rejects_contradictory_custody_key(db, test_user):
    """AC-extraction.custody-binding.5: an owned mapped UUID cannot bypass the binding."""
    from src.extraction import resolve_statement_posting_account
    from tests.factories import seed_parsed_statement

    await parse(db, test_user.id)
    other = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(other)
    await db.flush()
    pending = await seed_parsed_statement(db, test_user.id)
    pending.statement.institution = "DBS"
    pending.statement.account_last4 = "2468"
    pending.statement.account_id = other.id
    await db.commit()
    with pytest.raises(ValueError, match="contradicts"):
        await resolve_statement_posting_account(db, pending.statement, test_user.id)


@pytest.mark.parametrize("seam", ["create", "posting"])
async def test_brokerage_sources_do_not_allocate_bank_binding(db, test_user, seam):
    """AC-extraction.custody-binding.3: bank custody never absorbs brokerage sources."""
    from src.extraction.extension.statement_posting import resolve_statement_posting_account
    from src.extraction.orm.bank_custody_binding import BankCustodyBinding
    from src.routers.statements import _create_statement_account_from_confirmation

    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    document = UploadedDocument(
        user_id=test_user.id,
        file_path="synthetic-broker.pdf",
        file_hash=uuid4().hex,
        original_filename="synthetic-broker.pdf",
        document_type=DocumentType.BROKERAGE_STATEMENT,
    )
    db.add(document)
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
    resolver = _create_statement_account_from_confirmation if seam == "create" else resolve_statement_posting_account
    assert (await resolver(db, statement, test_user.id)).id == account.id
    assert await db.scalar(select(func.count()).select_from(BankCustodyBinding)) == 0


@pytest.mark.parametrize("typed", [None, "bank", "brokerage"])
@pytest.mark.parametrize("document_kind", [None, DocumentType.BANK_STATEMENT, DocumentType.BROKERAGE_STATEMENT])
def test_bank_source_classification_is_shared(typed, document_kind):
    """AC-extraction.custody-binding.3: typed evidence takes precedence over legacy ODS classification."""
    from types import SimpleNamespace

    from src.extraction import StatementEvidenceType, StatementSourceType, is_bank_custody_source

    source = (
        None
        if typed is None
        else SimpleNamespace(
            source_type=StatementSourceType.BANK if typed == "bank" else StatementSourceType.BROKERAGE,
            evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        )
    )
    document = None if document_kind is None else SimpleNamespace(document_type=document_kind)
    expected = typed == "bank" if typed is not None else document_kind is not DocumentType.BROKERAGE_STATEMENT
    assert is_bank_custody_source(source, document) is expected
