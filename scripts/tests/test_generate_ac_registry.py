"""Tests for scripts/generate_ac_registry.py.
Covers AC registry generation from EPIC markdown files, including ID sorting,
extraction, deduplication, classification (feature vs infra), and YAML output.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

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

    def test_writes_yaml_header(self, tmp_path):
        acs = {
            "AC1.1.1": {"epic": 1, "epic_name": "phase0-setup", "description": "Test"},
        }
        out = tmp_path / "ac_registry.yaml"
        gar.write_registry(acs, output_path=str(out))
        content = out.read_text()

        assert "version: '1.0'" in content
        assert "total: 1" in content
        assert "acs:" in content

    def test_writes_ac_entry(self, tmp_path):
        acs = {
            "AC2.1.1": {
                "epic": 2,
                "epic_name": "double-entry-core",
                "description": "Accounting",
            },
        }
        out = tmp_path / "ac_registry.yaml"
        gar.write_registry(acs, output_path=str(out))
        content = out.read_text()

        assert "id: AC2.1.1" in content
        assert "epic: 2" in content
        assert "mandatory: true" in content

    def test_entries_sorted_numerically(self, tmp_path):
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
        gar.write_registry(acs, output_path=str(out))
        content = out.read_text()

        assert content.index("AC2.1.1") < content.index("AC10.1.1")

    def test_epic_group_comment(self, tmp_path):
        acs = {
            "AC1.1.1": {"epic": 1, "epic_name": "phase0-setup", "description": "Setup"},
        }
        out = tmp_path / "ac_registry.yaml"
        gar.write_registry(acs, output_path=str(out))
        content = out.read_text()

        assert "EPIC-001" in content

    def test_escapes_single_quotes_in_description(self, tmp_path):
        acs = {
            "AC1.1.1": {
                "epic": 1,
                "epic_name": "phase0-setup",
                "description": "It's done",
            },
        }
        out = tmp_path / "ac_registry.yaml"
        gar.write_registry(acs, output_path=str(out))
        content = out.read_text()

        assert "It''s done" in content


class TestClassifyAc:
    """classify_ac routes ACs to feature or infra based on EPIC and group."""

    def test_feature_epic_returns_feature(self):
        entry = {"epic": 1, "epic_name": "phase0-setup", "description": "Setup"}
        assert gar.classify_ac("AC1.1.1", entry) == "feature"

    def test_infra_epic_returns_infra(self):
        entry = {"epic": 7, "epic_name": "deployment", "description": "Deploy"}
        assert gar.classify_ac("AC7.1.1", entry) == "infra"

    def test_epic16_default_is_feature(self):
        entry = {"epic": 16, "epic_name": "two-stage-review-ui", "description": "UI"}
        assert gar.classify_ac("AC16.1.1", entry) == "feature"

    def test_epic16_group11_is_infra(self):
        entry = {"epic": 16, "epic_name": "two-stage-review-ui", "description": "Tooling"}
        assert gar.classify_ac("AC16.11.1", entry) == "infra"

    def test_epic16_group13_is_infra(self):
        entry = {"epic": 16, "epic_name": "two-stage-review-ui", "description": "Test lifecycle"}
        assert gar.classify_ac("AC16.13.1", entry) == "infra"

    def test_all_infra_epics_covered(self):
        """Every EPIC in INFRA_EPICS classifies its ACs as infra."""
        for epic_num in gar.INFRA_EPICS:
            entry = {"epic": epic_num, "epic_name": f"epic-{epic_num}", "description": "x"}
            assert gar.classify_ac(f"AC{epic_num}.1.1", entry) == "infra"

    def test_all_feature_epics_covered(self):
        """Every EPIC in FEATURE_EPICS classifies its ACs as feature."""
        for epic_num in gar.FEATURE_EPICS:
            if epic_num == 16:
                continue  # EPIC-16 has sub-classification
            entry = {"epic": epic_num, "epic_name": f"epic-{epic_num}", "description": "x"}
            assert gar.classify_ac(f"AC{epic_num}.1.1", entry) == "feature"


class TestMain:
    """main() extracts, classifies, and writes two output files."""

    def _setup_epic_dir(self, tmp_path):
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True, exist_ok=True)
        return epic_dir

    def test_main_returns_zero(self, tmp_path, monkeypatch):
        epic_dir = self._setup_epic_dir(tmp_path)
        (epic_dir / "EPIC-001.phase0-setup.md").write_text("AC1.1.1: Setup\n")
        out_feature = tmp_path / "docs" / "ac_registry.yaml"
        out_infra = tmp_path / "docs" / "infra_registry.yaml"
        monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
        monkeypatch.setattr(gar, "OUTPUT_FEATURE", str(out_feature))
        monkeypatch.setattr(gar, "OUTPUT_INFRA", str(out_infra))
        assert gar.main() == 0

    def test_main_creates_both_output_files(self, tmp_path, monkeypatch):
        epic_dir = self._setup_epic_dir(tmp_path)
        (epic_dir / "EPIC-001.phase0-setup.md").write_text("AC1.1.1: Setup\n")
        out_feature = tmp_path / "docs" / "ac_registry.yaml"
        out_infra = tmp_path / "docs" / "infra_registry.yaml"
        monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
        monkeypatch.setattr(gar, "OUTPUT_FEATURE", str(out_feature))
        monkeypatch.setattr(gar, "OUTPUT_INFRA", str(out_infra))
        gar.main()
        assert out_feature.exists()
        assert out_infra.exists()

    def test_main_splits_feature_and_infra(self, tmp_path, monkeypatch):
        """main() routes feature ACs to ac_registry.yaml and infra ACs to infra_registry.yaml."""
        epic_dir = self._setup_epic_dir(tmp_path)
        # EPIC-001 is feature, EPIC-007 is infra
        (epic_dir / "EPIC-001.phase0-setup.md").write_text("AC1.1.1: Feature AC\n")
        (epic_dir / "EPIC-007.deployment.md").write_text("AC7.1.1: Infra AC\n")
        out_feature = tmp_path / "docs" / "ac_registry.yaml"
        out_infra = tmp_path / "docs" / "infra_registry.yaml"
        monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
        monkeypatch.setattr(gar, "OUTPUT_FEATURE", str(out_feature))
        monkeypatch.setattr(gar, "OUTPUT_INFRA", str(out_infra))
        gar.main()
        feature_content = out_feature.read_text()
        infra_content = out_infra.read_text()
        # Feature file has AC1.1.1 only
        assert "AC1.1.1" in feature_content
        assert "AC7.1.1" not in feature_content
        assert "total: 1" in feature_content
        # Infra file has AC7.1.1 only
        assert "AC7.1.1" in infra_content
        assert "AC1.1.1" not in infra_content
        assert "total: 1" in infra_content

    def test_main_epic16_sub_classification(self, tmp_path, monkeypatch):
        """EPIC-016 ACs are sub-classified: group 11/13 → infra, others → feature."""
        epic_dir = self._setup_epic_dir(tmp_path)
        content = (
            "AC16.1.1: Feature UI\n"
            "AC16.11.1: Infra tooling\n"
            "AC16.13.1: Test lifecycle\n"
        )
        (epic_dir / "EPIC-016.two-stage-review-ui.md").write_text(content)
        out_feature = tmp_path / "docs" / "ac_registry.yaml"
        out_infra = tmp_path / "docs" / "infra_registry.yaml"
        monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
        monkeypatch.setattr(gar, "OUTPUT_FEATURE", str(out_feature))
        monkeypatch.setattr(gar, "OUTPUT_INFRA", str(out_infra))
        gar.main()
        feature_content = out_feature.read_text()
        infra_content = out_infra.read_text()
        # AC16.1.1 is feature
        assert "AC16.1.1" in feature_content
        assert "total: 1" in feature_content
        # AC16.11.1 and AC16.13.1 are infra
        assert "AC16.11.1" in infra_content
        assert "AC16.13.1" in infra_content
        assert "total: 2" in infra_content