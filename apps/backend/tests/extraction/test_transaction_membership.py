"""Set-based effective_statement_transaction_filter tests (#2630, #2629)."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy import func, select, text

from src.extraction import effective_statement_transaction_filter
from src.extraction.base.source_vocabulary import BankStatementStatus, DocumentType, Stage1Status, TransactionDirection
from src.extraction.extension.deduplication import DeduplicationService
from src.extraction.extension.statement_workflow import TENANT_ANALYZE_TABLES, analyze_tenant_tables
from src.extraction.extension.transaction_identity import versioned_transaction_hash
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction, AtomicTransactionIdentity
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from tests.factories import AccountFactory, StatementSummaryFactory


async def _create_source(
    db,
    user_id,
    *,
    account=None,
    currency: str = "SGD",
    currency_balances: list[dict] | None = None,
    status: BankStatementStatus = BankStatementStatus.APPROVED,
    stage1_status: Stage1Status | None = Stage1Status.APPROVED,
    payload: dict | None = None,
):
    document = UploadedDocument(
        user_id=user_id,
        file_path=f"synthetic/{uuid4()}.pdf",
        file_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
        original_filename="synthetic.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(document)
    await db.flush()
    summary = StatementSummaryFactory.build(
        user_id=user_id,
        uploaded_document_id=document.id,
        file_hash=document.file_hash,
        account_id=account.id if account else None,
        currency=currency,
        currency_balances=currency_balances,
        institution="Synthetic Bank",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("145.00"),
        status=status,
        stage1_status=stage1_status,
    )
    db.add(summary)
    await db.flush()
    if payload is not None:
        result_id = uuid4()
        db.add(
            StatementExtractionResultRecord(
                id=result_id,
                user_id=user_id,
                statement_id=summary.id,
                content_digest=hashlib.sha256(result_id.bytes).hexdigest(),
                source_content_digest=document.file_hash,
                schema_version=str(payload.get("schema_version") or "1"),
                producer_version="test-v1",
                payload=payload,
                source_trace_record_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )
        await db.flush()
        summary.current_extraction_result_id = result_id
        await db.flush()
    return document, summary


async def _create_txn(
    db,
    user_id,
    *,
    source_docs: list[dict],
    txn_date: date = date(2025, 1, 2),
    amount: Decimal = Decimal("10.00"),
    currency: str = "SGD",
    description: str = "Synthetic txn",
    dedup_hash: str | None = None,
) -> AtomicTransaction:
    computed_hash = dedup_hash or DeduplicationService.calculate_transaction_hash(
        user_id,
        txn_date,
        amount,
        TransactionDirection.IN,
        description,
        balance_after=Decimal("110.00"),
    )
    txn = AtomicTransaction(
        user_id=user_id,
        txn_date=txn_date,
        amount=amount,
        direction=TransactionDirection.IN,
        description=description,
        currency=currency,
        balance_after=Decimal("110.00"),
        dedup_hash=computed_hash,
        source_documents=source_docs,
    )
    db.add(txn)
    await db.flush()
    return txn


async def test_set_based_filter_covers_custody_alias_multicurrency_and_stage1_matrix(db, test_user):
    """AC-extraction.persistence-proof.2: set-based filter matches all custody, v2 alias, and Stage-1 states."""
    account_a = AccountFactory.build(user_id=test_user.id, currency="SGD")
    account_b = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add_all([account_a, account_b])
    await db.flush()

    # 1. Approved statement with v2 alias and multi-currency balance row (EUR)
    legacy_hash = DeduplicationService.calculate_transaction_hash(
        test_user.id,
        date(2025, 1, 5),
        Decimal("45.00"),
        TransactionDirection.IN,
        "EUR v2 alias deposit",
        balance_after=Decimal("145.00"),
    )
    v2_hash = versioned_transaction_hash(legacy_hash, "EUR", f"account:{account_a.id}")
    approved_payload = {
        "schema_version": 1,
        "currency": "SGD",
        "balances": [
            {"currency": "SGD", "opening": "100", "closing": "100"},
            {"currency": "EUR", "opening": "100", "closing": "145"},
        ],
        "transactions": [{"fact_id": v2_hash, "currency": "EUR"}],
    }
    doc_approved, summary_approved = await _create_source(
        db,
        test_user.id,
        account=account_a,
        currency="SGD",
        currency_balances=[
            {"currency": "SGD", "opening": "100", "closing": "100"},
            {"currency": "EUR", "opening": "100", "closing": "145"},
        ],
        status=BankStatementStatus.APPROVED,
        stage1_status=Stage1Status.APPROVED,
        payload=approved_payload,
    )
    txn_v2_eur = await _create_txn(
        db,
        test_user.id,
        source_docs=[{"doc_id": str(doc_approved.id), "doc_type": "bank_statement"}],
        currency="EUR",
        description="EUR v2 alias deposit",
        dedup_hash=legacy_hash,
    )
    db.add(
        AtomicTransactionIdentity(
            user_id=test_user.id,
            identity_version="v2",
            identity_hash=v2_hash,
            legacy_hash=legacy_hash,
            atomic_txn_id=txn_v2_eur.id,
            currency="EUR",
            custody_scope=f"account:{account_a.id}",
        )
    )

    # 2. Legacy statement without StatementExtractionResultRecord
    doc_legacy, summary_legacy = await _create_source(
        db,
        test_user.id,
        account=account_a,
        currency="SGD",
        status=BankStatementStatus.APPROVED,
        stage1_status=Stage1Status.APPROVED,
        payload=None,
    )
    txn_legacy = await _create_txn(
        db,
        test_user.id,
        source_docs=[{"doc_id": str(doc_legacy.id), "doc_type": "bank_statement"}],
        currency="SGD",
        description="Legacy statement row",
    )

    # 3. Pending review statement (excluded when include_pending_stage1=False, included when True)
    doc_pending, summary_pending = await _create_source(
        db,
        test_user.id,
        account=account_a,
        currency="SGD",
        status=BankStatementStatus.PARSED,
        stage1_status=Stage1Status.PENDING_REVIEW,
        payload=None,
    )
    txn_pending = await _create_txn(
        db,
        test_user.id,
        source_docs=[{"doc_id": str(doc_pending.id), "doc_type": "bank_statement"}],
        currency="SGD",
        description="Pending stage1 row",
    )

    # 4. Rejected statement (always excluded)
    doc_rejected, summary_rejected = await _create_source(
        db,
        test_user.id,
        account=account_a,
        currency="SGD",
        status=BankStatementStatus.REJECTED,
        stage1_status=Stage1Status.REJECTED,
        payload=None,
    )
    txn_rejected = await _create_txn(
        db,
        test_user.id,
        source_docs=[{"doc_id": str(doc_rejected.id), "doc_type": "bank_statement"}],
        currency="SGD",
        description="Rejected statement row",
    )

    # 5. Multi-source transaction with compatible custody (same account_a across two statements)
    doc_compat_2, _ = await _create_source(
        db,
        test_user.id,
        account=account_a,
        currency="SGD",
        status=BankStatementStatus.APPROVED,
        stage1_status=Stage1Status.APPROVED,
        payload=None,
    )
    txn_compat_multi = await _create_txn(
        db,
        test_user.id,
        source_docs=[
            {"doc_id": str(doc_legacy.id), "doc_type": "bank_statement"},
            {"doc_id": str(doc_compat_2.id), "doc_type": "bank_statement"},
        ],
        currency="SGD",
        description="Compatible multi-source row",
    )

    # 6. Multi-source transaction with incompatible custody (account_a + account_b)
    doc_incompat, _ = await _create_source(
        db,
        test_user.id,
        account=account_b,
        currency="SGD",
        status=BankStatementStatus.APPROVED,
        stage1_status=Stage1Status.APPROVED,
        payload=None,
    )
    txn_incompat_multi = await _create_txn(
        db,
        test_user.id,
        source_docs=[
            {"doc_id": str(doc_legacy.id), "doc_type": "bank_statement"},
            {"doc_id": str(doc_incompat.id), "doc_type": "bank_statement"},
        ],
        currency="SGD",
        description="Incompatible multi-source row",
    )

    # 7. Standalone transaction whose doc_id does not belong to any StatementSummary
    txn_standalone = await _create_txn(
        db,
        test_user.id,
        source_docs=[{"doc_id": str(uuid4()), "doc_type": "receipt"}],
        currency="SGD",
        description="Standalone receipt row",
    )
    await db.flush()

    default_ids = set(
        (
            await db.scalars(select(AtomicTransaction.id).where(effective_statement_transaction_filter(test_user.id)))
        ).all()
    )
    assert txn_v2_eur.id in default_ids
    assert txn_legacy.id in default_ids
    assert txn_compat_multi.id in default_ids
    assert txn_standalone.id in default_ids
    assert txn_pending.id in default_ids
    assert txn_rejected.id not in default_ids
    assert txn_incompat_multi.id not in default_ids

    approved_only_ids = set(
        (
            await db.scalars(
                select(AtomicTransaction.id).where(
                    effective_statement_transaction_filter(test_user.id, include_pending_stage1=False)
                )
            )
        ).all()
    )
    assert txn_pending.id not in approved_only_ids
    assert txn_v2_eur.id in approved_only_ids
    assert txn_legacy.id in approved_only_ids

    scoped_approved = set(
        (
            await db.scalars(
                select(AtomicTransaction.id).where(
                    effective_statement_transaction_filter(test_user.id, summary_approved.id)
                )
            )
        ).all()
    )
    assert scoped_approved == {txn_v2_eur.id}

    scoped_rejected = set(
        (
            await db.scalars(
                select(AtomicTransaction.id).where(
                    effective_statement_transaction_filter(test_user.id, summary_rejected.id)
                )
            )
        ).all()
    )
    assert scoped_rejected == set()


def _sum_leaf_scan_rows_read(node: dict) -> int:
    loops = int(node.get("Actual Loops") or 1)
    plans = node.get("Plans") or []
    if not plans:
        own_rows = int(node.get("Actual Rows") or 0) * loops
        removed = (
            int(node.get("Rows Removed by Filter") or 0) + int(node.get("Rows Removed by Index Recheck") or 0)
        ) * loops
        return own_rows + removed
    return sum(_sum_leaf_scan_rows_read(child) for child in plans)


async def test_set_based_filter_scales_linearly_at_year_scale(db, test_user):
    """#2630: 12 statements x 80 rows (960 txns) reads < 30,000 total rows and < 20 rows/txn."""
    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()

    num_statements = 12
    txns_per_statement = 80
    total_expected = num_statements * txns_per_statement

    for s_idx in range(num_statements):
        doc_id = uuid4()
        db.add(
            UploadedDocument(
                id=doc_id,
                user_id=test_user.id,
                file_path=f"synthetic/bench_{s_idx}.pdf",
                file_hash=hashlib.sha256(doc_id.bytes).hexdigest(),
                original_filename=f"bench_{s_idx}.pdf",
                document_type=DocumentType.BANK_STATEMENT,
            )
        )
        summary_id = uuid4()
        summary = StatementSummaryFactory.build(
            id=summary_id,
            user_id=test_user.id,
            uploaded_document_id=doc_id,
            file_hash=hashlib.sha256(doc_id.bytes).hexdigest(),
            account_id=account.id,
            currency="SGD",
            institution="Synthetic Bank",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 1, 31),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("2000.00"),
            status=BankStatementStatus.APPROVED,
            stage1_status=Stage1Status.APPROVED,
        )
        db.add(summary)
        await db.flush()
        fact_hashes: list[str] = []
        txns: list[AtomicTransaction] = []
        for t_idx in range(txns_per_statement):
            dedup_hash = hashlib.sha256(f"{test_user.id}:{s_idx}:{t_idx}".encode()).hexdigest()
            fact_hashes.append(dedup_hash)
            txns.append(
                AtomicTransaction(
                    id=uuid4(),
                    user_id=test_user.id,
                    txn_date=date(2025, (s_idx % 12) + 1, (t_idx % 28) + 1),
                    amount=Decimal("10.00") + Decimal(t_idx),
                    direction=TransactionDirection.OUT,
                    description=f"Bench txn {s_idx}-{t_idx}",
                    currency="SGD",
                    dedup_hash=dedup_hash,
                    source_documents=[{"doc_id": str(doc_id), "doc_type": "bank_statement"}],
                )
            )
        db.add_all(txns)
        result_id = uuid4()
        payload = {
            "schema_version": 1,
            "currency": "SGD",
            "balances": [{"currency": "SGD", "opening": "1000", "closing": "2000"}],
            "transactions": [{"fact_id": h, "currency": "SGD"} for h in fact_hashes],
        }
        db.add(
            StatementExtractionResultRecord(
                id=result_id,
                user_id=test_user.id,
                statement_id=summary_id,
                content_digest=hashlib.sha256(result_id.bytes).hexdigest(),
                source_content_digest=hashlib.sha256(doc_id.bytes).hexdigest(),
                schema_version="1",
                producer_version="test-v1",
                payload=payload,
                source_trace_record_id=uuid4(),
                created_at=datetime.now(UTC),
            )
        )
        await db.flush()
        summary.current_extraction_result_id = result_id
    await db.flush()

    stmt = select(func.count(AtomicTransaction.id)).where(
        AtomicTransaction.user_id == test_user.id,
        effective_statement_transaction_filter(test_user.id),
    )
    count = await db.scalar(stmt)
    assert count == total_expected

    compiled = stmt.compile(dialect=db.bind.dialect, compile_kwargs={"literal_binds": True})
    explain_rows = (await db.execute(text(f"EXPLAIN (ANALYZE, FORMAT JSON) {compiled}"))).scalar_one()
    plan_root = explain_rows[0]["Plan"]
    rows_read = _sum_leaf_scan_rows_read(plan_root)
    assert rows_read < 19_200, (
        f"Expected < 19,200 leaf rows read (< 20 rows/txn) for {total_expected} txns, got {rows_read}"
    )
    assert (rows_read / total_expected) < 20.0


async def test_source_documents_gin_index_and_analyze_helper(db, monkeypatch):
    """#2630 & #2629: GIN jsonb_path_ops index is registered on atomic_transactions and analyze helper runs cleanly."""
    from src.config import settings

    index_def = await db.scalar(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = 'ix_atomic_transactions_source_documents_gin'"
        )
    )
    assert index_def is not None
    assert "USING gin" in index_def
    assert "jsonb_path_ops" in index_def

    # In testing environment, analyze_tenant_tables is a no-op to preserve worker DB reltuples == -1 (#2398)
    monkeypatch.setattr(settings, "environment", "testing")
    spy_testing_session = AsyncMock()
    await analyze_tenant_tables(spy_testing_session)
    spy_testing_session.execute.assert_not_awaited()

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setenv("ENVIRONMENT", "production")
    pg_session = AsyncMock()
    pg_bind = MagicMock()
    pg_bind.dialect.name = "postgresql"
    pg_session.get_bind = MagicMock(return_value=pg_bind)
    await analyze_tenant_tables(pg_session)
    pg_session.execute.assert_awaited_once()
    executed_sql = str(pg_session.execute.call_args.args[0])
    assert executed_sql == f"ANALYZE {', '.join(TENANT_ANALYZE_TABLES)}"

    sqlite_session = AsyncMock()
    sqlite_bind = MagicMock()
    sqlite_bind.dialect.name = "sqlite"
    sqlite_session.get_bind = MagicMock(return_value=sqlite_bind)
    await analyze_tenant_tables(sqlite_session)
    sqlite_session.execute.assert_not_awaited()

    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0073_statement_filter_gin_and_trace_trigger_perf.py"
    )
    spec = spec_from_file_location("migration_0073", migration_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.AUTOVACUUM_TUNED_TABLES == TENANT_ANALYZE_TABLES
