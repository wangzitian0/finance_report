"""Tests for grouped AC registry format helpers."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from common.testing.ac_registry_format import (  # noqa: E402
    epic_group_key,
    load_registry_entries,
    registry_validation_errors,
    scenario_group_key,
)


def test_load_registry_entries_returns_empty_for_missing_file(tmp_path):
    assert load_registry_entries(tmp_path / "missing.yaml") == []


def test_group_key_helpers_reject_invalid_ac_ids():
    with pytest.raises(ValueError, match="Invalid AC ID: AC8.13"):
        epic_group_key("AC8.13")

    with pytest.raises(ValueError, match="Invalid AC ID: BAD"):
        scenario_group_key("BAD")


def test_registry_validation_rejects_legacy_flat_fields(tmp_path):
    registry = tmp_path / "ac_registry.yaml"
    registry.write_text(
        "version: '1.0'\ntotal: 1\ngroups: {}\nacs:\n  - id: AC8.13.17\n",
        encoding="utf-8",
    )

    assert registry_validation_errors(registry) == [
        "uses unsupported flat 'acs' format",
        "uses unsupported committed 'total' field",
    ]


def test_registry_validation_reports_duplicate_invalid_and_misplaced_entries(tmp_path):
    registry = tmp_path / "ac_registry.yaml"
    registry.write_text(
        "version: '1.0'\n"
        "groups:\n"
        "  AC8:\n"
        "    AC8.13:\n"
        "      - id: AC8.13.17\n"
        "      - id: AC8.13.17\n"
        "      - id: NOT-AN-AC\n"
        "    AC8.14:\n"
        "      - id: AC8.13.18\n",
        encoding="utf-8",
    )

    assert registry_validation_errors(registry) == [
        "duplicates AC8.13.17",
        "Invalid AC ID: NOT-AN-AC",
        "places AC8.13.18 under AC8/AC8.14, expected AC8/AC8.13",
    ]


def test_generated_registry_index_materializes_from_declared_sources(tmp_path):
    epic_dir = tmp_path / "docs" / "project"
    epic_dir.mkdir(parents=True)
    (epic_dir / "EPIC-001.phase0-setup.md").write_text(
        "AC1.1.1: Generated from EPIC\n",
        encoding="utf-8",
    )
    overrides = tmp_path / "docs" / "ac_registry_overrides.yaml"
    overrides.write_text(
        "version: '1.0'\n"
        "groups:\n"
        "  AC1:\n"
        "    AC1.2:\n"
        "      - id: AC1.2.1\n"
        "        epic: 1\n"
        "        epic_name: phase0-setup\n"
        "        description: Override-only AC\n"
        "        mandatory: false\n",
        encoding="utf-8",
    )
    registry = tmp_path / "docs" / "ac_registry.yaml"
    registry.write_text(
        "version: '2.0'\n"
        "kind: feature\n"
        "generated_from_epics: true\n"
        f"epic_source: {epic_dir.as_posix()}\n"
        f"overrides: {overrides.as_posix()}\n",
        encoding="utf-8",
    )

    entries = load_registry_entries(registry)
    assert [entry["id"] for entry in entries] == ["AC1.1.1", "AC1.2.1"]
    assert entries[1]["mandatory"] is False
