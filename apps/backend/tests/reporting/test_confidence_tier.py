import pytest

from src.audit import JournalEntrySourceType
from src.reporting.extension.confidence_tier import derive_confidence_tier, derive_reconciliation_score_tier


@pytest.mark.parametrize(
    "source_type,expected",
    [
        (JournalEntrySourceType.MANUAL, "TRUSTED"),
        (JournalEntrySourceType.USER_CONFIRMED, "HIGH"),
        (JournalEntrySourceType.AUTO_MATCHED, "MEDIUM"),
        (JournalEntrySourceType.AUTO_PARSED, "LOW"),
        # bank_statement was retired from the enum in 0040 (#896); the raw-string
        # case is still covered by the string-parametrized test below.
        (JournalEntrySourceType.SYSTEM, "LOW"),
        (JournalEntrySourceType.FX_REVALUATION, "LOW"),
    ],
)
def test_derive_confidence_tier_enum(source_type, expected):
    assert derive_confidence_tier(source_type) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("manual", "TRUSTED"),
        ("user_confirmed", "HIGH"),
        ("auto_matched", "MEDIUM"),
        ("auto_parsed", "LOW"),
        ("bank_statement", "LOW"),
        ("system", "LOW"),
        ("fx_revaluation", "LOW"),
    ],
)
def test_derive_confidence_tier_str(raw, expected):
    assert derive_confidence_tier(raw) == expected


def test_derive_confidence_tier_none_returns_low():
    assert derive_confidence_tier(None) == "LOW"


def test_derive_confidence_tier_unknown_string_defaults_low():
    assert derive_confidence_tier("totally_unknown_source") == "LOW"


@pytest.mark.parametrize(
    "score,expected",
    [
        (None, "LOW"),
        (59, "LOW"),
        (60, "MEDIUM"),
        (84, "MEDIUM"),
        (85, "HIGH"),
        (100, "HIGH"),
    ],
)
def test_ac4_9_4_derive_reconciliation_score_tier(score, expected):
    """AC-reconciliation.bank-side-amount.5."""
    assert derive_reconciliation_score_tier(score) == expected
