"""Tests for the EPIC-003 extraction audit failed-case registry."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_AC3_9_1_extraction_failed_case_registry_preserves_audit_cases_without_parser_expansion() -> (
    None
):
    """AC-extraction.9.1: Failed parsing cases are registry-owned, not parser expansion triggers."""
    registry = yaml.safe_load(
        (ROOT / "common/extraction/audit-failed-cases.yaml").read_text()
    )
    epic = (ROOT / "docs/project/EPIC-003.statement-parsing.md").read_text()
    manifest = (ROOT / "common/meta/data/MANIFEST.yaml").read_text()

    assert registry["kind"] == "extraction_audit_failed_case_registry"
    assert registry["owner_epic"] == "EPIC-003"
    assert registry["policy"]["real_documents_committed"] is False
    assert registry["policy"]["parser_expansion_allowed_from_registry"] is False
    assert "balance_mismatch" in registry["policy"]["allowed_failure_categories"]
    assert "provider_shape_changed" in registry["policy"]["allowed_failure_categories"]
    assert registry["cases"] == []
    assert "AC-extraction.9.1" in epic
    assert "extraction_failed_case_registry" in manifest
