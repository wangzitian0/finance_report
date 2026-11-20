from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.selectable import CTE
from sqlalchemy.sql.visitors import iterate

from src.config import settings
from src.extraction import effective_statement_transaction_filter
from src.extraction.base.source_vocabulary import BankStatementStatus, DocumentType, Stage1Status, TransactionDirection
from src.extraction.extension import statement_workflow
from src.extraction.extension.deduplication import DeduplicationService
from src.extraction.extension.statement_workflow import (
    TENANT_ANALYZE_TABLES,
    analyze_tenant_tables,
    request_tenant_statistics_refresh,
)
from src.extraction.extension.transaction_identity import versioned_transaction_hash
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction, AtomicTransactionIdentity
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.identity import User
from tests.factories import AccountFactory, StatementSummaryFactory

_ANONYMOUS_CTE_NAME = re.compile(r"%\((\d+) anon\)s")


def _source_models(
    user_id,
    *,
    doc_id=None,
    account=None,
    status=BankStatementStatus.APPROVED,
    stage1_status=Stage1Status.APPROVED,
    currency_balances=None,
    payload=None,
    prefix="synthetic",
):
    did = doc_id or uuid4()
    fhash = hashlib.sha256(did.bytes).hexdigest()
    doc = UploadedDocument(
        id=did,
        user_id=user_id,
        file_path=f"synthetic/{prefix}_{did}.pdf",
        file_hash=fhash,
        original_filename=f"{prefix}.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    rid = uuid4() if payload is not None else None
    summary = StatementSummaryFactory.build(
        id=uuid4(),
        user_id=user_id,
        uploaded_document_id=did,
        file_hash=fhash,
        account_id=account.id if account else None,
        currency="SGD",
        currency_balances=currency_balances,
        institution="Synthetic Bank",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("145.00"),
        status=status,
        stage1_status=stage1_status,
        current_extraction_result_id=None,
    )
    rec = (
        None
        if rid is None
        else StatementExtractionResultRecord(
            id=rid,
            user_id=user_id,
            statement_id=summary.id,
            content_digest=hashlib.sha256(rid.bytes).hexdigest(),
            source_content_digest=fhash,
            schema_version=str(payload.get("schema_version") or "1"),
            producer_version="test-v1",
            payload=payload,
            source_trace_record_id=uuid4(),
            created_at=datetime.now(UTC),
        )
    )
    return doc, summary, rec


async def _create_source(db, user_id, **kwargs):
    doc, summary, rec = _source_models(user_id, **kwargs)
    db.add_all([doc, summary])
    await db.flush()
    if rec is not None:
        db.add(rec)
        await db.flush()
        summary.current_extraction_result_id = rec.id
        await db.flush()
    return doc, summary


async def _create_txn(
    db, user_id, *, source_docs: list[dict], description: str, currency: str = "SGD", dedup_hash: str | None = None
) -> AtomicTransaction:
    computed = dedup_hash or DeduplicationService.calculate_transaction_hash(
        user_id,
        date(2025, 1, 2),
        Decimal("10.00"),
        TransactionDirection.IN,
        description,
        balance_after=Decimal("110.00"),
    )
    txn = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2025, 1, 2),
        amount=Decimal("10.00"),
        direction=TransactionDirection.IN,
        description=description,
        currency=currency,
        balance_after=Decimal("110.00"),
        dedup_hash=computed,
        source_documents=source_docs,
    )
    db.add(txn)
    await db.flush()
    return txn


def _doc_ref(doc: UploadedDocument) -> dict[str, str]:
    return {"doc_id": str(doc.id), "doc_type": "bank_statement"}


async def test_set_based_filter_covers_custody_alias_multicurrency_and_stage1_matrix(db, test_user):
    account_a, account_b = (
        AccountFactory.build(user_id=test_user.id, currency="SGD"),
        AccountFactory.build(user_id=test_user.id, currency="SGD"),
    )
    db.add_all([account_a, account_b])
    await db.flush()

    legacy_hash = DeduplicationService.calculate_transaction_hash(
        test_user.id,
        date(2025, 1, 5),
        Decimal("45.00"),
        TransactionDirection.IN,
        "EUR v2 alias deposit",
        balance_after=Decimal("145.00"),
    )
    v2_hash, balances = (
        versioned_transaction_hash(legacy_hash, "EUR", f"account:{account_a.id}"),
        [
            {"currency": "SGD", "opening": "100", "closing": "100"},
            {"currency": "EUR", "opening": "100", "closing": "145"},
        ],
    )
    doc_app, sum_app = await _create_source(
        db,
        test_user.id,
        account=account_a,
        currency_balances=balances,
        payload={
            "schema_version": 1,
            "currency": "SGD",
            "balances": balances,
            "transactions": [{"fact_id": v2_hash, "currency": "EUR"}],
        },
    )
    txn_v2 = await _create_txn(
        db,
        test_user.id,
        source_docs=[_doc_ref(doc_app)],
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
            atomic_txn_id=txn_v2.id,
            currency="EUR",
            custody_scope=f"account:{account_a.id}",
        )
    )

    doc_leg, _ = await _create_source(db, test_user.id, account=account_a)
    doc_pen, _ = await _create_source(
        db,
        test_user.id,
        account=account_a,
        status=BankStatementStatus.PARSED,
        stage1_status=Stage1Status.PENDING_REVIEW,
    )
    doc_rej, sum_rej = await _create_source(
        db, test_user.id, account=account_a, status=BankStatementStatus.REJECTED, stage1_status=Stage1Status.REJECTED
    )
    doc_c2, _ = await _create_source(db, test_user.id, account=account_a)
    doc_inc, _ = await _create_source(db, test_user.id, account=account_b)

    txn_leg, txn_pen, txn_rej, txn_compat, txn_incompat, txn_receipt = [
        await _create_txn(db, test_user.id, source_docs=sdocs, description=desc)
        for sdocs, desc in (
            ([_doc_ref(doc_leg)], "Legacy statement row"),
            ([_doc_ref(doc_pen)], "Pending stage1 row"),
            ([_doc_ref(doc_rej)], "Rejected statement row"),
            ([_doc_ref(doc_leg), _doc_ref(doc_c2)], "Compatible multi-source row"),
            ([_doc_ref(doc_leg), _doc_ref(doc_inc)], "Incompatible multi-source row"),
            ([{"doc_id": str(uuid4()), "doc_type": "receipt"}], "Standalone receipt row"),
        )
    ]
    await db.flush()

    async def _ids(stmt_id=None, *, include_pending_stage1=True):
        return set(
            (
                await db.scalars(
                    select(AtomicTransaction.id).where(
                        effective_statement_transaction_filter(
                            test_user.id, stmt_id, include_pending_stage1=include_pending_stage1
                        )
                    )
                )
            ).all()
        )

    default_ids, approved_only_ids = await _ids(), await _ids(include_pending_stage1=False)
    assert {txn_v2.id, txn_leg.id, txn_compat.id, txn_receipt.id, txn_pen.id} <= default_ids and {
        txn_rej.id,
        txn_incompat.id,
    }.isdisjoint(default_ids)
    assert (
        txn_pen.id not in approved_only_ids
        and {txn_v2.id, txn_leg.id} <= approved_only_ids
        and (await _ids(sum_app.id), await _ids(sum_rej.id)) == ({txn_v2.id}, set())
    )


def _sum_leaf_scan_rows_read(node: dict) -> int:
    if plans := (node.get("Plans") or []):
        return sum(_sum_leaf_scan_rows_read(child) for child in plans)
    return (
        int(node.get("Actual Rows") or 0)
        + int(node.get("Rows Removed by Filter") or 0)
        + int(node.get("Rows Removed by Index Recheck") or 0)
    ) * int(node.get("Actual Loops") or 1)


async def _seed_and_measure_scale(db, user_id, *, num_statements: int, txns_per_statement: int, prefix: str) -> int:
    account = AccountFactory.build(user_id=user_id, currency="SGD")
    db.add(account)
    await db.flush()
    doc_ids = [uuid4() for _ in range(num_statements)]
    hashes_by_stmt = [
        [hashlib.sha256(f"{user_id}:{prefix}:{s}:{t}".encode()).hexdigest() for t in range(txns_per_statement)]
        for s in range(num_statements)
    ]
    rows = [
        _source_models(
            user_id,
            doc_id=doc_ids[s],
            account=account,
            prefix=f"{prefix}_{s}",
            payload={
                "schema_version": 1,
                "currency": "SGD",
                "balances": [{"currency": "SGD", "opening": "1000", "closing": "2000"}],
                "transactions": [{"fact_id": h, "currency": "SGD"} for h in hashes_by_stmt[s]],
            },
        )
        for s in range(num_statements)
    ]
    db.add_all([m for doc, summary, _ in rows for m in (doc, summary)])
    await db.flush()
    db.add_all([rec for _, _, rec in rows])
    for _, summary, rec in rows:
        summary.current_extraction_result_id = rec.id
    db.add_all(
        [
            AtomicTransaction(
                id=uuid4(),
                user_id=user_id,
                txn_date=date(2025, s % 12 + 1, t % 28 + 1),
                amount=Decimal("10.00") + Decimal(t),
                direction=TransactionDirection.OUT,
                description=f"Bench txn {prefix}-{s}-{t}",
                currency="SGD",
                dedup_hash=hashes_by_stmt[s][t],
                source_documents=[{"doc_id": str(doc_ids[s]), "doc_type": "bank_statement"}]
                + (
                    [{"doc_id": str(doc_ids[(s + 1) % num_statements]), "doc_type": "bank_statement"}]
                    if t % 10 == 0
                    else []
                ),
            )
            for s in range(num_statements)
            for t in range(txns_per_statement)
        ]
    )
    await db.flush()
    await db.execute(
        text("ANALYZE uploaded_documents, statement_summaries, statement_extraction_results, atomic_transactions")
    )
    stmt = select(func.count(AtomicTransaction.id)).where(
        AtomicTransaction.user_id == user_id, effective_statement_transaction_filter(user_id)
    )
    assert await db.scalar(stmt) == num_statements * txns_per_statement
    explain_rows = (
        await db.execute(
            text(
                f"EXPLAIN (ANALYZE, FORMAT JSON) {stmt.compile(dialect=db.bind.dialect, compile_kwargs={'literal_binds': True})}"
            )
        )
    ).scalar_one()
    return _sum_leaf_scan_rows_read(explain_rows[0]["Plan"])


async def test_set_based_filter_scales_linearly_at_year_scale(db, test_user):
    rows_12 = await _seed_and_measure_scale(db, test_user.id, num_statements=12, txns_per_statement=80, prefix="s12")
    user_120 = User(id=uuid4(), email=f"scale120-{uuid4()}@example.com", hashed_password="hashed")
    db.add(user_120)
    await db.flush()
    rows_120 = await _seed_and_measure_scale(db, user_120.id, num_statements=120, txns_per_statement=80, prefix="s120")
    assert (
        rows_12 < 19200
        and rows_12 / 960 < 20.0
        and rows_120 < 192000
        and rows_120 / 9600 < 20.0
        and rows_120 / 9600 <= rows_12 / 960 * 1.5
    )


async def test_source_documents_gin_index_and_analyze_helper(db, monkeypatch):
    index_def = await db.scalar(
        text(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'ix_atomic_transactions_source_documents_gin'"
        )
    )
    reloptions = {
        r[0]: set(r[1])
        for r in (
            await db.execute(
                text(
                    "SELECT c.relname, coalesce(c.reloptions, ARRAY[]::text[]) FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relname = ANY(:tables)"
                ),
                {"tables": list(TENANT_ANALYZE_TABLES)},
            )
        ).all()
    }
    assert (
        index_def is not None
        and "USING gin" in index_def
        and "jsonb_path_ops" in index_def
        and set(reloptions) == set(TENANT_ANALYZE_TABLES)
    )
    assert all(
        {"autovacuum_analyze_scale_factor=0.02", "autovacuum_analyze_threshold=50"} <= opts
        for opts in reloptions.values()
    )

    spy_runner = AsyncMock()
    for name, val in (("analyze_tenant_tables", spy_runner), ("_refresh_task", None), ("_refresh_requested", False)):
        monkeypatch.setattr(statement_workflow, name, val)
    monkeypatch.setattr(settings, "environment", "testing")
    request_tenant_statistics_refresh(AsyncMock())
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setenv("ENVIRONMENT", "production")
    sqlite_session = AsyncMock()
    sqlite_session.get_bind = MagicMock(return_value=MagicMock(dialect=MagicMock(name="sqlite")))
    sqlite_session.get_bind.return_value.dialect.name = "sqlite"
    request_tenant_statistics_refresh(sqlite_session)
    assert statement_workflow._refresh_task is None
    spy_runner.assert_not_awaited()

    pg_session, pg_maker = AsyncMock(), MagicMock()
    pg_maker.return_value.__aenter__.return_value = pg_session
    await analyze_tenant_tables(pg_maker)
    pg_session.commit.assert_awaited_once()
    executed_sql = [str(call.args[0]) for call in pg_session.execute.await_args_list]
    spec = spec_from_file_location(
        "migration_0073",
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "0073_statement_filter_gin_and_trace_trigger_perf.py",
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (
        len(executed_sql) == 3
        and executed_sql[-1] == f"ANALYZE {', '.join(TENANT_ANALYZE_TABLES)}"
        and module.AUTOVACUUM_TUNED_TABLES == TENANT_ANALYZE_TABLES
    )


@pytest.mark.parametrize(
    ("with_statement", "include_pending_stage1"),
    [(False, True), (True, True), (True, False)],
    ids=["global", "scoped", "scoped-approved-only"],
)
def test_filter_ctes_keep_their_name_owner_alive(with_statement, include_pending_stage1):
    ctes = list(
        {
            id(el): el
            for el in iterate(
                effective_statement_transaction_filter(
                    uuid4(), uuid4() if with_statement else None, include_pending_stage1=include_pending_stage1
                )
            )
            if isinstance(el, CTE)
        }.values()
    )
    assert len(ctes) == 3 and len({str(c.name) for c in ctes}) == 3
    assert all(
        (m := _ANONYMOUS_CTE_NAME.fullmatch(str(c.name))) is not None
        and int(m.group(1)) in {id(c), id(getattr(c, "_anonymous_name_owner", c))}
        for c in ctes
    )


def test_two_filter_instances_compile_in_one_query():
    uid = uuid4()
    stmt = select(AtomicTransaction.id).where(
        effective_statement_transaction_filter(uid),
        AtomicTransaction.id.in_(
            select(AtomicTransaction.id).where(effective_statement_transaction_filter(uid, uuid4()))
        ),
    )
    cte_names = re.findall(
        r"(anon_\d+) AS\s+(?:MATERIALIZED\s+)?\(SELECT", str(stmt.compile(dialect=postgresql.dialect()))
    )
    assert len(cte_names) == len(set(cte_names)) == 6
