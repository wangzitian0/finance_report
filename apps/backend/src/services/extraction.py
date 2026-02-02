import base64
import hashlib
import ipaddress
import json
import re  # noqa: F401 (used in regex patterns)
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from src.config import settings
from src.logger import get_logger
from src.models import BankStatement, BankStatementTransaction, ConfidenceLevel
from src.models.layer1 import DocumentType
from src.models.layer2 import TransactionDirection
from src.prompts import get_parsing_prompt
from src.services.deduplication import DeduplicationService
from src.services.openrouter_streaming import (
    OpenRouterStreamError,
    accumulate_stream,
    stream_openrouter_json,
)
from src.services.pii_redaction import detect_pii
from src.services.validation import (
    compute_confidence_score,
    route_by_threshold,
    validate_balance,
    validate_balance_explicit,
)

logger = get_logger(__name__)


class ExtractionError(Exception):
    """Raised when extraction fails."""

    pass


class ExtractionService:
    """Service for extracting structured data from financial documents."""

    def __init__(self) -> None:
        self.api_key = settings.openrouter_api_key
        self.base_url = settings.openrouter_base_url
        self.primary_model = settings.primary_model
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

    def _safe_decimal(self, value: str | None, default: str | None = None) -> Decimal:
        """Safely convert string to Decimal."""
        if value is None:
            if default is None:
                raise ValueError("Decimal value is required")
            value = default
        try:
            return Decimal(str(value))
        except (ValueError, TypeError, InvalidOperation) as exc:
            raise ValueError(f"Invalid decimal value: {value}") from exc

    def _compute_event_confidence(self, txn: dict[str, Any]) -> ConfidenceLevel:
        """Heuristic confidence for a single transaction."""
        required = ["date", "description", "amount", "direction"]
        missing = [f for f in required if not txn.get(f)]
        if missing:
            return ConfidenceLevel.LOW

        # Validate date format
        try:
            date.fromisoformat(str(txn["date"]))
        except (ValueError, TypeError):
            return ConfidenceLevel.LOW

        return ConfidenceLevel.HIGH

    def _validate_balance(self, extracted: dict[str, Any]) -> dict[str, Any]:
        """Wrapper for test compatibility."""
        return validate_balance(extracted)

    def _compute_confidence(self, extracted: dict[str, Any], balance_result: dict[str, Any]) -> int:
        """Wrapper for test compatibility."""
        return compute_confidence_score(extracted, balance_result)

    def _build_media_payload(self, file_type: str, mime_type: str, data: str) -> dict[str, Any]:
        """Build OpenRouter-compatible media payload based on file type.

        PDFs use 'file' type (Universal PDF Support), images use 'image_url'.
        """
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

    def _validate_external_url(self, url: str) -> bool:
        """Validate if a URL is accessible by external services (OpenRouter).

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
            logger.debug(
                "URL validation failed",
                url=url[:100] if url else None,
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
    ) -> tuple[BankStatement, list[BankStatementTransaction]]:
        """Parse document using AI vision models or CSV parser."""
        model = force_model or self.primary_model
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

            statement = BankStatement(
                user_id=user_id,
                account_id=account_id,
                file_path=str(file_path) if file_path else None,
                file_hash=file_hash or hashlib.sha256(file_content or b"").hexdigest(),
                original_filename=original_filename or (file_path.name if file_path else "unknown"),
                institution=final_institution,
                account_last4=extracted.get("account_last4"),
                currency=extracted.get("currency", "SGD"),
                period_start=self._safe_date(extracted.get("period_start")),
                period_end=self._safe_date(extracted.get("period_end")),
                opening_balance=self._safe_decimal(extracted.get("opening_balance")),
                closing_balance=self._safe_decimal(extracted.get("closing_balance")),
            )

            transactions = []
            net_transactions = Decimal("0.00")
            for txn in extracted.get("transactions", []):
                if not txn.get("date") or txn.get("amount") is None:
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
                    raise ExtractionError(f"Invalid transaction date format: {txn_date_val}") from exc

                try:
                    amount = Decimal(str(txn["amount"]))
                except (ValueError, TypeError, InvalidOperation) as exc:
                    raise ExtractionError(f"Invalid transaction amount: {txn.get('amount')}") from exc
                direction = txn.get("direction", "IN")
                if direction == "IN":
                    net_transactions += amount
                else:
                    net_transactions -= amount

                event_confidence = self._compute_event_confidence(txn)
                transaction = BankStatementTransaction(
                    txn_date=parsed_date,
                    description=txn.get("description", "Unknown"),
                    amount=amount,
                    direction=direction,
                    reference=txn.get("reference"),
                    confidence=event_confidence,
                    confidence_reason=txn.get("confidence_reason"),
                    raw_text=txn.get("raw_text"),
                    statement=statement,
                )
                transactions.append(transaction)

            # Validation
            balance_result = validate_balance_explicit(
                opening=statement.opening_balance or Decimal("0.00"),
                closing=statement.closing_balance or Decimal("0.00"),
                net_transactions=net_transactions,
            )
            is_valid = balance_result["balance_valid"]

            # For confidence score, we use the original extracted dict to maintain logic
            confidence = compute_confidence_score(extracted, balance_result)
            status = route_by_threshold(confidence, is_valid)

            statement.balance_validated = is_valid
            statement.confidence_score = confidence
            statement.status = status

            logger.info(
                "Parsing validation completed",
                status=status,
                confidence=confidence,
                is_balanced=is_valid,
                tx_count=len(transactions),
            )

            if settings.enable_4_layer_write and db:
                await self._dual_write_layer2(
                    db=db,
                    user_id=user_id,
                    file_path=file_path,
                    file_hash=file_hash or hashlib.sha256(file_content or b"").hexdigest(),
                    original_filename=original_filename or (file_path.name if file_path else "unknown"),
                    institution=final_institution,
                    transactions=transactions,
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

    async def extract_financial_data(
        self,
        file_content: bytes | None,
        institution: str | None,
        file_type: str,
        return_raw: bool = False,
        file_url: str | None = None,
        force_model: str | None = None,
    ) -> dict[str, Any]:
        """Call OpenRouter vision API."""
        if file_content is None and not file_url:
            raise ExtractionError("File content is required")

        if not self.api_key:
            raise ExtractionError("OpenRouter API key not configured")

        # Determine MIME type
        mime_types = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "image": "image/png",  # Default for generic "image"
        }
        mime_type = mime_types.get(file_type, "application/pdf")

        media_payload = None

        if file_type == "pdf":
            if file_url:
                if self._validate_external_url(file_url):
                    media_payload = self._build_media_payload(
                        file_type=file_type,
                        mime_type=mime_type,
                        data=file_url,
                    )
                else:
                    logger.warning("Rejected internal/private file URL for PDF extraction", url=file_url)

            if not media_payload:
                raise ExtractionError(
                    "PDF extraction requires a public URL. Ensure the uploaded file is accessible externally."
                )
        else:
            if file_content:
                b64_content = base64.b64encode(file_content).decode("utf-8")
                media_payload = self._build_media_payload(
                    file_type=file_type,
                    mime_type=mime_type,
                    data=f"data:{mime_type};base64,{b64_content}",
                )
            elif file_url:
                if self._validate_external_url(file_url):
                    media_payload = self._build_media_payload(
                        file_type=file_type,
                        mime_type=mime_type,
                        data=file_url,
                    )
                else:
                    logger.warning("Rejected internal/private file URL for AI extraction", url=file_url)

            if not media_payload:
                raise ExtractionError(
                    "No valid file content or accessible URL provided for AI extraction. "
                    "Ensure file content is uploaded or URL is public."
                )

        logger.info(
            "Sending document to AI for extraction",
            file_type=file_type,
            institution=institution,
            pii_warning="PDF/image content may contain PII - prompt instructs AI to ignore it",
        )

        prompt = get_parsing_prompt(institution)
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    media_payload,
                ],
            }
        ]

        if force_model:
            models = [force_model]
        else:
            models = [self.primary_model]

        logger.info(
            "Model selection for extraction",
            force_model=force_model,
            primary_model=self.primary_model,
            fallback_models=self.fallback_models,
            will_use=models[0] if models else None,
            has_fallback=bool(self.fallback_models),
        )

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

                stream = stream_openrouter_json(
                    messages=messages,
                    model=model,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=180.0,
                )

                content = await accumulate_stream(stream)

                if not content or not content.strip():
                    from src.constants.error_ids import ErrorIds

                    logger.error(
                        "AI returned empty response",
                        error_id=ErrorIds.EXTRACTION_EMPTY_RESPONSE,
                        model=model,
                        institution=institution,
                        file_type="pdf" if file_content else "url",
                        prompt_length=len(prompt),
                        has_content=bool(file_content),
                        has_url=bool(file_url),
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

            except OpenRouterStreamError as e:
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
            logger.warning(
                "CSV parsing found no valid transactions",
                institution=institution,
                headers=headers,
                row_count=len(rows),
            )
            raise ExtractionError(f"No valid transactions found in CSV for {institution}")

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
            "transactions": transactions,
        }

    async def _dual_write_layer2(
        self,
        db: Any,
        user_id: UUID,
        file_path: Path | None,
        file_hash: str,
        original_filename: str,
        institution: str,
        transactions: list[BankStatementTransaction],
    ) -> None:
        """Write parsed data to Layer 1/2 tables (Phase 2 dual write)."""
        dedup_service = DeduplicationService()

        doc_type_map = {
            "dbs": DocumentType.BANK_STATEMENT,
            "ocbc": DocumentType.BANK_STATEMENT,
            "standard chartered": DocumentType.BANK_STATEMENT,
            "citibank": DocumentType.BANK_STATEMENT,
            "uob": DocumentType.BANK_STATEMENT,
            "posb": DocumentType.BANK_STATEMENT,
        }
        doc_type = doc_type_map.get(institution.lower(), DocumentType.BANK_STATEMENT)

        try:
            uploaded_doc = await dedup_service.create_uploaded_document(
                db=db,
                user_id=user_id,
                file_path=str(file_path) if file_path else file_hash,
                file_hash=file_hash,
                original_filename=original_filename,
                document_type=doc_type,
            )

            layer2_count = 0
            for txn in transactions:
                direction_map = {"IN": TransactionDirection.IN, "OUT": TransactionDirection.OUT}
                l2_direction = direction_map.get(txn.direction, TransactionDirection.IN)

                await dedup_service.upsert_atomic_transaction(
                    db=db,
                    user_id=user_id,
                    txn_date=txn.txn_date,
                    amount=txn.amount,
                    direction=l2_direction,
                    description=txn.description,
                    currency=txn.statement.currency or "SGD",
                    source_doc_id=uploaded_doc.id,
                    source_doc_type=doc_type,
                    reference=txn.reference,
                )
                layer2_count += 1

            logger.info(
                "Dual write to Layer 2 completed",
                uploaded_doc_id=str(uploaded_doc.id),
                layer2_transactions=layer2_count,
                layer0_transactions=len(transactions),
            )

        except IntegrityError:
            # Duplicate upload - acceptable silent failure
            logger.warning(
                "Dual write skipped - document already exists",
                file_hash=file_hash,
                user_id=str(user_id),
            )
        except Exception as e:
            # All other errors are CRITICAL - must be visible to user
            logger.error(
                "Dual write to Layer 2 FAILED - data integrity compromised",
                error=str(e),
                error_type=type(e).__name__,
                user_id=str(user_id),
                file_hash=file_hash,
                layer0_transactions=len(transactions),
            )
            # Re-raise to ensure caller knows dual-write failed
            raise RuntimeError(f"Failed to write to Layer 2: {e}") from e
