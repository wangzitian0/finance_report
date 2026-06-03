"""Tests for tools/generate_ac_registry.py.
Covers AC registry generation from EPIC markdown files, including ID sorting,
extraction, deduplication, classification (feature vs infra), and YAML output.
"""

from pathlib import Path

from common.ssot import generate_ac_registry as gar
from common.ssot.ac_registry_format import load_registry_entries


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

    def test_extracts_checkbox_bullet_description(self, tmp_path, monkeypatch):
        """AC8.13.17: Checklist AC definitions are EPIC-owned registry input."""
        self._write_epic(
            tmp_path,
            "EPIC-011.asset-lifecycle.md",
            "- [x] **AC11.8.5** Net worth calculation toggle stays complete\n",
        )
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs()
        assert result["AC11.8.5"]["description"] == (
            "Net worth calculation toggle stays complete"
        )

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

    def test_skips_tombstone_and_summary_lines(self, tmp_path, monkeypatch):
        """AC IDs in tombstone/removal notes and summary lines are NOT extracted."""
        content = (
            "| AC9.1.1 | PDF analyzer exists |\n"
            "*(AC9.8.1 removed \u2014 duplicate of AC9.3.x)*\n"
            "- Total AC IDs: 31 (AC9.8.2\u20139.8.10 removed as duplicates)\n"
            "*(AC10.2.1 removed \u2014 canonical copy is AC12.1.1 in EPIC-012)*\n"
            "| AC10.1.1 | OTEL settings in config |\n"
        )
        self._write_epic(tmp_path, "EPIC-009.pdf-fixture-generation.md", content)
        self._write_epic(
            tmp_path, "EPIC-010.signoz-logging.md", ""
        )  # empty placeholder
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs()
        # Real AC definitions should be extracted
        assert "AC9.1.1" in result
        assert "AC10.1.1" in result
        # Tombstone/summary references should NOT be extracted
        assert "AC9.8.1" not in result
        assert "AC9.8.2" not in result
        assert "AC10.2.1" not in result

    def test_ignores_plain_references_without_definition(self, tmp_path, monkeypatch):
        """AC8.13.17: Registry generation must not create ghost ACs from references."""
        content = (
            "This paragraph references AC8.13.17 as historical context only.\n"
            "| AC8.13.16 | Existing defined AC |\n"
        )
        self._write_epic(tmp_path, "EPIC-008.testing-strategy.md", content)
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs()
        assert "AC8.13.16" in result
        assert "AC8.13.17" not in result

    def test_preserves_existing_registry_description(self, tmp_path, monkeypatch):
        """AC8.13.17: Existing canonical registry text wins over EPIC extraction."""
        self._write_epic(
            tmp_path,
            "EPIC-008.testing-strategy.md",
            "| AC8.13.17 | EPIC table text that must not overwrite registry text |\n",
        )
        existing = {
            "AC8.13.17": {
                "epic": 8,
                "epic_name": "testing-strategy",
                "description": "Canonical registry description",
                "mandatory": False,
            }
        }
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs(existing_acs=existing)
        assert result["AC8.13.17"]["description"] == "Canonical registry description"
        assert result["AC8.13.17"]["mandatory"] is False


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
        assert "groups:" in content
        assert "AC1:" in content
        assert "AC1.1:" in content
        assert "total:" not in content

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

    def test_epic_group_anchor(self, tmp_path):
        acs = {
            "AC1.1.1": {"epic": 1, "epic_name": "phase0-setup", "description": "Setup"},
        }
        out = tmp_path / "ac_registry.yaml"
        gar.write_registry(acs, output_path=str(out))
        content = out.read_text()

        assert "AC1:" in content
        assert "AC1.1:" in content

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

        assert "It's done" in content

    def test_default_output_alias_and_extra_metadata_are_preserved(
        self, tmp_path, monkeypatch
    ):
        """AC8.13.17: Generated grouped registries keep canonical metadata."""
        out = tmp_path / "ac_registry.yaml"
        monkeypatch.setattr(gar, "OUTPUT", str(out))

        gar.write_registry(
            {
                "AC8.13.17": {
                    "epic": 8,
                    "epic_name": "testing-strategy",
                    "description": "Grouped registry",
                    "owner": "ci",
                }
            }
        )

        content = out.read_text()
        assert "owner: ci" in content
        assert "AC8.13:" in content

    def test_extract_definition_ignores_blank_and_invalid_table_rows(self):
        assert gar._extract_ac_definition("   ") is None
        assert gar._extract_ac_definition("| not-an-ac | ignored |\n") is None
        assert gar._extract_ac_definition("plain reference to AC8.13.17 only") is None

    def test_append_registry_entries_noops_for_empty_input(self, tmp_path):
        out = tmp_path / "ac_registry.yaml"

        gar.append_registry_entries({}, out)

        assert not out.exists()


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
        entry = {
            "epic": 16,
            "epic_name": "two-stage-review-ui",
            "description": "Tooling",
        }
        assert gar.classify_ac("AC16.11.1", entry) == "infra"

    def test_epic16_group13_is_infra(self):
        entry = {
            "epic": 16,
            "epic_name": "two-stage-review-ui",
            "description": "Test lifecycle",
        }
        assert gar.classify_ac("AC16.13.1", entry) == "infra"

    def test_all_infra_epics_covered(self):
        """Every EPIC in INFRA_EPICS classifies its ACs as infra."""
        for epic_num in gar.INFRA_EPICS:
            entry = {
                "epic": epic_num,
                "epic_name": f"epic-{epic_num}",
                "description": "x",
            }
            assert gar.classify_ac(f"AC{epic_num}.1.1", entry) == "infra"

    def test_all_feature_epics_covered(self):
        """Every EPIC in FEATURE_EPICS classifies its ACs as feature."""
        for epic_num in gar.FEATURE_EPICS:
            if epic_num == 16:
                continue  # EPIC-16 has sub-classification
            entry = {
                "epic": epic_num,
                "epic_name": f"epic-{epic_num}",
                "description": "x",
            }
            assert gar.classify_ac(f"AC{epic_num}.1.1", entry) == "feature"


class TestMain:
    """main() extracts, classifies, and writes two output files."""

    def _setup_epic_dir(self, tmp_path, monkeypatch):
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True, exist_ok=True)
        overrides = tmp_path / "docs" / "ac_registry_overrides.yaml"
        overrides.write_text("version: '1.0'\ngroups: {}\n", encoding="utf-8")
        monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
        monkeypatch.setattr(gar, "OVERRIDES", str(overrides))
        return epic_dir

    def _setup_outputs(self, tmp_path, monkeypatch):
        out_feature = tmp_path / "docs" / "ac_registry.yaml"
        out_infra = tmp_path / "docs" / "infra_registry.yaml"
        monkeypatch.setattr(gar, "OUTPUT_FEATURE", str(out_feature))
        monkeypatch.setattr(gar, "OUTPUT_INFRA", str(out_infra))
        return out_feature, out_infra

    def _ids(self, path: Path) -> list[str]:
        return [entry["id"] for entry in load_registry_entries(path)]

    def test_main_returns_zero(self, tmp_path, monkeypatch):
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        (epic_dir / "EPIC-001.phase0-setup.md").write_text("AC1.1.1: Setup\n")
        self._setup_outputs(tmp_path, monkeypatch)
        assert gar.main() == 0

    def test_main_creates_both_output_files(self, tmp_path, monkeypatch):
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        (epic_dir / "EPIC-001.phase0-setup.md").write_text("AC1.1.1: Setup\n")
        out_feature, out_infra = self._setup_outputs(tmp_path, monkeypatch)
        gar.main()
        assert out_feature.exists()
        assert out_infra.exists()
        assert "generated_from_epics: true" in out_feature.read_text()
        assert "generated_from_epics: true" in out_infra.read_text()

    def test_main_splits_feature_and_infra(self, tmp_path, monkeypatch):
        """main() routes feature ACs to ac_registry.yaml and infra ACs to infra_registry.yaml."""
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        # EPIC-001 is feature, EPIC-007 is infra
        (epic_dir / "EPIC-001.phase0-setup.md").write_text("AC1.1.1: Feature AC\n")
        (epic_dir / "EPIC-007.deployment.md").write_text("AC7.1.1: Infra AC\n")
        out_feature, out_infra = self._setup_outputs(tmp_path, monkeypatch)
        gar.main()
        assert self._ids(out_feature) == ["AC1.1.1"]
        assert self._ids(out_infra) == ["AC7.1.1"]
        assert "groups:" not in out_feature.read_text()
        assert "total:" not in out_feature.read_text()

    def test_main_epic16_sub_classification(self, tmp_path, monkeypatch):
        """EPIC-016 ACs are sub-classified: group 11/13 → infra, others → feature."""
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        content = (
            "AC16.1.1: Feature UI\n"
            "AC16.11.1: Infra tooling\n"
            "AC16.13.1: Test lifecycle\n"
        )
        (epic_dir / "EPIC-016.two-stage-review-ui.md").write_text(content)
        out_feature, out_infra = self._setup_outputs(tmp_path, monkeypatch)
        gar.main()
        assert self._ids(out_feature) == ["AC16.1.1"]
        assert self._ids(out_infra) == ["AC16.11.1", "AC16.13.1"]

    def test_main_appends_missing_ac_without_rewriting_current_epic_text(
        self, tmp_path, monkeypatch
    ):
        """AC8.13.17: Current non-stub EPIC text and mandatory state win."""
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        (epic_dir / "EPIC-008.testing-strategy.md").write_text(
            "| AC8.13.16 | EPIC text that must not replace canonical text |\n"
            "| AC8.13.17 | Append-only generator behavior |\n"
        )
        out_feature, _out_infra = self._setup_outputs(tmp_path, monkeypatch)
        Path(gar.OVERRIDES).write_text(
            "# DO NOT edit this file manually - run tools/generate_ac_registry.py\n"
            "version: '1.0'\n"
            "groups:\n"
            "  AC8:\n"
            "    AC8.13:\n"
            "    - id: AC8.13.16\n"
            "      epic: 8\n"
            "      epic_name: testing-strategy\n"
            "      description: 'Canonical historical description'\n"
            "      status: deprecated\n"
            "      mandatory: false\n"
        )

        assert gar.main() == 0

        entries = {entry["id"]: entry for entry in load_registry_entries(out_feature)}
        assert entries["AC8.13.16"]["description"] == (
            "EPIC text that must not replace canonical text"
        )
        assert entries["AC8.13.16"]["mandatory"] is True
        assert "status" not in entries["AC8.13.16"]
        assert entries["AC8.13.17"]["description"] == "Append-only generator behavior"

    def test_current_stub_ac_can_preserve_deprecated_override_metadata(
        self, tmp_path, monkeypatch
    ):
        """AC8.13.17: Current stub placeholders can stay non-mandatory."""
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        (epic_dir / "EPIC-016.two-stage-review-ui.md").write_text(
            "| AC16.15.7 | stub |\n"
        )
        out_feature, _out_infra = self._setup_outputs(tmp_path, monkeypatch)
        Path(gar.OVERRIDES).write_text(
            "# DO NOT edit this file manually - run tools/generate_ac_registry.py\n"
            "version: '1.0'\n"
            "groups:\n"
            "  AC16:\n"
            "    AC16.15:\n"
            "    - id: AC16.15.7\n"
            "      epic: 16\n"
            "      epic_name: two-stage-review-ui\n"
            "      description: '~~retired historical registry placeholder~~'\n"
            "      status: deprecated\n"
            "      mandatory: false\n"
        )

        assert gar.main() == 0

        entries = {entry["id"]: entry for entry in load_registry_entries(out_feature)}
        assert entries["AC16.15.7"]["description"] == "stub"
        assert entries["AC16.15.7"]["mandatory"] is False
        assert entries["AC16.15.7"]["status"] == "deprecated"

    def test_main_check_fails_when_epic_ac_is_missing_from_registry(
        self, tmp_path, monkeypatch
    ):
        """AC8.13.17: Check mode catches EPIC-defined ACs missing from registry."""
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        (epic_dir / "EPIC-008.testing-strategy.md").write_text(
            "| AC8.13.17 | Append-only generator behavior |\n"
        )
        out_feature, out_infra = self._setup_outputs(tmp_path, monkeypatch)
        out_feature.write_text("version: '1.0'\ngroups: {}\n")
        out_infra.write_text("version: '1.0'\ngroups: {}\n")

        assert gar.main(["--check"]) == 1

    def test_append_registry_entries_expands_empty_groups_map(self, tmp_path):
        """AC8.13.17: Incremental append keeps an empty registry as valid YAML."""
        out = tmp_path / "ac_registry.yaml"
        out.write_text("version: '1.0'\ngroups: {}\n")

        gar.append_registry_entries(
            {
                "AC8.13.17": {
                    "epic": 8,
                    "epic_name": "testing-strategy",
                    "description": "Append-only generator behavior",
                    "mandatory": True,
                }
            },
            out,
        )

        content = out.read_text()
        assert "total:" not in content
        assert "groups:\n" in content
        assert "AC8.13:" in content
        assert "id: AC8.13.17" in content
        assert gar.load_existing_registry(out)["AC8.13.17"]["epic"] == 8

    def test_main_check_fails_when_registry_uses_legacy_flat_format(
        self, tmp_path, monkeypatch
    ):
        """AC8.13.17: Check mode rejects the legacy flat registry format."""
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        (epic_dir / "EPIC-008.testing-strategy.md").write_text(
            "| AC8.13.17 | Append-only generator behavior |\n"
        )
        out_feature, out_infra = self._setup_outputs(tmp_path, monkeypatch)
        out_feature.write_text(
            "version: '1.0'\n"
            "total: 0\n"
            "acs:\n"
            "  - id: AC8.13.17\n"
            "    epic: 8\n"
            "    epic_name: testing-strategy\n"
            "    description: 'Append-only generator behavior'\n"
            "    mandatory: true\n"
        )
        out_infra.write_text("version: '1.0'\ntotal: 0\nacs: []\n")

        assert gar.main(["--check"]) == 1

    def test_main_rewrites_legacy_flat_registry_to_grouped_format(
        self, tmp_path, monkeypatch
    ):
        """AC8.13.17: Normal generation rewrites legacy registries to index format."""
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        (epic_dir / "EPIC-008.testing-strategy.md").write_text(
            "| AC8.13.17 | Append-only generator behavior |\n"
        )
        out_feature, out_infra = self._setup_outputs(tmp_path, monkeypatch)
        out_feature.write_text(
            "version: '1.0'\n"
            "total: 0\n"
            "acs:\n"
            "  - id: AC8.13.17\n"
            "    epic: 8\n"
            "    epic_name: testing-strategy\n"
            "    description: 'Canonical historical description'\n"
            "    mandatory: true\n"
        )
        out_infra.write_text("version: '1.0'\ntotal: 0\nacs: []\n")

        assert gar.main() == 0

        content = out_feature.read_text()
        assert "total:" not in content
        assert "generated_from_epics: true" in content
        assert "Canonical historical description" not in content
        entries = {entry["id"]: entry for entry in load_registry_entries(out_feature)}
        assert entries["AC8.13.17"]["description"] == "Append-only generator behavior"

    def test_main_check_succeeds_when_registry_is_current(self, tmp_path, monkeypatch):
        """AC8.13.17: Check mode accepts current generated registry indexes."""
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        (epic_dir / "EPIC-008.testing-strategy.md").write_text(
            "| AC8.13.17 | Append-only generator behavior |\n"
        )
        out_feature, out_infra = self._setup_outputs(tmp_path, monkeypatch)
        gar.write_registry_index("feature", out_feature)
        gar.write_registry_index("infra", out_infra)

        assert gar.main(["--check"]) == 0

    def test_main_normal_mode_noops_when_registry_is_current(
        self, tmp_path, monkeypatch
    ):
        """AC8.13.17: Normal mode leaves current generated indexes valid."""
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        (epic_dir / "EPIC-008.testing-strategy.md").write_text(
            "| AC8.13.17 | Append-only generator behavior |\n"
        )
        out_feature, out_infra = self._setup_outputs(tmp_path, monkeypatch)
        gar.write_registry_index("feature", out_feature)
        gar.write_registry_index("infra", out_infra)

        assert gar.main() == 0

    def test_main_materialized_registries_have_no_duplicate_or_missing_ids(
        self, tmp_path, monkeypatch
    ):
        """Generated indexes materialize exactly one classified entry per AC ID."""
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        (epic_dir / "EPIC-001.phase0-setup.md").write_text("AC1.1.1: Feature\n")
        (epic_dir / "EPIC-007.deployment.md").write_text("AC7.1.1: Infra\n")
        out_feature, out_infra = self._setup_outputs(tmp_path, monkeypatch)

        assert gar.main() == 0

        feature_ids = self._ids(out_feature)
        infra_ids = self._ids(out_infra)
        all_ids = feature_ids + infra_ids
        assert all_ids == ["AC1.1.1", "AC7.1.1"]
        assert len(all_ids) == len(set(all_ids))
        assert set(feature_ids).isdisjoint(infra_ids)
