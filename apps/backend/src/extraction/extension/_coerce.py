"""Value coercion and balanced JSON recovery helpers."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from src.extraction.base.normalization_engine import sanitize_account_last4
from src.extraction.extension._base import _tolerant_parse_date, logger


def scan_balanced_json_candidates(
    content: str,
    open_char: str,
    close_char: str,
    *,
    stop_on_unclosed_array: bool = False,
) -> list[str]:
    """Scan balanced top-level JSON delimiters while respecting string literals."""
    if not content:
        return []
    text = content.strip()
    candidates: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != open_char:
            i += 1
            continue
        depth = bracket_depth = 0
        in_string = escaped = False
        end: int | None = None
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
            elif char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0:
                    end = j
                    break
            elif stop_on_unclosed_array:
                if char == "[":
                    bracket_depth += 1
                elif char == "]" and bracket_depth > 0:
                    bracket_depth -= 1
        if end is None:
            if stop_on_unclosed_array and bracket_depth > 0:
                break
            if open_char == "[":
                break
            i += 1
            continue
        candidates.append(text[i : end + 1])
        i = end + 1
    return candidates


class _CoerceMixin:
    def _safe_date(self, value: str | None) -> date:
        if not value:
            logger.error("Date is required but was None or empty", value=value)
            raise ValueError("Date is required")
        parsed = _tolerant_parse_date(value)
        if parsed is None:
            logger.error("Failed to parse date", value=value)
            raise ValueError(f"Invalid date format: {value}")
        return parsed

    def _safe_optional_date(self, value: str | None) -> date | None:
        return self._safe_date(value) if value else None

    def _safe_decimal(self, value: str | None, default: str | None = None, *, required: bool = False) -> Decimal | None:
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
        return sanitize_account_last4(value)

    def _extract_status_code(self, error_msg: str) -> str | None:
        match = re.search(r"HTTP (\d{3})", error_msg)
        return match.group(1) if match else None

    @staticmethod
    def _repair_json_object(content: str) -> str | None:
        """Recover the largest balanced top-level JSON object from a model response."""
        objects = scan_balanced_json_candidates(content, "{", "}", stop_on_unclosed_array=True)
        return max(objects, key=len) if objects else None
