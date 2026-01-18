"""Document extraction service using OpenRouter vision models."""

import base64
import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx

from src.config import settings
from src.logger import get_logger
from src.models import BankStatement, BankStatementTransaction, ConfidenceLevel
from src.prompts import get_parsing_prompt
from src.services.validation import (
    compute_confidence_score,
    route_by_threshold,
    validate_balance,
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

    def _safe_date(self, value: str | None) -> date:
        """Safely parse date from string."""
        if not value:
            raise ValueError("Date is required")
        try:
            return date.fromisoformat(value)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid date format: {value}")

    def _safe_decimal(self, value: str | None, default: str = "0.00") -> Decimal:
        """Safely convert string to Decimal."""
        try:
            return Decimal(str(value or default))
        except (ValueError, TypeError, InvalidOperation):
            return Decimal(default)

    def _compute_event_confidence(self, txn: dict[str, Any]) -> ConfidenceLevel:
        """Heuristic confidence for a single transaction."""
        required = ["date", "description", "amount", "direction"]
        missing = [f for f in required if not txn.get(f)]
        if missing:
            return ConfidenceLevel.LOW
        return ConfidenceLevel.HIGH

    async def parse_document(
        self,
        *,
        file_path: Path,
        institution: str,
        user_id: UUID,
        file_type: str = "pdf",
        account_id: UUID | None = None,
        file_content: bytes | None = None,
        file_hash: str | None = None,
        file_url: str | None = None,
        original_filename: str | None = None,
        force_model: str | None = None,
    ) -> tuple[BankStatement, list[BankStatementTransaction]]:
        """Parse document using AI vision models."""
        model = force_model or self.primary_model
        logger.info(
            "Parsing document",
            institution=institution,
            file_type=file_type,
            model=model,
            filename=original_filename or file_path.name,
        )

        try:
            extracted = await self.extract_financial_data(
                file_content=file_content,
                institution=institution,
                file_type=file_type,
                file_url=file_url,
                force_model=force_model,
            )

            # Build models
            statement = BankStatement(
                user_id=user_id,
                account_id=account_id,
                file_path=str(file_path),
                file_hash=file_hash or hashlib.sha256(file_content or b"").hexdigest(),
                original_filename=original_filename or file_path.name,
                institution=institution,
                account_last4=extracted.get("account_last4"),
                currency=extracted.get("currency", "SGD"),
                period_start=self._safe_date(extracted.get("period_start")),
                period_end=self._safe_date(extracted.get("period_end")),
                opening_balance=self._safe_decimal(extracted.get("opening_balance")),
                closing_balance=self._safe_decimal(extracted.get("closing_balance")),
            )

            transactions = []
            for txn in extracted.get("transactions", []):
                # Skip transactions with missing required fields
                if not txn.get("date") or txn.get("amount") is None:
                    continue

                # Handle case where the model returns date as non-string
                txn_date_val = txn["date"]
                if not isinstance(txn_date_val, str):
                    txn_date_val = str(txn_date_val)

                # Skip if date is still invalid
                if txn_date_val in ("None", "", "null"):
                    continue

                try:
                    parsed_date = date.fromisoformat(txn_date_val)
                except ValueError:
                    continue  # Skip invalid date formats

                event_confidence = self._compute_event_confidence(txn)
                transaction = BankStatementTransaction(
                    txn_date=parsed_date,
                    description=txn.get("description", "Unknown"),
                    amount=Decimal(str(txn["amount"])),
                    direction=txn.get("direction", "IN"),
                    reference=txn.get("reference"),
                    confidence=event_confidence,
                    confidence_reason=txn.get("confidence_reason"),
                    raw_text=txn.get("raw_text"),
                    statement=statement,
                )
                transactions.append(transaction)

            # Validation
            is_valid = validate_balance(
                opening=statement.opening_balance,
                closing=statement.closing_balance,
                transactions=transactions,
            )
            confidence = compute_confidence_score(
                is_valid=is_valid,
                transactions=transactions,
                institution=institution,
            )
            status = route_by_threshold(confidence)

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

            return statement, transactions

        except Exception as e:
            if not isinstance(e, ExtractionError):
                logger.exception("Failed to parse document")
                raise ExtractionError(f"Failed to parse document: {e}") from e
            raise

    async def extract_financial_data(
        self,
        file_content: bytes | None,
        institution: str,
        file_type: str,
        return_raw: bool = False,
        file_url: str | None = None,
        force_model: str | None = None,
    ) -> dict[str, Any]:
        """Call OpenRouter vision API."""
        if not self.api_key:
            raise ExtractionError("OpenRouter API key not configured")

        if file_content is None and not file_url:
            raise ExtractionError("File content or URL required for extraction")

        # Determine MIME type
        mime_types = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "image": "image/png",  # Default for generic "image"
        }
        mime_type = mime_types.get(file_type, "application/pdf")

        if file_url:
            media_payload = {
                "type": "image_url",
                "image_url": {"url": file_url},
            }
        elif file_content:
            b64_content = base64.b64encode(file_content).decode("utf-8")
            media_payload = {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{b64_content}",
                },
            }
        else:
            raise ExtractionError("Either file_url or file_content is required")

        # Build request
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

        models = (
            [force_model]
            if force_model
            else [self.primary_model] + list(self.fallback_models or [])
        )
        last_error: ExtractionError | None = None

        async with httpx.AsyncClient(timeout=120.0) as client:
            for model in models:
                if not model:
                    continue
                try:
                    logger.info("Attempting AI extraction", model=model, institution=institution)
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://finance-report.local",
                            "X-Title": "Finance Report Backend",
                        },
                        json={
                            "model": model,
                            "messages": messages,
                            "response_format": {"type": "json_object"},
                        },
                    )

                    if response.status_code != 200:
                        error_msg = f"API error {response.status_code}: {response.text}"
                        logger.error("AI extraction failed", model=model, error=error_msg)
                        error = ExtractionError(error_msg)
                        if response.status_code == 429:
                            raise error
                        last_error = error
                        continue

                    data = response.json()
                    if return_raw:
                        logger.info("AI extraction successful (raw)", model=model)
                        return data

                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")

                    # Parse JSON from response
                    try:
                        parsed = json.loads(content)
                        logger.info("AI extraction successful", model=model)
                        return parsed
                    except json.JSONDecodeError as e:
                        # Try to extract JSON from markdown code blocks
                        json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
                        if json_match:
                            parsed = json.loads(json_match.group(1))
                            logger.info("AI extraction successful (markdown fallback)", model=model)
                            return parsed
                        logger.error("Failed to parse AI JSON response", model=model, error=str(e))
                        last_error = ExtractionError(f"Failed to parse JSON response: {e}")
                        continue

                except Exception as e:
                    if isinstance(e, ExtractionError):
                        raise
                    logger.exception("AI extraction unexpected error", model=model)
                    last_error = ExtractionError(str(e))
                    continue

        raise last_error or ExtractionError("Extraction failed after all retries")

    async def _parse_csv_content(self, file_content: bytes, institution: str) -> dict[str, Any]:
        """Parse CSV content directly from bytes."""
        # This is a placeholder for actual CSV parsing logic
        return {}