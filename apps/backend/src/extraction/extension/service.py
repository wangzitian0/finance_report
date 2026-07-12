"""ExtractionService: core LLM parse path + mixin composition."""

import asyncio
import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select

import src.config
from src.audit.money.currency import normalize_currency_code
from src.extraction.base.validation import (
    bank_currency_balances,
    compute_confidence_score,
    count_within_document_dedup_collapse,
    detect_balance_chain_break,
    normalize_amount_direction,
    route_by_threshold,
    validate_balance,
    validate_balance_explicit,
    validate_balance_per_currency,
)
from src.extraction.extension._base import (
    CSV_INFERRED_BALANCE_REVIEW_NOTE,
    ExtractionError,
    _tolerant_parse_date,
    accumulate_stream,
    logger,
    stream_ai_json,
)
from src.extraction.extension._brokerage import _BrokerageMixin
from src.extraction.extension._coerce import _CoerceMixin
from src.extraction.extension._csv import _CsvMixin
from src.extraction.extension._llm_led_gate import evaluate_llm_led_extraction_gate
from src.extraction.extension._media import _MediaMixin
from src.extraction.extension._ocr import _OcrMixin
from src.extraction.extension.brokerage_positions import (
    brokerage_currency_balances,
    looks_like_brokerage_document,
    looks_like_brokerage_payload,
)
from src.extraction.extension.chain_repair import RegionReExtractor, repair_under_extraction
from src.extraction.extension.currency_resolution import resolve_ingest_currency
from src.extraction.extension.deduplication import DeduplicationService, _decimal_key, dual_write_layer2
from src.extraction.extension.prompts.statement import get_parsing_prompt
from src.extraction.orm.layer1 import DocumentType
from src.ledger import Account, AccountType
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement_enums import BankStatementStatus, Stage1Status
from src.models.statement_summary import StatementSummary
from src.observability import record_financial_invariant_violation

# Bound from the bare published root (config publishes no named symbols).
settings = src.config.settings


def _ai_stream_error() -> type[Exception]:
    # Lazy: see the stream_ai_json proxy note (litellm-free package root).
    from src.llm import AIStreamError

    return AIStreamError


def _institution_class(*, is_brokerage: bool) -> str:
    """Anonymized, low-cardinality institution bucket for invariant metrics.

    Deliberately coarse — ``"brokerage"`` vs ``"bank"`` — so the metric never
    carries a real institution name or any account identifier (PII-free, bounded
    label space).
    """
    return "brokerage" if is_brokerage else "bank"


class ExtractionService(_MediaMixin, _CoerceMixin, _OcrMixin, _BrokerageMixin, _CsvMixin):
    """Service for extracting structured data from financial documents."""

    PDF_VISION_MAX_PAGES = 5
    PDF_VISION_RENDER_SCALE = 1.6

    def __init__(self) -> None:
        self.api_key = settings.ai_api_key
        self.base_url = settings.ai_base_url
        self.primary_model = settings.primary_model
        self.vision_model = settings.vision_model
        self.ocr_model = settings.ocr_model
        self.fallback_models = settings.fallback_models
        self.vision_fallback_models = settings.vision_fallback_models
        self.deduplication_service = DeduplicationService()
        # Injectable region re-extraction backend for the under-extraction repair
        # pass (#1140 / AC13.20). ``None`` => the repair hook is a safe no-op: the
        # deterministic chain-break detector still runs and logs, but no live model
        # is called. A real LLM-backed backend is wired separately.
        self.region_reextractor: RegionReExtractor | None = None

    async def _get_or_create_bank_account(
        self,
        db: Any,
        *,
        user_id: UUID,
        institution: str,
        account_last4: str,
        currency: str,
    ) -> Account:
        """Get-or-create the physical asset account for a bank statement (#1444).

        Keyed on (user_id, institution, account_last4, currency) via a stable
        display name so re-uploaded statements for the same account reuse one
        account. The account is a fact (the money lives here); category
        classification of each transaction is a separate, user-adjustable layer.
        """
        currency = normalize_currency_code(currency) or settings.base_currency
        name = f"{institution} ••{account_last4}"
        existing = (
            await db.execute(
                select(Account)
                .where(Account.user_id == user_id)
                .where(Account.name == name)
                .where(Account.type == AccountType.ASSET)
                .where(Account.currency == currency)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        account = Account(
            user_id=user_id,
            name=name,
            type=AccountType.ASSET,
            currency=currency,
            code="AUTO-BANK",
        )
        db.add(account)
        await db.flush()
        return account

    async def parse_document(
        self,
        file_path: Path,
        institution: str | None,
        user_id: UUID,
        file_type: str = "pdf",
        account_id: UUID | None = None,
        file_content: bytes | None = None,
        file_hash: str | None = None,
        file_url: str | None = None,
        original_filename: str | None = None,
        force_model: str | None = None,
        db: Any | None = None,
    ) -> tuple[StatementSummary, list[AtomicTransaction]]:
        """Parse document using AI vision models or CSV parser.

        Builds a DWD ``StatementSummary`` envelope and a list of Layer-2
        ``AtomicTransaction`` rows. The atomic rows carry a precomputed
        ``dedup_hash`` (with the extracted running ``balance_after`` threaded in so
        otherwise-identical transactions stay distinct) and an empty
        ``source_documents`` placeholder; ``dual_write_layer2`` creates the
        ``UploadedDocument``, fills ``source_documents``/upserts the rows, links the
        summary's ``uploaded_document_id`` and persists the summary.
        """
        model = force_model or self.ocr_model
        logger.info(
            "Parsing document",
            institution=institution or "(auto-detect)",
            file_type=file_type,
            model=model,
            filename=original_filename or (file_path.name if file_path else "unknown"),
        )

        try:
            if file_type == "csv":
                if not file_content:
                    raise ExtractionError("File content is required for CSV parsing")
                if not institution:
                    raise ExtractionError("Institution is required for CSV parsing")
                extracted = await self._parse_csv_content(file_content, institution)
            elif file_type in ("pdf", "png", "jpg", "jpeg"):
                extracted = await self._extract_with_balance_retry(
                    file_content=file_content,
                    institution=institution,
                    file_type=file_type,
                    file_url=file_url,
                    force_model=force_model,
                    filename=original_filename or (file_path.name if file_path else None),
                    user_id=user_id,
                )
                extracted = self._backfill_generated_brokerage_positions(
                    extracted,
                    file_content=file_content,
                    file_type=file_type,
                    filename=original_filename or (file_path.name if file_path else None),
                    institution=institution,
                )
            else:
                raise ExtractionError(f"Unsupported file type: {file_type}")

            detected_institution = extracted.get("institution")
            final_institution = institution or detected_institution or "Unknown"
            is_brokerage_payload = looks_like_brokerage_payload(
                extracted,
                filename=original_filename or (file_path.name if file_path else None),
                institution=final_institution,
            )

            resolved_file_hash = file_hash or hashlib.sha256(file_content or b"").hexdigest()
            # Raw extracted statement currency (no fallback) — feeds the per-transaction
            # ingest-boundary resolution (AC12.40) so a genuinely-missing currency is
            # flagged for review rather than masked by the StatementSummary default.
            raw_statement_currency = extracted.get("currency")
            # Normalize the envelope currency (strip/upper) so the StatementSummary,
            # the auto-created bank account, and the posting-account currency check all
            # agree on a canonical ISO code. A non-normalized extraction ("sgd"/"SGD ")
            # would otherwise mismatch `normalize_currency_code(statement.currency)` in
            # the posting path and silently block auto-post (CR on #1467).
            statement_currency = normalize_currency_code(raw_statement_currency) or settings.base_currency
            # A bank statement requires a period; resolve it tolerantly (a missing
            # bound falls back to the transaction-date range, then the other bound)
            # so a single missing ``period_start`` no longer hard-fails an
            # otherwise-good parse (#1449).
            # Brokerage payloads import via Layer-2 positions and carry no required
            # period, so they keep the optional treatment.
            if is_brokerage_payload:
                resolved_period_start = self._safe_optional_date(extracted.get("period_start"))
                resolved_period_end = self._safe_optional_date(extracted.get("period_end"))
            else:
                resolved_period_start, resolved_period_end = self._resolve_required_period(extracted)

            sanitized_account_last4 = self._sanitize_account_last4(extracted.get("account_last4"))
            # Auto-create and link the physical bank account so a high-confidence,
            # balance-validated statement can reach APPROVED and auto-post without
            # the everyday user having to map an account first (#1444). The account
            # is a *factual* asset account keyed on institution + last4 + currency
            # (mirrors the brokerage auto-account path); category (counter-account)
            # classification stays a separate, user-adjustable layer. Skipped for
            # brokerage payloads (they own a broker account at import) and when no
            # db, real institution, or last4 is available to key a stable account.
            if (
                account_id is None
                and db is not None
                and not is_brokerage_payload
                and final_institution
                and final_institution != "Unknown"
                and sanitized_account_last4
            ):
                bank_account = await self._get_or_create_bank_account(
                    db,
                    user_id=user_id,
                    institution=final_institution,
                    account_last4=sanitized_account_last4,
                    currency=statement_currency,
                )
                account_id = bank_account.id

            statement = StatementSummary(
                user_id=user_id,
                account_id=account_id,
                file_hash=resolved_file_hash,
                institution=final_institution,
                account_last4=sanitized_account_last4,
                currency=statement_currency,
                period_start=resolved_period_start,
                period_end=resolved_period_end,
                opening_balance=self._safe_decimal(
                    extracted.get("opening_balance"),
                    required=not is_brokerage_payload,
                ),
                closing_balance=self._safe_decimal(
                    extracted.get("closing_balance"),
                    required=not is_brokerage_payload,
                ),
                extraction_metadata={"extraction_payload": extracted},
            )
            statement._extracted_payload = extracted

            # Per-currency brokerage NAV (#1139 AC-B3): a multi-currency brokerage
            # statement holds positions in several currencies at once. Persisting
            # only the scalar opening/closing would cross-sum unrelated currencies
            # into a meaningless NAV. Instead derive the per-currency balance array
            # (each currency an independent closed loop) and persist it additively
            # to the scalar columns; reconciliation then runs per currency.
            # When per-currency brokerage reconciliation fails we must not stamp the
            # statement as balance-valid (mirrors the scalar invalid-balance path
            # below). Capture the failure note here so it propagates into
            # ``balance_validated`` / ``validation_error`` after the scalar check.
            per_currency_invalid_note: str | None = None
            if is_brokerage_payload:
                brokerage_balances = brokerage_currency_balances(
                    extracted,
                    filename=original_filename or (file_path.name if file_path else None),
                    institution=final_institution,
                )
                if brokerage_balances:
                    # Reconcile each currency independently (open + ΣIN − ΣOUT ≈
                    # close per currency); never cross-sum. A snapshot has no cash
                    # flow, so each currency is a zero-net closed loop and must
                    # reconcile before we trust it.
                    per_currency_result = validate_balance_per_currency(
                        {"balances": brokerage_balances, "transactions": []}
                    )
                    if not per_currency_result["balance_valid"]:
                        # Respect the self-check result: surface the failing
                        # currencies so the persisted statement carries the invalid
                        # flag rather than silently looking reconciled (#1160 CR1).
                        failed = [
                            f"{r['currency']} (expected {r.get('expected_closing')}, got {r.get('actual_closing')})"
                            for r in per_currency_result.get("per_currency", [])
                            if not r.get("balance_valid")
                        ]
                        per_currency_invalid_note = (
                            "Per-currency NAV self-check failed: " + ", ".join(failed)
                            if failed
                            else "Per-currency NAV self-check failed"
                        )
                        logger.warning(
                            "Per-currency brokerage NAV failed self-check",
                            per_currency=per_currency_result["per_currency"],
                        )
                        # Observability (EPIC-026 AC26.8.1): promote this invariant
                        # violation to a structured, queryable counter. Pure
                        # detection — the per_currency_invalid_note above already
                        # owns the (unchanged) status/balance_validated behavior.
                        record_financial_invariant_violation(
                            kind="per_currency_nav",
                            institution_class=_institution_class(is_brokerage=is_brokerage_payload),
                        )
                    # Serialize Decimal -> str for the JSONB column (no float). The
                    # scalar opening/closing columns stay populated for the
                    # single-currency degenerate case and backward compatibility;
                    # this array is additive and never cross-sums currencies. The
                    # array is still persisted (it is the per-currency evidence), but
                    # the invalid flag above ensures it is not mistaken for valid.
                    statement.currency_balances = [
                        {
                            "currency": bucket["currency"],
                            "opening": str(bucket["opening"]),
                            "closing": str(bucket["closing"]),
                        }
                        for bucket in brokerage_balances
                    ]

            # AC4.13.9 (#1502): bank parity with the brokerage per-currency path.
            # A multi-currency BANK statement (e.g. a DBS consolidated / multi-
            # currency account) holds several currencies at once. Collapsing them
            # into one scalar opening/closing — or worse, cross-summing the per-
            # currency transaction nets — is meaningless. When the bank payload
            # declares per-currency ``balances`` for >1 currency, persist the array
            # and reconcile each currency independently; ``is_valid`` is then
            # governed by that per-currency self-check below. Single-currency bank
            # statements keep ``bank_balances=None`` and the unchanged scalar path.
            bank_balances = None
            if not is_brokerage_payload:
                # A malformed multi-currency payload (duplicate currency, non-numeric
                # amount) must not crash the whole extraction: degrade to a flagged,
                # reviewable statement instead of a 500. The deterministic invalid
                # note routes it through the existing quarantine path.
                try:
                    bank_balances = bank_currency_balances(extracted)
                except (ValueError, InvalidOperation, TypeError) as exc:
                    bank_balances = None
                    per_currency_invalid_note = f"Per-currency balances could not be parsed: {exc}"
                    record_financial_invariant_violation(
                        kind="per_currency_balance",
                        institution_class=_institution_class(is_brokerage=is_brokerage_payload),
                    )
                if bank_balances:
                    bank_per_currency = validate_balance_per_currency(
                        {"balances": bank_balances, "transactions": extracted.get("transactions", [])}
                    )
                    if not bank_per_currency["balance_valid"]:
                        failed = [
                            f"{r['currency']} (expected {r.get('expected_closing')}, got {r.get('actual_closing')})"
                            for r in bank_per_currency.get("per_currency", [])
                            if not r.get("balance_valid")
                        ]
                        per_currency_invalid_note = (
                            "Per-currency balance self-check failed: " + ", ".join(failed)
                            if failed
                            else "Per-currency balance self-check failed"
                        )
                        record_financial_invariant_violation(
                            kind="per_currency_balance",
                            institution_class=_institution_class(is_brokerage=is_brokerage_payload),
                        )
                    statement.currency_balances = bank_balances

            transactions: list[AtomicTransaction] = []
            net_transactions = Decimal("0.00")
            # Per-document occurrence ordinal among rows that would otherwise hash
            # identically (same date/amount/direction/description/reference/balance): lets
            # genuinely repeated rows stay distinct instead of collapsing in the dedup hash —
            # both balance-less repeats (two same-day CSV coffees) and same-balance repeats
            # (#1254: two same-amount deposits printed against one carried-forward /
            # brought-forward running balance across a page boundary).
            occurrence_counts: dict[tuple, int] = {}
            for txn in extracted.get("transactions", []):
                if not txn.get("date") or txn.get("amount") is None:
                    if is_brokerage_payload:
                        logger.info(
                            "Skipping non-bank transaction row in brokerage payload",
                            filename=original_filename or (file_path.name if file_path else "unknown"),
                        )
                        continue
                    raise ExtractionError("Transaction missing required fields: date or amount")

                # Handle case where the model returns date as non-string
                txn_date_val = txn["date"]
                if not isinstance(txn_date_val, str):
                    txn_date_val = str(txn_date_val)

                # Skip if date is still invalid
                if txn_date_val in ("None", "", "null"):
                    logger.warning(
                        "Transaction skipped due to invalid date",
                        raw_date=txn["date"],
                        description=txn.get("description", "N/A"),
                        amount=txn.get("amount"),
                        statement_file=original_filename or "unknown",
                    )
                    continue

                # Primary date normalization is the model's job (see the parsing
                # prompt's ISO rule). `_tolerant_parse_date` is only a defensive net
                # for the few rows the model still emits in a non-ISO/empty form.
                parsed_date = _tolerant_parse_date(txn_date_val)
                if parsed_date is None:
                    # #1086: one unparseable row date is non-fatal — skip and flag the
                    # row instead of rejecting the whole (often multi-month) statement.
                    # Carry description/amount so the skipped row is identifiable from
                    # logs without reproducing locally.
                    logger.warning(
                        "Skipping transaction row with unparseable date",
                        raw_date=txn_date_val,
                        description=txn.get("description", "N/A"),
                        amount=txn.get("amount"),
                        is_brokerage=is_brokerage_payload,
                        statement_file=original_filename or (file_path.name if file_path else "unknown"),
                    )
                    continue

                try:
                    amount = Decimal(str(txn["amount"]))
                except (ValueError, TypeError, InvalidOperation) as exc:
                    if is_brokerage_payload:
                        logger.info(
                            "Skipping brokerage transaction row with non-bank amount",
                            filename=original_filename or (file_path.name if file_path else "unknown"),
                        )
                        continue
                    raise ExtractionError(f"Invalid transaction amount: {txn.get('amount')}") from exc
                amount, direction = normalize_amount_direction(amount, txn.get("direction"))
                if direction == "IN":
                    net_transactions += amount
                else:
                    net_transactions -= amount

                # EPIC-012 AC12.40.1/.2: establish the currency at the ingest boundary from
                # the parsed transaction then the statement's RAW extracted currency. When
                # neither is a valid ISO-4217 code, flag the row ``currency_unresolved`` so it
                # is routed to human review instead of silently defaulting to the base currency.
                resolved_currency = resolve_ingest_currency(txn.get("currency"), raw_statement_currency)
                txn_currency = resolved_currency.code
                txn_balance_after = self._safe_decimal(txn.get("balance_after"))
                txn_direction = TransactionDirection.IN if direction == "IN" else TransactionDirection.OUT
                txn_description = txn.get("description", "Unknown")
                txn_reference = txn.get("reference")

                # Dedup disambiguator (see calculate_transaction_hash): the running balance
                # (when present) paired with a per-document occurrence ordinal among rows that
                # would otherwise hash identically. The ordinal is counted over the FULL hash
                # key — including balance_after — so two genuinely-distinct same-date/same-amount
                # rows that share one running balance (#1254: a deposit before a carried-forward
                # row and an identical deposit after the brought-forward row across a page
                # boundary) stay distinct instead of the second collapsing into the first. Rows
                # with a different running balance get their own independent ordinal-0 counter, so
                # this never merges rows that the balance already separates. 🚨 The extracted
                # balance_after / occurrence_index are stashed on transient attributes that
                # dual_write_layer2 reuses to keep its upsert hash identical.
                occ_key = (
                    parsed_date,
                    _decimal_key(amount),
                    txn_direction.value,
                    txn_description.strip().lower(),
                    txn_reference or "",
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
                )

                transaction = AtomicTransaction(
                    user_id=user_id,
                    txn_date=parsed_date,
                    amount=amount,
                    direction=txn_direction,
                    description=txn_description,
                    reference=txn_reference,
                    currency=txn_currency,
                    dedup_hash=dedup_hash,
                    source_documents=[],
                )
                transaction._extracted_balance_after = txn_balance_after
                transaction._occurrence_index = occurrence_index
                # AC12.40.2: carry the ingest-boundary resolution decision to dual_write_layer2.
                transaction._currency_unresolved = resolved_currency.unresolved
                transactions.append(transaction)

            # Within-document dedup-collapse signal (EPIC-026 AC26.8.1; #1254 class).
            # Compare the rows kept for THIS parse against the distinct dedup hashes
            # they produced. A positive count means two rows in this single document
            # collided on one hash despite the per-document occurrence_index
            # disambiguator — the silent within-parse row loss that #1254 fixed. This
            # is computed only over this parse's freshly-built rows and BEFORE any DB
            # upsert, so legitimate cross-document dedup (a re-uploaded statement
            # collapsing against an already-persisted row) can never trip it. The
            # detection log + metric below are pure observability; the value also
            # feeds the BLOCKING LLM-LED gate (AC20.9.3, #1352) further down, where a
            # positive count quarantines the extraction.
            within_doc_collapse = count_within_document_dedup_collapse([t.dedup_hash for t in transactions])
            if within_doc_collapse > 0:
                logger.warning(
                    "Within-document dedup collapse detected (defense-in-depth, #1254 class)",
                    extracted_rows=len(transactions),
                    distinct_hashes=len(transactions) - within_doc_collapse,
                    collapsed_rows=within_doc_collapse,
                    is_brokerage=is_brokerage_payload,
                    statement_file=original_filename or (file_path.name if file_path else "unknown"),
                )
                record_financial_invariant_violation(
                    kind="dedup_within_doc_collapse",
                    institution_class=_institution_class(is_brokerage=is_brokerage_payload),
                )
                # Audit flag on the envelope's metadata so the collapse is queryable
                # per statement, in addition to the blocking-gate quarantine below.
                metadata = statement.extraction_metadata if isinstance(statement.extraction_metadata, dict) else {}
                metadata = {**metadata, "within_document_dedup_collapse": within_doc_collapse}
                statement.extraction_metadata = metadata

            # Validation
            balance_result = validate_balance_explicit(
                opening=statement.opening_balance or Decimal("0.00"),
                closing=statement.closing_balance or Decimal("0.00"),
                net_transactions=net_transactions,
            )
            is_valid = balance_result["balance_valid"]
            # Per-currency self-check governs for multi-currency statements — applied
            # HERE, before confidence and routing, so both use the authoritative
            # verdict rather than the meaningless cross-summed scalar. A failing
            # per-currency check invalidates even if the scalar passed (#1160); a
            # multi-currency bank that reconciled per currency is valid even though
            # its cross-summed scalar "mismatches" (#1502 AC4.13.9). For the latter,
            # confidence scores against a validated balance_result so it is not
            # penalised for the scalar cross-sum.
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
            has_inferred_csv_balances = extracted.get("balance_source") == "inferred_from_csv_transactions"
            # Fail-closed input for the LLM-LED gate (AC20.9.4): the balance chain is only
            # *evaluable* when the bank statement actually carries both an opening and a
            # closing balance. Without them ``validate_balance_explicit`` silently
            # substitutes ``0.00`` and a zero-chain "passes" — exactly the silent pass
            # the blocking gate must reject. The inferred-CSV path is an explicit,
            # already-flagged review marker (not a silent pass) so it keeps its own
            # routing and is excluded from this evaluability check.
            balance_evaluable = has_inferred_csv_balances or (
                statement.opening_balance is not None and statement.closing_balance is not None
            )

            if has_inferred_csv_balances:
                confidence = compute_confidence_score(
                    extracted,
                    {
                        **balance_result,
                        "balance_valid": False,
                        "balance_proof_available": False,
                        "notes": CSV_INFERRED_BALANCE_REVIEW_NOTE,
                    },
                    is_brokerage=is_brokerage_payload,
                    effective_txn_count=len(transactions),
                )
                status = BankStatementStatus.PARSED
                is_valid = False
            else:
                # For confidence score, we use the original extracted dict to maintain logic.
                # ``effective_balance_result`` carries the per-currency-governed verdict
                # (#1502) so a reconciled multi-currency bank is not scored as a mismatch.
                confidence = compute_confidence_score(
                    extracted,
                    effective_balance_result,
                    is_brokerage=is_brokerage_payload,
                    effective_txn_count=len(transactions),
                )
                # Routing differs by document class on purpose (#981): brokerage payloads
                # reconcile via Layer-2 AtomicPosition snapshots, not a running-balance chain, so
                # `balance_valid` is not their gating signal — they always go to `parsed`/review.
                # Bank statements route by `route_by_threshold`. As of #1141 an invalid balance
                # chain also sends a bank statement to `parsed` (review with a validation_error),
                # not `uploaded`: a parsed-but-unreconciled statement is reviewable, not a manual-
                # entry dead-end. `uploaded` is now reserved for genuinely low-signal valid-balance
                # parses (score < 60). Both classes therefore converge on `parsed`/review for the
                # "balance invalid" outcome.
                status = (
                    BankStatementStatus.PARSED if is_brokerage_payload else route_by_threshold(confidence, is_valid)
                )
                if status == BankStatementStatus.APPROVED and account_id is None:
                    status = BankStatementStatus.PARSED

            # (Per-currency governance of ``is_valid`` is applied above, before
            # confidence/routing, so the verdict here is already authoritative.)
            # Only assert a balance verdict when the chain was actually evaluable.
            # A brokerage/no-balance statement has no opening+closing to check, so
            # `validate_balance_explicit` returns a vacuous `0 == 0` True — report
            # `None` (not-applicable) instead, so the UI never shows a green
            # "validated" badge for something that was never validated (#1443). A
            # real failure signal (per-currency NAV mismatch) still records False.
            if not balance_evaluable and per_currency_invalid_note is None:
                statement.balance_validated = None
            else:
                statement.balance_validated = is_valid
            if has_inferred_csv_balances:
                statement.validation_error = CSV_INFERRED_BALANCE_REVIEW_NOTE
            elif per_currency_invalid_note is not None:
                statement.validation_error = per_currency_invalid_note
            elif not is_valid:
                statement.validation_error = balance_result["notes"]
            statement.confidence_score = confidence
            statement.status = status

            # Promote invariant violations to structured, queryable counters
            # (EPIC-026 AC26.8.1). These mirror the already-computed self-check
            # results; they add observability ONLY and do not change is_valid,
            # status, or the validation_error set above.
            institution_class = _institution_class(is_brokerage=is_brokerage_payload)
            if not is_valid and per_currency_invalid_note is None and not has_inferred_csv_balances:
                # Scalar running-balance reconciliation failed. (The per-currency
                # NAV failure already emits its own counter at detection time, and
                # the inferred-CSV path is a review marker, not a true mismatch.)
                record_financial_invariant_violation(
                    kind="balance_mismatch",
                    institution_class=institution_class,
                )
                # Deterministic chain-break detector: pinpoint a dropped/misparsed
                # row when the mismatch has that shape. Emitted as a distinct,
                # queryable signal; never alters routing.
                chain_break = detect_balance_chain_break(
                    extracted.get("transactions", []) or [],
                    opening_balance=statement.opening_balance,
                )
                if chain_break is not None:
                    logger.warning(
                        "Running-balance chain break detected",
                        break_index=chain_break.index,
                        delta=str(chain_break.delta),
                        statement_file=original_filename or (file_path.name if file_path else "unknown"),
                    )
                    record_financial_invariant_violation(
                        kind="chain_break",
                        institution_class=institution_class,
                    )

            # Blocking LLM-LED tier invariant gate (EPIC-020 AC20.9.1/.2/.3/.4, #1352).
            # The ``event → L2`` layer is LLM-LED: code may reject the LLM's
            # extraction, never author it. Before #1352 a balance-chain failure or a
            # within-document dedup collapse only *flagged* the statement and routed
            # it to PARSED/review (#1141) — an internally-inconsistent extraction
            # could still persist as reviewable financial truth. Now those two
            # deterministic invariants are blocking: a failure quarantines the
            # extraction to the existing ``rejected`` terminal state (already excluded
            # from trusted report input by report_readiness) with a typed reason, and
            # its Layer-2 rows are NOT written. The inferred-CSV review marker keeps
            # its own routing; the balance gate exempts brokerage payloads (#981).
            llm_led_gate = evaluate_llm_led_extraction_gate(
                is_brokerage=is_brokerage_payload,
                balance_evaluable=balance_evaluable,
                balance_valid=is_valid,
                within_doc_collapse=within_doc_collapse,
                balance_gate_exempt=has_inferred_csv_balances,
            )
            if llm_led_gate.quarantined:
                status = BankStatementStatus.REJECTED
                statement.status = status
                statement.balance_validated = False
                statement.stage1_status = Stage1Status.REJECTED
                # The reason CODE is included verbatim so the terminal state is
                # queryable by failure mode; the human message follows it.
                statement.validation_error = f"{llm_led_gate.reason.value}: {llm_led_gate.message}"
                record_financial_invariant_violation(
                    kind=llm_led_gate.metric_kind,
                    institution_class=institution_class,
                )
                logger.warning(
                    "LLM-LED invariant gate quarantined extraction (blocked from trusted truth)",
                    reason=llm_led_gate.reason.value,
                    is_brokerage=is_brokerage_payload,
                    # Log the non-PII content hash, never the real statement filename
                    # or local path (red-lines.md): the hash is enough to correlate
                    # the quarantine with the upload without leaking PII.
                    file_hash=resolved_file_hash,
                )

            # A statement that lands in review must carry an explicit pending_review marker so the
            # queue does not rely on a NULL fallback. The auto-approve path owns the approved/None
            # transitions for APPROVED rows, so only set this for review-bound PARSED statements.
            if status == BankStatementStatus.PARSED:
                statement.stage1_status = Stage1Status.PENDING_REVIEW

            logger.info(
                "Parsing validation completed",
                status=status,
                confidence=confidence,
                is_balanced=is_valid,
                tx_count=len(transactions),
            )

            # A quarantined extraction must never persist its Layer-2 rows: those
            # rows are precisely the untrusted financial truth the gate exists to
            # block. The statement *envelope* must still be persisted, though — its
            # terminal ``rejected`` status and reason are exactly what the user and
            # the review queue need. Skipping the write entirely (the prior
            # behavior) left the row stuck in ``parsing`` forever even though the
            # verdict was computed (#1452): ``dual_write_layer2`` is the only path
            # that updates the API-visible row's status. So always write the
            # envelope when ``db`` is present, but pass no transactions when
            # quarantined so no Layer-2 financial rows are created.
            if db:
                await dual_write_layer2(
                    db=db,
                    user_id=user_id,
                    statement=statement,
                    transactions=[] if llm_led_gate.quarantined else transactions,
                    file_path=file_path,
                    original_filename=original_filename or (file_path.name if file_path else "unknown"),
                    document_type=(
                        DocumentType.BROKERAGE_STATEMENT if is_brokerage_payload else DocumentType.BANK_STATEMENT
                    ),
                    extraction_metadata={"extraction_payload": extracted} if is_brokerage_payload else None,
                    # A quarantined extraction persists only its terminal rejected
                    # envelope: no new Layer-2 rows, and (on re-parse) no detaching
                    # of a prior good parse's existing Layer-2 facts (#1452 CR).
                    envelope_only=llm_led_gate.quarantined,
                )

            return statement, transactions

        except Exception as e:
            if not isinstance(e, ExtractionError):
                logger.exception("Failed to parse document")
                raise ExtractionError(f"Failed to parse document: {e}") from e
            raise

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
        """Re-extract until the running-balance chain reconciles (#989 Step B).

        A non-deterministic model can drop/misread a transaction so the same PDF
        sometimes reconciles and sometimes does not. When a bank statement fails
        balance validation, re-extract up to ``ai_extract_max_attempts`` times,
        each with a *different but reproducible* seed, and keep the first parse
        that reconciles. Brokerage payloads do not reconcile like bank statements
        (they import via Layer-2 positions), so they are never retried. If no
        attempt reconciles, the smallest-difference result is returned so routing
        to ``uploaded`` is unchanged.
        """
        max_attempts = max(1, settings.ai_extract_max_attempts)
        base_seed = settings.ai_json_seed
        best: dict[str, Any] | None = None
        best_diff: Decimal | None = None
        last_parse: dict[str, Any] | None = None
        last_error: ExtractionError | None = None

        for attempt in range(max_attempts):
            # Attempt 0 uses the configured seed; retries vary it so each is a
            # distinct deterministic sample (None base => provider-side variance).
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
                # A transient error on one attempt must not fail an upload that
                # another attempt can satisfy. Skip it and keep trying remaining
                # attempts (a later one may still reconcile); any earlier parse is
                # retained as best/last_parse, and only the all-attempts-failed
                # case re-raises below.
                last_error = exc
                continue
            last_parse = extracted

            if looks_like_brokerage_payload(
                extracted,
                filename=filename,
                institution=institution or extracted.get("institution"),
            ):
                return extracted

            result = validate_balance(extracted)
            if result.get("balance_valid"):
                if attempt > 0:
                    logger.info(
                        "Balance reconciled on re-extract",
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        institution=institution or extracted.get("institution"),
                    )
                return extracted

            # Only parses whose balance was actually computable compete for "best".
            # validate_balance sets balance_computable=False when the payload is
            # structurally broken (missing/non-numeric amount) and its difference
            # defaults to "0"; such a parse must not win over a numerically-close
            # one just because its difference is 0.
            if result.get("balance_computable", True):
                try:
                    diff = Decimal(str(result.get("difference", "0") or "0"))
                except (ValueError, TypeError, InvalidOperation):
                    diff = None
                if diff is not None and (best is None or diff < best_diff):
                    best, best_diff = extracted, diff

        if best is not None:
            if max_attempts > 1:
                logger.info(
                    "Balance did not reconcile after re-extract; keeping best parse",
                    attempts=max_attempts,
                    best_difference=str(best_diff),
                )
            # Under-extraction repair pass (#1140 / AC13.20): whole-document
            # re-extract did not reconcile. Run the deterministic chain-break
            # detector and, when it pinpoints a dropped-row region, attempt a single
            # region-targeted re-extract via the injectable backend. Safe no-op when
            # no backend is wired — recall stays a soft metric, the self-check guard
            # stays hard. A successful repair replaces ``best``; a failed one keeps it.
            repair = repair_under_extraction(best, reextractor=self.region_reextractor)
            return repair.payload
        if last_parse is not None:
            # No balance-computable parse, but at least one attempt produced a
            # (structurally-broken) result; return it so parse_document reports the
            # failure exactly as the single-call path did.
            return last_parse
        # Every attempt raised — propagate so the upload fails as before.
        raise last_error or ExtractionError("Extraction failed after all retries")

    async def _extract_json_with_models(
        self,
        messages: list[dict[str, Any]],
        models: list[str],
        prompt: str,
        institution: str | None,
        file_type: str,
        return_raw: bool,
        has_content: bool,
        has_url: bool,
        seed_override: int | None = None,
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Stream JSON extraction through the configured chat models."""
        last_error: ExtractionError | None = None
        error_summary: dict[str, int] = {}

        for i, model in enumerate(models):
            if not model:
                continue
            try:
                logger.info(
                    "Attempting AI extraction (streaming)",
                    model=model,
                    attempt=i + 1,
                    total=len(models),
                    institution=institution,
                )

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
                    from src.observability import ErrorIds

                    logger.error(
                        "AI returned empty response",
                        error_id=ErrorIds.EXTRACTION_EMPTY_RESPONSE,
                        model=model,
                        institution=institution,
                        file_type=file_type,
                        prompt_length=len(prompt),
                        has_content=has_content,
                        has_url=has_url,
                    )
                    error_summary["empty_response"] = error_summary.get("empty_response", 0) + 1
                    last_error = ExtractionError(
                        f"Model {model} returned empty response. Please retry with a different model."
                    )
                    continue

                if return_raw:
                    logger.info("AI extraction successful (raw)", model=model)
                    return {"choices": [{"message": {"content": content}}]}

                try:
                    parsed = json.loads(content)
                    if not isinstance(parsed, dict):
                        raise ExtractionError("AI response must be a strict JSON object (no arrays).")
                    logger.info("AI extraction successful (streaming)", model=model)
                    return parsed
                except json.JSONDecodeError as e:
                    from src.observability import ErrorIds

                    # A single malformed-but-recoverable response (markdown fence or
                    # prose around a valid object) should not reject the upload (#982).
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
                        raw_preview=content[:500],
                        content_length=len(content),
                        looks_like_html=content.strip().startswith("<"),
                        looks_like_xml=content.strip().startswith("<?xml"),
                    )
                    error_summary["json_parse"] = error_summary.get("json_parse", 0) + 1
                    last_error = ExtractionError(
                        "AI response must be a strict JSON object (no markdown or extra text). "
                        "Please retry with a different model."
                    )
                    continue

            except _ai_stream_error() as e:
                from src.observability import ErrorIds

                error_msg = str(e)
                if "429" in error_msg or "quota" in error_msg.lower():
                    logger.warning(
                        "AI extraction rate limited",
                        error_id=ErrorIds.OPENROUTER_HTTP_ERROR,
                        model=model,
                        attempt=i + 1,
                        retryable=getattr(e, "retryable", False),
                    )
                    error_summary["rate_limit"] = error_summary.get("rate_limit", 0) + 1
                    last_error = ExtractionError(f"Model {model} rate limited: {error_msg}")
                elif "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                    logger.warning(
                        "AI extraction timed out",
                        error_id=ErrorIds.OPENROUTER_TIMEOUT,
                        model=model,
                        attempt=i + 1,
                    )
                    error_summary["timeout"] = error_summary.get("timeout", 0) + 1
                    last_error = ExtractionError(f"Model {model} timed out: {error_msg}")
                else:
                    logger.error(
                        "AI extraction HTTP error",
                        error_id=ErrorIds.OPENROUTER_HTTP_ERROR,
                        model=model,
                        error=error_msg,
                        error_type=type(e).__name__,
                        retryable=getattr(e, "retryable", False),
                        http_status=self._extract_status_code(error_msg),
                        attempt=i + 1,
                    )
                    error_summary["http_error"] = error_summary.get("http_error", 0) + 1
                    last_error = ExtractionError(f"Model {model} failed: {error_msg}")
                continue
            except httpx.TimeoutException:
                from src.observability import ErrorIds

                logger.warning(
                    "AI extraction timed out",
                    error_id=ErrorIds.OPENROUTER_TIMEOUT,
                    model=model,
                    attempt=i + 1,
                    timeout_seconds=settings.ai_json_timeout_seconds,
                )
                error_summary["timeout"] = error_summary.get("timeout", 0) + 1
                last_error = ExtractionError(f"Model {model} timed out after {settings.ai_json_timeout_seconds}s")
                continue
            except ExtractionError:
                raise
            except (ValueError, TypeError, KeyError, AttributeError) as e:
                from src.observability import ErrorIds

                logger.exception(
                    "Programming error in extraction",
                    error_id=ErrorIds.EXTRACTION_ALL_MODELS_FAILED,
                    model=model,
                    error_type=type(e).__name__,
                )
                raise ExtractionError(f"Internal error: {type(e).__name__}") from e

        from src.observability import ErrorIds

        if error_summary:
            breakdown = ", ".join(f"{ct} {et}" for et, ct in error_summary.items())
            logger.error(
                "All extraction models failed",
                error_id=ErrorIds.EXTRACTION_ALL_MODELS_FAILED,
                models_tried=len(models),
                error_breakdown=error_summary,
            )
            raise ExtractionError(f"All {len(models)} models failed. Breakdown: {breakdown}. Last: {last_error}")

        raise last_error or ExtractionError("Extraction failed after all retries")

    async def extract_financial_data(
        self,
        file_content: bytes | None,
        institution: str | None,
        file_type: str,
        return_raw: bool = False,
        file_url: str | None = None,
        force_model: str | None = None,
        seed_override: int | None = None,
        filename: str | None = None,
        user_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Extract structured statement data using OCR + chat models."""
        if file_content is None and not file_url:
            raise ExtractionError("File content is required")

        if not self.api_key:
            raise ExtractionError("AI provider API key not configured")

        mime_types = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "image": "image/png",  # Default for generic "image"
        }
        mime_type = mime_types.get(file_type, "application/pdf")

        logger.info(
            "Sending document to AI for extraction",
            file_type=file_type,
            institution=institution,
            provider=settings.ai_provider,
            primary_model=self.primary_model,
            ocr_model=self.ocr_model,
            vision_model=self.vision_model,
            force_model=force_model,
            pii_warning="PDF/image content may contain PII - prompt instructs AI to ignore it",
        )

        # AC-B1 (#1139): producer routing. Decide the prompt class BEFORE the model
        # call from pre-extraction signals (filename + institution) so brokerage
        # statements get the positions-emitting prompt rather than the bank schema,
        # which has no positions field. Bank documents keep the unchanged bank prompt.
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
        if force_model:
            media_payloads = await asyncio.to_thread(
                self._build_vision_media_payloads,
                file_content,
                file_url,
                file_type,
                mime_type,
            )
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        *media_payloads,
                    ],
                }
            ]
            return await self._extract_json_with_models(
                messages=messages,
                models=[force_model],
                prompt=prompt,
                institution=institution,
                file_type=file_type,
                return_raw=return_raw,
                has_content=bool(file_content),
                has_url=bool(file_url),
                seed_override=seed_override,
                user_id=user_id,
            )

        if self._uses_dedicated_layout_ocr():
            try:
                ocr_markdown = await self._extract_ocr_markdown(file_content, file_url, file_type, mime_type)
                text_prompt = (
                    f"{prompt}\n\n"
                    "The statement has already been converted to OCR Markdown by the dedicated OCR model. "
                    "Extract the structured financial data from this OCR text only.\n\n"
                    f"```markdown\n{ocr_markdown}\n```"
                )
                return await self._extract_json_with_models(
                    messages=[{"role": "user", "content": text_prompt}],
                    models=[self.primary_model, *self.fallback_models],
                    prompt=text_prompt,
                    institution=institution,
                    file_type=file_type,
                    return_raw=return_raw,
                    has_content=bool(file_content),
                    has_url=bool(file_url),
                    seed_override=seed_override,
                    user_id=user_id,
                )
            except ExtractionError as ocr_error:
                logger.warning(
                    "OCR-first extraction failed, falling back to vision model",
                    ocr_model=self.ocr_model,
                    vision_model=self.vision_model,
                    error=str(ocr_error),
                )
        elif self.ocr_model:
            logger.info(
                "OCR model shares the vision path; skipping dedicated layout parser",
                ocr_model=self.ocr_model,
                vision_model=self.vision_model,
            )

        vision_models = self._vision_extraction_models()
        if not vision_models:
            raise ExtractionError("Extraction failed after all retries")

        media_payloads = await asyncio.to_thread(
            self._build_vision_media_payloads,
            file_content,
            file_url,
            file_type,
            mime_type,
        )
        vision_messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    *media_payloads,
                ],
            }
        ]
        return await self._extract_json_with_models(
            messages=vision_messages,
            models=vision_models,
            prompt=prompt,
            institution=institution,
            file_type=file_type,
            return_raw=return_raw,
            has_content=bool(file_content),
            has_url=bool(file_url),
            seed_override=seed_override,
            user_id=user_id,
        )
