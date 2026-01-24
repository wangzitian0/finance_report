"""PII (Personally Identifiable Information) redaction service.

Detects and redacts sensitive information before sending to external AI APIs.
Focuses on Singapore-specific PII patterns: NRIC, bank account numbers, addresses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from src.logger import get_logger

logger = get_logger(__name__)


class PIIType(Enum):
    NRIC = "nric"
    BANK_ACCOUNT = "bank_account"
    PHONE = "phone"
    EMAIL = "email"
    POSTAL_CODE = "postal_code"


class PIIMatch(NamedTuple):
    pii_type: PIIType
    original: str
    start: int
    end: int


@dataclass
class RedactionResult:
    redacted_text: str
    matches: list[PIIMatch]
    redaction_count: int


# Singapore NRIC/FIN: S/T/F/G/M followed by 7 digits and a letter
# Examples: S1234567A, G9876543Z, T0123456B
NRIC_PATTERN = re.compile(r"\b[SGTFM]\d{7}[A-Z]\b", re.IGNORECASE)

# Singapore bank account numbers (various formats)
# DBS/POSB: 9-10 digits, UOB: 10 digits, OCBC: 7-12 digits
# Be conservative: only match standalone 9-12 digit numbers
BANK_ACCOUNT_PATTERN = re.compile(r"\b\d{9,12}\b")

# Singapore phone: +65 or 65 followed by 8 digits starting with 6/8/9
PHONE_PATTERN = re.compile(r"(?:\+?65[-\s]?)?[689]\d{7}\b")

EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

# Singapore postal code: 6 digits in 01xxxx-82xxxx range
POSTAL_CODE_PATTERN = re.compile(r"\b[0-8]\d{5}\b")

PII_PATTERNS: list[tuple[PIIType, re.Pattern[str]]] = [
    (PIIType.NRIC, NRIC_PATTERN),
    (PIIType.EMAIL, EMAIL_PATTERN),
    (PIIType.PHONE, PHONE_PATTERN),
    (PIIType.POSTAL_CODE, POSTAL_CODE_PATTERN),
    (PIIType.BANK_ACCOUNT, BANK_ACCOUNT_PATTERN),
]


def detect_pii(text: str) -> list[PIIMatch]:
    matches: list[PIIMatch] = []

    for pii_type, pattern in PII_PATTERNS:
        for match in pattern.finditer(text):
            # Skip bank account pattern for likely transaction amounts or dates
            if pii_type == PIIType.BANK_ACCOUNT:
                value = match.group()
                # Skip if it looks like a date (YYYYMMDD format)
                if len(value) == 8 and value[:4].isdigit() and 1900 <= int(value[:4]) <= 2100:
                    continue
                # Skip if it looks like an amount with many zeros
                if value.count("0") >= len(value) // 2:
                    continue

            matches.append(
                PIIMatch(
                    pii_type=pii_type,
                    original=match.group(),
                    start=match.start(),
                    end=match.end(),
                )
            )

    return matches


def redact_text(text: str, replacement: str = "[REDACTED]") -> RedactionResult:
    matches = detect_pii(text)

    if not matches:
        return RedactionResult(redacted_text=text, matches=[], redaction_count=0)

    sorted_matches = sorted(matches, key=lambda m: m.start, reverse=True)

    redacted = text
    for match in sorted_matches:
        pii_label = f"[{match.pii_type.value.upper()}]"
        redacted = redacted[: match.start] + pii_label + redacted[match.end :]

    logger.info(
        "PII redaction completed",
        redaction_count=len(matches),
        pii_types=[m.pii_type.value for m in matches],
    )

    return RedactionResult(
        redacted_text=redacted,
        matches=matches,
        redaction_count=len(matches),
    )


def mask_account_number(account_number: str, visible_digits: int = 4) -> str:
    if len(account_number) <= visible_digits:
        return account_number
    masked_len = len(account_number) - visible_digits
    return "*" * masked_len + account_number[-visible_digits:]
