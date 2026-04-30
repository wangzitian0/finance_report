import pytest

from src.models.journal import JournalEntrySourceType
from src.services.confidence_tier import derive_confidence_tier


@pytest.mark.parametrize(
    "source_type,expected",
    [
        (JournalEntrySourceType.MANUAL, "TRUSTED"),
        (JournalEntrySourceType.BANK_STATEMENT, "LOW"),
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
