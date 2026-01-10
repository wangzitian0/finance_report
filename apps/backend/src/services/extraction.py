"""Document extraction service using OpenRouter + Gemini 3 Flash Vision."""

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
from src.models import BankStatement, BankStatementTransaction, ConfidenceLevel
from src.prompts import get_parsing_prompt
from src.services.validation import (
    compute_confidence_score,
    route_by_threshold,
    validate_balance,
    validate_completeness,
)


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

    async def parse_document(
        self,
        file_path: Path,
        institution: str,
        user_id: UUID,
        file_type: str = "pdf",
        account_id: UUID | None = None,
        file_content: bytes | None = None,
        file_hash: str | None = None,
    ) -> tuple[BankStatement, list[BankStatementTransaction]]:
        """
        Parse a financial statement document.

        Args:
            file_path: Path to the document file
            institution: Bank/broker name for institution-specific prompts
            file_type: Type of file (pdf, csv, image)

        Returns:
            Tuple of (BankStatement, list of BankStatementTransactions)
        """
        # Read file content
        if file_content is None:
            file_content = file_path.read_bytes()
        if file_hash is None:
            file_hash = hashlib.sha256(file_content).hexdigest()

        # Call Gemini for extraction
        if file_type in ("pdf", "image", "png", "jpg", "jpeg"):
            extracted = await self.extract_financial_data(file_content, institution, file_type)
        elif file_type == "csv":
            extracted = await self._parse_csv(file_path, institution)
        else:
            raise ExtractionError(f"Unsupported file type: {file_type}")

        # Validate extracted data
        validation = self._validate_balance(extracted)
        missing_fields = validate_completeness(extracted)

        # Compute confidence score
        confidence_score = compute_confidence_score(extracted, validation, missing_fields)
        if not validation["balance_valid"]:
            confidence_score = min(confidence_score, 59)

        # Determine status based on confidence and validation
        status = route_by_threshold(confidence_score, validation["balance_valid"])

        validation_notes = []
        if not validation["balance_valid"] and validation.get("notes"):
            validation_notes.append(validation["notes"])
        if missing_fields:
            validation_notes.append(f"Missing fields: {', '.join(missing_fields)}")
        validation_error = "; ".join(validation_notes) if validation_notes else None

        # Create BankStatement object
        statement = BankStatement(
            file_path=str(file_path),
            file_hash=file_hash,
            original_filename=file_path.name,
            institution=institution,
            user_id=user_id,
            account_id=account_id,
            account_last4=extracted.get("account_last4"),
            currency=extracted.get("currency", "SGD"),
            period_start=self._safe_date(extracted.get("period_start")),
            period_end=self._safe_date(extracted.get("period_end")),
            opening_balance=self._safe_decimal(extracted.get("opening_balance")),
            closing_balance=self._safe_decimal(extracted.get("closing_balance")),
            status=status,
            confidence_score=confidence_score,
            balance_validated=validation["balance_valid"],
            validation_error=validation_error,
        )

        # Create BankStatementTransaction objects
        transactions: list[BankStatementTransaction] = []
        for txn in extracted.get("transactions", []):
            # Skip transactions with missing required fields
            if not txn.get("date") or txn.get("amount") is None:
                continue

            # Handle case where Gemini returns date as non-string
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

        return statement, transactions

    async def extract_financial_data(
        self,
        file_content: bytes,
        institution: str,
        file_type: str,
        return_raw: bool = False,
    ) -> dict[str, Any]:
        """Call Gemini Vision API via OpenRouter."""
        if not self.api_key:
            raise ExtractionError("OpenRouter API key not configured")

        # Encode file as base64
        b64_content = base64.b64encode(file_content).decode("utf-8")

        # Determine MIME type
        mime_types = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "image": "image/png",  # Default for generic "image"
        }
        mime_type = mime_types.get(file_type, "application/pdf")

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
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{b64_content}",
                        },
                    },
                ],
            }
        ]

        models = [self.primary_model] + list(self.fallback_models or [])
        last_error: ExtractionError | None = None

        async with httpx.AsyncClient(timeout=120.0) as client:
            for model in models:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://finance-report.local",
                        "X-Title": "Finance Report",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                    },
                )

                if response.status_code != 200:
                    error = ExtractionError(
                        f"OpenRouter API error: {response.status_code} - {response.text}"
                    )
                    if response.status_code == 429:
                        raise error
                    last_error = error
                    continue

                result = response.json()
                if return_raw:
                    return result

                content = result["choices"][0]["message"]["content"]

                # Parse JSON from response
                try:
                    return json.loads(content)
                except json.JSONDecodeError as e:
                    # Try to extract JSON from markdown code blocks
                    json_match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group(1))
                    last_error = ExtractionError(f"Failed to parse JSON response: {e}")
                    continue

        if last_error:
            raise last_error
        raise ExtractionError("OpenRouter API error: no models available")

    async def _parse_csv(self, file_path: Path, institution: str) -> dict[str, Any]:
        """Parse CSV files directly (for structured data like Moomoo exports)."""
        import csv
        from datetime import datetime as dt

        with open(file_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            raise ExtractionError("Empty CSV file")

        # Extract transactions
        transactions = []
        for row in rows:
            # Try common column names
            date_str = row.get("Date") or row.get("date") or row.get("Transaction Date")
            amount_str = row.get("Amount") or row.get("amount") or row.get("Net Amount")
            desc = row.get("Description") or row.get("description") or row.get("Type")

            if not date_str or not amount_str:
                continue

            # Parse date (try multiple formats)
            txn_date = None
            for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y%m%d"]:
                try:
                    txn_date = dt.strptime(date_str.split()[0], fmt).date()
                    break
                except ValueError:
                    continue

            if not txn_date:
                continue

            # Parse amount
            amount = Decimal(amount_str.replace(",", "").replace("$", ""))
            direction = "IN" if amount >= 0 else "OUT"

            transactions.append(
                {
                    "date": txn_date.isoformat(),
                    "description": desc or "Unknown",
                    "amount": str(abs(amount)),
                    "direction": direction,
                    "reference": row.get("Reference") or row.get("reference"),
                    "raw_text": str(row),
                }
            )

        # Calculate totals
        if not transactions:
            raise ExtractionError("No valid transactions found in CSV")

        # Sort by date
        transactions.sort(key=lambda x: x["date"])

        return {
            "institution": institution,
            "account_last4": None,
            "currency": "SGD",  # Default, could be detected from data
            "period_start": transactions[0]["date"],
            "period_end": transactions[-1]["date"],
            "opening_balance": "0.00",  # CSV typically doesn't have this
            "closing_balance": "0.00",  # Will fail balance validation intentionally
            "transactions": transactions,
        }

    def _validate_balance(self, extracted: dict[str, Any]) -> dict[str, Any]:
        """Validate that opening + transactions ≈ closing."""
        return validate_balance(extracted)

    def _compute_confidence(self, extracted: dict[str, Any], validation: dict[str, Any]) -> int:
        """
        Compute overall confidence score (0-100).

        Factors:
        - Balance validation: 40%
        - Field completeness: 30%
        - Format consistency: 20%
        - Transaction count reasonableness: 10%
        """
        missing_fields = validate_completeness(extracted)
        return compute_confidence_score(extracted, validation, missing_fields)

    def _compute_event_confidence(self, txn: dict[str, Any]) -> ConfidenceLevel:
        """Compute confidence level for a single event."""
        issues = []

        # Check required fields
        if not txn.get("date"):
            issues.append("missing_date")
        if not txn.get("description"):
            issues.append("missing_description")
        if txn.get("amount") is None:
            issues.append("missing_amount")

        # Check format
        try:
            date_val = txn.get("date", "")
            # Handle case where Gemini returns date as non-string
            if not isinstance(date_val, str):
                date_val = str(date_val) if date_val else ""
            date.fromisoformat(date_val)
        except (ValueError, TypeError):
            issues.append("invalid_date_format")

        try:
            Decimal(str(txn.get("amount", "0")))
        except (ValueError, TypeError):
            issues.append("invalid_amount_format")

        # Determine confidence level
        if not issues:
            return ConfidenceLevel.HIGH
        elif len(issues) == 1:
            return ConfidenceLevel.MEDIUM
        else:
            return ConfidenceLevel.LOW
