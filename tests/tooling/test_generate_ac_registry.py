"""Tests for tools/generate_ac_registry.py.
Covers AC registry generation from EPIC markdown files, including ID sorting,
extraction, deduplication, classification (feature vs infra), and YAML output.
"""

from pathlib import Path

from common.meta.extension import generate_ac_registry as gar
from common.meta.extension.ac_registry_format import load_registry_entries


class TestSortKey:
    """sort_key totally orders BOTH id grammars.

    Legacy numeric ids carry a leading ``0`` discriminant, package-scoped ids a
    leading ``1`` (so they sort after, and an int field is never compared to a
    str one). The contract that matters is the ORDERING, asserted below.
    """

    def test_simple_ac(self):
        assert gar.sort_key("AC1.2.3") == (0, "", 1, 2, 3)

    def test_double_digit_epic(self):
        assert gar.sort_key("AC16.3.1") == (0, "", 16, 3, 1)

    def test_ordering_correctness(self):
        ids = ["AC10.1.1", "AC2.1.1", "AC1.99.1"]
        sorted_ids = sorted(ids, key=gar.sort_key)
        assert sorted_ids == ["AC1.99.1", "AC2.1.1", "AC10.1.1"]

    def test_three_digit_sort_stability(self):
        assert gar.sort_key("AC1.1.10") == (0, "", 1, 1, 10)
        assert gar.sort_key("AC1.1.9") == (0, "", 1, 1, 9)
        assert gar.sort_key("AC1.1.10") > gar.sort_key("AC1.1.9")

    def test_package_ids_sort_after_legacy_and_by_package(self):
        # group is a string (a package's group may be a word-entity slug like
        # "guardrail", not a number), so a numeric group like "1" is asserted
        # as a string here too.
        assert gar.sort_key("AC-counter.1.1") == (1, "counter", "1", 1)
        # Package ids sort after every legacy numeric id...
        assert gar.sort_key("AC-counter.1.1") > gar.sort_key("AC999.9.9")
        # ...then by (package, group, seq).
        ids = ["AC-platform.1.2", "AC-counter.2.1", "AC-counter.1.1", "AC1.1.1"]
        assert sorted(ids, key=gar.sort_key) == [
            "AC1.1.1",
            "AC-counter.1.1",
            "AC-counter.2.1",
            "AC-platform.1.2",
        ]

    def test_word_entity_group_sorts_and_orders(self):
        # A word-entity group (e.g. "guardrail") is a legitimate package
        # convention (advisor, reconciliation, reporting all use it) and must
        # not crash sort_key or be silently dropped from the registry.
        assert gar.sort_key("AC-advisor.guardrail.3") == (1, "advisor", "guardrail", 3)
        assert gar.sort_key("AC-advisor.guardrail.3") > gar.sort_key("AC999.9.9")


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
            "| AC1.1.1 | System is deployed | <!-- epic-owned: horizontal -->\n",
        )
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs()
        assert "AC1.1.1" in result
        assert result["AC1.1.1"]["epic"] == 1

    def test_extracts_description(self, tmp_path, monkeypatch):
        self._write_epic(
            tmp_path,
            "EPIC-002.double-entry-core.md",
            "| AC2.1.1 | Balanced entries are stored | <!-- epic-owned: horizontal -->\n",
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
            "- [x] **AC11.8.5** Net worth calculation toggle stays complete <!-- epic-owned: horizontal -->\n",
        )
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs()
        assert result["AC11.8.5"]["description"] == (
            "Net worth calculation toggle stays complete"
        )

    def test_deduplicates_ac_ids(self, tmp_path, monkeypatch):
        content = (
            "AC1.1.1: First occurrence <!-- epic-owned: horizontal -->\n"
            "AC1.1.1: Second occurrence <!-- epic-owned: horizontal -->\n"
        )
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
            "AC4.1.1: Matching works <!-- epic-owned: horizontal -->\n",
        )
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs()
        assert result["AC4.1.1"]["epic_name"] == "reconciliation-engine"

    def test_multiple_epics(self, tmp_path, monkeypatch):
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True, exist_ok=True)
        (epic_dir / "EPIC-001.phase0-setup.md").write_text(
            "AC1.1.1: Setup <!-- epic-owned: horizontal -->\n"
        )
        (epic_dir / "EPIC-002.double-entry-core.md").write_text(
            "AC2.1.1: Accounting <!-- epic-owned: horizontal -->\n"
        )
        monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
        result = gar.extract_acs()
        assert "AC1.1.1" in result
        assert "AC2.1.1" in result

    def test_skips_tombstone_and_summary_lines(self, tmp_path, monkeypatch):
        """AC IDs in tombstone/removal notes and summary lines are NOT extracted."""
        content = (
            "| AC9.1.1 | PDF analyzer exists | <!-- epic-owned: horizontal -->\n"
            "*(AC9.8.1 removed \u2014 duplicate of AC9.3.x)*\n"
            "- Total AC IDs: 31 (AC9.8.2\u20139.8.10 removed as duplicates)\n"
            "*(AC10.2.1 removed \u2014 canonical copy is AC12.1.1 in EPIC-012)*\n"
            "| AC10.1.1 | OTEL settings in config | <!-- epic-owned: horizontal -->\n"
        )
        self._write_epic(tmp_path, "EPIC-009.pdf-fixture-generation.md", content)
        self._write_epic(
            tmp_path, "EPIC-010.observability-logging.md", ""
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
            "| AC8.13.16 | Existing defined AC | <!-- epic-owned: horizontal -->\n"
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
            "| AC8.13.17 | EPIC table text that must not overwrite registry text | <!-- epic-owned: horizontal -->\n",
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
                "epic_name": "observability-logging",
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

    def test_default_output_and_extra_metadata_are_preserved(
        self, tmp_path, monkeypatch
    ):
        """AC8.13.17: Generated grouped registries keep canonical metadata."""
        out = tmp_path / "ac_registry.yaml"
        monkeypatch.setattr(gar, "OUTPUT_FEATURE", str(out))

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
        (epic_dir / "EPIC-001.phase0-setup.md").write_text(
            "AC1.1.1: Setup <!-- epic-owned: horizontal -->\n"
        )
        self._setup_outputs(tmp_path, monkeypatch)
        assert gar.main() == 0

    def test_main_creates_both_output_files(self, tmp_path, monkeypatch):
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        (epic_dir / "EPIC-001.phase0-setup.md").write_text(
            "AC1.1.1: Setup <!-- epic-owned: horizontal -->\n"
        )
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
        (epic_dir / "EPIC-001.phase0-setup.md").write_text(
            "AC1.1.1: Feature AC <!-- epic-owned: horizontal -->\n"
        )
        (epic_dir / "EPIC-007.deployment.md").write_text(
            "AC7.1.1: Infra AC <!-- epic-owned: horizontal -->\n"
        )
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
            "AC16.1.1: Feature UI <!-- epic-owned: fe-only -->\n"
            "AC16.11.1: Infra tooling <!-- epic-owned: horizontal -->\n"
            "AC16.13.1: Test lifecycle <!-- epic-owned: horizontal -->\n"
        )
        (epic_dir / "EPIC-016.two-stage-review-ui.md").write_text(content)
        out_feature, out_infra = self._setup_outputs(tmp_path, monkeypatch)
        gar.main()
        assert self._ids(out_feature) == ["AC16.1.1"]
        assert self._ids(out_infra) == ["AC16.11.1", "AC16.13.1"]

    def test_main_appends_missing_ac_without_rewriting_current_epic_text(
        self, tmp_path, monkeypatch
    ):
        """AC-testing.acgates.1: AC8.13.17: Current non-stub EPIC text and mandatory state win."""
        epic_dir = self._setup_epic_dir(tmp_path, monkeypatch)
        (epic_dir / "EPIC-008.testing-strategy.md").write_text(
            "| AC8.13.16 | EPIC text that must not replace canonical text | <!-- epic-owned: horizontal -->\n"
            "| AC8.13.17 | Append-only generator behavior | <!-- epic-owned: horizontal -->\n"
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
            "| AC16.15.7 | stub | <!-- epic-owned: fe-only -->\n"
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
            "| AC8.13.17 | Append-only generator behavior | <!-- epic-owned: horizontal -->\n"
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
            "| AC8.13.17 | Append-only generator behavior | <!-- epic-owned: horizontal -->\n"
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
            "| AC8.13.17 | Append-only generator behavior | <!-- epic-owned: horizontal -->\n"
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
            "| AC8.13.17 | Append-only generator behavior | <!-- epic-owned: horizontal -->\n"
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
            "| AC8.13.17 | Append-only generator behavior | <!-- epic-owned: horizontal -->\n"
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
        (epic_dir / "EPIC-001.phase0-setup.md").write_text(
            "AC1.1.1: Feature <!-- epic-owned: horizontal -->\n"
        )
        (epic_dir / "EPIC-007.deployment.md").write_text(
            "AC7.1.1: Infra <!-- epic-owned: horizontal -->\n"
        )
        out_feature, out_infra = self._setup_outputs(tmp_path, monkeypatch)

        assert gar.main() == 0

        feature_ids = self._ids(out_feature)
        infra_ids = self._ids(out_infra)
        all_ids = feature_ids + infra_ids
        assert all_ids == ["AC1.1.1", "AC7.1.1"]
        assert len(all_ids) == len(set(all_ids))
        assert set(feature_ids).isdisjoint(infra_ids)


class TestFindAcCollisions:
    """find_ac_collisions guards AC ID uniqueness across EPIC docs.

    extract_acs keeps the first definition of a repeated AC ID and silently drops
    the rest, so a duplicate row can hide a real, differently-scoped AC (and its
    test) from the registry. These tests pin the collision detector that makes
    such drift fail the registry --check gate instead of passing silently.
    """

    def _write_epic(self, tmp_path, fname, content):
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True, exist_ok=True)
        (epic_dir / fname).write_text(content)
        return epic_dir

    def test_clean_doc_has_no_collisions(self, tmp_path):
        epic_dir = self._write_epic(
            tmp_path,
            "EPIC-002.double-entry-core.md",
            "### AC2.1: Group\n\n| AC2.1.1 | First |\n| AC2.1.2 | Second |\n",
        )
        dup_defs, dup_headings = gar.find_ac_collisions(epic_dir=epic_dir)
        assert dup_defs == {}
        assert dup_headings == {}

    def test_duplicate_table_definition_is_flagged(self, tmp_path):
        epic_dir = self._write_epic(
            tmp_path,
            "EPIC-002.double-entry-core.md",
            "| AC2.91.1 | User-scoped rule |\n"
            "| AC2.91.1 | A different framework rule sharing the id |\n",
        )
        dup_defs, _ = gar.find_ac_collisions(epic_dir=epic_dir)
        assert "AC2.91.1" in dup_defs

    def test_checklist_bullet_is_not_a_competing_definition(self, tmp_path):
        """A bullet that restates an AC must not be treated as a duplicate row."""
        epic_dir = self._write_epic(
            tmp_path,
            "EPIC-015.processing-account.md",
            "| AC15.7.6 | Sidebar shows Processing |\n- [x] AC15.7.6 done\n",
        )
        dup_defs, _ = gar.find_ac_collisions(epic_dir=epic_dir)
        assert dup_defs == {}

    def test_duplicate_group_heading_is_flagged(self, tmp_path):
        epic_dir = self._write_epic(
            tmp_path,
            "EPIC-002.double-entry-core.md",
            "### AC2.12: UI Responsiveness\n\n| AC2.12.3 | mobile |\n"
            "### AC2.12: Multi-Currency\n\n| AC2.12.1 | base ccy |\n",
        )
        _, dup_headings = gar.find_ac_collisions(epic_dir=epic_dir)
        assert any(key.endswith(":AC2.12") for key in dup_headings)

    def test_check_mode_fails_on_collision(self, tmp_path, monkeypatch):
        epic_dir = self._write_epic(
            tmp_path,
            "EPIC-002.double-entry-core.md",
            "| AC2.91.1 | one |\n| AC2.91.1 | two |\n",
        )
        monkeypatch.setattr(gar, "EPIC_DIR", str(epic_dir))
        assert gar.main(["--check"]) == 1


class TestResidueMarkerFlip:
    """#1719 'retire the center': EPIC docs feed the registry only through
    explicitly marked residue rows, and package roadmaps are authoritative on
    any id collision (roadmap-wins; the old EPIC-wins rule is retired)."""

    def _write_epic(self, tmp_path, fname, content):
        epic_dir = tmp_path / "docs" / "project"
        epic_dir.mkdir(parents=True, exist_ok=True)
        (epic_dir / fname).write_text(content)
        return epic_dir

    def test_unmarked_epic_row_does_not_feed_the_registry(self, tmp_path, monkeypatch):
        """AC-meta.residue.1: an unmarked EPIC AC row is invisible to the registry."""
        self._write_epic(
            tmp_path,
            "EPIC-002.double-entry-core.md",
            "| AC2.1.1 | Marked residue row | <!-- epic-owned: fe-only -->\n"
            "| AC2.1.2 | Unmarked row that must not feed the registry |\n"
            "- [x] **AC2.1.3** Unmarked checklist definition\n",
        )
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs()
        assert set(result) == {"AC2.1.1"}

    def test_residue_marker_is_stripped_from_description(self, tmp_path, monkeypatch):
        self._write_epic(
            tmp_path,
            "EPIC-002.double-entry-core.md",
            "- [x] **AC2.1.1** Bullet residue <!-- epic-owned: horizontal -->\n",
        )
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs()
        # Exact equality proves the marker never leaks into the description.
        assert result["AC2.1.1"]["description"] == "Bullet residue"

    def test_extract_definition_returns_residue_category(self):
        definition = gar._extract_ac_definition(
            "| AC2.1.1 | Row | P0 | <!-- epic-owned: fe-half -->\n"
        )
        assert definition is not None
        assert definition[5] == "fe-half"
        unmarked = gar._extract_ac_definition("| AC2.1.1 | Row | P0 |\n")
        assert unmarked is not None
        assert unmarked[5] is None

    def test_package_roadmap_wins_on_id_collision(self, tmp_path, monkeypatch):
        """Roadmap-wins (#1719): a stale marked EPIC row cannot shadow the
        package contract's statement or tier."""
        self._write_epic(
            tmp_path,
            "EPIC-002.double-entry-core.md",
            "| AC2.1.1 | Stale EPIC text {tier:HU} | <!-- epic-owned: fe-only -->\n",
        )
        contract_dir = tmp_path / "common" / "demo"
        contract_dir.mkdir(parents=True)
        (contract_dir / "contract.py").write_text(
            "CONTRACT = PackageContract(\n"
            '    name="demo",\n'
            '    status="active",\n'
            '    tier="CODE-ONLY",\n'
            "    roadmap=[\n"
            "        ACRecord(\n"
            '            id="AC2.1.1",\n'
            '            statement="Roadmap statement wins",\n'
            '            test="tests/tooling/test_x.py::test_x",\n'
            '            priority="P1",\n'
            '            status="done",\n'
            "        ),\n"
            "    ],\n"
            ")\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(gar, "EPIC_DIR", str(tmp_path / "docs" / "project"))
        result = gar.extract_acs()
        assert result["AC2.1.1"]["description"] == "Roadmap statement wins"
        assert result["AC2.1.1"]["tier"] == "CODE-ONLY"
