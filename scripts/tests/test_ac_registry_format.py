"""Tests for grouped AC registry format helpers."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pytest  # noqa: E402

from common.ssot.ac_registry_format import (  # noqa: E402
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
