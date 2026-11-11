"""ExtractionService: core LLM parse path and mixin composition."""

import asyncio
import json
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import src.config
from src.audit.money.currency import normalize_currency_code
from src.extraction.base.paged_extraction import build_paged_meta_prompt, build_paged_prompt, merge_paged_extractions
from src.extraction.base.result import ExtractionMethod, StatementEvidenceType, StatementExtractionResult
from src.extraction.base.source_balance_check import SourceBalanceVerdict, check_closing_balance_against_text
from src.extraction.base.source_vocabulary import BankStatementStatus, DocumentType, Stage1Status, TransactionDirection
from src.extraction.base.types import DocumentSource, ExtractedTransactionRow
from src.extraction.base.validation import (
    bank_currency_balances,
    compute_confidence_score,
    count_within_document_dedup_collapse,
    detect_balance_chain_break,
    normalize_amount_direction,
    normalize_statement_balance_payload,
    route_by_threshold,
    validate_balance,
    validate_balance_explicit,
    validate_balance_per_currency,
)
from src.extraction.extension._base import (
    ExtractionError,
    _tolerant_parse_date,
    accumulate_stream,
    logger,
    stream_ai_json,
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
    release_rejected_custody,
    resolve_bank_custody,
    validate_custody_account,
)
from src.extraction.extension.deduplication import DeduplicationService, _decimal_key, dual_write_layer2
from src.extraction.extension.pdf_text_layer import read_pdf_text_layer
from src.extraction.extension.prompts.statement import get_parsing_prompt
from src.extraction.extension.result_contract import build_statement_extraction_result, statement_evidence_type
from src.extraction.orm.bank_custody_binding import BankCustodyBinding
from src.extraction.orm.statement_summary import StatementSummary
from src.observability import record_financial_invariant_violation

settings = src.config.settings


def _ai_stream_error() -> type[Exception]:
    from src.llm import AIStreamError

    return AIStreamError


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
        force_model: str | None,
        user_id: UUID,
    ) -> dict[str, Any]:
        return await self._extract_with_balance_retry(
            file_content=source.content,
            institution=institution,
            file_type=file_type,
            file_url=source.url,
            force_model=force_model,
            filename=source.filename,
            user_id=user_id,
        )

    async def parse_document(
        self,
        source: DocumentSource,
        institution: str | None = None,
        *,
        user_id: UUID,
        file_type: str = "pdf",
        account_id: UUID | None = None,
        force_model: str | None = None,
        db: AsyncSession | None = None,
    ) -> StatementExtractionResult:
        """Parse document via AI vision or CSV parser into an immutable StatementExtractionResult."""
        if not isinstance(source, DocumentSource):
            raise TypeError("parse_document requires a DocumentSource")

        file_path = source.path
        original_filename = source.filename
        display_filename = original_filename or (file_path.name if file_path else None)
        model = force_model or self.multimodal_model
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
            elif file_type in ("pdf", "png", "jpg", "jpeg"):
                extracted = await self._extract_vision_source(
                    source, institution=institution, file_type=file_type, force_model=force_model, user_id=user_id
                )
            else:
                raise ExtractionError(f"Unsupported file type: {file_type}")

            extracted = normalize_statement_balance_payload(extracted)
            final_institution = institution or extracted.get("institution")
            if not final_institution:
                raise ExtractionError("Institution is required; extraction cannot invent source identity")
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

            sanitized_account_last4 = self._sanitize_account_last4(extracted.get("account_last4"))
            account_id, sanitized_account_last4, bank_allocation = await self._resolve_bank_account_binding(
                db=db,
                user_id=user_id,
                account_id=account_id,
                institution=final_institution,
                statement_currency=statement_currency,
                sanitized_account_last4=sanitized_account_last4,
                is_brokerage_payload=is_position_snapshot,
            )

            statement = StatementSummary(
                user_id=user_id,
                account_id=account_id,
                file_hash=resolved_file_hash,
                institution=final_institution,
                account_last4=sanitized_account_last4,
                currency=statement_currency,
                period_start=resolved_period_start,
                period_end=resolved_period_end,
                opening_balance=self._safe_decimal(extracted.get("opening_balance")),
                closing_balance=self._safe_decimal(extracted.get("closing_balance")),
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
                record_financial_invariant_violation(kind="dedup_within_doc_collapse", institution_class=institution_class)
                metadata = statement.extraction_metadata if isinstance(statement.extraction_metadata, dict) else {}
                statement.extraction_metadata = {**metadata, "within_document_dedup_collapse": within_doc_collapse}

            balance_result = validate_balance_explicit(
                opening=statement.opening_balance or Decimal("0.00"),
                closing=statement.closing_balance or Decimal("0.00"),
                net_transactions=net_transactions,
            )
            is_valid = balance_result["balance_valid"]
            effective_balance_result = balance_result
            if per_currency_invalid_note is not None:
                is_valid = False
            elif bank_balances is not None:
                is_valid = True
                effective_balance_result = {
                    **balance_result,
                    "balance_valid": True,
                    "difference": "0.00",
                    "notes": None,
                }
            csv_balance_missing = extracted.get("balance_source") == "missing_from_csv_export"
            csv_balance_declared = extracted.get("balance_source") == "declared_in_csv_export"
            scalar_balance_evaluable = statement.opening_balance is not None and statement.closing_balance is not None
            balance_evaluable = scalar_balance_evaluable or bank_balances is not None
            declared_balance_absent = not balance_evaluable

            source_fact_gaps = StatementExtractionResult.required_fact_kinds(
                evidence_type=evidence_type,
                period_start=resolved_period_start,
                period_end=resolved_period_end,
                has_statement_currency=statement_currency is not None or bool(statement.currency_balances),
                has_balances=bool(statement.currency_balances)
                or (statement.currency is not None and scalar_balance_evaluable),
                has_positions=bool(brokerage_positions),
                has_unresolved_transaction_currency=any(t.currency_unresolved for t in transactions),
            )
            source_review_reason = (
                f"Source is missing required facts: {', '.join(StatementExtractionResult.required_fact_labels(source_fact_gaps))}"
                if source_fact_gaps
                else None
            )
            if file_type == "pdf" and not is_position_snapshot and bank_balances is None:
                closing_source_verdict = check_closing_balance_against_text(
                    await asyncio.to_thread(
                        read_pdf_text_layer, source.content, max_pages=self.PDF_VISION_MAX_TOTAL_PAGES
                    ),
                    opening=statement.opening_balance,
                    closing=statement.closing_balance,
                    amounts=[transaction.amount for transaction in transactions],
                )
                if closing_source_verdict is SourceBalanceVerdict.CLOSING_NOT_IN_TEXT:
                    record_financial_invariant_violation(
                        kind="closing_balance_not_in_source", institution_class=institution_class
                    )
                    if source_review_reason is None:
                        source_review_reason = (
                            f"Closing balance {statement.closing_balance} is not in the document text"
                        )

            if csv_balance_missing or source_review_reason is not None:
                confidence = min(
                    compute_confidence_score(
                        extracted,
                        {
                            **balance_result,
                            "balance_valid": is_valid if balance_evaluable else False,
                            "balance_proof_available": balance_evaluable,
                            "notes": source_review_reason or "Source CSV does not declare opening and closing balances",
                        },
                        is_brokerage=is_brokerage_payload,
                        effective_txn_count=len(transactions),
                    ),
                    59,
                )
                status = BankStatementStatus.PARSED
            else:
                confidence = compute_confidence_score(
                    extracted,
                    effective_balance_result,
                    is_brokerage=is_brokerage_payload,
                    effective_txn_count=len(transactions),
                )
                status = (
                    BankStatementStatus.PARSED if is_position_snapshot else route_by_threshold(confidence, is_valid)
                )
                if status == BankStatementStatus.APPROVED and account_id is None:
                    status = BankStatementStatus.PARSED

            statement.balance_validated = None if (not balance_evaluable and per_currency_invalid_note is None) else is_valid

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
                statement.validation_error = f"{reason.value}: {llm_led_gate.message}"
                record_financial_invariant_violation(kind=metric_kind, institution_class=institution_class)
                logger.warning(
                    "LLM-LED invariant gate quarantined extraction (blocked from trusted truth)",
                    reason=reason.value,
                    is_brokerage=is_brokerage_payload,
                    file_hash=resolved_file_hash,
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
            result_metadata = {"statement_extraction_result": extraction_result.to_payload()}
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
        force_model: str | None,
        filename: str | None,
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        max_attempts = max(1, settings.ai_extract_max_attempts)
        base_seed = settings.ai_json_seed
        best: dict[str, Any] | None = None
        best_diff: Decimal | None = None
        last_parse: dict[str, Any] | None = None
        last_error: ExtractionError | None = None

        for attempt in range(max_attempts):
            seed_override = base_seed + attempt if base_seed is not None and attempt > 0 else None
            try:
                extracted = await self.extract_financial_data(
                    file_content=file_content,
                    institution=institution,
                    file_type=file_type,
                    file_url=file_url,
                    force_model=force_model,
                    seed_override=seed_override,
                    filename=filename,
                    user_id=user_id,
                )
            except ExtractionError as exc:
                last_error = exc
                continue
            extracted = normalize_statement_balance_payload(extracted)
            last_parse = extracted

            if looks_like_brokerage_payload(
                extracted, filename=filename, institution=institution or extracted.get("institution")
            ):
                return extracted

            result = validate_balance(extracted)
            if bank_currency_balances(extracted) is not None:
                currency_result = validate_balance_per_currency(extracted)
                result = {
                    **result,
                    "balance_valid": currency_result["balance_valid"],
                    "balance_computable": currency_result["balance_computable"],
                }
            if result.get("balance_valid"):
                if attempt > 0:
                    logger.info(
                        "Balance reconciled on re-extract",
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        institution=institution or extracted.get("institution"),
                    )
                return extracted

            if result.get("balance_computable", True):
                try:
                    diff = Decimal(str(result.get("difference", "0") or "0"))
                except (ValueError, TypeError, InvalidOperation):
                    diff = None
                if diff is not None and (best is None or best_diff is None or diff < best_diff):
                    best, best_diff = extracted, diff

        if best is not None:
            if max_attempts > 1:
                logger.info(
                    "Balance did not reconcile after re-extract; keeping best parse",
                    attempts=max_attempts,
                    best_difference=str(best_diff),
                )
            return best
        if last_parse is not None:
            return last_parse
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
            stream = stream_ai_json(
                messages=messages,
                model=model,
                user_id=user_id,
                timeout=settings.ai_json_timeout_seconds,
                max_tokens=settings.ai_json_max_tokens,
                temperature=0.0,
                do_sample=False,
                seed=seed_override if seed_override is not None else settings.ai_json_seed,
                thinking={"type": "disabled"} if settings.ai_json_disable_thinking else None,
            )
            content = await accumulate_stream(stream)
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
            except json.JSONDecodeError as e:
                repaired = self._repair_json_object(content)
                if repaired is not None:
                    try:
                        parsed = json.loads(repaired)
                        if isinstance(parsed, dict):
                            logger.info("AI extraction recovered via JSON repair", model=model)
                            return parsed
                    except json.JSONDecodeError:
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

        except _ai_stream_error() as e:
            error_msg = str(e)
            if "429" in error_msg or "quota" in error_msg.lower():
                logger.warning(
                    "AI extraction rate limited",
                    error_id=ErrorIds.OPENROUTER_HTTP_ERROR,
                    model=model,
                    retryable=getattr(e, "retryable", False),
                )
                raise failed("rate_limit", f"Model {model} rate limited: {error_msg}") from e
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                logger.warning("AI extraction timed out", error_id=ErrorIds.OPENROUTER_TIMEOUT, model=model)
                raise failed("timeout", f"Model {model} timed out: {error_msg}") from e
            logger.error(
                "AI extraction HTTP error",
                error_id=ErrorIds.OPENROUTER_HTTP_ERROR,
                model=model,
                error=error_msg,
                error_type=type(e).__name__,
                retryable=getattr(e, "retryable", False),
                http_status=self._extract_status_code(error_msg),
            )
            raise failed("http_error", f"Model {model} failed: {error_msg}") from e
        except httpx.TimeoutException as e:
            logger.warning(
                "AI extraction timed out",
                error_id=ErrorIds.OPENROUTER_TIMEOUT,
                model=model,
                timeout_seconds=settings.ai_json_timeout_seconds,
            )
            raise failed("timeout", f"Model {model} timed out after {settings.ai_json_timeout_seconds}s") from e
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
        force_model: str | None = None,
        seed_override: int | None = None,
        filename: str | None = None,
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Extract structured statement data with the vision model."""
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
            force_model=force_model,
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
        model = force_model or self.multimodal_model
        if not model:
            raise ExtractionError("Multimodal model is not configured")

        media_batches = await asyncio.to_thread(
            self._build_vision_media_payload_batches, file_content, file_url, file_type, mime_type
        )
        del file_content
        return await self._extract_json_from_media_batches(
            media_batches=media_batches, model=model, prompt=prompt, seed_override=seed_override, user_id=user_id
        )

    async def _extract_json_from_media_batches(
        self,
        *,
        media_batches: Sequence[list[dict[str, Any]]],
        model: str,
        prompt: str,
        seed_override: int | None,
        user_id: UUID | None,
    ) -> dict[str, Any]:
        def _messages(part_prompt: str, media: list[dict[str, Any]]) -> list[dict[str, Any]]:
            return [{"role": "user", "content": [{"type": "text", "text": part_prompt}, *media]}]

        async def _load_batch(batch_index: int) -> list[dict[str, Any]]:
            pop_batch = getattr(media_batches, "pop_batch", None)
            if callable(pop_batch):
                return await asyncio.to_thread(pop_batch, batch_index)
            return list(media_batches[batch_index])

        if len(media_batches) == 1:
            single_batch = await _load_batch(0)
            messages = _messages(prompt, single_batch)
            del single_batch
            return await self._extract_json_with_model(
                messages=messages, model=model, seed_override=seed_override, user_id=user_id
            )

        part_count = len(media_batches)
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
            build_paged_meta_prompt(prompt, page_numbers=meta_page_numbers, total_pages=total_pages), meta_media
        )
        del meta_media
        meta_part = await self._extract_json_with_model(
            messages=meta_messages, model=model, seed_override=seed_override, user_id=user_id
        )
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
            )
            part_media = [context_page, *media] if has_context_page and context_page is not None else list(media)
            messages = _messages(part_prompt, part_media)
            del media, part_media
            part = await self._extract_json_with_model(
                messages=messages, model=model, seed_override=seed_override, user_id=user_id
            )
            del messages
            parts.append(part)

        merged = merge_paged_extractions(parts)
        logger.info(
            "Merged paged vision extraction",
            part_count=part_count,
            transactions=len(merged.get("transactions") or []),
            positions=len(merged.get("positions") or []),
        )
        return merged
