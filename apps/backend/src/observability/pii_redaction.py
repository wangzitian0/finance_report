"""PII (Personally Identifiable Information) detector.

Finds sensitive information that audit text and extraction's CSV path must not
pass on. Focuses on Singapore-specific PII patterns: NRIC, bank account
numbers, phone numbers, email addresses, postal codes.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple


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
