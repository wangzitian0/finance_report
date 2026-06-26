"""Value coercion + JSON-repair helpers."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from src.services.extraction._base import (
    _tolerant_parse_date,
    logger,
)


class _CoerceMixin:
    def _safe_date(self, value: str | None) -> date:
        """Safely parse a required date, accepting common non-ISO formats (#1086)."""
        if not value:
            logger.error("Date is required but was None or empty", value=value)
            raise ValueError("Date is required")
        parsed = _tolerant_parse_date(value)
        if parsed is None:
            logger.error("Failed to parse date", value=value)
            raise ValueError(f"Invalid date format: {value}")
        return parsed

    def _safe_optional_date(self, value: str | None) -> date | None:
        """Safely parse an optional date from extraction output."""
        if not value:
            return None
        return self._safe_date(value)

    def _resolve_required_period(self, extracted: dict) -> tuple[date, date]:
        """Resolve a bank statement's required (period_start, period_end).

        The model occasionally omits ``period_start`` (or ``period_end``) even
        when the statement clearly has a period and transactions — sending it
        verbatim to ``_safe_date`` then hard-fails the whole parse with
        "Date is required" (#1449), and the failure is non-deterministic for the
        same statement format. Degrade gracefully instead: for a missing bound,
        prefer the transaction-date range (which yields a meaningful period),
        then fall back to the other explicit bound. Only raise when no date can
        be recovered at all, so a genuinely date-less document still rejects.
        """
        start = self._safe_optional_date(extracted.get("period_start"))
        end = self._safe_optional_date(extracted.get("period_end"))
        if start is not None and end is not None:
            return start, end

        txn_dates = sorted(
            parsed
            for txn in (extracted.get("transactions") or [])
            if (raw := txn.get("date")) not in (None, "", "None", "null")
            and (parsed := _tolerant_parse_date(str(raw))) is not None
        )
        first_txn = txn_dates[0] if txn_dates else None
        last_txn = txn_dates[-1] if txn_dates else None
        # A missing bound prefers the transaction-date range over the opposite
        # explicit bound: using the opposite bound would collapse the period to a
        # zero-length range (e.g. start==end), so it is only the last resort.
        resolved_start = start or first_txn or end
        resolved_end = end or last_txn or start
        if resolved_start is None or resolved_end is None:
            logger.error("Statement period could not be resolved from dates or transactions")
            raise ValueError("Date is required")
        return resolved_start, resolved_end

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

    def _extract_status_code(self, error_msg: str) -> str | None:
        match = re.search(r"HTTP (\d{3})", error_msg)
        return match.group(1) if match else None

    @staticmethod
    def _repair_json_object(content: str) -> str | None:
        """Best-effort recovery of a JSON object from a malformed model response.

        Models occasionally wrap an otherwise-valid object in a markdown code
        fence or pad it with prose. Rather than rejecting the upload (#982),
        scan every top-level balanced ``{...}`` object — tracking string literals
        so braces inside values do not truncate one — and return the **largest**.
        Returning the largest (rather than the first) avoids picking a small
        inline *example* object that precedes the real, much larger extraction.
        Any surrounding fence (including single-line ``` ```json {...}``` ``` blocks)
        or prose is naturally ignored. The repair is deterministic and does not
        invent data; it returns ``None`` when no balanced object can be recovered,
        leaving the original failure path intact.
        """
        if not content:
            return None

        text = content.strip()
        objects: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            if text[i] != "{":
                i += 1
                continue
            # Scan one balanced top-level object starting at i.
            depth = 0
            in_string = False
            escaped = False
            end = None
            for j in range(i, n):
                char = text[j]
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
                        end = j
                        break
            if end is None:
                # This ``{`` never balances (leading junk like ``note: {oops`` or a
                # truncated tail). Skip just this brace and keep scanning, so a
                # complete object appearing later is still recovered. A salvaged
                # fragment that is not a real statement is caught downstream by
                # completeness/period validation.
                i += 1
                continue
            objects.append(text[i : end + 1])
            i = end + 1

        if not objects:
            return None
        return max(objects, key=len)
