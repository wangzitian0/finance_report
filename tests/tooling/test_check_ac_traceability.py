"""Tests for the common.testing.check_ac_traceability validation library.

Covers AC traceability verification: every mandatory AC has at least one CI-stage
test reference, and the pure functions correctly classify covered / unexecuted /
placeholder / stub / missing ACs. The library is consumed by the single gate
``tools/check_ac_index.py`` (via ``check_ac_index.check_repo_contracts``).
"""

import ast
import re
from pathlib import Path

import pytest
from common.testing import check_ac_traceability as cat

SAMPLE_REGISTRY_YAML = """\
version: '1.0'
groups:
  AC1:
    AC1.1:
      - id: AC1.1.1
        epic: 1
        epic_name: phase0-setup
        description: 'System is deployed'
        mandatory: true
      - id: AC1.1.2
        epic: 1
        epic_name: phase0-setup
        description: 'Health check passes'
        mandatory: true
  AC2:
    AC2.1:
      - id: AC2.1.1
        epic: 2
        epic_name: double-entry-core
        description: 'Balanced entries stored'
        mandatory: false
"""


class TestLoadRegistry:
    """load_registry parses YAML and returns list of AC named tuples."""

    def test_loads_all_entries(self, tmp_path):
        reg = tmp_path / "ac_registry.yaml"
        reg.write_text(SAMPLE_REGISTRY_YAML)
        acs = cat.load_registry(reg)
        assert len(acs) == 3

    def test_ac_fields(self, tmp_path):
        reg = tmp_path / "ac_registry.yaml"
        reg.write_text(SAMPLE_REGISTRY_YAML)
        acs = cat.load_registry(reg)
        first = acs[0]
        assert first.id == "AC1.1.1"
        assert first.epic == 1
        assert first.epic_name == "phase0-setup"
        assert first.mandatory is True

    def test_mandatory_false_parsed(self, tmp_path):
        reg = tmp_path / "ac_registry.yaml"
        reg.write_text(SAMPLE_REGISTRY_YAML)
        acs = cat.load_registry(reg)
        non_mandatory = [ac for ac in acs if ac.id == "AC2.1.1"][0]
        assert non_mandatory.mandatory is False

    def test_missing_registry_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            cat.load_registry(tmp_path / "nonexistent.yaml")


class TestFindTestFiles:
    """find_test_files discovers test files in given directories."""

    def test_finds_test_py_files(self, tmp_path):
        d = tmp_path / "tests"
        d.mkdir()
        (d / "test_accounting.py").write_text("")
        files = cat.find_test_files([d])
        assert any("test_accounting.py" in str(f) for f in files)

    def test_finds_test_ts_files(self, tmp_path):
        d = tmp_path / "src"
        d.mkdir()
        (d / "accounts.test.ts").write_text("")
        files = cat.find_test_files([d])
        assert any("accounts.test.ts" in str(f) for f in files)

    def test_finds_test_tsx_files(self, tmp_path):
        d = tmp_path / "src"
        d.mkdir()
        (d / "Button.test.tsx").write_text("")
        files = cat.find_test_files([d])
        assert any("Button.test.tsx" in str(f) for f in files)

    def test_skips_non_test_files(self, tmp_path):
        d = tmp_path / "src"
        d.mkdir()
        (d / "accounts.ts").write_text("")
        (d / "utils.py").write_text("")
        files = cat.find_test_files([d])
        assert len(files) == 0

    def test_excludes_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules"
        nm.mkdir()
        (nm / "test_something.py").write_text("")
        files = cat.find_test_files([tmp_path])
        assert len(files) == 0

    def test_missing_directory_skipped(self, tmp_path):
        files = cat.find_test_files([tmp_path / "nonexistent"])
        assert files == []

    def test_multiple_directories(self, tmp_path):
        d1 = tmp_path / "backend"
        d1.mkdir()
        (d1 / "test_a.py").write_text("")
        d2 = tmp_path / "frontend"
        d2.mkdir()
        (d2 / "a.test.ts").write_text("")
        files = cat.find_test_files([d1, d2])
        assert len(files) == 2


class TestCollectReferencedAcs:
    """collect_referenced_acs extracts AC IDs from test file content."""

    def _write_test(self, d, fname, content):
        f = d / fname
        f.write_text(content)
        return f

    def test_finds_ac_reference(self, tmp_path):
        f = self._write_test(
            tmp_path,
            "test_accounting.py",
            'def test_entry():\n    """AC1.1.1: Balanced entry"""\n    pass\n',
        )
        refs = cat.collect_referenced_acs([f])
        assert "AC1.1.1" in refs

    def test_finds_multiple_references_in_file(self, tmp_path):
        content = "# AC1.1.1\n# AC2.1.1\n"
        f = self._write_test(tmp_path, "test_multi.py", content)
        refs = cat.collect_referenced_acs([f])
        assert "AC1.1.1" in refs
        assert "AC2.1.1" in refs

    def test_same_ac_multiple_files(self, tmp_path):
        f1 = self._write_test(tmp_path, "test_a.py", "# AC1.1.1\n")
        f2 = self._write_test(tmp_path, "test_b.py", "# AC1.1.1\n")
        refs = cat.collect_referenced_acs([f1, f2])
        assert len(refs["AC1.1.1"].real_files) == 2

    def test_no_references_returns_empty(self, tmp_path):
        f = self._write_test(tmp_path, "test_empty.py", "def test_nothing(): pass\n")
        refs = cat.collect_referenced_acs([f])
        assert refs == {}

    def test_does_not_match_partial_ids(self, tmp_path):
        f = self._write_test(tmp_path, "test_partial.py", "# AC1.1 is not a valid ID\n")
        refs = cat.collect_referenced_acs([f])
        assert "AC1.1" not in refs

    def test_classifies_placeholder_assertion(self, tmp_path):
        """AC-testing.acgates.3: AC8.13.35: Trivial placeholder assertions are not real AC coverage."""
        f = self._write_test(
            tmp_path,
            "uiGapAudit.test.ts",
            "test('AC1.1.1 placeholder', () => { expect(true).toBe(true); });\n",
        )
        refs = cat.collect_referenced_acs([f])
        assert str(f) in refs["AC1.1.1"].placeholder_files
        assert refs["AC1.1.1"].real_files == set()

    def test_AC8_13_78_fixture_placeholder_string_does_not_taint_file(self, tmp_path):
        """AC8.13.78: Fixture text with trivial assertions does not hide real proof."""
        f = self._write_test(
            tmp_path,
            "test_tooling_contract.py",
            "def test_contract():\n"
            '    """AC1.1.1: behavior proof"""\n'
            '    fixture = "expect(true).toBe(true)"\n'
            '    assert "expect" in fixture\n',
        )
        refs = cat.collect_referenced_acs([f])
        assert str(f) in refs["AC1.1.1"].real_files
        assert refs["AC1.1.1"].placeholder_files == set()

    def test_classifies_pure_pass_ac_file_as_placeholder(self, tmp_path):
        """AC8.13.35: Pure pass tests are not real AC coverage."""
        f = self._write_test(
            tmp_path,
            "test_gap.py",
            'def test_gap():\n    """AC1.1.1: placeholder only"""\n    pass\n',
        )
        refs = cat.collect_referenced_acs([f])
        assert str(f) in refs["AC1.1.1"].placeholder_files
        assert refs["AC1.1.1"].real_files == set()

    def test_classifies_pure_skip_ac_file_as_placeholder(self, tmp_path):
        """AC8.13.35: Pure skipped tests are not real AC coverage."""
        f = self._write_test(
            tmp_path,
            "test_gap.py",
            'import pytest\n\ndef test_gap():\n    """AC1.1.1: placeholder only"""\n    pytest.skip("todo")\n',
        )
        refs = cat.collect_referenced_acs([f])
        assert str(f) in refs["AC1.1.1"].placeholder_files
        assert refs["AC1.1.1"].real_files == set()

    def test_environment_skip_with_behavioral_assertion_stays_real(self, tmp_path):
        """AC8.13.35: Environment-gated E2E tests can still count as real."""
        f = self._write_test(
            tmp_path,
            "test_e2e.py",
            'import pytest\n\ndef test_flow():\n    """AC1.1.1: configured flow"""\n    if False:\n        pytest.skip("not configured")\n    assert True\n',
        )
        refs = cat.collect_referenced_acs([f])
        assert str(f) in refs["AC1.1.1"].real_files
        assert refs["AC1.1.1"].placeholder_files == set()

    def test_AC8_13_78_unexecuted_real_reference_is_tracked(self, tmp_path):
        """AC8.13.78: Real refs outside CI-required stages do not prove mandatory ACs."""
        f = self._write_test(
            tmp_path,
            "test_local_e2e.py",
            'def test_flow():\n    """AC1.1.1: local-only behavior"""\n    assert True\n',
        )
        matrix = cat.ExecutionMatrix(
            rules=[
                cat.ExecutionRule(
                    path_prefix=str(tmp_path),
                    stage="local_only",
                    ci_required=False,
                )
            ]
        )

        refs = cat.collect_referenced_acs([f], execution_matrix=matrix)

        assert str(f) in refs["AC1.1.1"].real_files
        assert refs["AC1.1.1"].ci_real_files == set()

    def test_classifies_ac_stub_directory(self, tmp_path):
        """AC8.13.35: AC stub files are tracked separately from real tests."""
        stub_dir = tmp_path / "_ac_stubs"
        stub_dir.mkdir()
        f = self._write_test(
            stub_dir, "test_stub.py", "# AC1.1.1\ndef test_stub(): pass\n"
        )
        refs = cat.collect_referenced_acs([f])
        assert str(f) in refs["AC1.1.1"].stub_files
        assert refs["AC1.1.1"].real_files == set()


class TestLoadMultipleRegistries:
    """load_multiple_registries combines registries and keeps the first AC id."""

    def test_combines_both_registries(self, tmp_path):
        feat = tmp_path / "ac_registry.yaml"
        feat.write_text(SAMPLE_REGISTRY_YAML)
        infra = tmp_path / "infra_registry.yaml"
        infra.write_text(
            "version: '1.0'\ngroups:\n  AC7:\n    AC7.1:\n      - id: AC7.1.1\n"
            "        epic: 7\n        epic_name: deployment\n"
            "        description: 'CI pipeline'\n        mandatory: true\n"
        )
        ids = [ac.id for ac in cat.load_multiple_registries([feat, infra])]
        assert "AC1.1.1" in ids and "AC7.1.1" in ids

    def test_first_registry_wins_on_duplicate_id(self, tmp_path):
        feat = tmp_path / "ac_registry.yaml"
        feat.write_text(SAMPLE_REGISTRY_YAML)
        infra = tmp_path / "infra_registry.yaml"
        infra.write_text(
            "version: '1.0'\ngroups:\n  AC1:\n    AC1.1:\n      - id: AC1.1.1\n"
            "        epic: 1\n        epic_name: infra-version\n"
            "        description: 'Infra duplicate'\n        mandatory: false\n"
        )
        matching = [
            ac
            for ac in cat.load_multiple_registries([feat, infra])
            if ac.id == "AC1.1.1"
        ]
        assert len(matching) == 1
        assert matching[0].epic_name == "phase0-setup"


class TestIsDeprecated:
    """The one deprecation rule: a non-blank ``~~strikethrough~~`` description."""

    @pytest.mark.parametrize(
        "description",
        ["~~removed~~", "  ~~gone~~  ", "~~two\nlines~~", "~~~~~", "~~x~~\n"],
    )
    def test_strikethrough_is_deprecated(self, description):
        assert cat.is_deprecated(description)

    @pytest.mark.parametrize(
        "description",
        ["", "plain", "~~only start", "only end~~", "~~~", "~~~~", "~~ ~~", "~~  ~~"],
    )
    def test_everything_else_stays_active(self, description):
        assert not cat.is_deprecated(description)

    def test_the_rule_is_defined_exactly_once(self):
        """No second deprecation rule exists in common/ or tools/ (AST census)."""
        root = Path(__file__).resolve().parents[2]
        pattern = re.compile(r"^_?is_deprecated(_description)?$")
        scanned = 0
        defs: list[tuple[str, str]] = []
        for base in ("common", "tools"):
            for path in sorted((root / base).rglob("*.py")):
                scanned += 1
                tree = ast.parse(path.read_text(encoding="utf-8"))
                defs.extend(
                    (path.relative_to(root).as_posix(), node.name)
                    for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and pattern.match(node.name)
                )
        assert scanned > 100, f"census scanned only {scanned} files"
        assert defs == [("common/testing/check_ac_traceability.py", "is_deprecated")]


class TestClassifyReferences:
    """classify_references is the one real/placeholder/stub/missing classifier."""

    def test_no_stats_is_missing(self):
        assert cat.classify_references(None) == "missing"

    def test_empty_stats_is_missing(self):
        assert cat.classify_references(cat.ACReferenceStats()) == "missing"

    def test_real_wins_over_placeholder_and_stub(self):
        stats = cat.ACReferenceStats(
            real_files={"a"}, placeholder_files={"b"}, stub_files={"c"}
        )
        assert cat.classify_references(stats) == "real"

    def test_placeholder_wins_over_stub(self):
        stats = cat.ACReferenceStats(placeholder_files={"b"}, stub_files={"c"})
        assert cat.classify_references(stats) == "placeholder"

    def test_stub_only(self):
        assert cat.classify_references(cat.ACReferenceStats(stub_files={"c"})) == "stub"


class TestEmptyInputFails:
    """A gate that scanned zero mandatory ACs must fail, not pass."""

    def test_empty_ac_list_fails(self):
        result = cat.check_traceability([], {})
        messages = cat.traceability_failure_messages(result)
        assert len(messages) == 1
        assert "0 mandatory AC(s) were scanned" in messages[0]

    def test_only_deprecated_acs_fails(self):
        acs = [cat.AC("AC1.1.1", 1, "t", "~~retired~~", True)]
        result = cat.check_traceability(acs, {})
        assert result.total == 1 and result.mandatory_total == 0
        assert cat.traceability_failure_messages(result)

    def test_registry_with_empty_epic_source_fails(self, tmp_path):
        """A registry index that resolves to zero ACs (wrong epic_source) cannot pass."""
        docs = tmp_path / "docs"
        (docs / "empty_epics").mkdir(parents=True)
        for name, kind in (
            ("ac_registry.yaml", "feature"),
            ("infra_registry.yaml", "infra"),
        ):
            (docs / name).write_text(
                f"version: '2.0'\nkind: {kind}\ngenerated_from_epics: true\n"
                f"epic_source: {docs / 'empty_epics'}\n"
                f"overrides: {docs / 'no_overrides.yaml'}\n"
            )
        result = cat.run_traceability(tmp_path)
        assert result.mandatory_total == 0
        assert cat.traceability_failure_messages(result)


class TestCheckTraceability:
    """check_traceability computes covered vs missing mandatory ACs."""

    def _make_ac(self, ac_id, mandatory=True):
        return cat.AC(
            id=ac_id, epic=1, epic_name="test", description="", mandatory=mandatory
        )

    def test_all_covered(self):
        acs = [self._make_ac("AC1.1.1"), self._make_ac("AC1.1.2")]
        refs = {
            "AC1.1.1": cat.ACReferenceStats(
                real_files={"test_a.py"}, ci_real_files={"test_a.py"}
            ),
            "AC1.1.2": cat.ACReferenceStats(
                real_files={"test_b.py"}, ci_real_files={"test_b.py"}
            ),
        }
        result = cat.check_traceability(acs, refs)
        assert result.missing == []
        assert sorted(result.covered) == ["AC1.1.1", "AC1.1.2"]

    def test_none_covered(self):
        acs = [self._make_ac("AC1.1.1"), self._make_ac("AC1.1.2")]
        result = cat.check_traceability(acs, {})
        assert sorted(result.missing) == ["AC1.1.1", "AC1.1.2"]
        assert result.covered == []

    def test_non_mandatory_not_required(self):
        acs = [
            self._make_ac("AC1.1.1", mandatory=True),
            self._make_ac("AC1.1.2", mandatory=False),
        ]
        refs = {
            "AC1.1.1": cat.ACReferenceStats(
                real_files={"test_a.py"}, ci_real_files={"test_a.py"}
            )
        }
        result = cat.check_traceability(acs, refs)
        assert result.missing == []
        assert result.mandatory_total == 1

    def test_deprecated_mandatory_not_required(self):
        acs = [
            cat.AC("AC1.1.1", 1, "test", "active behavior", True),
            cat.AC("AC1.1.2", 1, "test", "~~deprecated behavior~~", True),
        ]
        refs = {
            "AC1.1.1": cat.ACReferenceStats(
                real_files={"test_a.py"}, ci_real_files={"test_a.py"}
            )
        }
        result = cat.check_traceability(acs, refs)
        assert result.missing == []
        assert result.mandatory_total == 1

    def test_total_count(self):
        acs = [self._make_ac("AC1.1.1"), self._make_ac("AC1.1.2")]
        result = cat.check_traceability(
            acs,
            {
                "AC1.1.1": cat.ACReferenceStats(
                    real_files={"f.py"}, ci_real_files={"f.py"}
                )
            },
        )
        assert result.total == 2
        assert result.mandatory_total == 2

    def test_partial_coverage(self):
        acs = [
            self._make_ac("AC1.1.1"),
            self._make_ac("AC1.1.2"),
            self._make_ac("AC1.1.3"),
        ]
        refs = {
            "AC1.1.1": cat.ACReferenceStats(
                real_files={"f.py"}, ci_real_files={"f.py"}
            ),
            "AC1.1.3": cat.ACReferenceStats(
                real_files={"g.py"}, ci_real_files={"g.py"}
            ),
        }
        result = cat.check_traceability(acs, refs)
        assert "AC1.1.2" in result.missing
        assert "AC1.1.1" in result.covered
        assert "AC1.1.3" in result.covered

    def test_placeholder_and_stub_refs_do_not_count_as_real_coverage(self):
        """AC-testing.acgates.4: AC8.13.35: Non-real AC references stay visible but uncovered."""
        acs = [
            self._make_ac("AC1.1.1"),
            self._make_ac("AC1.1.2"),
            self._make_ac("AC1.1.3"),
        ]
        refs = {
            "AC1.1.1": cat.ACReferenceStats(placeholder_files={"placeholder.test.ts"}),
            "AC1.1.2": cat.ACReferenceStats(stub_files={"_ac_stubs/test_stub.py"}),
        }
        result = cat.check_traceability(acs, refs)
        assert result.covered == []
        assert result.placeholder_only == ["AC1.1.1"]
        assert result.stub_only == ["AC1.1.2"]
        assert result.missing == ["AC1.1.3"]

    def test_AC8_13_78_unexecuted_real_refs_fail_mandatory_gate(self):
        """AC8.13.78: Mandatory ACs require a CI-required real proof file."""
        acs = [self._make_ac("AC1.1.1")]
        refs = {"AC1.1.1": cat.ACReferenceStats(real_files={"tools/tier2_http_e2e.py"})}

        result = cat.check_traceability(acs, refs)

        assert result.covered == []
        assert result.unexecuted_only == ["AC1.1.1"]
        assert result.missing == []

    def test_AC8_13_78_ci_required_real_refs_cover_mandatory_gate(self):
        """AC-testing.acgates.11: AC8.13.78: CI-required real proof files satisfy mandatory ACs."""
        acs = [self._make_ac("AC1.1.1")]
        refs = {
            "AC1.1.1": cat.ACReferenceStats(
                real_files={"apps/backend/tests/e2e/test_core_journeys.py"},
                ci_real_files={"apps/backend/tests/e2e/test_core_journeys.py"},
            )
        }

        result = cat.check_traceability(acs, refs)

        assert result.covered == ["AC1.1.1"]
        assert result.unexecuted_only == []
