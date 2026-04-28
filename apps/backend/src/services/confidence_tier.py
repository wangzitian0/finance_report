"""Confidence tier derivation from journal source type."""

from typing import Literal

from src.models.journal import JournalEntrySourceType

ConfidenceTier = Literal["TRUSTED", "HIGH", "MEDIUM", "LOW"]


def derive_confidence_tier(source_type: JournalEntrySourceType | str | None) -> ConfidenceTier:
    """Map journal source_type to the EPIC-018 UI confidence tier contract."""
    if source_type is None:
        return "LOW"

    value = source_type.value if isinstance(source_type, JournalEntrySourceType) else str(source_type)
    tiers: dict[str, ConfidenceTier] = {
        "manual": "TRUSTED",
        "user_confirmed": "HIGH",
        "auto_matched": "MEDIUM",
        "auto_parsed": "LOW",
        "bank_statement": "LOW",
        "system": "LOW",
        "fx_revaluation": "LOW",
    }
    return tiers.get(value, "LOW")
