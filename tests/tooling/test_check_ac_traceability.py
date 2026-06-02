"""Tests for tools/check_ac_traceability.py.
Covers AC traceability verification: every mandatory AC has at least one
test reference, and the check correctly identifies covered vs missing ACs.
"""

import pytest
from common.ssot import check_ac_traceability as cat

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
        """AC8.13.35: Trivial placeholder assertions are not real AC coverage."""
        f = self._write_test(
            tmp_path,
            "uiGapAudit.test.ts",
            "test('AC1.1.1 placeholder', () => { expect(true).toBe(true); });\n",
        )
        refs = cat.collect_referenced_acs([f])
        assert str(f) in refs["AC1.1.1"].placeholder_files
        assert refs["AC1.1.1"].real_files == set()

    def test_AC8_13_78_fixture_placeholder_string_does_not_taint_file(
        self, tmp_path
    ):
        """AC8.13.78: Fixture text with trivial assertions does not hide real proof."""
        f = self._write_test(
            tmp_path,
            "test_tooling_contract.py",
            'def test_contract():\n'
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
        """AC8.13.35: Non-real AC references stay visible but uncovered."""
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
        refs = {
            "AC1.1.1": cat.ACReferenceStats(
                real_files={"apps/backend/tests/e2e/test_auth_flows.py"}
            )
        }

        result = cat.check_traceability(acs, refs)

        assert result.covered == []
        assert result.unexecuted_only == ["AC1.1.1"]
        assert result.missing == []

    def test_AC8_13_78_ci_required_real_refs_cover_mandatory_gate(self):
        """AC8.13.78: CI-required real proof files satisfy mandatory ACs."""
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
            covered=["AC1.1.1"],
            placeholder_only=[],
            stub_only=[],
            unexecuted_only=[],
            missing=[],
            total=1,
            mandatory_total=1,
        )
        cat.print_report(
            result, acs, {"AC1.1.1": cat.ACReferenceStats(real_files={"f.py"})}
        )
        out = capsys.readouterr().out
        assert "AC TRACEABILITY REPORT" in out

    def test_shows_missing_acs(self, capsys):
        acs = [self._make_ac("AC1.1.1")]
        result = cat.TraceabilityResult(
            covered=[],
            placeholder_only=[],
            stub_only=[],
            unexecuted_only=[],
            missing=["AC1.1.1"],
            total=1,
            mandatory_total=1,
        )
        cat.print_report(result, acs, {})
        out = capsys.readouterr().out
        assert "AC1.1.1" in out
        assert "MISSING" in out

    def test_verbose_shows_covered(self, capsys):
        acs = [self._make_ac("AC1.1.1")]
        result = cat.TraceabilityResult(
            covered=["AC1.1.1"],
            placeholder_only=[],
            stub_only=[],
            unexecuted_only=[],
            missing=[],
            total=1,
            mandatory_total=1,
        )
        cat.print_report(
            result,
            acs,
            {
                "AC1.1.1": cat.ACReferenceStats(
                    real_files={"f.py"},
                    ci_real_files={"f.py"},
                )
            },
            verbose=True,
        )
        out = capsys.readouterr().out
        assert "OK" in out or "AC1.1.1" in out
        assert "f.py" in out

    def test_AC8_13_78_shows_unexecuted_real_refs(self, capsys):
        """AC8.13.78: Reports identify real refs outside CI-required stages."""
        acs = [self._make_ac("AC1.1.1")]
        result = cat.TraceabilityResult(
            covered=[],
            placeholder_only=[],
            stub_only=[],
            unexecuted_only=["AC1.1.1"],
            missing=[],
            total=1,
            mandatory_total=1,
        )

        cat.print_report(
            result,
            acs,
            {
                "AC1.1.1": cat.ACReferenceStats(
                    real_files={"apps/backend/tests/e2e/test_auth_flows.py"}
                )
            },
        )

        out = capsys.readouterr().out
        assert "WARNING: ACs WITH ONLY NON-CI REAL TEST REFERENCES" in out
        assert "UNEXECUTED AC1.1.1" in out
        assert "apps/backend/tests/e2e/test_auth_flows.py" in out

    def test_zero_mandatory_no_crash(self, capsys):
        result = cat.TraceabilityResult(
            covered=[],
            placeholder_only=[],
            stub_only=[],
            unexecuted_only=[],
            missing=[],
            total=0,
            mandatory_total=0,
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
        empty_infra = tmp_path / "empty_infra.yaml"
        empty_infra.write_text("version: '1.0'\ngroups: {}\n")
        monkeypatch.setattr(
            "sys.argv",
            [
                "check_ac_traceability.py",
                "--registry",
                str(reg),
                "--infra-registry",
                str(empty_infra),
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
        empty_infra = tmp_path / "empty_infra.yaml"
        empty_infra.write_text("version: '1.0'\ngroups: {}\n")
        monkeypatch.setattr(
            "sys.argv",
            [
                "check_ac_traceability.py",
                "--registry",
                str(reg),
                "--infra-registry",
                str(empty_infra),
                "--test-dirs",
                str(test_dir),
            ],
        )
        assert cat.main() == 1

    def test_returns_one_with_placeholder_only(self, tmp_path, monkeypatch):
        """AC8.13.35: Placeholder-only mandatory ACs fail the default gate."""
        reg, test_dir = self._setup(
            tmp_path,
            SAMPLE_REGISTRY_YAML,
            "test('AC1.1.1 placeholder', () => expect(true).toBe(true));\n# AC1.1.2\n",
        )
        empty_infra = tmp_path / "empty_infra.yaml"
        empty_infra.write_text("version: '1.0'\ntotal: 0\nacs: []\n")
        monkeypatch.setattr(
            "sys.argv",
            [
                "check_ac_traceability.py",
                "--registry",
                str(reg),
                "--infra-registry",
                str(empty_infra),
                "--test-dirs",
                str(test_dir),
            ],
        )
        assert cat.main() == 1

    def test_returns_one_with_stub_only(self, tmp_path, monkeypatch):
        """AC8.13.37: Stub-only mandatory ACs fail the default gate."""
        reg = tmp_path / "registry.yaml"
        reg.write_text(SAMPLE_REGISTRY_YAML)
        test_dir = tmp_path / "tests"
        stub_dir = test_dir / "_ac_stubs"
        stub_dir.mkdir(parents=True)
        (stub_dir / "test_stub.py").write_text("# AC1.1.1\n# AC1.1.2\n")
        empty_infra = tmp_path / "empty_infra.yaml"
        empty_infra.write_text("version: '1.0'\ngroups: {}\n")
        monkeypatch.setattr(
            "sys.argv",
            [
                "check_ac_traceability.py",
                "--registry",
                str(reg),
                "--infra-registry",
                str(empty_infra),
                "--test-dirs",
                str(test_dir),
            ],
        )
        assert cat.main() == 1

    def test_AC8_13_78_returns_one_with_unexecuted_only(
        self, tmp_path, monkeypatch, capsys
    ):
        """AC8.13.78: Non-CI real refs fail the default mandatory gate."""
        reg, test_dir = self._setup(
            tmp_path,
            SAMPLE_REGISTRY_YAML,
            'def test_flow_one():\n'
            '    """AC1.1.1: local-only behavior"""\n'
            '    assert True\n\n'
            'def test_flow_two():\n'
            '    """AC1.1.2: local-only behavior"""\n'
            '    assert True\n',
        )
        matrix = tmp_path / "execution-matrix.yaml"
        matrix.write_text(
            "version: '1.0'\n"
            "rules:\n"
            f"  - path: {test_dir.name}\n"
            "    stage: local_only\n"
            "    ci_required: false\n"
        )
        empty_infra = tmp_path / "empty_infra.yaml"
        empty_infra.write_text("version: '1.0'\ngroups: {}\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            "sys.argv",
            [
                "check_ac_traceability.py",
                "--registry",
                reg.name,
                "--infra-registry",
                empty_infra.name,
                "--test-dirs",
                test_dir.name,
                "--execution-matrix",
                matrix.name,
            ],
        )

        assert cat.main() == 1
        assert "non-CI-required stages" in capsys.readouterr().err

    def test_explicit_missing_infra_registry_returns_one(
        self, tmp_path, monkeypatch, capsys
    ):
        reg, test_dir = self._setup(
            tmp_path,
            SAMPLE_REGISTRY_YAML,
            "# AC1.1.1\n# AC1.1.2\n",
        )
        missing_infra = tmp_path / "missing_infra.yaml"
        monkeypatch.setattr(
            "sys.argv",
            [
                "check_ac_traceability.py",
                "--registry",
                str(reg),
                "--infra-registry",
                str(missing_infra),
                "--test-dirs",
                str(test_dir),
            ],
        )

        assert cat.main() == 1
        assert "Infra registry file not found" in capsys.readouterr().err

    def test_report_only_returns_zero_even_with_missing(self, tmp_path, monkeypatch):
        reg, test_dir = self._setup(
            tmp_path,
            SAMPLE_REGISTRY_YAML,
            "no ac references here\n",
        )
        empty_infra = tmp_path / "empty_infra.yaml"
        empty_infra.write_text("version: '1.0'\ngroups: {}\n")
        monkeypatch.setattr(
            "sys.argv",
            [
                "check_ac_traceability.py",
                "--registry",
                str(reg),
                "--infra-registry",
                str(empty_infra),
                "--test-dirs",
                str(test_dir),
                "--report-only",
            ],
        )
        assert cat.main() == 0
