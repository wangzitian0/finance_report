"""Shared effective-source membership for downstream transaction queues/actions."""

from uuid import UUID

from sqlalchemy import String, and_, case, cast, func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from src.extraction.base.source_vocabulary import BankStatementStatus
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction, AtomicTransactionIdentity
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.extraction.orm.statement_summary import StatementSummary


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
    linked = and_(
        StatementSummary.user_id == user_id,
        StatementSummary.uploaded_document_id.is_not(None),
        AtomicTransaction.source_documents.op("@>")(
            func.jsonb_build_array(
                func.jsonb_build_object("doc_id", cast(StatementSummary.uploaded_document_id, String))
            )
        ),
    )
    known_source_ids = (
        select(AtomicTransaction.id)
        .select_from(StatementSummary)
        .join(
            AtomicTransaction,
            and_(
                AtomicTransaction.user_id == user_id,
                linked,
            ),
        )
    )
    payload = case(
        (
            StatementSummary.current_extraction_result_id.is_(None),
            StatementSummary.extraction_metadata["statement_extraction_result"],
        ),
        else_=StatementExtractionResultRecord.payload,
    )
    expected_scope = case(
        (StatementSummary.account_id.is_not(None), func.concat("account:", cast(StatementSummary.account_id, String))),
        else_=func.concat("source:", UploadedDocument.file_hash),
    )
    # A raw legacy hash may have collapsed same-currency accounts. Every
    # historical source must independently agree with the requested custody;
    # one matching envelope is not enough to authorize this atomic identity.
    source_summary = aliased(StatementSummary)
    source_document = aliased(UploadedDocument)
    source_linked = AtomicTransaction.source_documents.op("@>")(
        func.jsonb_build_array(func.jsonb_build_object("doc_id", cast(source_summary.uploaded_document_id, String)))
    )
    compatible_sources = (
        select(func.count(func.distinct(source_document.id)))
        .select_from(source_summary)
        .join(source_document, source_document.id == source_summary.uploaded_document_id)
        .where(
            source_summary.user_id == user_id,
            source_document.user_id == user_id,
            source_linked,
            or_(
                and_(
                    StatementSummary.account_id.is_not(None), source_summary.account_id == StatementSummary.account_id
                ),
                and_(StatementSummary.account_id.is_(None), source_document.id == UploadedDocument.id),
            ),
            or_(
                source_summary.currency == AtomicTransaction.currency,
                source_summary.currency_balances.op("@>")(
                    func.jsonb_build_array(func.jsonb_build_object("currency", AtomicTransaction.currency))
                ),
            ),
        )
        .correlate(AtomicTransaction, StatementSummary, UploadedDocument)
        .scalar_subquery()
    )
    source_count = case(
        (
            func.jsonb_typeof(AtomicTransaction.source_documents) == "array",
            func.jsonb_array_length(AtomicTransaction.source_documents),
        ),
        else_=0,
    )
    statement_currency_compatible = or_(
        StatementSummary.currency == AtomicTransaction.currency,
        StatementSummary.currency_balances.op("@>")(
            func.jsonb_build_array(func.jsonb_build_object("currency", AtomicTransaction.currency))
        ),
    )
    custody_proven = and_(
        statement_currency_compatible,
        or_(
            source_count == 1,
            and_(source_count > 1, compatible_sources == source_count),
        ),
    )

    def fact_match(identity):
        return or_(
            func.jsonb_extract_path(payload, "transactions").op("@>")(
                func.jsonb_build_array(
                    func.jsonb_build_object("fact_id", identity, "currency", AtomicTransaction.currency)
                )
            ),
            func.jsonb_extract_path(payload, "transactions").op("@>")(
                func.jsonb_build_array(func.jsonb_build_object("fact_id", identity, "currency", None))
            ),
        )

    alias_match = (
        select(AtomicTransactionIdentity.atomic_txn_id)
        .where(
            AtomicTransactionIdentity.user_id == user_id,
            AtomicTransactionIdentity.atomic_txn_id == AtomicTransaction.id,
            AtomicTransactionIdentity.currency == AtomicTransaction.currency,
            AtomicTransactionIdentity.custody_scope == expected_scope,
            AtomicTransactionIdentity.identity_version == "v2",
            fact_match(AtomicTransactionIdentity.identity_hash),
        )
        .correlate(AtomicTransaction, StatementSummary, StatementExtractionResultRecord, UploadedDocument)
        .exists()
    )
    eligible_ids = (
        select(AtomicTransaction.id)
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
        .join(
            AtomicTransaction,
            and_(
                AtomicTransaction.user_id == user_id,
                linked,
            ),
        )
        .where(
            UploadedDocument.user_id == user_id,
            (
                StatementSummary.status.notin_([BankStatementStatus.RETIRED, BankStatementStatus.REJECTED])
                if include_pending_stage1
                else StatementSummary.status == BankStatementStatus.APPROVED
            ),
            custody_proven,
            or_(
                and_(StatementSummary.current_extraction_result_id.is_(None), payload.is_(None)),
                fact_match(AtomicTransaction.dedup_hash),
                alias_match,
            ),
        )
    )
    if statement_id is not None:
        eligible_ids = eligible_ids.where(StatementSummary.id == statement_id)
    return and_(
        AtomicTransaction.user_id == user_id,
        AtomicTransaction.id.in_(eligible_ids)
        if statement_id is not None
        else or_(AtomicTransaction.id.notin_(known_source_ids), AtomicTransaction.id.in_(eligible_ids)),
    )
