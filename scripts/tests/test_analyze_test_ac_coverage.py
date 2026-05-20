"""Tests for scripts/analyze_test_ac_coverage.py."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import analyze_test_ac_coverage as coverage


class TestAnalyzeRepo:
    def _write_registry(self, repo_root: Path) -> None:
        docs = repo_root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "ac_registry.yaml").write_text(
            """
version: '1.0'
total: 4
acs:
  - id: AC1.1.1
    epic: 1
    epic_name: phase0
    description: backend real
    mandatory: true
  - id: AC1.1.2
    epic: 1
    epic_name: phase0
    description: frontend real
    mandatory: true
  - id: AC2.2.1
    epic: 2
    epic_name: testing-strategy
    description: e2e real
    mandatory: true
  - id: AC3.3.3
    epic: 3
    epic_name: placeholders
    description: stub only
    mandatory: true
  - id: AC4.4.4
    epic: 4
    epic_name: untested
    description: no real or stub reference
    mandatory: true
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (docs / "infra_registry.yaml").write_text(
            "version: '1.0'\ntotal: 0\nacs: []\n",
            encoding="utf-8",
        )

    def _write_tests(self, repo_root: Path) -> None:
        backend = repo_root / "apps" / "backend" / "tests"
        frontend = repo_root / "apps" / "frontend" / "src" / "__tests__"
        e2e = repo_root / "tests" / "e2e"
        repo_e2e = repo_root / "repo" / "e2e_regressions"
        stubs = backend / "_ac_stubs"

        backend.mkdir(parents=True, exist_ok=True)
        frontend.mkdir(parents=True, exist_ok=True)
        e2e.mkdir(parents=True, exist_ok=True)
        repo_e2e.mkdir(parents=True, exist_ok=True)
        stubs.mkdir(parents=True, exist_ok=True)

        (backend / "test_backend_real.py").write_text(
            'def test_backend_real():\n    """AC1.1.1 AC9.9.9"""\n    assert True\n',
            encoding="utf-8",
        )
        (frontend / "dashboard.test.tsx").write_text(
            "// AC1.1.2\n// AC18.4.4\nexport {}\n",
            encoding="utf-8",
        )
        (e2e / "test_core.py").write_text(
            "# AC2.2.1\n",
            encoding="utf-8",
        )
        (repo_e2e / "test_regression.py").write_text(
            "# AC2.2.1\n",
            encoding="utf-8",
        )
        (stubs / "test_placeholder.py").write_text(
            "import pytest\n# AC3.3.3\n# AC8.12.7\ndef test_stub():\n    pytest.skip('placeholder')\n",
            encoding="utf-8",
        )

    def test_analyze_repo_classifies_real_stub_invalid_and_untested(self, tmp_path: Path) -> None:
        self._write_registry(tmp_path)
        self._write_tests(tmp_path)

        result = coverage.analyze_repo(tmp_path)

        assert result.source_file_counts["backend"] == 2
        assert result.source_file_counts["frontend"] == 1
        assert result.source_file_counts["e2e"] == 1
        assert result.source_file_counts["repo_e2e"] == 1

        assert result.covered_ids == {"AC1.1.1", "AC1.1.2", "AC2.2.1"}
        assert result.stub_only_ids == {"AC3.3.3"}
        assert result.untested_ids == ["AC3.3.3", "AC4.4.4"]

        assert "AC9.9.9" in result.invalid_real_refs
        assert "apps/backend/tests/test_backend_real.py" in result.invalid_real_refs["AC9.9.9"]
        assert "AC18.4.4" in result.invalid_real_refs
        assert "apps/frontend/src/__tests__/dashboard.test.tsx" in result.invalid_real_refs["AC18.4.4"]

        assert "AC8.12.7" in result.invalid_stub_refs
        assert (
            "apps/backend/tests/_ac_stubs/test_placeholder.py"
            in result.invalid_stub_refs["AC8.12.7"]
        )

    def test_render_markdown_contains_required_sections(self, tmp_path: Path) -> None:
        self._write_registry(tmp_path)
        self._write_tests(tmp_path)

        result = coverage.analyze_repo(tmp_path)
        report = coverage.render_markdown(
            result,
            generated_at=datetime(2026, 5, 19, 13, 29, 12, tzinfo=timezone.utc),
        )

        assert "Coverage accounting (EPIC-008 aligned)" in report
        assert "Scan scope summary" in report
        assert "Invalid AC references (unregistered)" in report
        assert "`AC18.4.4`" in report
        assert "`AC9.9.9`" in report
        assert "Stub-only AC placeholders (`_ac_stubs`)" in report
        assert "Registered ACs with no real test reference" in report
        assert "EPIC-003 (placeholders) — 1 untested" in report
        assert "EPIC-004 (untested) — 1 untested" in report

    def test_analyze_repo_handles_missing_duplicate_unreadable_and_external_paths(
        self,
        tmp_path: Path,
    ) -> None:
        self._write_registry(tmp_path)
        self._write_tests(tmp_path)

        missing_registry = tmp_path / "docs" / "missing_registry.yaml"
        duplicate_registry = tmp_path / "docs" / "duplicate_registry.yaml"
        extra_ac_id = "AC" + "5.5.5"
        duplicate_registry.write_text(
            f"""
version: '1.0'
total: 2
acs:
  - id: AC1.1.1
    epic: 99
    epic_name: duplicate
    description: should be ignored
  - id: {extra_ac_id}
    epic: 5
    epic_name: extra
    description: extra registry entry
""".strip()
            + "\n",
            encoding="utf-8",
        )

        registry = coverage.load_registry(
            (
                tmp_path / "docs" / "ac_registry.yaml",
                missing_registry,
                duplicate_registry,
            )
        )

        assert registry["AC1.1.1"].epic == 1
        assert registry[extra_ac_id].epic == 5

        external_file = tmp_path.parent / "external_ac_test.py"
        assert coverage._relative(external_file, tmp_path) == str(external_file)

        references, source_real_refs, source_stub_refs = coverage.collect_references(
            [
                coverage.ScanFile(source="backend", path=tmp_path / "missing.py"),
                coverage.ScanFile(source="backend", path=external_file),
            ],
            repo_root=tmp_path,
        )

        assert references == {}
        assert source_real_refs == {}
        assert source_stub_refs == {}


class TestMain:
    def test_main_writes_report_file(self, tmp_path: Path, monkeypatch) -> None:
        docs = tmp_path / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "ac_registry.yaml").write_text(
            "version: '1.0'\ntotal: 1\nacs:\n  - id: AC1.1.1\n    epic: 1\n    epic_name: phase0\n    description: demo\n    mandatory: true\n",
            encoding="utf-8",
        )
        (docs / "infra_registry.yaml").write_text("version: '1.0'\ntotal: 0\nacs: []\n", encoding="utf-8")
        backend = tmp_path / "apps" / "backend" / "tests"
        backend.mkdir(parents=True, exist_ok=True)
        (backend / "test_demo.py").write_text("# AC1.1.1\n", encoding="utf-8")

        output = tmp_path / "docs" / "analysis" / "out.md"

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "analyze_test_ac_coverage.py",
                "--repo-root",
                str(tmp_path),
                "--output",
                str(output),
            ],
        )

        exit_code = coverage.main()

        assert exit_code == 0
        assert output.exists()
        text = output.read_text(encoding="utf-8")
        assert "AC Coverage Analysis Report" in text
        assert "Registered ACs" in text

    def test_main_can_print_report_to_stdout(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys,
    ) -> None:
        docs = tmp_path / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "ac_registry.yaml").write_text(
            "version: '1.0'\ntotal: 1\nacs:\n  - id: AC1.1.1\n    epic: 1\n    epic_name: phase0\n    description: demo\n    mandatory: true\n",
            encoding="utf-8",
        )
        (docs / "infra_registry.yaml").write_text(
            "version: '1.0'\ntotal: 0\nacs: []\n",
            encoding="utf-8",
        )
        backend = tmp_path / "apps" / "backend" / "tests"
        backend.mkdir(parents=True, exist_ok=True)
        (backend / "test_demo.py").write_text("# AC1.1.1\n", encoding="utf-8")

        output = tmp_path / "docs" / "analysis" / "out.md"

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "analyze_test_ac_coverage.py",
                "--repo-root",
                str(tmp_path),
                "--output",
                str(output),
                "--stdout",
            ],
        )

        assert coverage.main() == 0
        captured = capsys.readouterr()
        assert "AC Coverage Analysis Report" in captured.out
        assert "Summary: registered=1" in captured.out
