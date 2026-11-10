"""Shared effective-source membership for downstream transaction queues/actions."""

from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import CTE, Select

from src.extraction.base.source_vocabulary import BankStatementStatus
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction, AtomicTransactionIdentity
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.extraction.orm.statement_summary import StatementSummary


def _materialized_cte(statement: Select[Any]) -> CTE:
    """Return a MATERIALIZED CTE and keep its original CTE alive.

    SQLAlchemy names an anonymous CTE from an object address, and prefix_with returns a copy with the same name.
    A freed original lets a later CTE get that address and so the same name (#2899).
    """
    original = statement.cte()
    materialized = original.prefix_with("MATERIALIZED", dialect="postgresql")
    materialized._anonymous_name_owner = original  # type: ignore[attr-defined]
    return materialized


def effective_statement_transaction_filter(
    user_id: UUID,
    statement_id: UUID | None = None,
    *,
    include_pending_stage1: bool = True,
) -> ColumnElement[bool]:
    """Return a predicate over AtomicTransaction without exposing historical rows.

    A typed source contributes only its current result's facts, including v2
    aliases. Legacy source rows without typed results retain their old membership.
    Global callers may also handle unattached legacy/manual rows; scoped callers
    must prove membership of the specifically requested source. When
    ``include_pending_stage1`` is False, statement-backed membership is restricted
    to ``APPROVED`` statements so Stage-2 reconciliation queues and stats exclude
    unapproved Stage-1 statements (#2826).
    """
    payload = case(
        (
            StatementSummary.current_extraction_result_id.is_(None),
            StatementSummary.extraction_metadata["statement_extraction_result"],
        ),
        else_=StatementExtractionResultRecord.payload,
    )
    active_statements = _materialized_cte(
        select(
            StatementSummary.id.label("stmt_id"),
            StatementSummary.account_id.label("account_id"),
            StatementSummary.uploaded_document_id.label("uploaded_document_id"),
            StatementSummary.currency.label("currency"),
            StatementSummary.currency_balances.label("currency_balances"),
            StatementSummary.current_extraction_result_id.label("current_extraction_result_id"),
            UploadedDocument.file_hash.label("file_hash"),
            payload.label("payload"),
        )
        .select_from(StatementSummary)
        .join(UploadedDocument, UploadedDocument.id == StatementSummary.uploaded_document_id)
        .outerjoin(
            StatementExtractionResultRecord,
            and_(
                StatementExtractionResultRecord.id == StatementSummary.current_extraction_result_id,
                StatementExtractionResultRecord.user_id == user_id,
                StatementExtractionResultRecord.statement_id == StatementSummary.id,
            ),
        )
        .where(
            StatementSummary.user_id == user_id,
            StatementSummary.uploaded_document_id.is_not(None),
            UploadedDocument.user_id == user_id,
            (
                StatementSummary.status.notin_([BankStatementStatus.RETIRED, BankStatementStatus.REJECTED])
                if include_pending_stage1
                else StatementSummary.status == BankStatementStatus.APPROVED
            ),
            *([StatementSummary.id == statement_id] if statement_id is not None else []),
        )
    )
    active_expected_scope = case(
        (
            active_statements.c.account_id.is_not(None),
            func.concat("account:", cast(active_statements.c.account_id, String)),
        ),
        else_=func.concat("source:", active_statements.c.file_hash),
    )
    source_count = case(
        (
            func.jsonb_typeof(AtomicTransaction.source_documents) == "array",
            func.jsonb_array_length(AtomicTransaction.source_documents),
        ),
        else_=0,
    )
    # Extract doc_id strings from the JSONB source_documents array so PostgreSQL
    # can Hash Join against statement uploaded_document_id in O(transactions) time
    # instead of evaluating an O(transactions * statements) Nested Loop over @> (#2630).
    txn_doc = (
        func.jsonb_array_elements(
            case(
                (func.jsonb_typeof(AtomicTransaction.source_documents) == "array", AtomicTransaction.source_documents),
                else_=func.jsonb_build_array(),
            )
        )
        .table_valued("value", joins_implicitly=True)
        .render_derived(name="txn_doc")
    )
    txn_doc_id = txn_doc.c.value.op("->>")("doc_id")
    txn_source_docs = (
        select(
            AtomicTransaction.id.label("txn_id"),
            AtomicTransaction.currency.label("currency"),
            AtomicTransaction.dedup_hash.label("dedup_hash"),
            source_count.label("source_count"),
            txn_doc_id.label("doc_id_str"),
        )
        .where(
            AtomicTransaction.user_id == user_id,
            txn_doc_id.is_not(None),
        )
        .cte()
    )
    known_source_ids = (
        select(txn_source_docs.c.txn_id)
        .select_from(StatementSummary)
        .join(
            txn_source_docs,
            and_(
                StatementSummary.user_id == user_id,
                StatementSummary.uploaded_document_id.is_not(None),
                txn_source_docs.c.doc_id_str == cast(StatementSummary.uploaded_document_id, String),
            ),
        )
    )
    # A raw legacy hash may have collapsed same-currency accounts. Every
    # historical source must independently agree with the requested custody;
    # one matching envelope is not enough to authorize this atomic identity.
    # Evaluate multi-source compatibility via a grouped set-based CTE (#2630).
    source_summary = aliased(StatementSummary)
    source_document = aliased(UploadedDocument)
    compatible_source_counts = (
        select(
            txn_source_docs.c.txn_id.label("txn_id"),
            source_summary.account_id.label("account_id"),
            func.count(func.distinct(source_document.id)).label("compat_count"),
        )
        .select_from(source_summary)
        .join(
            source_document,
            and_(
                source_document.id == source_summary.uploaded_document_id,
                source_document.user_id == user_id,
            ),
        )
        .join(
            txn_source_docs,
            and_(
                source_summary.uploaded_document_id.is_not(None),
                txn_source_docs.c.doc_id_str == cast(source_summary.uploaded_document_id, String),
                txn_source_docs.c.source_count > 1,
            ),
        )
        .where(
            source_summary.user_id == user_id,
            source_summary.account_id.is_not(None),
            or_(
                source_summary.currency == txn_source_docs.c.currency,
                source_summary.currency_balances.op("@>")(
                    func.jsonb_build_array(func.jsonb_build_object("currency", txn_source_docs.c.currency))
                ),
            ),
        )
        .group_by(txn_source_docs.c.txn_id, source_summary.account_id)
        .cte()
    )
    statement_currency_compatible = or_(
        active_statements.c.currency == txn_source_docs.c.currency,
        active_statements.c.currency_balances.op("@>")(
            func.jsonb_build_array(func.jsonb_build_object("currency", txn_source_docs.c.currency))
        ),
    )
    custody_proven = and_(
        statement_currency_compatible,
        or_(
            txn_source_docs.c.source_count == 1,
            and_(
                txn_source_docs.c.source_count > 1,
                active_statements.c.account_id.is_not(None),
                compatible_source_counts.c.compat_count == txn_source_docs.c.source_count,
            ),
        ),
    )

    def fact_match(identity):
        return or_(
            func.jsonb_extract_path(active_statements.c.payload, "transactions").op("@>")(
                func.jsonb_build_array(
                    func.jsonb_build_object("fact_id", identity, "currency", txn_source_docs.c.currency)
                )
            ),
            func.jsonb_extract_path(active_statements.c.payload, "transactions").op("@>")(
                func.jsonb_build_array(func.jsonb_build_object("fact_id", identity, "currency", None))
            ),
        )

    alias_matched_ids = (
        select(AtomicTransactionIdentity.atomic_txn_id)
        .select_from(active_statements)
        .join(
            AtomicTransactionIdentity,
            and_(
                AtomicTransactionIdentity.user_id == user_id,
                AtomicTransactionIdentity.custody_scope == active_expected_scope,
                AtomicTransactionIdentity.identity_version == "v2",
                or_(
                    func.jsonb_extract_path(active_statements.c.payload, "transactions").op("@>")(
                        func.jsonb_build_array(
                            func.jsonb_build_object(
                                "fact_id",
                                AtomicTransactionIdentity.identity_hash,
                                "currency",
                                AtomicTransactionIdentity.currency,
                            )
                        )
                    ),
                    func.jsonb_extract_path(active_statements.c.payload, "transactions").op("@>")(
                        func.jsonb_build_array(
                            func.jsonb_build_object(
                                "fact_id", AtomicTransactionIdentity.identity_hash, "currency", None
                            )
                        )
                    ),
                ),
            ),
        )
    )
    eligible_ids = (
        select(txn_source_docs.c.txn_id)
        .select_from(active_statements)
        .join(
            txn_source_docs,
            txn_source_docs.c.doc_id_str == cast(active_statements.c.uploaded_document_id, String),
        )
        .outerjoin(
            compatible_source_counts,
            and_(
                compatible_source_counts.c.txn_id == txn_source_docs.c.txn_id,
                compatible_source_counts.c.account_id == active_statements.c.account_id,
            ),
        )
        .where(
            custody_proven,
            or_(
                and_(active_statements.c.current_extraction_result_id.is_(None), active_statements.c.payload.is_(None)),
                fact_match(txn_source_docs.c.dedup_hash),
                txn_source_docs.c.txn_id.in_(alias_matched_ids),
            ),
        )
    )
    return and_(
        AtomicTransaction.user_id == user_id,
        AtomicTransaction.id.in_(eligible_ids)
        if statement_id is not None
        else or_(AtomicTransaction.id.notin_(known_source_ids), AtomicTransaction.id.in_(eligible_ids)),
    )
