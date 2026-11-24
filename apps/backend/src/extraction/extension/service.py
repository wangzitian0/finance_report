"""ExtractionService: core LLM parse path and mixin composition."""

import asyncio
import json
import time
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from infra2_sdk.runtime import DecodingSpec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.audit.money.currency import normalize_currency_code
from src.extraction.base.decoding import EXTRACTION_TIMEOUT_SECONDS, JSON_MAX_TOKENS
from src.extraction.base.findings import (
    Finding,
    PassScore,
    check_feedback_block,
    document_findings,
    replaces,
    score_pass,
)
from src.extraction.base.normalization_engine import sanitize_account_last4
from src.extraction.base.paged_extraction import (
    MultipleAccountsError,
    build_meta_prompt,
    build_paged_meta_prompt,
    build_paged_prompt,
    build_rows_prompt,
    merge_paged_extractions,
    split_paged_extractions_by_account,
)
from src.extraction.base.result import ExtractionMethod, StatementEvidenceType, StatementExtractionResult
from src.extraction.base.source_balance_check import (
    SourceBalanceVerdict,
    check_closing_balance_against_text,
    rows_missing_from_text,
    text_prints_money,
)
from src.extraction.base.source_capability import SOURCE_CAPABILITIES
from src.extraction.base.source_vocabulary import BankStatementStatus, DocumentType, Stage1Status, TransactionDirection
from src.extraction.base.types import DocumentSource, ExtractedTransactionRow, RunHints
from src.extraction.base.validation import (
    HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD,
    AccountExtractionSlice,
    DuplicateCurrencyError,
    balance_gap_suspect_rows,
    balance_is_evaluable,
    bank_currency_balances,
    compute_confidence_breakdown,
    count_within_document_dedup_collapse,
    detect_balance_chain_break,
    evaluate_statement_balance,
    normalize_amount_direction,
    split_multi_account_extraction,
    validate_balance_per_currency,
)
from src.extraction.extension._base import (
    ExtractionError,
    _tolerant_parse_date,
    logger,
)
from src.extraction.extension._coerce import _CoerceMixin
from src.extraction.extension._csv import _CsvMixin
from src.extraction.extension._llm_led_gate import evaluate_llm_led_extraction_gate
from src.extraction.extension._media import _MediaMixin
from src.extraction.extension.brokerage_positions import (
    brokerage_currency_balances,
    looks_like_brokerage_document,
    looks_like_brokerage_payload,
    parse_brokerage_positions,
)
from src.extraction.extension.currency_resolution import resolve_ingest_currency
from src.extraction.extension.custody_binding import (
    BankCustodyAllocation,
    custody_account_type_for_statement,
    release_rejected_custody,
    resolve_bank_custody,
    validate_custody_account,
)
from src.extraction.extension.deduplication import DeduplicationService, _decimal_key, dual_write_layer2
from src.extraction.extension.pdf_text_layer import read_pdf_text_layer
from src.extraction.extension.prompts.statement import PROMPT_FILE_TYPES, get_parsing_prompt, parsing_hints_block
from src.extraction.extension.result_contract import build_statement_extraction_result, statement_evidence_type
from src.extraction.orm.bank_custody_binding import BankCustodyBinding
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import AccountType
from src.llm import ModelCallFailed, ModelFailureKind
from src.llm.extension.agent import CallSite, complete_text
from src.observability import record_financial_invariant_violation

settings = src.config.settings

# What a failed pass raises when the model failed (`ExtractionError`) or its reading has the wrong shape: a field of
# the wrong type, a missing key, a number that does not parse. The loop keeps the earlier pass for these. Any other
# error is a bug and ends the loop.
_PASS_FAILURES = (ExtractionError, ValueError, ArithmeticError, LookupError, AttributeError, TypeError)

# The failure kinds of a model call, grouped by the `ExtractionError` kind that the caller and the run report.
_EXTRACTION_RATE_LIMITED = frozenset({ModelFailureKind.RATE_LIMIT, ModelFailureKind.USAGE_LIMIT})
_EXTRACTION_PROVIDER_FAULTS = frozenset(
    {ModelFailureKind.UNAVAILABLE, ModelFailureKind.REJECTED, ModelFailureKind.NOT_CONFIGURED}
)


# A review reason names at most this many rows; the log line holds every row number.
MAX_ROWS_NAMED_IN_REVIEW_REASON = 20


def rows_not_in_text_review_reason(rows: list[int]) -> str:
    """Return the review reason that names the rows whose numbers the PDF text does not print."""
    named = ", ".join(str(number) for number in rows[:MAX_ROWS_NAMED_IN_REVIEW_REASON])
    more = len(rows) - MAX_ROWS_NAMED_IN_REVIEW_REASON
    return f"Rows not found in the document text: {named}" + (f" and {more} more" if more > 0 else "")


def _institution_class(*, is_brokerage: bool) -> str:
    return "brokerage" if is_brokerage else "bank"


def _format_failed_currencies(per_currency_result: dict[str, Any], prefix: str) -> str:
    failed = [
        f"{r['currency']} (expected {r.get('expected_closing')}, got {r.get('actual_closing')})"
        for r in per_currency_result.get("per_currency", [])
        if not r.get("balance_valid")
    ]
    return f"{prefix}: {', '.join(failed)}" if failed else prefix


class ExtractionService(_MediaMixin, _CoerceMixin, _CsvMixin):
    """Service for extracting structured data from financial documents."""

    def __init__(self) -> None:
        self.api_key = settings.ai_api_key
        self.small_model = settings.small_model
        self.multimodal_model = settings.multimodal_model
        self.deduplication_service = DeduplicationService()

    async def _extract_csv_source(self, source: DocumentSource, *, institution: str | None) -> dict[str, Any]:
        if not source.content:
            raise ExtractionError("File content is required for CSV parsing")
        if not institution:
            raise ExtractionError("Institution is required for CSV parsing")
        return await self._parse_csv_content(source.content, institution)

    async def _extract_vision_source(
        self,
        source: DocumentSource,
        *,
        institution: str | None,
        file_type: str,
        user_id: UUID,
        hints: RunHints | None = None,
    ) -> tuple[list[AccountExtractionSlice], bool | None]:
        return await self._extract_with_balance_retry(
            file_content=source.content,
            institution=institution,
            file_type=file_type,
            file_url=source.url,
            filename=source.filename,
            user_id=user_id,
            hints=hints,
        )

    async def parse_document(
        self,
        source: DocumentSource,
        institution: str | None = None,
        *,
        user_id: UUID,
        file_type: str = "pdf",
        account_id: UUID | None = None,
        db: AsyncSession | None = None,
        hints: RunHints | None = None,
    ) -> StatementExtractionResult:
        """Parse document via AI vision or CSV parser into the primary immutable StatementExtractionResult."""
        results = await self.parse_documents(
            source,
            institution=institution,
            user_id=user_id,
            file_type=file_type,
            account_id=account_id,
            db=db,
            hints=hints,
        )
        return results[0]

    async def extract_document_slices(
        self,
        source: DocumentSource,
        institution: str | None = None,
        *,
        user_id: UUID,
        file_type: str = "pdf",
        hints: RunHints | None = None,
    ) -> tuple[list[AccountExtractionSlice], bool | None]:
        """Extract raw document slices via CSV parser or multimodal LLM without touching DB."""
        if not isinstance(source, DocumentSource):
            raise TypeError("parse_documents requires a DocumentSource")

        model = self.multimodal_model
        logger.info(
            "Parsing document",
            institution=institution or "(auto-detect)",
            file_type=file_type,
            model=model,
            filename=source.filename,
        )

        try:
            if file_type == "csv":
                extracted = await self._extract_csv_source(source, institution=institution)
                return split_multi_account_extraction(extracted), None
            if file_type in PROMPT_FILE_TYPES:
                return await self._extract_vision_source(
                    source,
                    institution=institution,
                    file_type=file_type,
                    user_id=user_id,
                    hints=hints,
                )
            raise ExtractionError(f"Unsupported file type: {file_type}")
        except Exception as e:
            if not isinstance(e, ExtractionError):
                logger.exception("Failed to parse document")
                raise ExtractionError(f"Failed to parse document: {e}") from e
            raise

    async def materialize_extracted_slices(
        self,
        source: DocumentSource,
        slices: list[AccountExtractionSlice],
        *,
        split_meta_agreed: bool | None,
        institution: str | None = None,
        user_id: UUID,
        file_type: str = "pdf",
        account_id: UUID | None = None,
        db: AsyncSession | None = None,
    ) -> list[StatementExtractionResult]:
        """Validate, score, persist, and build immutable results for extracted slices."""
        file_path = source.path
        original_filename = source.filename
        display_filename = original_filename or (file_path.name if file_path else None)
        model = self.multimodal_model
        try:
            results: list[StatementExtractionResult] = []
            for idx, slice_obj in enumerate(slices):
                results.append(
                    await self._parse_single_statement_payload(
                        slice_obj=slice_obj,
                        split_meta_agreed=split_meta_agreed,
                        source=source,
                        institution=institution,
                        user_id=user_id,
                        file_type=file_type,
                        account_id=account_id if idx == 0 else None,
                        model=model,
                        file_path=file_path,
                        display_filename=display_filename,
                        db=db,
                    )
                )
            return results
        except Exception as e:
            if not isinstance(e, ExtractionError):
                logger.exception("Failed to parse document")
                raise ExtractionError(f"Failed to parse document: {e}") from e
            raise

    async def parse_documents(
        self,
        source: DocumentSource,
        institution: str | None = None,
        *,
        user_id: UUID,
        file_type: str = "pdf",
        account_id: UUID | None = None,
        db: AsyncSession | None = None,
        hints: RunHints | None = None,
    ) -> list[StatementExtractionResult]:
        """Parse a document into 1..N immutable StatementExtractionResult values (splitting multi-account PDFs)."""
        slices, split_meta_agreed = await self.extract_document_slices(
            source,
            institution=institution,
            user_id=user_id,
            file_type=file_type,
            hints=hints,
        )
        return await self.materialize_extracted_slices(
            source,
            slices,
            split_meta_agreed=split_meta_agreed,
            institution=institution,
            user_id=user_id,
            file_type=file_type,
            account_id=account_id,
            db=db,
        )

    async def _parse_single_statement_payload(
        self,
        *,
        slice_obj: AccountExtractionSlice,
        split_meta_agreed: bool | None,
        source: DocumentSource,
        institution: str | None,
        user_id: UUID,
        file_type: str,
        account_id: UUID | None,
        model: str,
        file_path: Path | None,
        display_filename: str | None,
        db: AsyncSession | None,
    ) -> StatementExtractionResult:
        try:
            extracted = slice_obj.payload
            sub_account_key = slice_obj.sub_account_key
            if slice_obj.analysis.directions_repaired:
                # The model direction of these rows contradicted the printed running balance (#2987 AC6).
                logger.warning(
                    "statement.extraction.directions_repaired",
                    row_count=len(extracted.get("transactions") or []),
                    repaired_count=slice_obj.analysis.directions_repaired,
                )
            # A source without an institution keeps its rows. The institution is a missing fact for the reviewer.
            stated_institution = institution or extracted.get("institution")
            final_institution = stated_institution if str(stated_institution or "").strip() else None
            is_brokerage_payload = looks_like_brokerage_payload(
                extracted, filename=display_filename, institution=final_institution
            )
            brokerage_positions = (
                parse_brokerage_positions(extracted, filename=display_filename, institution=final_institution)
                if is_brokerage_payload
                else []
            )
            evidence_type = statement_evidence_type(
                is_brokerage=is_brokerage_payload, provider_payload=extracted, positions=brokerage_positions
            )
            is_position_snapshot = is_brokerage_payload and evidence_type is StatementEvidenceType.POSITION_SNAPSHOT
            if final_institution is None and (
                is_brokerage_payload or evidence_type is StatementEvidenceType.POSITION_SNAPSHOT
            ):
                # A missing institution is accepted for a bank ledger only. The envelope confirmation binds a
                # custody identity for a bank source only, and it takes no position snapshot.
                raise ExtractionError("Institution is required; extraction cannot invent source identity")

            resolved_file_hash = source.content_hash
            statement_payload = extracted.get("statement")
            nested_currency = statement_payload.get("currency") if isinstance(statement_payload, dict) else None
            raw_statement_currency = extracted.get("currency") or nested_currency
            statement_currency = normalize_currency_code(raw_statement_currency)
            resolved_period_start = self._safe_optional_date(extracted.get("period_start"))
            resolved_period_end = self._safe_optional_date(extracted.get("period_end"))
            if evidence_type is StatementEvidenceType.POSITION_SNAPSHOT and (
                resolved_period_start is None or resolved_period_end is None
            ):
                snapshot_dates = {pos.snapshot_date for pos in brokerage_positions if pos.snapshot_date is not None}
                if len(snapshot_dates) == 1:
                    resolved_period_start = resolved_period_end = next(iter(snapshot_dates))

            opening_balance_dec = self._safe_decimal(extracted.get("opening_balance"))
            closing_balance_dec = self._safe_decimal(extracted.get("closing_balance"))
            custody_account_type = custody_account_type_for_statement(
                institution=final_institution,
                filename=display_filename,
                opening_balance=opening_balance_dec,
                closing_balance=closing_balance_dec,
            )
            sanitized_account_last4 = sanitize_account_last4(extracted.get("account_last4"))
            account_id, sanitized_account_last4, bank_allocation = await self._resolve_bank_account_binding(
                db=db,
                user_id=user_id,
                account_id=account_id,
                institution=final_institution,
                statement_currency=statement_currency,
                sanitized_account_last4=sanitized_account_last4,
                is_brokerage_payload=is_position_snapshot,
                account_type=custody_account_type,
            )

            statement = StatementSummary(
                user_id=user_id,
                account_id=account_id,
                file_hash=resolved_file_hash,
                sub_account_key=sub_account_key,
                institution=final_institution,
                account_last4=sanitized_account_last4,
                currency=statement_currency,
                period_start=resolved_period_start,
                period_end=resolved_period_end,
                opening_balance=opening_balance_dec,
                closing_balance=closing_balance_dec,
                extraction_metadata=None,
            )

            bank_balances, currency_balances_value, per_currency_invalid_note = self._compute_per_currency_balances(
                extracted=extracted,
                statement=statement,
                is_brokerage_payload=is_brokerage_payload,
                filename=display_filename,
                institution=final_institution,
            )
            if currency_balances_value is not None:
                statement.currency_balances = currency_balances_value

            transactions: list[ExtractedTransactionRow] = []
            net_transactions = Decimal("0.00")
            occurrence_counts: dict[tuple, int] = {}
            custody_scope = f"account:{account_id}" if account_id is not None else f"source:{source.content_hash}"
            for txn in extracted.get("transactions", []):
                built = self._build_transaction_row(
                    txn=txn,
                    evidence_type=evidence_type,
                    filename=display_filename or "unknown",
                    raw_statement_currency=raw_statement_currency,
                    user_id=user_id,
                    occurrence_counts=occurrence_counts,
                    custody_scope=custody_scope,
                )
                if built is not None:
                    transaction, signed_delta = built
                    net_transactions += signed_delta
                    transactions.append(transaction)

            institution_class = _institution_class(is_brokerage=is_brokerage_payload)
            within_doc_collapse = count_within_document_dedup_collapse([t.dedup_hash for t in transactions])
            if within_doc_collapse > 0:
                logger.warning(
                    "Within-document dedup collapse detected (defense-in-depth, #1254 class)",
                    extracted_rows=len(transactions),
                    distinct_hashes=len(transactions) - within_doc_collapse,
                    collapsed_rows=within_doc_collapse,
                    is_brokerage=is_brokerage_payload,
                    statement_file=display_filename or "unknown",
                )
                record_financial_invariant_violation(
                    kind="dedup_within_doc_collapse", institution_class=institution_class
                )

            capability_id = (
                "csv_export"
                if file_type == "csv"
                else ("brokerage_statement" if is_brokerage_payload else "bank_statement")
            )
            source_capability = next((c for c in SOURCE_CAPABILITIES if c.capability_id == capability_id), None)

            balance_result = evaluate_statement_balance(
                opening=statement.opening_balance,
                closing=statement.closing_balance,
                currency=statement_currency,
                currency_balances=None,
                transactions=extracted.get("transactions", []) or [],
            )
            is_valid = bool(balance_result["balance_valid"])
            effective_balance_result = balance_result
            if per_currency_invalid_note is not None:
                is_valid = False
            elif bank_balances is not None:
                is_valid = True
                effective_balance_result = {
                    **balance_result,
                    "balance_valid": True,
                    "balance_proof_available": True,
                    "difference": "0.00",
                    "notes": None,
                }
            csv_balance_missing = extracted.get("balance_source") == "missing_from_csv_export"
            csv_balance_declared = extracted.get("balance_source") == "declared_in_csv_export"
            balance_evaluable = balance_is_evaluable(
                statement.opening_balance, statement.closing_balance, bank_balances
            )
            declared_balance_absent = not balance_evaluable

            source_fact_gaps = StatementExtractionResult.required_fact_kinds(
                evidence_type=evidence_type,
                has_institution=final_institution is not None,
                period_start=resolved_period_start,
                period_end=resolved_period_end,
                has_statement_currency=statement_currency is not None or bool(statement.currency_balances),
                has_balances=bool(statement.currency_balances)
                or (statement.currency is not None and balance_evaluable),
                has_positions=bool(brokerage_positions),
                has_unresolved_transaction_currency=any(t.currency_unresolved for t in transactions),
            )
            source_review_reason = (
                f"Source is missing required facts: {', '.join(StatementExtractionResult.required_fact_labels(source_fact_gaps))}"
                if source_fact_gaps
                else None
            )

            source_verified: bool | None = None
            rows_not_in_text_reason: str | None = None
            closing_not_in_source = False
            opening_not_in_source = False
            if file_type == "csv":
                source_verified = csv_balance_declared and not csv_balance_missing
            elif file_type == "pdf" and not is_position_snapshot:
                pdf_text = await asyncio.to_thread(
                    read_pdf_text_layer, source.content, max_pages=self.PDF_VISION_MAX_TOTAL_PAGES
                )
                if bank_balances is None:
                    closing_source_verdict = check_closing_balance_against_text(
                        pdf_text,
                        opening=statement.opening_balance,
                        closing=statement.closing_balance,
                        amounts=[transaction.amount for transaction in transactions],
                    )
                    if closing_source_verdict is SourceBalanceVerdict.CLOSING_NOT_IN_TEXT:
                        closing_not_in_source = True
                        source_verified = False
                        record_financial_invariant_violation(
                            kind="closing_balance_not_in_source", institution_class=institution_class
                        )
                        if source_review_reason is None:
                            source_review_reason = (
                                f"Closing balance {statement.closing_balance} is not in the document text"
                            )
                    elif closing_source_verdict is SourceBalanceVerdict.OPENING_NOT_IN_TEXT:
                        opening_not_in_source = True
                        source_verified = False
                        record_financial_invariant_violation(
                            kind="opening_balance_not_in_source", institution_class=institution_class
                        )
                        if source_review_reason is None:
                            source_review_reason = (
                                f"Opening balance {statement.opening_balance} is not in the document text"
                            )
                    elif closing_source_verdict is SourceBalanceVerdict.TEXT_UNUSABLE:
                        source_verified = False
                        if source_review_reason is None:
                            source_review_reason = (
                                source_capability.review_semantics
                                if source_capability and "text" in source_capability.review_semantics.lower()
                                else "PDF text layer is unusable; source review required before approval"
                            )
                    else:
                        source_verified = True
                else:
                    source_verified = bool(pdf_text and text_prints_money(pdf_text))
                    if not source_verified and source_review_reason is None:
                        source_review_reason = "PDF text layer is unusable; source review required before approval"
                rows_not_in_text = rows_missing_from_text(pdf_text, [(t.amount, t.balance_after) for t in transactions])
                if rows_not_in_text:
                    source_verified = False
                    rows_not_in_text_reason = rows_not_in_text_review_reason(rows_not_in_text)
                    source_review_reason = (
                        f"{source_review_reason}; {rows_not_in_text_reason}"
                        if source_review_reason
                        else rows_not_in_text_reason
                    )
                    logger.warning(
                        "statement.extraction.rows_not_in_text",
                        row_count=len(transactions),
                        missing_count=len(rows_not_in_text),
                        rows=rows_not_in_text,
                    )
            elif file_type in {"png", "jpg", "jpeg"} and not is_position_snapshot:
                source_verified = False
                if source_review_reason is None:
                    source_review_reason = (
                        "Image upload has no verifiable text layer; source review required before approval"
                    )

            balance_not_in_source = closing_not_in_source or opening_not_in_source
            effective_balance_valid = is_valid and not balance_not_in_source
            breakdown = compute_confidence_breakdown(
                extracted,
                {
                    **effective_balance_result,
                    "balance_valid": effective_balance_valid if balance_evaluable else False,
                    "balance_proof_available": balance_evaluable,
                    "notes": source_review_reason or effective_balance_result.get("notes"),
                },
                is_brokerage=is_brokerage_payload,
                effective_txn_count=len(transactions),
                source_verified=source_verified,
                split_meta_agreed=split_meta_agreed,
                has_source_fact_gaps=bool(source_fact_gaps) or csv_balance_missing,
                closing_not_in_source=closing_not_in_source,
                opening_not_in_source=opening_not_in_source,
                has_source_review_reason=source_review_reason is not None,
            )

            confidence = breakdown.score
            status = (
                BankStatementStatus.APPROVED
                if (
                    not is_position_snapshot
                    and is_valid
                    and not csv_balance_missing
                    and not source_fact_gaps
                    and not balance_not_in_source
                    and source_review_reason is None
                    and confidence >= HIGH_CONFIDENCE_AUTO_APPROVE_THRESHOLD
                    and account_id is not None
                )
                else BankStatementStatus.PARSED
            )

            statement.balance_validated = (
                None if (not balance_evaluable and per_currency_invalid_note is None) else effective_balance_valid
            )

            if not transactions and not brokerage_positions:
                statement.validation_error = (
                    "Document appears to contain no transactions or holdings in recognizable format."
                )
            elif per_currency_invalid_note is not None:
                statement.validation_error = per_currency_invalid_note
            elif not is_valid and balance_evaluable:
                statement.validation_error = balance_result["notes"]
            elif source_review_reason is not None:
                statement.validation_error = source_review_reason
            elif csv_balance_missing:
                statement.validation_error = "Source CSV does not declare opening and closing balances"
            statement.confidence_score = confidence
            statement.status = status

            if not is_valid and per_currency_invalid_note is None and not csv_balance_missing:
                record_financial_invariant_violation(kind="balance_mismatch", institution_class=institution_class)
                chain_break = detect_balance_chain_break(
                    extracted.get("transactions", []) or [], opening_balance=statement.opening_balance
                )
                if chain_break is not None:
                    logger.warning(
                        "Running-balance chain break detected",
                        break_index=chain_break.index,
                        delta=str(chain_break.delta),
                        statement_file=display_filename or "unknown",
                    )
                    record_financial_invariant_violation(kind="chain_break", institution_class=institution_class)

            llm_led_gate = evaluate_llm_led_extraction_gate(
                is_brokerage=is_brokerage_payload,
                balance_valid=is_valid,
                within_doc_collapse=within_doc_collapse,
                balance_gate_exempt=csv_balance_missing or csv_balance_declared or declared_balance_absent,
            )
            if llm_led_gate.quarantined:
                reason, metric_kind = llm_led_gate.reason, llm_led_gate.metric_kind
                if reason is None or metric_kind is None:
                    raise ExtractionError("quarantined extraction gate requires a typed reason and metric")
                status = BankStatementStatus.REJECTED
                statement.status = status
                statement.balance_validated = False
                statement.stage1_status = Stage1Status.REJECTED
                statement.validation_error = f"{reason.value}: {llm_led_gate.message}" + (
                    f"; {rows_not_in_text_reason}" if rows_not_in_text_reason else ""
                )
                record_financial_invariant_violation(kind=metric_kind, institution_class=institution_class)
                balance_gap = balance_result["difference"]
                logger.warning(
                    "LLM-LED invariant gate quarantined extraction (blocked from trusted truth)",
                    reason=reason.value,
                    is_brokerage=is_brokerage_payload,
                    file_hash=resolved_file_hash,
                    row_count=len(transactions),
                    balance_gap=balance_gap,
                    in_count=sum(1 for t in transactions if t.direction == TransactionDirection.IN.value),
                    out_count=sum(1 for t in transactions if t.direction == TransactionDirection.OUT.value),
                    suspect_rows=balance_gap_suspect_rows([t.amount for t in transactions], Decimal(balance_gap)),
                )
                if bank_allocation is not None and db is not None:
                    await release_rejected_custody(db, bank_allocation)
                    if bank_allocation.account_created:
                        statement.account_id = None

            if status == BankStatementStatus.PARSED:
                statement.stage1_status = Stage1Status.PENDING_REVIEW

            try:
                extraction_result = build_statement_extraction_result(
                    source=source,
                    file_type=file_type,
                    statement=statement,
                    transactions=[] if llm_led_gate.quarantined else transactions,
                    provider_payload=extracted,
                    model=model,
                    provider=settings.ai_provider,
                    method=(
                        ExtractionMethod(extracted.get("extraction_method", "live_llm"))
                        if file_type == "csv"
                        else ExtractionMethod.LIVE_LLM
                    ),
                    is_brokerage=is_brokerage_payload,
                    evidence_type=evidence_type,
                    positions=brokerage_positions,
                )
            except (TypeError, ValueError) as exc:
                raise ExtractionError(f"Incomplete statement extraction result: {exc}") from exc
            result_metadata: dict[str, Any] = {"statement_extraction_result": extraction_result.to_payload()}
            statement.extraction_metadata = result_metadata

            logger.info(
                "Parsing validation completed",
                status=status,
                confidence=confidence,
                is_balanced=is_valid,
                tx_count=len(transactions),
            )

            if db:
                await dual_write_layer2(
                    db=db,
                    user_id=user_id,
                    statement=statement,
                    transactions=[] if llm_led_gate.quarantined else transactions,
                    file_path=file_path,
                    original_filename=display_filename or "unknown",
                    document_type=(
                        DocumentType.BROKERAGE_STATEMENT if is_brokerage_payload else DocumentType.BANK_STATEMENT
                    ),
                    extraction_metadata=result_metadata,
                    envelope_only=llm_led_gate.quarantined,
                )

            return extraction_result

        except Exception as e:
            if not isinstance(e, ExtractionError):
                logger.exception("Failed to parse document")
                raise ExtractionError(f"Failed to parse document: {e}") from e
            raise

    async def _resolve_bank_account_binding(
        self,
        *,
        db: AsyncSession | None,
        user_id: UUID,
        account_id: UUID | None,
        institution: str | None,
        statement_currency: str | None,
        sanitized_account_last4: str | None,
        is_brokerage_payload: bool,
        account_type: AccountType = AccountType.ASSET,
    ) -> tuple[UUID | None, str | None, BankCustodyAllocation | None]:
        bank_allocation = None
        if db is not None and account_id is not None and not is_brokerage_payload:
            await validate_custody_account(db, user_id=user_id, account_id=account_id, currency=statement_currency)
        if db is not None and not is_brokerage_payload and institution and statement_currency:
            if sanitized_account_last4:
                bank_allocation = await resolve_bank_custody(
                    db,
                    user_id=user_id,
                    institution=institution,
                    account_last4=sanitized_account_last4,
                    currency=statement_currency,
                    account_id=account_id,
                    account_type=account_type,
                )
                account_id = bank_allocation.account.id
            elif account_id is None:
                bindings = (
                    (
                        await db.execute(
                            select(BankCustodyBinding)
                            .where(
                                BankCustodyBinding.user_id == user_id,
                                BankCustodyBinding.institution == institution,
                                BankCustodyBinding.currency == statement_currency,
                            )
                            .limit(2)
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(bindings) == 1:
                    await validate_custody_account(
                        db, user_id=user_id, account_id=bindings[0].account_id, currency=statement_currency
                    )
                    account_id = bindings[0].account_id
                    sanitized_account_last4 = bindings[0].account_last4
        return account_id, sanitized_account_last4, bank_allocation

    def _compute_per_currency_balances(
        self,
        *,
        extracted: dict[str, Any],
        statement: StatementSummary,
        is_brokerage_payload: bool,
        filename: str | None,
        institution: str | None,
    ) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None, str | None]:
        _ = statement
        per_currency_invalid_note: str | None = None
        currency_balances_value: list[dict[str, Any]] | None = None
        institution_class = _institution_class(is_brokerage=is_brokerage_payload)

        if is_brokerage_payload:
            brokerage_balances = brokerage_currency_balances(extracted, filename=filename, institution=institution)
            if brokerage_balances:
                per_currency_result = validate_balance_per_currency(
                    {"balances": brokerage_balances, "transactions": []}
                )
                if not per_currency_result["balance_valid"]:
                    per_currency_invalid_note = _format_failed_currencies(
                        per_currency_result, "Per-currency NAV self-check failed"
                    )
                    logger.warning(
                        "Per-currency brokerage NAV failed self-check",
                        per_currency=per_currency_result["per_currency"],
                    )
                    record_financial_invariant_violation(kind="per_currency_nav", institution_class=institution_class)
                currency_balances_value = [
                    {
                        "currency": bucket["currency"],
                        "opening": str(bucket["opening"]),
                        "closing": str(bucket["closing"]),
                    }
                    for bucket in brokerage_balances
                ]
            return None, currency_balances_value, per_currency_invalid_note

        bank_balances = None
        try:
            bank_balances = bank_currency_balances(extracted)
        except (ValueError, InvalidOperation, TypeError) as exc:
            per_currency_invalid_note = f"Per-currency balances could not be parsed: {exc}"
            record_financial_invariant_violation(kind="per_currency_balance", institution_class=institution_class)
        if bank_balances:
            bank_per_currency = validate_balance_per_currency(
                {"balances": bank_balances, "transactions": extracted.get("transactions", [])}
            )
            if not bank_per_currency["balance_valid"]:
                per_currency_invalid_note = _format_failed_currencies(
                    bank_per_currency, "Per-currency balance self-check failed"
                )
                record_financial_invariant_violation(kind="per_currency_balance", institution_class=institution_class)
            currency_balances_value = bank_balances
        return bank_balances, currency_balances_value, per_currency_invalid_note

    def _build_transaction_row(
        self,
        *,
        txn: dict[str, Any],
        evidence_type: StatementEvidenceType,
        filename: str | None,
        raw_statement_currency: str | None,
        user_id: UUID,
        occurrence_counts: dict[tuple, int],
        custody_scope: str,
    ) -> tuple[ExtractedTransactionRow, Decimal] | None:
        if not txn.get("date") or txn.get("amount") is None:
            if evidence_type is StatementEvidenceType.POSITION_SNAPSHOT:
                logger.info("Skipping non-bank transaction row in brokerage payload", filename=filename)
                return None
            raise ExtractionError("Transaction missing required fields: date or amount")

        parsed_date = _tolerant_parse_date(str(txn["date"]))
        if parsed_date is None:
            raise ExtractionError(
                "Transaction date could not be parsed. No partial transaction set was imported; "
                "retry extraction or review the original source."
            )

        try:
            amount = Decimal(str(txn["amount"]))
        except (ValueError, TypeError, InvalidOperation) as exc:
            if evidence_type is StatementEvidenceType.POSITION_SNAPSHOT:
                logger.info("Skipping brokerage transaction row with non-bank amount", filename=filename)
                return None
            raise ExtractionError(f"Invalid transaction amount: {txn.get('amount')}") from exc

        amount, direction = normalize_amount_direction(amount, txn.get("direction"))
        resolved_currency = resolve_ingest_currency(txn.get("currency"), raw_statement_currency)
        txn_currency = resolved_currency.code
        txn_balance_after = self._safe_decimal(txn.get("balance_after"))
        txn_direction = TransactionDirection.IN if direction == "IN" else TransactionDirection.OUT
        raw_description = txn.get("description")
        txn_description = str(raw_description) if raw_description is not None else ""
        if not txn_description.strip():
            txn_description = "Unknown"
        txn_reference = txn.get("reference")

        occ_key = (
            parsed_date,
            _decimal_key(amount),
            txn_direction.value,
            txn_description.strip().lower(),
            txn_reference or "",
            txn_currency,
            _decimal_key(txn_balance_after) if txn_balance_after is not None else "",
        )
        occurrence_index = occurrence_counts.get(occ_key, 0)
        occurrence_counts[occ_key] = occurrence_index + 1

        dedup_hash = self.deduplication_service.calculate_transaction_hash(
            user_id,
            parsed_date,
            amount,
            txn_direction,
            txn_description,
            reference=txn_reference,
            balance_after=txn_balance_after,
            occurrence_index=occurrence_index,
            currency=txn_currency,
            custody_scope=custody_scope,
        )
        transaction = ExtractedTransactionRow(
            user_id=user_id,
            txn_date=parsed_date,
            amount=amount,
            direction=txn_direction.value,
            description=txn_description,
            reference=txn_reference,
            currency=txn_currency,
            currency_unresolved=resolved_currency.unresolved,
            balance_after=txn_balance_after,
            occurrence_index=occurrence_index,
            dedup_hash=dedup_hash,
            custody_scope=custody_scope,
        )
        return transaction, (amount if direction == "IN" else -amount)

    async def _extract_with_balance_retry(
        self,
        *,
        file_content: bytes | None,
        institution: str | None,
        file_type: str,
        file_url: str | None,
        filename: str | None,
        user_id: UUID | None = None,
        hints: RunHints | None = None,
    ) -> tuple[list[AccountExtractionSlice], bool | None]:
        max_attempts = max(1, settings.ai_extract_max_attempts)
        base_seed = settings.ai_json_seed
        best: tuple[list[AccountExtractionSlice], bool | None] | None = None
        best_score: PassScore | None = None
        best_findings: list[Finding] = []
        last_error: Exception | None = None
        last_pass_error: Exception | None = None  # the error of the last pass; None when the last pass completed
        extract_overridden = (
            type(self).extract_financial_data is not _ORIGINAL_EXTRACT_FINANCIAL_DATA
            or "extract_financial_data" in self.__dict__
        )
        source_text = (
            await asyncio.to_thread(read_pdf_text_layer, file_content, max_pages=self.PDF_VISION_MAX_TOTAL_PAGES)
            if file_type == "pdf" and file_content
            else None
        )
        # The check results of the last pass. The next pass sends them to the model.
        feedback = ""
        read_text_layer = True

        for attempt in range(max_attempts):
            seed_override = base_seed + attempt if base_seed is not None and attempt > 0 else None
            structlog.contextvars.bind_contextvars(extract_attempt=attempt + 1)
            try:
                if extract_overridden:
                    raw_extracted = await self.extract_financial_data(
                        file_content=file_content,
                        institution=institution,
                        file_type=file_type,
                        file_url=file_url,
                        seed_override=seed_override,
                        filename=filename,
                        user_id=user_id,
                        read_text_layer=read_text_layer,
                        hints=hints,
                        feedback=feedback,
                    )
                    split_meta_agreed: bool | None = None
                else:
                    raw_extracted, split_meta_agreed = await self._extract_financial_data_with_meta(
                        file_content=file_content,
                        institution=institution,
                        file_type=file_type,
                        file_url=file_url,
                        seed_override=seed_override,
                        filename=filename,
                        user_id=user_id,
                        read_text_layer=read_text_layer,
                        split_single_batch=attempt == 0,
                        hints=hints,
                        feedback=feedback,
                    )
                slices = split_multi_account_extraction(raw_extracted)
                readings = [s.payload for s in slices]
                findings = document_findings(readings, source_text=source_text, institution_given=bool(institution))
                score = score_pass(readings, findings, source_text=source_text)
                is_brokerage = looks_like_brokerage_payload(
                    readings[0], filename=filename, institution=institution or readings[0].get("institution")
                )
            except _PASS_FAILURES as exc:
                # A later pass that fails this way never discards the kept pass. Without a kept pass, two
                # balances in one currency end the loop with a message for the user, and an unknown error is
                # raised. An error of another class is a bug: it ends the loop with that error.
                if best is None and isinstance(exc, DuplicateCurrencyError):
                    raise ExtractionError(
                        f"This statement lists several balances in {exc.currency}, usually several accounts in "
                        "one PDF. Upload one account per file."
                    ) from exc
                if best is None and not isinstance(exc, (ExtractionError, ValueError, ArithmeticError)):
                    raise
                logger.warning(
                    "Extraction pass failed",
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    error_type=type(exc).__name__,
                    error=str(exc)[:300],
                )
                last_error = last_pass_error = exc
                # A pass that gave no reading has no check result. The next pass reads the pages another way.
                read_text_layer = False
                continue
            finally:
                structlog.contextvars.unbind_contextvars("extract_attempt")
            current_parse = (slices, split_meta_agreed)
            last_pass_error = None

            if is_brokerage and (best_score is None or best_score.balance_fails or best_score.unusable):
                # A brokerage reading is judged by its positions, not by the checks of a bank account. It
                # does not replace a kept bank reading that is usable and has no balance gap.
                return current_parse

            logger.info(
                "statement.extraction.pass_checked",
                attempt=attempt + 1,
                max_attempts=max_attempts,
                finding_codes=[finding.code.value for finding in findings],
            )
            if best is None or best_score is None or replaces(score, best_score):
                best, best_score, best_findings, improved = current_parse, score, findings, True
            else:
                improved = False
            if not best_findings:
                return best
            if not improved and not best_score.balance_fails:
                # The pass did not improve the kept pass: the document does not print what the checks ask for.
                break
            # The next pass gets the check results of the kept pass. The text checks judge the text, so the
            # next pass reads the text again. A balance gap sends the last pass to the page images, and each
            # pass after the second.
            feedback = check_feedback_block(best_findings)
            last_pass_is_next = attempt + 2 >= max_attempts
            read_text_layer = not best_score.balance_fails or (attempt == 0 and not last_pass_is_next)

        if best is not None and best_score is not None:
            if max_attempts > 1:
                logger.info(
                    "Checks did not pass after re-extract; keeping the best pass",
                    attempts=max_attempts,
                    ended_on_failure=last_pass_error is not None,
                    failed_pass=type(last_pass_error).__name__ if last_pass_error is not None else None,
                    finding_count=best_score.finding_count,
                    best_difference=str(best_score.gap),
                    rows=best_score.rows,
                )
            return best
        raise last_error or ExtractionError("Extraction failed after all retries")

    async def _extract_json_with_model(
        self,
        messages: list[dict[str, Any]],
        model: str,
        seed_override: int | None = None,
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        from src.observability import ErrorIds

        def failed(kind: str, detail: str) -> ExtractionError:
            logger.error(
                "Extraction model call failed",
                error_id=ErrorIds.EXTRACTION_ALL_MODELS_FAILED,
                model=model,
                failure_kind=kind,
            )
            return ExtractionError(f"Extraction failed ({kind}): {detail}")

        try:
            logger.info("Attempting AI extraction (streaming)", model=model)
            content = await complete_text(
                CallSite.EXTRACTION_STATEMENT,
                "multimodal",
                messages[-1]["content"],
                model=model,
                decoding=DecodingSpec(
                    "extraction.statement.v1",
                    thinking=False,
                    temperature=0.0,
                    seed=seed_override if seed_override is not None else settings.ai_json_seed,
                    max_tokens=JSON_MAX_TOKENS,
                    timeout=EXTRACTION_TIMEOUT_SECONDS,
                ),
                extra_body={"do_sample": False},
                max_attempts=2,
            )
            if not content or not content.strip():
                logger.error("AI returned empty response", error_id=ErrorIds.EXTRACTION_EMPTY_RESPONSE, model=model)
                raise failed(
                    "empty_response", f"Model {model} returned empty response. Please retry with a different model."
                )

            try:
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise ExtractionError("AI response must be a strict JSON object (no arrays).")
                logger.info("AI extraction successful (streaming)", model=model)
                return parsed
            except (json.JSONDecodeError, RecursionError) as e:  # nesting of 100000 brackets is a reply that cannot be read
                repaired = self._repair_json_object(content)
                if repaired is not None:
                    try:
                        parsed = json.loads(repaired)
                        if isinstance(parsed, dict):
                            logger.info("AI extraction recovered via JSON repair", model=model)
                            return parsed
                    except (json.JSONDecodeError, RecursionError):
                        pass

                logger.error(
                    "Failed to parse AI JSON",
                    error_id=ErrorIds.EXTRACTION_JSON_PARSE,
                    model=model,
                    error=str(e),
                    error_position=getattr(e, "pos", None),
                    content_length=len(content),
                    looks_like_html=content.strip().startswith("<"),
                    looks_like_xml=content.strip().startswith("<?xml"),
                )
                raise failed(
                    "json_parse",
                    "AI response must be a strict JSON object (no markdown or extra text). "
                    "Please retry with a different model.",
                ) from e

        except ModelCallFailed as e:
            # The entry point counted and logged the failure and redacted its text; the kind is the cause.
            if e.kind in _EXTRACTION_RATE_LIMITED:
                logger.warning("AI extraction rate limited", error_id=ErrorIds.OPENROUTER_HTTP_ERROR, model=model)
                raise failed("rate_limit", f"Model {model} rate limited: {e.summary}") from e
            if e.kind is ModelFailureKind.TIMEOUT:
                logger.warning(
                    "AI extraction timed out",
                    error_id=ErrorIds.OPENROUTER_TIMEOUT,
                    model=model,
                    timeout_seconds=EXTRACTION_TIMEOUT_SECONDS,
                )
                raise failed("timeout", f"Model {model} timed out: {e.summary}") from e
            if e.kind in _EXTRACTION_PROVIDER_FAULTS:
                raise failed("http_error", f"Model {model} failed: {e.summary}") from e
            raise failed("model_error", f"Model {model} failed: {e.summary}") from e
        except ExtractionError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            logger.exception(
                "Programming error in extraction",
                error_id=ErrorIds.EXTRACTION_ALL_MODELS_FAILED,
                model=model,
                error_type=type(e).__name__,
            )
            raise ExtractionError(f"Internal error: {type(e).__name__}") from e

    async def extract_financial_data(
        self,
        file_content: bytes | None,
        institution: str | None,
        file_type: str,
        file_url: str | None = None,
        seed_override: int | None = None,
        filename: str | None = None,
        user_id: UUID | None = None,
        read_text_layer: bool = True,
        hints: RunHints | None = None,
        feedback: str = "",
    ) -> dict[str, Any]:
        """Extract structured statement data from the PDF text layer, or from page images when it is unusable.

        ``read_text_layer=False`` skips the text layer, so a later pass reads the pages another way.
        ``feedback`` is the block of check results of an earlier pass (``check_feedback_block``).
        """
        extracted, _ = await self._extract_financial_data_with_meta(
            file_content=file_content,
            institution=institution,
            file_type=file_type,
            file_url=file_url,
            seed_override=seed_override,
            filename=filename,
            user_id=user_id,
            read_text_layer=read_text_layer,
            split_single_batch=True,
            hints=hints,
            feedback=feedback,
        )
        return extracted

    async def _extract_financial_data_with_meta(
        self,
        *,
        file_content: bytes | None,
        institution: str | None,
        file_type: str,
        file_url: str | None = None,
        seed_override: int | None = None,
        filename: str | None = None,
        user_id: UUID | None = None,
        read_text_layer: bool = True,
        split_single_batch: bool = True,
        hints: RunHints | None = None,
        feedback: str = "",
    ) -> tuple[dict[str, Any], bool | None]:
        if file_content is None and not file_url:
            raise ExtractionError("File content is required")
        if not self.api_key:
            raise ExtractionError("AI provider API key not configured")

        mime_types = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "image": "image/png",
        }
        mime_type = mime_types.get(file_type, "application/pdf")

        logger.info(
            "Sending document to AI for extraction",
            file_type=file_type,
            institution=institution,
            provider=settings.ai_provider,
            small_model=self.small_model,
            multimodal_model=self.multimodal_model,
            pii_warning="PDF/image content may contain PII - prompt instructs AI to ignore it",
        )

        document_kind = (
            "brokerage" if looks_like_brokerage_document(filename=filename, institution=institution) else "bank"
        )
        if document_kind == "brokerage":
            logger.info(
                "Selected brokerage positions prompt for extraction",
                institution=institution,
                filename=filename,
                file_type=file_type,
            )
        prompt = get_parsing_prompt(institution, document_kind=document_kind)
        # The check results come before the reviewer guidance, which is always the last block of a prompt.
        guidance = feedback + parsing_hints_block(hints)
        model = self.multimodal_model
        if not model:
            raise ExtractionError("Multimodal model is not configured")

        allow_multiple_accounts = document_kind == "brokerage"
        text_batches = (
            await asyncio.to_thread(self._build_text_page_batches, file_content)
            if read_text_layer and file_type == "pdf"
            else None
        )
        if text_batches is not None:
            from_text, text_split_agreed = await self._extract_json_from_media_batches(
                media_batches=text_batches,
                model=model,
                prompt=prompt,
                hints_block=guidance,
                seed_override=seed_override,
                user_id=user_id,
                allow_multiple_accounts=allow_multiple_accounts,
                split_single_batch=False,
            )
            # A reply with ``accounts`` holds the rows of several accounts, read from the text (#2983).
            accounts = from_text.get("accounts")
            has_rows = from_text.get("transactions") or any(
                isinstance(account, dict)
                and isinstance(account.get("transactions"), list)
                and any(isinstance(row, dict) for row in account["transactions"])
                for account in (accounts if isinstance(accounts, list) else [])
            )
            if has_rows or (document_kind == "brokerage" and from_text.get("positions")):
                return from_text, text_split_agreed
            logger.warning(
                "PDF text layer gave no transactions or positions; reading the page images",
                page_batches=len(text_batches),
            )
        media_batches = await asyncio.to_thread(
            self._build_vision_media_payload_batches, file_content, file_url, file_type, mime_type
        )
        del file_content
        return await self._extract_json_from_media_batches(
            media_batches=media_batches,
            model=model,
            prompt=prompt,
            hints_block=guidance,
            seed_override=seed_override,
            user_id=user_id,
            allow_multiple_accounts=allow_multiple_accounts,
            split_single_batch=split_single_batch,
        )

    async def _extract_json_from_media_batches(
        self,
        *,
        media_batches: Sequence[list[dict[str, Any]]],
        model: str,
        prompt: str,
        seed_override: int | None,
        user_id: UUID | None,
        hints_block: str = "",
        allow_multiple_accounts: bool = False,
        split_single_batch: bool = False,
    ) -> tuple[dict[str, Any], bool | None]:
        """Call the model once per page batch. ``hints_block`` is the last part of every prompt."""

        def _messages(part_prompt: str, media: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [{"role": "user", "content": [{"type": "text", "text": part_prompt}, *media]}]

        async def _load_batch(batch_index: int) -> list[dict[str, Any]]:
            pop_batch = getattr(media_batches, "pop_batch", None)
            if callable(pop_batch):
                return await asyncio.to_thread(pop_batch, batch_index)
            return list(media_batches[batch_index])

        part_count = len(media_batches)

        async def _call(messages: list[dict[str, Any]], *, batch_index: int, pages: int) -> dict[str, Any]:
            started = time.perf_counter()
            part = await self._extract_json_with_model(
                messages=messages, model=model, seed_override=seed_override, user_id=user_id
            )
            logger.info(
                "statement.extraction.call_completed",
                batch_index=batch_index,
                batch_count=part_count,
                pages=pages,
                rows=len(part.get("transactions") or []),
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            return part

        if part_count == 1:
            single_batch = await _load_batch(0)
            pages = len(single_batch)
            if split_single_batch:
                meta_messages = _messages(build_meta_prompt(prompt, hints_block=hints_block), single_batch)
                rows_messages = _messages(build_rows_prompt(prompt, hints_block=hints_block), single_batch)
                del single_batch
                meta_part, rows_part = await asyncio.gather(
                    _call(meta_messages, batch_index=0, pages=pages),
                    _call(rows_messages, batch_index=1, pages=pages),
                )
                clean_meta = {k: v for k, v in meta_part.items() if k not in ("transactions", "positions")}
                rows_only = {
                    k: v for k, v in rows_part.items() if k not in ("opening_balance", "closing_balance", "balances")
                }
                merged = merge_paged_extractions([clean_meta, rows_only])
                meta_open = self._safe_decimal(meta_part.get("opening_balance"))
                meta_close = self._safe_decimal(meta_part.get("closing_balance"))
                rows_open = self._safe_decimal(rows_part.get("opening_balance"))
                rows_close = self._safe_decimal(rows_part.get("closing_balance"))
                agreed = bool((meta_open is not None and meta_close is not None) or meta_part.get("balances"))
                if agreed and rows_open is not None and meta_open is not None and rows_open != meta_open:
                    agreed = False
                if agreed and rows_close is not None and meta_close is not None and rows_close != meta_close:
                    agreed = False
                return merged, agreed
            messages = _messages(f"{prompt}{hints_block}", single_batch)
            del single_batch
            return await _call(messages, batch_index=1, pages=pages), None

        pages_per_call = self.PDF_VISION_MAX_PAGES
        total_pages = getattr(media_batches, "total_pages", None) or sum(len(media) for media in media_batches)

        parts: list[dict[str, Any]] = []
        pop_meta = getattr(media_batches, "pop_head_tail_meta_pages", None)
        if callable(pop_meta):
            meta_media, meta_page_numbers = await asyncio.to_thread(pop_meta)
        else:
            all_flat = [img for batch in media_batches for img in batch]
            head_end = min(len(all_flat), pages_per_call)
            tail_start = max(head_end, len(all_flat) - pages_per_call)
            meta_media = [*all_flat[:head_end], *all_flat[tail_start:]]
            meta_page_numbers = [*range(1, head_end + 1), *range(tail_start + 1, len(all_flat) + 1)]

        meta_messages = _messages(
            build_paged_meta_prompt(
                prompt, page_numbers=meta_page_numbers, total_pages=total_pages, hints_block=hints_block
            ),
            meta_media,
        )
        meta_pages = len(meta_media)
        del meta_media
        meta_part = await _call(meta_messages, batch_index=0, pages=meta_pages)
        del meta_messages
        parts.append({k: v for k, v in meta_part.items() if k not in ("transactions", "positions")})

        context_page: dict[str, Any] | None = None
        for part_index in range(1, part_count + 1):
            media = await _load_batch(part_index - 1)
            if part_index == 1:
                context_page = media[0]
            page_start = (part_index - 1) * pages_per_call + 1
            page_end = page_start + len(media) - 1
            has_context_page = part_index > 1
            part_prompt = build_paged_prompt(
                prompt,
                part_index=part_index,
                part_count=part_count,
                page_start=page_start,
                page_end=page_end,
                total_pages=total_pages,
                has_context_page=has_context_page,
                hints_block=hints_block,
            )
            part_media = [context_page, *media] if has_context_page and context_page is not None else list(media)
            messages = _messages(part_prompt, part_media)
            pages = len(media)
            del media, part_media
            part = await _call(messages, batch_index=part_index, pages=pages)
            del messages
            parts.append(part)

        meta_agreed: bool | None = (
            True
            if (meta_part.get("opening_balance") is not None and meta_part.get("closing_balance") is not None)
            or bool(meta_part.get("balances"))
            else None
        )
        try:
            merged = merge_paged_extractions(parts, allow_multiple_accounts=allow_multiple_accounts)
        except MultipleAccountsError as exc:
            logger.info("Multiple accounts in paged extraction", parts_by_account=exc.parts_by_account)
            account_parts = split_paged_extractions_by_account(parts)
            # Each account takes the institution and the period of the document.
            shared = {
                key: next((p.get(key) for p in parts if p.get(key)), None)
                for key in ("institution", "period_start", "period_end")
            }
            return {**shared, "accounts": account_parts}, meta_agreed
        logger.info(
            "Merged paged vision extraction",
            part_count=part_count,
            transactions=len(merged.get("transactions") or []),
            positions=len(merged.get("positions") or []),
        )
        return merged, meta_agreed


_ORIGINAL_EXTRACT_FINANCIAL_DATA = ExtractionService.extract_financial_data
