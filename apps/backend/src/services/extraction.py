import asyncio
import base64
import hashlib
import ipaddress
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx

from src.config import settings
from src.logger import get_logger
from src.models import DocumentType
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement_enums import BankStatementStatus, Stage1Status
from src.models.statement_summary import StatementSummary
from src.prompts import get_parsing_prompt
from src.services.ai_streaming import (
    AIStreamError,
    accumulate_stream,
    stream_ai_json,
)
from src.services.brokerage_positions import looks_like_brokerage_payload
from src.services.deduplication import DeduplicationService, _decimal_key, dual_write_layer2
from src.services.pii_redaction import detect_pii
from src.services.storage import redact_presigned_url
from src.services.validation import (
    compute_confidence_score,
    normalize_amount_direction,
    route_by_threshold,
    validate_balance_explicit,
)

logger = get_logger(__name__)
CSV_INFERRED_BALANCE_REVIEW_NOTE = (
    "CSV import does not include source statement opening/closing balances; manual review required"
)


class ExtractionError(Exception):
    """Raised when extraction fails."""

    pass


class ExtractionService:
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
        self.deduplication_service = DeduplicationService()

    def _safe_date(self, value: str | None) -> date:
        """Safely parse date from string."""
        if not value:
            logger.error("Date is required but was None or empty", value=value)
            raise ValueError("Date is required")
        try:
            return date.fromisoformat(str(value))
        except (ValueError, TypeError) as exc:
            logger.error(
                "Failed to parse date",
                value=value,
                error_type=type(exc).__name__,
            )
            raise ValueError(f"Invalid date format: {value}") from exc

    def _safe_optional_date(self, value: str | None) -> date | None:
        """Safely parse an optional date from extraction output."""
        if not value:
            return None
        return self._safe_date(value)

    def _safe_decimal(self, value: str | None, default: str | None = None, *, required: bool = False) -> Decimal | None:
        """Safely convert string to Decimal."""
        if value is None:
            if required:
                raise ValueError("Decimal value is required")
            if default is None:
                return None
            value = default
        try:
            return Decimal(str(value))
        except (ValueError, TypeError, InvalidOperation) as exc:
            raise ValueError(f"Invalid decimal value: {value}") from exc

    @staticmethod
    def _sanitize_account_last4(value: str | None) -> str | None:
        """Sanitize account_last4 to up to the last 4 alphanumeric characters.

        Strips all non-alphanumeric characters (hyphens, spaces, etc.)
        and returns only the last 4 characters. Returns None for empty
        or non-alphanumeric input. This prevents
        StringDataRightTruncationError from the VARCHAR(4) DB column.
        """
        if not value:
            return None
        alphanumeric_only = re.sub(r"[^a-zA-Z0-9]", "", value)
        return alphanumeric_only[-4:] if alphanumeric_only else None

    def _is_zai_provider(self) -> bool:
        return settings.ai_provider.lower() in {"zai", "glm"}

    def _build_media_payload(self, file_type: str, mime_type: str, data: str) -> dict[str, Any]:
        """Build OpenAI-compatible media payload based on file type.

        PDFs use provider-supported external URL payloads when available,
        otherwise 'file' type for base64-compatible providers.
        """
        is_base64 = data.startswith("data:")
        is_external_url = data.startswith(("http://", "https://"))
        payload_type = "image_url"
        if file_type == "pdf":
            payload_type = "image_url" if self._is_zai_provider() and is_external_url else "file"
        logger.info(
            "Building media payload",
            file_type=file_type,
            mime_type=mime_type,
            payload_type=payload_type,
            data_source="base64" if is_base64 else "url",
            data_size=len(data) if is_base64 else None,
        )
        if file_type == "pdf" and self._is_zai_provider() and is_external_url:
            return {
                "type": "image_url",
                "image_url": {"url": data},
            }
        if file_type == "pdf":
            return {
                "type": "file",
                "file": {
                    "filename": f"statement.{file_type}",
                    "file_data": data,
                },
            }
        return {
            "type": "image_url",
            "image_url": {"url": data},
        }

    def _render_pdf_pages_as_image_payloads(self, file_content: bytes) -> list[dict[str, Any]]:
        """Render a bounded number of PDF pages to in-memory image_url payloads."""
        try:
            import fitz  # type: ignore[import-untyped]
        except ImportError as e:  # pragma: no cover - dependency is installed in packaged runtime
            raise ExtractionError("PDF vision fallback requires PyMuPDF to render pages") from e

        if not file_content:
            raise ExtractionError("PDF vision fallback requires file content to render pages")

        try:
            document = fitz.open(stream=file_content, filetype="pdf")
        except Exception as e:
            raise ExtractionError("PDF vision fallback could not open PDF content") from e

        try:
            page_count = min(len(document), self.PDF_VISION_MAX_PAGES)
            if page_count <= 0:
                raise ExtractionError("PDF vision fallback could not render an empty PDF")

            matrix = fitz.Matrix(self.PDF_VISION_RENDER_SCALE, self.PDF_VISION_RENDER_SCALE)
            payloads: list[dict[str, Any]] = []
            total_bytes = 0
            for page_index in range(page_count):
                page = document.load_page(page_index)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                buffer = BytesIO(pixmap.tobytes("png"))
                image_bytes = buffer.getvalue()
                total_bytes += len(image_bytes)
                encoded = base64.b64encode(image_bytes).decode("utf-8")
                payloads.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{encoded}"},
                    }
                )

            logger.info(
                "Rendered PDF pages for vision fallback",
                rendered_pages=page_count,
                max_pages=self.PDF_VISION_MAX_PAGES,
                total_image_bytes=total_bytes,
            )
            return payloads
        finally:
            document.close()

    def _build_vision_media_payloads(
        self,
        file_content: bytes | None,
        file_url: str | None,
        file_type: str,
        mime_type: str,
    ) -> list[dict[str, Any]]:
        """Build vision-model media payloads, rendering Z.AI PDFs to images when possible."""
        if file_type == "pdf" and self._is_zai_provider() and file_content:
            try:
                return self._render_pdf_pages_as_image_payloads(file_content)
            except ExtractionError as render_error:
                if file_url and self._validate_external_url(file_url):
                    logger.warning(
                        "PDF page rendering failed, falling back to external PDF URL",
                        error=str(render_error),
                        url=redact_presigned_url(file_url),
                    )
                else:
                    raise

        prefer_url = self._requires_pdf_file_url_for_vision(file_type)
        file_input = self._build_ai_file_input(
            file_content,
            file_url,
            file_type,
            mime_type,
            prefer_url=prefer_url,
        )
        if prefer_url and not file_input.startswith(("http://", "https://")):
            raise ExtractionError("Z.AI PDF vision fallback requires file content or an external PDF URL")
        return [self._build_media_payload(file_type=file_type, mime_type=mime_type, data=file_input)]

    def _validate_external_url(self, url: str) -> bool:
        """Validate if a URL is accessible by external AI services.

        Rejects:
        - Private IP ranges (RFC 1918, RFC 4193, etc.)
        - Localhost names
        - Internal Docker DNS names (e.g., http://minio:9000)

        Returns:
        - True if the URL appears to be a valid, externally routable URL.
        - False if the URL is invalid, uses localhost, resolves to a private/loopback/link-local
          address, or appears to be an internal service name.
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            if not hostname:
                return False

            # Reject localhost by name
            if hostname.lower() == "localhost":
                return False

            # Check if it's an IP address (v4 or v6)
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_link_local:
                    return False
            except ValueError:
                # Not an IP address, proceed to hostname checks
                pass

            # Reject common internal Docker/Kubernetes service names
            # Heuristic: If it has no dots, it's likely an internal service discovery name
            if "." not in hostname:
                return False

            return True
        except Exception as exc:
            url_preview = url[:100] if isinstance(url, str) else repr(url)[:100]
            logger.debug(
                "URL validation failed",
                url=url_preview if url else None,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

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
                extracted = await self.extract_financial_data(
                    file_content=file_content,
                    institution=institution,
                    file_type=file_type,
                    file_url=file_url,
                    force_model=force_model,
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
            statement_currency = extracted.get("currency", "SGD")
            statement = StatementSummary(
                user_id=user_id,
                account_id=account_id,
                file_hash=resolved_file_hash,
                institution=final_institution,
                account_last4=self._sanitize_account_last4(extracted.get("account_last4")),
                currency=statement_currency,
                period_start=(
                    self._safe_optional_date(extracted.get("period_start"))
                    if is_brokerage_payload
                    else self._safe_date(extracted.get("period_start"))
                ),
                period_end=(
                    self._safe_optional_date(extracted.get("period_end"))
                    if is_brokerage_payload
                    else self._safe_date(extracted.get("period_end"))
                ),
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

            transactions: list[AtomicTransaction] = []
            net_transactions = Decimal("0.00")
            # Per-document occurrence ordinal for balance-less rows: lets genuinely
            # repeated identical rows (e.g. two same-day CSV coffees) stay distinct
            # instead of collapsing in the dedup hash. Only used when balance_after is None.
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

                try:
                    parsed_date = date.fromisoformat(txn_date_val)
                except ValueError as exc:
                    if is_brokerage_payload:
                        logger.info(
                            "Skipping brokerage transaction row with non-bank date",
                            filename=original_filename or (file_path.name if file_path else "unknown"),
                        )
                        continue
                    raise ExtractionError(f"Invalid transaction date format: {txn_date_val}") from exc

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

                txn_currency = txn.get("currency") or statement_currency or "SGD"
                txn_balance_after = self._safe_decimal(txn.get("balance_after"))
                txn_direction = TransactionDirection.IN if direction == "IN" else TransactionDirection.OUT
                txn_description = txn.get("description", "Unknown")
                txn_reference = txn.get("reference")

                # Confidence-tiered dedup disambiguator (see calculate_transaction_hash):
                # the running balance when present, else a per-document occurrence ordinal
                # so balance-less repeats stay distinct (recall first). 🚨 The extracted
                # balance_after / occurrence_index are stashed on transient attributes that
                # dual_write_layer2 reuses to keep its upsert hash identical.
                occurrence_index = 0
                if txn_balance_after is None:
                    occ_key = (
                        parsed_date,
                        _decimal_key(amount),
                        txn_direction.value,
                        txn_description.strip().lower(),
                        txn_reference or "",
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
                transactions.append(transaction)

            # Validation
            balance_result = validate_balance_explicit(
                opening=statement.opening_balance or Decimal("0.00"),
                closing=statement.closing_balance or Decimal("0.00"),
                net_transactions=net_transactions,
            )
            is_valid = balance_result["balance_valid"]
            has_inferred_csv_balances = extracted.get("balance_source") == "inferred_from_csv_transactions"

            if has_inferred_csv_balances:
                confidence = compute_confidence_score(
                    extracted,
                    {
                        **balance_result,
                        "balance_valid": False,
                        "balance_proof_available": False,
                        "notes": CSV_INFERRED_BALANCE_REVIEW_NOTE,
                    },
                )
                status = BankStatementStatus.PARSED
                is_valid = False
            else:
                # For confidence score, we use the original extracted dict to maintain logic.
                confidence = compute_confidence_score(extracted, balance_result)
                status = (
                    BankStatementStatus.PARSED if is_brokerage_payload else route_by_threshold(confidence, is_valid)
                )
                if status == BankStatementStatus.APPROVED and account_id is None:
                    status = BankStatementStatus.PARSED

            statement.balance_validated = is_valid
            if has_inferred_csv_balances:
                statement.validation_error = CSV_INFERRED_BALANCE_REVIEW_NOTE
            elif not is_valid:
                statement.validation_error = balance_result["notes"]
            statement.confidence_score = confidence
            statement.status = status
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

            if db:
                await dual_write_layer2(
                    db=db,
                    user_id=user_id,
                    statement=statement,
                    transactions=transactions,
                    file_path=file_path,
                    original_filename=original_filename or (file_path.name if file_path else "unknown"),
                    document_type=(
                        DocumentType.BROKERAGE_STATEMENT if is_brokerage_payload else DocumentType.BANK_STATEMENT
                    ),
                    extraction_metadata={"extraction_payload": extracted} if is_brokerage_payload else None,
                )

            return statement, transactions

        except Exception as e:
            if not isinstance(e, ExtractionError):
                logger.exception("Failed to parse document")
                raise ExtractionError(f"Failed to parse document: {e}") from e
            raise

    def _extract_status_code(self, error_msg: str) -> str | None:
        match = re.search(r"HTTP (\d{3})", error_msg)
        return match.group(1) if match else None

    def _build_ai_file_input(
        self,
        file_content: bytes | None,
        file_url: str | None,
        file_type: str,
        mime_type: str,
        *,
        prefer_url: bool = False,
    ) -> str:
        """Build URL or data URI input for AI provider file APIs."""
        if prefer_url and file_url and self._validate_external_url(file_url):
            return file_url
        if file_content:
            b64_content = base64.b64encode(file_content).decode("utf-8")
            return f"data:{mime_type};base64,{b64_content}"
        if file_url and self._validate_external_url(file_url):
            return file_url
        if file_url:
            logger.warning(
                "Rejected internal/private file URL for AI extraction",
                url=redact_presigned_url(file_url),
            )
        raise ExtractionError(
            f"No valid file content or accessible URL provided for {file_type} extraction. "
            "Ensure file content is uploaded or URL is public."
        )

    def _requires_pdf_file_url_for_vision(self, file_type: str) -> bool:
        return file_type == "pdf" and self._is_zai_provider()

    def _uses_dedicated_layout_ocr(self) -> bool:
        """Use the layout parser only when OCR is configured as a separate model."""
        return bool(self.ocr_model and self.ocr_model != self.vision_model)

    def _vision_extraction_models(self) -> list[str]:
        """Return ordered vision/OCR models without duplicate provider calls."""
        models: list[str] = []
        for model in (self.ocr_model, self.vision_model):
            if model and model not in models:
                models.append(model)
        return models

    async def _extract_ocr_markdown(
        self,
        file_content: bytes | None,
        file_url: str | None,
        file_type: str,
        mime_type: str,
    ) -> str:
        """Run dedicated OCR/layout parsing and return Markdown text."""
        file_input = self._build_ai_file_input(file_content, file_url, file_type, mime_type)
        layout_url = f"{self.base_url.rstrip('/')}/{settings.ai_layout_parsing_path.lstrip('/')}"
        payload = {
            "model": self.ocr_model,
            "file": file_input,
            "return_crop_images": False,
            "need_layout_visualization": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.info(
            "Sending document to OCR layout parser",
            provider=settings.ai_provider,
            model=self.ocr_model,
            file_type=file_type,
            data_source="base64" if file_input.startswith("data:") else "url",
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0, read=180.0)) as client:
            response = await client.post(layout_url, headers=headers, json=payload)

        if response.status_code != 200:
            error_body = response.text[:500]
            logger.error(
                "OCR layout parsing failed",
                provider=settings.ai_provider,
                model=self.ocr_model,
                status_code=response.status_code,
                error_body=error_body,
            )
            raise ExtractionError(f"OCR layout parsing failed: HTTP {response.status_code}: {error_body}")

        result = response.json()
        markdown = result.get("md_results")
        if isinstance(markdown, list):
            markdown = "\n\n".join(str(item) for item in markdown if item)
        if not isinstance(markdown, str) or not markdown.strip():
            raise ExtractionError("OCR layout parsing returned empty Markdown")

        logger.info(
            "OCR layout parsing completed",
            provider=settings.ai_provider,
            model=self.ocr_model,
            markdown_length=len(markdown),
        )
        return markdown

    @staticmethod
    def _repair_json_object(content: str) -> str | None:
        """Best-effort recovery of a JSON object from a malformed model response.

        Models occasionally wrap an otherwise-valid object in a markdown code
        fence or pad it with prose. Rather than rejecting the upload (#982), strip
        any fence and extract the outermost balanced ``{...}`` object — tracking
        string literals so braces inside values do not truncate it. The repair is
        deterministic and does not invent data; it returns ``None`` when no
        object can be recovered, leaving the original failure path intact.
        """
        if not content:
            return None

        text = content.strip()
        if text.startswith("```"):
            # Drop the opening fence line (``` or ```json) and any closing fence.
            text = text.split("\n", 1)[1] if "\n" in text else ""
            if text.rstrip().endswith("```"):
                text = text.rstrip()[: -len("```")]
            text = text.strip()

        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            char = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        return None

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
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=settings.ai_json_timeout_seconds,
                    max_tokens=settings.ai_json_max_tokens,
                    temperature=0.0,
                    do_sample=False,
                    thinking={"type": "disabled"} if settings.ai_json_disable_thinking else None,
                )

                content = await accumulate_stream(stream)

                if not content or not content.strip():
                    from src.constants.error_ids import ErrorIds

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
                    from src.constants.error_ids import ErrorIds

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

            except AIStreamError as e:
                from src.constants.error_ids import ErrorIds

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
                from src.constants.error_ids import ErrorIds

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
                from src.constants.error_ids import ErrorIds

                logger.exception(
                    "Programming error in extraction",
                    error_id=ErrorIds.EXTRACTION_ALL_MODELS_FAILED,
                    model=model,
                    error_type=type(e).__name__,
                )
                raise ExtractionError(f"Internal error: {type(e).__name__}") from e

        from src.constants.error_ids import ErrorIds

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

        prompt = get_parsing_prompt(institution)
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
        )

    async def _parse_csv_content(self, file_content: bytes | str, institution: str) -> dict[str, Any]:
        """Parse CSV content directly from bytes or string.

        Supports multiple bank formats with auto-detection and AI fallback.
        """
        import csv
        import io
        from datetime import datetime

        if isinstance(file_content, bytes):
            text = file_content.decode(encoding="utf-8-sig", errors="ignore")
        else:
            text = file_content.lstrip("\ufeff")

        pii_matches = detect_pii(text)
        if pii_matches:
            logger.warning(
                "PII detected in CSV content",
                pii_count=len(pii_matches),
                pii_types=list({m.pii_type.value for m in pii_matches}),
                institution=institution,
            )

        reader = csv.DictReader(io.StringIO(text))

        rows = list(reader)
        if not rows:
            raise ExtractionError("CSV file is empty or has no data rows")

        headers = list(reader.fieldnames or [])
        headers_lower = [h.lower().strip() for h in headers]
        institution_lower = institution.lower()

        transactions: list[dict[str, Any]] = []
        period_start: date | None = None
        period_end: date | None = None

        def parse_date(value: str) -> date | None:
            """Try multiple date formats."""
            formats = [
                "%d %b %Y",
                "%d/%m/%Y",
                "%Y-%m-%d",
                "%d-%m-%Y",
                "%m/%d/%Y",
                "%Y/%m/%d",
                "%d %B %Y",
            ]
            value = value.strip()
            for fmt in formats:
                try:
                    return datetime.strptime(value, fmt).date()
                except ValueError:
                    continue
            return None

        def parse_amount(value: str) -> Decimal | None:
            """Parse amount string to Decimal."""
            if not value or not value.strip():
                return None
            cleaned = value.strip().replace(",", "").replace("$", "").replace("SGD", "").replace("USD", "").strip()
            if not cleaned or cleaned == "-":
                return None
            try:
                return Decimal(cleaned)
            except (ValueError, InvalidOperation):
                return None

        def find_header(candidates: list[str]) -> str | None:
            for candidate in candidates:
                if candidate.lower() in headers_lower:
                    idx = headers_lower.index(candidate.lower())
                    return headers[idx]
            return None

        if institution_lower in ("dbs", "posb"):
            date_col = find_header(["Transaction Date", "Date", "Value Date"])
            debit_col = find_header(["Debit Amount", "Withdrawal", "Debit"])
            credit_col = find_header(["Credit Amount", "Deposit", "Credit"])
            desc_cols = [
                find_header(["Transaction Ref1", "Reference", "Description"]),
                find_header(["Transaction Ref2", "Details"]),
                find_header(["Transaction Ref3", "Particulars"]),
            ]
            ref_col = find_header(["Reference", "Transaction Reference", "Ref No"])

            for row in rows:
                txn_date = parse_date(row.get(date_col, "")) if date_col else None
                if not txn_date:
                    logger.warning(
                        "CSV transaction skipped - invalid date",
                        institution=institution,
                        date_raw=row.get(date_col, ""),
                        description=row.get(desc_cols[0] if desc_cols else None, ""),
                    )
                    continue

                debit = parse_amount(row.get(debit_col, "")) if debit_col else None
                credit = parse_amount(row.get(credit_col, "")) if credit_col else None

                if debit and debit > 0:
                    amount = debit
                    direction = "OUT"
                elif credit and credit > 0:
                    amount = credit
                    direction = "IN"
                else:
                    logger.warning(
                        "CSV transaction skipped - no valid amount",
                        institution=institution,
                        debit=debit,
                        credit=credit,
                        description=row.get(desc_cols[0] if desc_cols else None, ""),
                    )
                    continue

                desc_parts = [row.get(col, "") for col in desc_cols if col and row.get(col)]
                description = " ".join(desc_parts).strip() or "Transaction"

                transactions.append(
                    {
                        "date": txn_date.isoformat(),
                        "amount": str(amount),
                        "direction": direction,
                        "description": description,
                        "reference": row.get(ref_col, "") if ref_col else None,
                    }
                )

                if period_start is None or txn_date < period_start:
                    period_start = txn_date
                if period_end is None or txn_date > period_end:
                    period_end = txn_date

        elif institution_lower == "wise":
            date_col = find_header(["Created on", "Date", "Finished on"])
            amount_col = find_header(["Source amount (after fees)", "Amount", "Target amount (after fees)"])
            direction_col = find_header(["Direction", "Type"])
            desc_col = find_header(["Reference", "Description", "Target name", "Source name"])
            ref_col = find_header(["ID", "Reference", "TransferWise ID"])

            for row in rows:
                date_str = row.get(date_col, "") if date_col else ""
                if "T" in date_str:
                    date_str = date_str.split("T")[0]
                txn_date = parse_date(date_str)
                if not txn_date:
                    logger.warning(
                        "CSV transaction skipped - invalid date",
                        institution=institution,
                        date_raw=date_str,
                        description=row.get(desc_col, "Wise Transfer"),
                    )
                    continue

                amount = parse_amount(row.get(amount_col, "")) if amount_col else None
                if not amount or amount <= 0:
                    logger.warning(
                        "CSV transaction skipped - no valid amount",
                        institution=institution,
                        amount_raw=row.get(amount_col, ""),
                        description=row.get(desc_col, "Wise Transfer"),
                    )
                    continue

                direction_raw = row.get(direction_col, "").lower() if direction_col else ""
                if "out" in direction_raw or "send" in direction_raw:
                    direction = "OUT"
                else:
                    direction = "IN"

                description = row.get(desc_col, "Wise Transfer") if desc_col else "Wise Transfer"

                transactions.append(
                    {
                        "date": txn_date.isoformat(),
                        "amount": str(amount),
                        "direction": direction,
                        "description": description,
                        "reference": row.get(ref_col, "") if ref_col else None,
                    }
                )

                if period_start is None or txn_date < period_start:
                    period_start = txn_date
                if period_end is None or txn_date > period_end:
                    period_end = txn_date

        elif institution_lower in ("ocbc", "uob", "standard chartered", "citibank"):
            date_col = find_header(["Transaction Date", "Date", "Value Date", "Posting Date"])
            debit_col = find_header(["Debit", "Withdrawal", "Debit Amount", "Withdrawals"])
            credit_col = find_header(["Credit", "Deposit", "Credit Amount", "Deposits"])
            desc_col = find_header(["Description", "Transaction Description", "Particulars", "Details"])
            ref_col = find_header(["Reference", "Reference No", "Cheque No"])

            for row in rows:
                txn_date = parse_date(row.get(date_col, "")) if date_col else None
                if not txn_date:
                    logger.warning(
                        "CSV transaction skipped - invalid date",
                        institution=institution,
                        date_raw=row.get(date_col, ""),
                        description=row.get(desc_col, "Transaction") if desc_col else "Transaction",
                    )
                    continue

                debit = parse_amount(row.get(debit_col, "")) if debit_col else None
                credit = parse_amount(row.get(credit_col, "")) if credit_col else None

                if debit and debit > 0:
                    amount = debit
                    direction = "OUT"
                elif credit and credit > 0:
                    amount = credit
                    direction = "IN"
                else:
                    logger.warning(
                        "CSV transaction skipped - no valid amount",
                        institution=institution,
                        debit=debit,
                        credit=credit,
                        description=row.get(desc_col, "Transaction") if desc_col else "Transaction",
                    )
                    continue

                description = row.get(desc_col, "Transaction") if desc_col else "Transaction"

                transactions.append(
                    {
                        "date": txn_date.isoformat(),
                        "amount": str(amount),
                        "direction": direction,
                        "description": description.strip(),
                        "reference": row.get(ref_col, "") if ref_col else None,
                    }
                )

                if period_start is None or txn_date < period_start:
                    period_start = txn_date
                if period_end is None or txn_date > period_end:
                    period_end = txn_date

        else:
            date_col = find_header(["date", "transaction date", "value date", "posting date", "created on"])
            amount_col = find_header(["amount", "value", "sum"])
            debit_col = find_header(["debit", "withdrawal", "debit amount"])
            credit_col = find_header(["credit", "deposit", "credit amount"])
            desc_col = find_header(["description", "details", "particulars", "reference", "memo"])

            for row in rows:
                txn_date = parse_date(row.get(date_col, "")) if date_col else None
                if not txn_date:
                    logger.warning(
                        "CSV transaction skipped - invalid date",
                        institution=institution,
                        date_raw=row.get(date_col, ""),
                        description=row.get(desc_col, "Transaction") if desc_col else "Transaction",
                    )
                    continue

                if amount_col and row.get(amount_col):
                    amount = parse_amount(row.get(amount_col, ""))
                    if amount is not None:
                        direction = "OUT" if amount < 0 else "IN"
                        amount = abs(amount)
                    else:
                        logger.warning(
                            "CSV transaction skipped - no valid amount",
                            institution=institution,
                            amount_raw=row.get(amount_col, ""),
                            description=row.get(desc_col, "Transaction") if desc_col else "Transaction",
                        )
                        continue
                elif debit_col or credit_col:
                    debit = parse_amount(row.get(debit_col, "")) if debit_col else None
                    credit = parse_amount(row.get(credit_col, "")) if credit_col else None
                    if debit and debit > 0:
                        amount = debit
                        direction = "OUT"
                    elif credit and credit > 0:
                        amount = credit
                        direction = "IN"
                    else:
                        logger.warning(
                            "CSV transaction skipped - no valid amount",
                            institution=institution,
                            debit=debit,
                            credit=credit,
                            description=row.get(desc_col, "Transaction") if desc_col else "Transaction",
                        )
                        continue
                else:
                    logger.warning(
                        "CSV transaction skipped - no amount columns found",
                        institution=institution,
                        description=row.get(desc_col, "Transaction") if desc_col else "Transaction",
                    )
                    continue

                description = row.get(desc_col, "Transaction") if desc_col else "Transaction"

                transactions.append(
                    {
                        "date": txn_date.isoformat(),
                        "amount": str(amount),
                        "direction": direction,
                        "description": description.strip() if description else "Transaction",
                    }
                )

                if period_start is None or txn_date < period_start:
                    period_start = txn_date
                if period_end is None or txn_date > period_end:
                    period_end = txn_date

        if not transactions:
            # EPIC-018 Phase 4: AI CSV parsing fallback for unknown formats
            logger.info(
                "No transactions from heuristic parsing, trying AI CSV mapping",
                institution=institution,
                headers=headers,
            )
            try:
                transactions, period_start, period_end = await self._ai_parse_csv(
                    headers,
                    rows,
                    institution,
                    parse_date,
                    parse_amount,
                )
            except Exception as ai_err:
                logger.warning(
                    "AI CSV parsing fallback failed",
                    error=str(ai_err),
                    error_type=type(ai_err).__name__,
                    institution=institution,
                )

        if not transactions:
            logger.warning(
                "CSV parsing found no valid transactions",
                institution=institution,
                headers=headers,
                row_count=len(rows),
            )
            raise ExtractionError(f"No valid transactions found in CSV for {institution}")

        inferred_closing_balance = sum(
            (
                Decimal(str(txn["amount"])) if txn.get("direction") == "IN" else -Decimal(str(txn["amount"]))
                for txn in transactions
            ),
            Decimal("0.00"),
        )

        logger.info(
            "CSV parsing completed",
            institution=institution,
            transactions_count=len(transactions),
            period_start=period_start.isoformat() if period_start else None,
            period_end=period_end.isoformat() if period_end else None,
        )

        return {
            "currency": "SGD",
            "period_start": period_start.isoformat() if period_start else None,
            "period_end": period_end.isoformat() if period_end else None,
            "opening_balance": "0.00",
            "closing_balance": str(inferred_closing_balance),
            "balance_source": "inferred_from_csv_transactions",
            "transactions": transactions,
        }

    async def _ai_parse_csv(
        self,
        headers: list[str],
        rows: list[dict],
        institution: str,
        parse_date,
        parse_amount,
    ) -> tuple[list[dict], date | None, date | None]:
        """EPIC-018 Phase 4: AI-powered CSV column mapping for unknown institutions.

        Uses AI to identify which columns contain date, description, amount, etc.
        Returns (transactions, period_start, period_end).
        """
        import json

        from src.prompts.csv_mapping import build_csv_mapping_prompt
        from src.services.ai_streaming import (
            accumulate_stream,
            stream_ai_json,
        )

        if not self.api_key:
            raise ExtractionError("AI provider API key required for AI CSV parsing")

        # Build sample rows for the prompt
        sample_rows = []
        for row in rows[:5]:
            sample_rows.append([row.get(h, "") for h in headers])

        prompt = build_csv_mapping_prompt(headers, sample_rows)
        messages = [{"role": "user", "content": prompt}]

        stream = stream_ai_json(
            messages=messages,
            model=self.primary_model,
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=30.0,
        )
        content = await accumulate_stream(stream)

        if not content or not content.strip():
            raise ExtractionError("AI CSV mapping returned empty response")

        mapping = json.loads(content)

        date_col = mapping.get("date")
        desc_col = mapping.get("description")
        amount_col = mapping.get("amount")
        debit_col = mapping.get("debit")
        credit_col = mapping.get("credit")

        logger.info(
            "AI CSV column mapping identified",
            institution=institution,
            mapping=mapping,
        )

        transactions: list[dict] = []
        period_start: date | None = None
        period_end: date | None = None

        for row in rows:
            txn_date = parse_date(row.get(date_col, "")) if date_col else None
            if not txn_date:
                continue

            if amount_col and row.get(amount_col):
                amount = parse_amount(row.get(amount_col, ""))
                if amount is not None:
                    direction = "OUT" if amount < 0 else "IN"
                    amount = abs(amount)
                else:
                    continue
            elif debit_col or credit_col:
                debit = parse_amount(row.get(debit_col, "")) if debit_col else None
                credit = parse_amount(row.get(credit_col, "")) if credit_col else None
                if debit and debit > 0:
                    amount = debit
                    direction = "OUT"
                elif credit and credit > 0:
                    amount = credit
                    direction = "IN"
                else:
                    continue
            else:
                continue

            description = row.get(desc_col, "Transaction") if desc_col else "Transaction"

            transactions.append(
                {
                    "date": txn_date.isoformat(),
                    "amount": str(amount),
                    "direction": direction,
                    "description": description.strip() if description else "Transaction",
                }
            )

            if period_start is None or txn_date < period_start:
                period_start = txn_date
            if period_end is None or txn_date > period_end:
                period_end = txn_date

        logger.info(
            "AI CSV parsing completed",
            institution=institution,
            transactions_count=len(transactions),
        )

        return transactions, period_start, period_end
