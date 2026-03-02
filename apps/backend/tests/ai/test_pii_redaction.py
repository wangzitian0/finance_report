import re

from src.services import pii_redaction
from src.services.pii_redaction import PIIType, detect_pii


def test_detect_pii_skips_date_like_and_zero_heavy_numbers() -> None:
    original_patterns = pii_redaction.PII_PATTERNS
    pii_redaction.PII_PATTERNS = [(PIIType.BANK_ACCOUNT, re.compile(r"\b\d{8,12}\b"))]
    try:
        text = "Values: 20240301 90000000 812345678"
        matches = detect_pii(text)
    finally:
        pii_redaction.PII_PATTERNS = original_patterns

    assert [m.original for m in matches] == ["812345678"]
