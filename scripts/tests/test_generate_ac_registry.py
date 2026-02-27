"""
Tests for scripts/generate_ac_registry.py
Covers AC registry generation from EPIC markdown files, including ID sorting,
extraction, deduplication, and YAML output.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import generate_ac_registry as gar  # noqa: E402


class TestSortKey:
    """sort_key converts AC IDs to numeric tuples for correct ordering."""

    def test_simple_ac(self):
        assert gar.sort_key("AC1.2.3") == [1, 2, 3]

    def test_double_digit_epic(self):
        assert gar.sort_key("AC16.3.1") == [16, 3, 1]

    def test_ordering_correctness(self):
        ids = ["AC10.1.1", "AC2.1.1", "AC1.99.1"]
        sorted_ids = sorted(ids, key=gar.sort_key)
        assert sorted_ids == ["AC1.99.1", "AC2.1.1", "AC10.1.1"]

    def test_three_digit_sort_stability(self):
        assert gar.sort_key("AC1.1.10") == [1, 1, 10]
        assert gar.sort_key("AC1.1.9") == [1, 1, 9]
        assert gar.sort_key("AC1.1.10") > gar.sort_key("AC1.1.9")


class TestExtractAcs:
    """extract_acs scans EPIC markdown files and returns a registry dict."""

    def _write_epic(self, tmp_path, fname, content):
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True, exist_ok=True)
        (epic_dir / fname).write_text(content)
        return epic_dir

    def test_extracts_ac_from_table(self, tmp_path, monkeypatch):
        self._write_epic(
            tmp_path,
            "EPIC-001.phase0-setup.md",
            "| AC1.1.1 | System is deployed |\n",
        )
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs()
        assert "AC1.1.1" in result
        assert result["AC1.1.1"]["epic"] == 1

    def test_extracts_description(self, tmp_path, monkeypatch):
        self._write_epic(
            tmp_path,
            "EPIC-002.double-entry-core.md",
            "| AC2.1.1 | Balanced entries are stored |\n",
        )
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs()
        assert "AC2.1.1" in result
        assert "Balanced" in result["AC2.1.1"]["description"]

    def test_deduplicates_ac_ids(self, tmp_path, monkeypatch):
        content = "AC1.1.1: First occurrence\nAC1.1.1: Second occurrence\n"
        self._write_epic(tmp_path, "EPIC-001.phase0-setup.md", content)
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs()
        assert list(result.keys()).count("AC1.1.1") == 1

    def test_skips_implementation_files(self, tmp_path, monkeypatch):
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True, exist_ok=True)
        (epic_dir / "EPIC-001.IMPLEMENTATION.md").write_text(
            "AC1.1.1: should be skipped\n"
        )
        monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
        result = gar.extract_acs()
        assert "AC1.1.1" not in result

    def test_skips_encoding_files(self, tmp_path, monkeypatch):
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True, exist_ok=True)
        (epic_dir / "EPIC-001.ENCODING.md").write_text("AC1.1.1: should be skipped\n")
        monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
        result = gar.extract_acs()
        assert "AC1.1.1" not in result

    def test_epic_name_from_known_epics(self, tmp_path, monkeypatch):
        self._write_epic(
            tmp_path,
            "EPIC-004.reconciliation-engine.md",
            "AC4.1.1: Matching works\n",
        )
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs()
        assert result["AC4.1.1"]["epic_name"] == "reconciliation-engine"

    def test_multiple_epics(self, tmp_path, monkeypatch):
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True, exist_ok=True)
        (epic_dir / "EPIC-001.phase0-setup.md").write_text("AC1.1.1: Setup\n")
        (epic_dir / "EPIC-002.double-entry-core.md").write_text("AC2.1.1: Accounting\n")
        monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
        result = gar.extract_acs()
        assert "AC1.1.1" in result
        assert "AC2.1.1" in result


class TestWriteRegistry:
    """write_registry produces a valid YAML file from AC dict."""

    def test_writes_yaml_header(self, tmp_path, monkeypatch):
        acs = {
            "AC1.1.1": {"epic": 1, "epic_name": "phase0-setup", "description": "Test"},
        }
        out = tmp_path / "ac_registry.yaml"
        monkeypatch.setattr(gar, "OUTPUT", str(out))
        gar.write_registry(acs)
        content = out.read_text()
        assert "version: '1.0'" in content
        assert "total: 1" in content
        assert "acs:" in content

    def test_writes_ac_entry(self, tmp_path, monkeypatch):
        acs = {
            "AC2.1.1": {
                "epic": 2,
                "epic_name": "double-entry-core",
                "description": "Accounting",
            },
        }
        out = tmp_path / "ac_registry.yaml"
        monkeypatch.setattr(gar, "OUTPUT", str(out))
        gar.write_registry(acs)
        content = out.read_text()
        assert "id: AC2.1.1" in content
        assert "epic: 2" in content
        assert "mandatory: true" in content

    def test_entries_sorted_numerically(self, tmp_path, monkeypatch):
        acs = {
            "AC10.1.1": {
                "epic": 10,
                "epic_name": "signoz-logging",
                "description": "Logging",
            },
            "AC2.1.1": {
                "epic": 2,
                "epic_name": "double-entry-core",
                "description": "Accounting",
            },
        }
        out = tmp_path / "ac_registry.yaml"
        monkeypatch.setattr(gar, "OUTPUT", str(out))
        gar.write_registry(acs)
        content = out.read_text()
        assert content.index("AC2.1.1") < content.index("AC10.1.1")

    def test_epic_group_comment(self, tmp_path, monkeypatch):
        acs = {
            "AC1.1.1": {"epic": 1, "epic_name": "phase0-setup", "description": "Setup"},
        }
        out = tmp_path / "ac_registry.yaml"
        monkeypatch.setattr(gar, "OUTPUT", str(out))
        gar.write_registry(acs)
        content = out.read_text()
        assert "EPIC-001" in content

    def test_escapes_single_quotes_in_description(self, tmp_path, monkeypatch):
        acs = {
            "AC1.1.1": {
                "epic": 1,
                "epic_name": "phase0-setup",
                "description": "It's done",
            },
        }
        out = tmp_path / "ac_registry.yaml"
        monkeypatch.setattr(gar, "OUTPUT", str(out))
        gar.write_registry(acs)
        content = out.read_text()
        assert "It''s done" in content


class TestMain:
    """main() runs extract + write in sequence and returns 0."""

    def test_main_returns_zero(self, tmp_path, monkeypatch):
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True, exist_ok=True)
        (epic_dir / "EPIC-001.phase0-setup.md").write_text("AC1.1.1: Setup\n")
        out = tmp_path / "docs" / "ac_registry.yaml"
        monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
        monkeypatch.setattr(gar, "OUTPUT", str(out))
        assert gar.main() == 0

    def test_main_creates_output_file(self, tmp_path, monkeypatch):
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True, exist_ok=True)
        (epic_dir / "EPIC-001.phase0-setup.md").write_text("AC1.1.1: Setup\n")
        out = tmp_path / "docs" / "ac_registry.yaml"
        monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
        monkeypatch.setattr(gar, "OUTPUT", str(out))
        gar.main()
        assert out.exists()
