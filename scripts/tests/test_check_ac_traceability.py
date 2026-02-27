"""
Tests for scripts/check_ac_traceability.py
Covers AC traceability verification: every mandatory AC has at least one
test reference, and the check correctly identifies covered vs missing ACs.
"""

import sys
from pathlib import Path
from typing import NamedTuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

import check_ac_traceability as cat  # noqa: E402


SAMPLE_REGISTRY_YAML = """\
version: '1.0'
total: 3
acs:
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
        assert len(refs["AC1.1.1"]) == 2

    def test_no_references_returns_empty(self, tmp_path):
        f = self._write_test(tmp_path, "test_empty.py", "def test_nothing(): pass\n")
        refs = cat.collect_referenced_acs([f])
        assert refs == {}

    def test_does_not_match_partial_ids(self, tmp_path):
        f = self._write_test(tmp_path, "test_partial.py", "# AC1.1 is not a valid ID\n")
        refs = cat.collect_referenced_acs([f])
        assert "AC1.1" not in refs


class TestCheckTraceability:
    """check_traceability computes covered vs missing mandatory ACs."""

    def _make_ac(self, ac_id, mandatory=True):
        return cat.AC(
            id=ac_id, epic=1, epic_name="test", description="", mandatory=mandatory
        )

    def test_all_covered(self):
        acs = [self._make_ac("AC1.1.1"), self._make_ac("AC1.1.2")]
        refs = {"AC1.1.1": ["test_a.py"], "AC1.1.2": ["test_b.py"]}
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
        refs = {"AC1.1.1": ["test_a.py"]}
        result = cat.check_traceability(acs, refs)
        assert result.missing == []
        assert result.mandatory_total == 1

    def test_total_count(self):
        acs = [self._make_ac("AC1.1.1"), self._make_ac("AC1.1.2")]
        result = cat.check_traceability(acs, {"AC1.1.1": ["f.py"]})
        assert result.total == 2
        assert result.mandatory_total == 2

    def test_partial_coverage(self):
        acs = [
            self._make_ac("AC1.1.1"),
            self._make_ac("AC1.1.2"),
            self._make_ac("AC1.1.3"),
        ]
        refs = {"AC1.1.1": ["f.py"], "AC1.1.3": ["g.py"]}
        result = cat.check_traceability(acs, refs)
        assert "AC1.1.2" in result.missing
        assert "AC1.1.1" in result.covered
        assert "AC1.1.3" in result.covered


class TestPrintReport:
    """print_report outputs a human-readable report without errors."""

    def _make_ac(self, ac_id, mandatory=True):
        return cat.AC(
            id=ac_id,
            epic=1,
            epic_name="test-epic",
            description="Test desc",
            mandatory=mandatory,
        )

    def test_prints_without_error(self, capsys):
        acs = [self._make_ac("AC1.1.1")]
        result = cat.TraceabilityResult(
            covered=["AC1.1.1"], missing=[], total=1, mandatory_total=1
        )
        cat.print_report(result, acs, {"AC1.1.1": ["f.py"]})
        out = capsys.readouterr().out
        assert "AC TRACEABILITY REPORT" in out

    def test_shows_missing_acs(self, capsys):
        acs = [self._make_ac("AC1.1.1")]
        result = cat.TraceabilityResult(
            covered=[], missing=["AC1.1.1"], total=1, mandatory_total=1
        )
        cat.print_report(result, acs, {})
        out = capsys.readouterr().out
        assert "AC1.1.1" in out
        assert "MISSING" in out

    def test_verbose_shows_covered(self, capsys):
        acs = [self._make_ac("AC1.1.1")]
        result = cat.TraceabilityResult(
            covered=["AC1.1.1"], missing=[], total=1, mandatory_total=1
        )
        cat.print_report(result, acs, {"AC1.1.1": ["f.py"]}, verbose=True)
        out = capsys.readouterr().out
        assert "OK" in out or "AC1.1.1" in out

    def test_zero_mandatory_no_crash(self, capsys):
        result = cat.TraceabilityResult(
            covered=[], missing=[], total=0, mandatory_total=0
        )
        cat.print_report(result, [], {})
        capsys.readouterr()


class TestMain:
    """main() returns 0 when all mandatory ACs are covered, 1 otherwise."""

    def _setup(self, tmp_path, registry_content, test_content):
        reg = tmp_path / "registry.yaml"
        reg.write_text(registry_content)
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_something.py").write_text(test_content)
        return reg, test_dir

    def test_returns_zero_all_covered(self, tmp_path, monkeypatch):
        reg, test_dir = self._setup(
            tmp_path,
            SAMPLE_REGISTRY_YAML,
            "# AC1.1.1\n# AC1.1.2\n",
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "check_ac_traceability.py",
                "--registry",
                str(reg),
                "--test-dirs",
                str(test_dir),
            ],
        )
        assert cat.main() == 0

    def test_returns_one_with_missing(self, tmp_path, monkeypatch):
        reg, test_dir = self._setup(
            tmp_path,
            SAMPLE_REGISTRY_YAML,
            "no ac references here\n",
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "check_ac_traceability.py",
                "--registry",
                str(reg),
                "--test-dirs",
                str(test_dir),
            ],
        )
        assert cat.main() == 1

    def test_report_only_returns_zero_even_with_missing(self, tmp_path, monkeypatch):
        reg, test_dir = self._setup(
            tmp_path,
            SAMPLE_REGISTRY_YAML,
            "no ac references here\n",
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "check_ac_traceability.py",
                "--registry",
                str(reg),
                "--test-dirs",
                str(test_dir),
                "--report-only",
            ],
        )
        assert cat.main() == 0
