"""Tests for scripts/calculate_unified_coverage.py.
Covers unified coverage calculation across backend, frontend, and scripts,
including blacklist pattern exclusions and threshold enforcement.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Make scripts importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import calculate_unified_coverage as cuc  # noqa: E402


# ---------------------------------------------------------------------------
# is_test_file
# ---------------------------------------------------------------------------


class TestIsTestFile:
    """AC16.3.2: Blacklist patterns correctly exclude test files."""

    def test_test_prefix_excluded(self):
        assert cuc.is_test_file("test_foo.py") is True

    def test_test_dir_excluded(self):
        assert cuc.is_test_file("apps/backend/tests/test_accounting.py") is True

    def test_double_underscore_tests_excluded(self):
        assert cuc.is_test_file("apps/frontend/src/__tests__/Button.test.tsx") is True

    def test_test_ts_excluded(self):
        assert cuc.is_test_file("apps/frontend/src/Button.test.ts") is True

    def test_spec_ts_excluded(self):
        assert cuc.is_test_file("apps/frontend/src/Button.spec.ts") is True

    def test_spec_tsx_excluded(self):
        assert cuc.is_test_file("apps/frontend/src/Button.spec.tsx") is True

    def test_test_suffix_excluded(self):
        assert cuc.is_test_file("foo_test.py") is True

    def test_conftest_excluded(self):
        assert cuc.is_test_file("apps/backend/conftest.py") is True

    def test_pyproject_excluded(self):
        assert cuc.is_test_file("pyproject.toml") is True

    def test_node_modules_excluded(self):
        assert cuc.is_test_file("apps/frontend/node_modules/lib/index.js") is True

    def test_next_dir_excluded(self):
        assert cuc.is_test_file("apps/frontend/.next/static/main.js") is True

    def test_venv_excluded(self):
        assert cuc.is_test_file("apps/backend/.venv/lib/site.py") is True

    def test_normal_py_included(self):
        assert cuc.is_test_file("apps/backend/src/routers/accounts.py") is False

    def test_normal_ts_included(self):
        assert cuc.is_test_file("apps/frontend/src/lib/api.ts") is False

    def test_normal_tsx_included(self):
        assert cuc.is_test_file("apps/frontend/src/components/Button.tsx") is False

    def test_scripts_py_included(self):
        assert cuc.is_test_file("scripts/calculate_unified_coverage.py") is False

    def test_windows_path_normalised(self):
        # Backslash paths (Windows) should be normalised
        assert cuc.is_test_file("apps\\backend\\tests\\test_foo.py") is True


# ---------------------------------------------------------------------------
# count_lines
# ---------------------------------------------------------------------------


class TestCountLines:
    """Lines in a real file are counted correctly."""

    def test_counts_nonempty_file(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("line1\nline2\nline3\n")
        assert cuc.count_lines(f) == 3

    def test_counts_single_line_no_newline(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("just one line")
        assert cuc.count_lines(f) == 1

    def test_returns_zero_for_missing_file(self, tmp_path):
        assert cuc.count_lines(tmp_path / "nonexistent.py") == 0

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        assert cuc.count_lines(f) == 0


# ---------------------------------------------------------------------------
# count_code_lines
# ---------------------------------------------------------------------------


class TestCountCodeLines:
    """count_code_lines walks a directory and excludes test files."""

    def _write(self, tmp_path, rel, content):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def test_counts_py_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        src = tmp_path / "src"
        self._write(tmp_path, "src/a.py", "line1\nline2\n")
        self._write(tmp_path, "src/b.py", "line1\n")
        result = cuc.count_code_lines(src, [".py"])
        assert result["total_lines"] == 3
        assert result["file_count"] == 2

    def test_excludes_test_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        src = tmp_path / "src"
        self._write(tmp_path, "src/good.py", "a\nb\n")
        self._write(tmp_path, "src/test_bad.py", "x\ny\n")
        result = cuc.count_code_lines(src, [".py"])
        assert result["file_count"] == 1
        assert result["total_lines"] == 2

    def test_excludes_tests_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        src = tmp_path / "src"
        self._write(tmp_path, "src/good.py", "a\n")
        self._write(tmp_path, "src/tests/test_something.py", "b\n")
        result = cuc.count_code_lines(src, [".py"])
        assert result["file_count"] == 1

    def test_multiple_extensions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        src = tmp_path / "src"
        self._write(tmp_path, "src/a.ts", "ts line\n")
        self._write(tmp_path, "src/b.tsx", "tsx line\n")
        result = cuc.count_code_lines(src, [".ts", ".tsx"])
        assert result["file_count"] == 2
        assert result["total_lines"] == 2

    def test_empty_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        src = tmp_path / "empty_src"
        src.mkdir()
        result = cuc.count_code_lines(src, [".py"])
        assert result["total_lines"] == 0
        assert result["file_count"] == 0


# ---------------------------------------------------------------------------
# parse_lcov_file
# ---------------------------------------------------------------------------

SAMPLE_LCOV = """\
SF:apps/backend/src/routers/accounts.py
DA:1,1
DA:2,0
DA:3,5
LH:2
LF:3
end_of_record
SF:apps/backend/src/services/accounting.py
DA:10,3
DA:11,3
LH:2
LF:2
end_of_record
"""


class TestParseLcovFile:
    """LCOV parsing returns correct covered/total line counts."""

    def test_parses_two_files(self, tmp_path):
        f = tmp_path / "cov.lcov"
        f.write_text(SAMPLE_LCOV)
        result = cuc.parse_lcov_file(f)
        assert result["covered_lines"] == 4  # LH:2 + LH:2
        assert result["total_measured_lines"] == 5  # LF:3 + LF:2

    def test_missing_file_returns_zeros(self, tmp_path):
        result = cuc.parse_lcov_file(tmp_path / "no.lcov")
        assert result["covered_lines"] == 0
        assert result["total_measured_lines"] == 0

    def test_empty_lcov(self, tmp_path):
        f = tmp_path / "empty.lcov"
        f.write_text("")
        result = cuc.parse_lcov_file(f)
        assert result["covered_lines"] == 0
        assert result["total_measured_lines"] == 0

    def test_last_record_without_end_of_record(self, tmp_path):
        content = "SF:foo.py\nDA:1,1\nLH:1\nLF:1\n"
        f = tmp_path / "partial.lcov"
        f.write_text(content)
        result = cuc.parse_lcov_file(f)
        # Last record (no end_of_record) should still be counted
        assert result["covered_lines"] == 1
        assert result["total_measured_lines"] == 1

    def test_multiple_files_accumulated(self, tmp_path):
        lcov = """\
SF:a.py
LH:10
LF:20
end_of_record
SF:b.py
LH:5
LF:10
end_of_record
"""
        f = tmp_path / "multi.lcov"
        f.write_text(lcov)
        result = cuc.parse_lcov_file(f)
        assert result["covered_lines"] == 15
        assert result["total_measured_lines"] == 30


# ---------------------------------------------------------------------------
# calculate_unified_coverage
# ---------------------------------------------------------------------------


class TestCalculateUnifiedCoverage:
    """Unified aggregation combines backend + frontend + scripts correctly."""

    def _make(self, total, covered):
        return {"total_lines": total, "covered_lines": covered, "coverage_percent": 0}

    def test_sums_correctly(self):
        b = self._make(1000, 500)
        fe = self._make(500, 100)
        s = self._make(200, 80)
        result = cuc.calculate_unified_coverage(b, fe, s)
        assert result["total_lines"] == 1700
        assert result["covered_lines"] == 680

    def test_coverage_percent_rounded(self):
        b = self._make(100, 30)
        fe = self._make(0, 0)
        s = self._make(0, 0)
        result = cuc.calculate_unified_coverage(b, fe, s)
        assert result["coverage_percent"] == 30.0

    def test_zero_total_no_division_error(self):
        result = cuc.calculate_unified_coverage(
            self._make(0, 0), self._make(0, 0), self._make(0, 0)
        )
        assert result["coverage_percent"] == 0

    def test_breakdown_included(self):
        b = self._make(10, 5)
        fe = self._make(10, 5)
        s = self._make(10, 5)
        result = cuc.calculate_unified_coverage(b, fe, s)
        assert "breakdown" in result
        assert result["breakdown"]["backend"] is b
        assert result["breakdown"]["frontend"] is fe
        assert result["breakdown"]["scripts"] is s

    def test_coverage_close_to_30_pct(self):
        # Simulate production-like scenario: ~30% coverage
        b = self._make(15275, 5806)
        fe = self._make(7150, 0)
        s = self._make(5879, 2500)
        result = cuc.calculate_unified_coverage(b, fe, s)
        assert result["coverage_percent"] >= 29.0


# ---------------------------------------------------------------------------
# get_scripts_coverage — path resolution
# ---------------------------------------------------------------------------


class TestGetScriptsCoverage:
    """get_scripts_coverage checks both local and CI paths."""

    def test_uses_ci_path_when_present(self, tmp_path, monkeypatch):
        # Set up CI path: coverage/scripts.lcov
        cov_dir = tmp_path / "coverage"
        cov_dir.mkdir()
        lcov = cov_dir / "scripts.lcov"
        lcov.write_text("SF:scripts/foo.py\nLH:5\nLF:10\nend_of_record\n")

        # Point ROOT_DIR and SCRIPTS_DIR to tmp
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "foo.py").write_text("a\n" * 10)
        monkeypatch.setattr(cuc, "SCRIPTS_DIR", scripts_dir)

        result = cuc.get_scripts_coverage()
        assert result["covered_lines"] == 5

    def test_uses_root_fallback_when_no_ci_path(self, tmp_path, monkeypatch):
        # Only root-level coverage-scripts.lcov exists
        lcov = tmp_path / "coverage-scripts.lcov"
        lcov.write_text("SF:scripts/bar.py\nLH:3\nLF:6\nend_of_record\n")

        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "bar.py").write_text("b\n" * 6)
        monkeypatch.setattr(cuc, "SCRIPTS_DIR", scripts_dir)

        result = cuc.get_scripts_coverage()
        assert result["covered_lines"] == 3

    def test_returns_zero_when_no_lcov(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        monkeypatch.setattr(cuc, "SCRIPTS_DIR", scripts_dir)

        result = cuc.get_scripts_coverage()
        assert result["covered_lines"] == 0


# ---------------------------------------------------------------------------
# main() — integration smoke test
# ---------------------------------------------------------------------------


class TestMain:
    """main() writes unified-coverage.json and exits with correct code."""

    def _fake_coverage(self, total, covered):
        pct = round(covered / max(total, 1) * 100, 2)
        return {"total_lines": total, "covered_lines": covered, "coverage_percent": pct}

    def test_main_exits_zero_when_above_threshold(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        monkeypatch.setenv("COVERAGE_THRESHOLD", "10")
        monkeypatch.setattr(
            cuc, "get_backend_coverage", lambda: self._fake_coverage(100, 50)
        )
        monkeypatch.setattr(
            cuc, "get_frontend_coverage", lambda: self._fake_coverage(100, 50)
        )
        monkeypatch.setattr(
            cuc, "get_scripts_coverage", lambda: self._fake_coverage(100, 50)
        )

        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 0
        assert (tmp_path / "unified-coverage.json").exists()

    def test_main_exits_one_when_below_threshold(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        monkeypatch.setenv("COVERAGE_THRESHOLD", "90")
        monkeypatch.setattr(
            cuc, "get_backend_coverage", lambda: self._fake_coverage(100, 10)
        )
        monkeypatch.setattr(
            cuc, "get_frontend_coverage", lambda: self._fake_coverage(100, 10)
        )
        monkeypatch.setattr(
            cuc, "get_scripts_coverage", lambda: self._fake_coverage(100, 10)
        )

        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 1

    def test_main_writes_valid_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setattr(
            cuc, "get_backend_coverage", lambda: self._fake_coverage(50, 40)
        )
        monkeypatch.setattr(
            cuc, "get_frontend_coverage", lambda: self._fake_coverage(50, 40)
        )
        monkeypatch.setattr(
            cuc, "get_scripts_coverage", lambda: self._fake_coverage(50, 40)
        )

        with pytest.raises(SystemExit):
            cuc.main()

        data = json.loads((tmp_path / "unified-coverage.json").read_text())
        assert "total_lines" in data
        assert "covered_lines" in data
        assert "coverage_percent" in data
        assert "breakdown" in data

# ---------------------------------------------------------------------------
# Baseline comparison — compares current run against historical baseline
# ---------------------------------------------------------------------------


class TestBaselineComparison:
    """AC16.4: Baseline comparison enforces minimum coverage improvement."""

    def test_passes_when_coverage_equals_baseline(self, tmp_path, monkeypatch):
        """When current coverage equals baseline, expect exit 0."""
        # Setup baseline file
        baseline_file = tmp_path / "baseline.json"
        baseline_data = {
            "coverage_percent": 83.15,
            "total_lines": 10000,
            "covered_lines": 8315,
            "breakdown": {
                "backend": {"total_lines": 5000, "covered_lines": 4700, "coverage_percent": 94.0},
                "frontend": {"total_lines": 3000, "covered_lines": 2494, "coverage_percent": 83.13},
                "scripts": {"total_lines": 2000, "covered_lines": 1662, "coverage_percent": 83.10}
            }
        }
        baseline_file.write_text(json.dumps(baseline_data))

        # Set up environment
        monkeypatch.setenv("BASELINE_FILE", str(baseline_file))
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)

        # Mock all coverage functions to return same as baseline
        def mock_coverage(name):
            return baseline_data["breakdown"][name]

        monkeypatch.setattr(cuc, "get_backend_coverage", lambda: mock_coverage("backend"))
        monkeypatch.setattr(cuc, "get_frontend_coverage", lambda: mock_coverage("frontend"))
        monkeypatch.setattr(cuc, "get_scripts_coverage", lambda: mock_coverage("scripts"))

        # Should exit 0 (no regression)
        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 0

    def test_fails_when_unified_drops_below_baseline(self, tmp_path, monkeypatch, capfd):
        """When unified coverage drops below baseline, expect exit 1 with message."""
        # Setup baseline file
        baseline_file = tmp_path / "baseline.json"
        baseline_data = {
            "coverage_percent": 83.15,
            "total_lines": 10000,
            "covered_lines": 8315,
            "breakdown": {
                "backend": {"total_lines": 5000, "covered_lines": 4700, "coverage_percent": 94.0},
                "frontend": {"total_lines": 3000, "covered_lines": 2494, "coverage_percent": 83.13},
                "scripts": {"total_lines": 2000, "covered_lines": 1662, "coverage_percent": 83.10}
            }
        }
        baseline_file.write_text(json.dumps(baseline_data))

        # Set up environment
        monkeypatch.setenv("BASELINE_FILE", str(baseline_file))
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)

        # Mock unified coverage to drop (82.0% < 83.15%)
        current_data = {
            "coverage_percent": 82.0,
            "total_lines": 10000,
            "covered_lines": 8200,
            "breakdown": {
                "backend": {"total_lines": 5000, "covered_lines": 4500, "coverage_percent": 90.0},
                "frontend": {"total_lines": 3000, "covered_lines": 2400, "coverage_percent": 80.0},
                "scripts": {"total_lines": 2000, "covered_lines": 1300, "coverage_percent": 65.0}
            }
        }

        def mock_coverage(name):
            return current_data["breakdown"][name]

        monkeypatch.setattr(cuc, "get_backend_coverage", lambda: mock_coverage("backend"))
        monkeypatch.setattr(cuc, "get_frontend_coverage", lambda: mock_coverage("frontend"))
        monkeypatch.setattr(cuc, "get_scripts_coverage", lambda: mock_coverage("scripts"))

        # Should exit 1 with message containing both values
        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 1
        # Check stderr contains both baseline and current values
        captured = capfd.readouterr()
        assert "82.0" in captured.err
        assert "83.15" in captured.err

    def test_fails_when_backend_drops_despite_unified_ok(self, tmp_path, monkeypatch):
        """When backend drops significantly despite unified staying ok, expect exit 1."""
        # Setup baseline file
        baseline_file = tmp_path / "baseline.json"
        baseline_data = {
            "coverage_percent": 83.15,
            "total_lines": 10000,
            "covered_lines": 8315,
            "breakdown": {
                "backend": {"total_lines": 5000, "covered_lines": 4700, "coverage_percent": 94.0},
                "frontend": {"total_lines": 3000, "covered_lines": 2494, "coverage_percent": 83.13},
                "scripts": {"total_lines": 2000, "covered_lines": 1662, "coverage_percent": 83.10}
            }
        }
        baseline_file.write_text(json.dumps(baseline_data))

        monkeypatch.setenv("BASELINE_FILE", str(baseline_file))
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)

        # Mock: backend drops 94.0% → 90.0%, unified stays 83.15%
        def mock_backend():
            return {"total_lines": 5000, "covered_lines": 4500, "coverage_percent": 90.0}

        def mock_frontend():
            return {"total_lines": 3000, "covered_lines": 2494, "coverage_percent": 83.13}

        def mock_scripts():
            return {"total_lines": 2000, "covered_lines": 1662, "coverage_percent": 83.10}

        monkeypatch.setattr(cuc, "get_backend_coverage", mock_backend)
        monkeypatch.setattr(cuc, "get_frontend_coverage", mock_frontend)
        monkeypatch.setattr(cuc, "get_scripts_coverage", mock_scripts)

        # Should exit 1 due to backend regression
        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 1

    def test_fails_when_frontend_drops(self, tmp_path, monkeypatch):
        """When frontend drops significantly, expect exit 1."""
        baseline_file = tmp_path / "baseline.json"
        baseline_data = {
            "coverage_percent": 83.15,
            "total_lines": 10000,
            "covered_lines": 8315,
            "breakdown": {
                "backend": {"total_lines": 5000, "covered_lines": 4159, "coverage_percent": 83.18},
                "frontend": {"total_lines": 3000, "covered_lines": 2494, "coverage_percent": 83.13},
                "scripts": {"total_lines": 2000, "covered_lines": 1662, "coverage_percent": 83.10}
            }
        }
        baseline_file.write_text(json.dumps(baseline_data))

        monkeypatch.setenv("BASELINE_FILE", str(baseline_file))
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)

        # Frontend drops 61.77% → 60.0%
        def mock_backend():
            return {"total_lines": 5000, "covered_lines": 4159, "coverage_percent": 83.18}

        def mock_frontend():
            return {"total_lines": 3000, "covered_lines": 1800, "coverage_percent": 60.0}

        def mock_scripts():
            return {"total_lines": 2000, "covered_lines": 1662, "coverage_percent": 83.10}

        monkeypatch.setattr(cuc, "get_backend_coverage", mock_backend)
        monkeypatch.setattr(cuc, "get_frontend_coverage", mock_frontend)
        monkeypatch.setattr(cuc, "get_scripts_coverage", mock_scripts)

        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 1

    def test_fails_when_scripts_drops(self, tmp_path, monkeypatch):
        """When scripts drops significantly, expect exit 1."""
        baseline_file = tmp_path / "baseline.json"
        baseline_data = {
            "coverage_percent": 83.15,
            "total_lines": 10000,
            "covered_lines": 8315,
            "breakdown": {
                "backend": {"total_lines": 5000, "covered_lines": 4159, "coverage_percent": 83.18},
                "frontend": {"total_lines": 3000, "covered_lines": 2494, "coverage_percent": 83.13},
                "scripts": {"total_lines": 2000, "covered_lines": 1662, "coverage_percent": 83.10}
            }
        }
        baseline_file.write_text(json.dumps(baseline_data))

        monkeypatch.setenv("BASELINE_FILE", str(baseline_file))
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)

        # Scripts drops 68.02% → 65.0%
        def mock_backend():
            return {"total_lines": 5000, "covered_lines": 4159, "coverage_percent": 83.18}

        def mock_frontend():
            return {"total_lines": 3000, "covered_lines": 2494, "coverage_percent": 83.13}

        def mock_scripts():
            return {"total_lines": 2000, "covered_lines": 1300, "coverage_percent": 65.0}

        monkeypatch.setattr(cuc, "get_backend_coverage", mock_backend)
        monkeypatch.setattr(cuc, "get_frontend_coverage", mock_frontend)
        monkeypatch.setattr(cuc, "get_scripts_coverage", mock_scripts)

        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 1

    def test_passes_when_all_components_improve(self, tmp_path, monkeypatch):
        """When all components improve, expect exit 0 (no regression)."""
        baseline_file = tmp_path / "baseline.json"
        baseline_data = {
            "coverage_percent": 80.0,
            "total_lines": 10000,
            "covered_lines": 8000,
            "breakdown": {
                "backend": {"total_lines": 5000, "covered_lines": 4000, "coverage_percent": 80.0},
                "frontend": {"total_lines": 3000, "covered_lines": 2400, "coverage_percent": 80.0},
                "scripts": {"total_lines": 2000, "covered_lines": 1600, "coverage_percent": 80.0}
            }
        }
        baseline_file.write_text(json.dumps(baseline_data))

        monkeypatch.setenv("BASELINE_FILE", str(baseline_file))
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)

        # All components improve
        def mock_backend():
            return {"total_lines": 5000, "covered_lines": 4500, "coverage_percent": 90.0}

        def mock_frontend():
            return {"total_lines": 3000, "covered_lines": 2700, "coverage_percent": 90.0}

        def mock_scripts():
            return {"total_lines": 2000, "covered_lines": 1800, "coverage_percent": 90.0}

        monkeypatch.setattr(cuc, "get_backend_coverage", mock_backend)
        monkeypatch.setattr(cuc, "get_frontend_coverage", mock_frontend)
        monkeypatch.setattr(cuc, "get_scripts_coverage", mock_scripts)

        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 0

    def test_skips_baseline_check_when_file_missing(self, tmp_path, monkeypatch):
        """When baseline file doesn't exist, should fall through to threshold check only."""
        # No baseline file exists
        (tmp_path / "baseline.json").unlink(missing_ok=True)

        monkeypatch.setenv("BASELINE_FILE", "")
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)

        def mock_coverage(name):
            return {"total_lines": 1000, "covered_lines": 800, "coverage_percent": 80.0}

        monkeypatch.setattr(cuc, "get_backend_coverage", lambda: mock_coverage("backend"))
        monkeypatch.setattr(cuc, "get_frontend_coverage", lambda: mock_coverage("frontend"))
        monkeypatch.setattr(cuc, "get_scripts_coverage", lambda: mock_coverage("scripts"))

        # Should exit 0 (threshold check passes, baseline check is skipped)
        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 0

    def test_baseline_file_path_configurable(self, tmp_path, monkeypatch):
        """Verify BASELINE_FILE env var controls which file is read."""
        # Create multiple baseline files
        baseline_file1 = tmp_path / "baseline.json"
        baseline_file2 = tmp_path / "old-baseline.json"

        baseline_file1.write_text(json.dumps({
            "coverage_percent": 83.15,
            "total_lines": 10000,
            "covered_lines": 8315,
            "breakdown": {
                "backend": {"total_lines": 5000, "covered_lines": 4159, "coverage_percent": 83.18},
                "frontend": {"total_lines": 3000, "covered_lines": 2494, "coverage_percent": 83.13},
                "scripts": {"total_lines": 2000, "covered_lines": 1662, "coverage_percent": 83.10}
            }
        }))

        baseline_data1 = json.loads(baseline_file1.read_text())

        baseline_file2.write_text(json.dumps({
            "coverage_percent": 85.0,
            "total_lines": 10000,
            "covered_lines": 8500,
            "breakdown": {
                "backend": {"total_lines": 5000, "covered_lines": 4250, "coverage_percent": 85.0},
                "frontend": {"total_lines": 3000, "covered_lines": 2550, "coverage_percent": 85.0},
                "scripts": {"total_lines": 2000, "covered_lines": 1700, "coverage_percent": 85.0}
            }
        }))

        baseline_data2 = json.loads(baseline_file2.read_text())

        # Use baseline_file1
        monkeypatch.setenv("BASELINE_FILE", str(baseline_file1))
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)

        def mock_coverage(name):
            return baseline_data1["breakdown"][name]

        monkeypatch.setattr(cuc, "get_backend_coverage", lambda: mock_coverage("backend"))
        monkeypatch.setattr(cuc, "get_frontend_coverage", lambda: mock_coverage("frontend"))
        monkeypatch.setattr(cuc, "get_scripts_coverage", lambda: mock_coverage("scripts"))

        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 0  # Passes since current matches baseline_file1

        # Now use baseline_file2
        monkeypatch.setenv("BASELINE_FILE", str(baseline_file2))

        def mock_coverage2():
            return baseline_data2["breakdown"]["backend"]

        monkeypatch.setattr(cuc, "get_backend_coverage", mock_coverage2)
        monkeypatch.setattr(cuc, "get_frontend_coverage", mock_coverage2)
        monkeypatch.setattr(cuc, "get_scripts_coverage", mock_coverage2)

        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 0  # New run is better than old baseline


# ---------------------------------------------------------------------------
# parse_lcov_file — ValueError branches (lines 132-133, 138-139)
# ---------------------------------------------------------------------------


class TestParseLcovFileValueError:
    """Coverage for ValueError-handling in LH: and LF: parsing."""

    def test_invalid_lh_value_is_skipped(self, tmp_path):
        """LH: with non-integer value should not crash; covered stays 0."""
        content = "SF:foo.py\nLH:bad\nLF:5\nend_of_record\n"
        f = tmp_path / "bad_lh.lcov"
        f.write_text(content)
        result = cuc.parse_lcov_file(f)
        # LH parsing failed → covered stays 0; LF:5 still counted
        assert result["covered_lines"] == 0
        assert result["total_measured_lines"] == 5

    def test_invalid_lf_value_is_skipped(self, tmp_path):
        """LF: with non-integer value should not crash; total stays 0."""
        content = "SF:foo.py\nLH:3\nLF:oops\nend_of_record\n"
        f = tmp_path / "bad_lf.lcov"
        f.write_text(content)
        result = cuc.parse_lcov_file(f)
        # LF parsing failed → total stays 0; end_of_record fires but total stays 0
        assert result["total_measured_lines"] == 0


# ---------------------------------------------------------------------------
# get_backend_coverage / get_frontend_coverage — path resolution (lines 160-183)
# ---------------------------------------------------------------------------


class TestGetBackendCoverage:
    """get_backend_coverage picks CI path over local path when both exist."""

    def test_uses_ci_path_when_present(self, tmp_path, monkeypatch):
        # Create CI path: coverage/backend.lcov
        cov_dir = tmp_path / "coverage"
        cov_dir.mkdir()
        lcov = cov_dir / "backend.lcov"
        lcov.write_text("SF:apps/backend/src/main.py\nLH:10\nLF:20\nend_of_record\n")

        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        monkeypatch.setattr(cuc, "BACKEND_DIR", tmp_path / "apps" / "backend")
        # Create src dir so count_code_lines doesn't error
        (tmp_path / "apps" / "backend" / "src").mkdir(parents=True)
        (tmp_path / "apps" / "backend" / "src" / "main.py").write_text("a\n" * 20)

        result = cuc.get_backend_coverage()
        assert result["covered_lines"] == 10
        assert result["total_lines"] == 20

    def test_uses_local_path_when_no_ci_path(self, tmp_path, monkeypatch):
        # Create local path: apps/backend/coverage.lcov
        backend_dir = tmp_path / "apps" / "backend"
        backend_dir.mkdir(parents=True)
        lcov = backend_dir / "coverage.lcov"
        lcov.write_text("SF:src/main.py\nLH:7\nLF:14\nend_of_record\n")

        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        monkeypatch.setattr(cuc, "BACKEND_DIR", backend_dir)
        (backend_dir / "src").mkdir()
        (backend_dir / "src" / "main.py").write_text("b\n" * 14)

        result = cuc.get_backend_coverage()
        assert result["covered_lines"] == 7


class TestGetFrontendCoverage:
    """get_frontend_coverage picks CI path over local path when both exist."""

    def test_uses_ci_path_when_present(self, tmp_path, monkeypatch):
        cov_dir = tmp_path / "coverage"
        cov_dir.mkdir()
        lcov = cov_dir / "frontend.lcov"
        lcov.write_text("SF:apps/frontend/src/app.ts\nLH:6\nLF:12\nend_of_record\n")

        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        monkeypatch.setattr(cuc, "FRONTEND_DIR", tmp_path / "apps" / "frontend")
        (tmp_path / "apps" / "frontend" / "src").mkdir(parents=True)
        (tmp_path / "apps" / "frontend" / "src" / "app.ts").write_text("c\n" * 12)

        result = cuc.get_frontend_coverage()
        assert result["covered_lines"] == 6
        assert result["total_lines"] == 12

    def test_uses_local_path_when_no_ci_path(self, tmp_path, monkeypatch):
        frontend_dir = tmp_path / "apps" / "frontend"
        lcov_dir = frontend_dir / "coverage"
        lcov_dir.mkdir(parents=True)
        lcov = lcov_dir / "lcov.info"
        lcov.write_text("SF:src/foo.ts\nLH:4\nLF:8\nend_of_record\n")

        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        monkeypatch.setattr(cuc, "FRONTEND_DIR", frontend_dir)
        (frontend_dir / "src").mkdir(parents=True, exist_ok=True)
        (frontend_dir / "src" / "foo.ts").write_text("d\n" * 8)

        result = cuc.get_frontend_coverage()
        assert result["covered_lines"] == 4


# ---------------------------------------------------------------------------
# main() — exception paths in baseline loading (lines 293-300)
# ---------------------------------------------------------------------------


class TestMainBaselineExceptionPaths:
    """Cover the except clauses in main() baseline comparison."""

    def _mock_coverage(self, monkeypatch):
        cov = {"total_lines": 100, "covered_lines": 80, "coverage_percent": 80.0}
        monkeypatch.setattr(cuc, "get_backend_coverage", lambda: cov)
        monkeypatch.setattr(cuc, "get_frontend_coverage", lambda: cov)
        monkeypatch.setattr(cuc, "get_scripts_coverage", lambda: cov)

    def test_json_decode_error_falls_through(self, tmp_path, monkeypatch, capsys):
        """When baseline file is not valid JSON, should warn and continue."""
        baseline = tmp_path / "bad.json"
        baseline.write_text("not valid json {{")
        monkeypatch.setenv("BASELINE_FILE", str(baseline))
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        self._mock_coverage(monkeypatch)

        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 0  # Falls through to threshold check
        captured = capsys.readouterr()
        assert "Invalid baseline" in captured.err

    def test_generic_exception_falls_through(self, tmp_path, monkeypatch, capsys):
        """When baseline reading raises an unexpected Exception, should warn and continue."""
        baseline = tmp_path / "baseline.json"
        baseline.write_text('{"coverage_percent": 50}')
        monkeypatch.setenv("BASELINE_FILE", str(baseline))
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        self._mock_coverage(monkeypatch)

        # Patch json.load to raise a generic Exception
        import json as _json
        original_load = _json.load

        def raiser(f):
            raise RuntimeError("disk read error")

        monkeypatch.setattr(_json, "load", raiser)

        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Error reading baseline" in captured.err

    def test_file_not_found_falls_through(self, tmp_path, monkeypatch, capsys):
        """When baseline file doesn't exist, should warn and continue."""
        monkeypatch.setenv("BASELINE_FILE", str(tmp_path / "no_baseline.json"))
        monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
        monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
        self._mock_coverage(monkeypatch)

        with pytest.raises(SystemExit) as exc:
            cuc.main()
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "Baseline file not found" in captured.err


# ---------------------------------------------------------------------------
# __main__ entry point (line 327)
# ---------------------------------------------------------------------------


def test_module_main_entry_point(tmp_path, monkeypatch):
    """Cover line 327: __main__ calls main()."""
    cov = {"total_lines": 100, "covered_lines": 90, "coverage_percent": 90.0}
    monkeypatch.setattr(cuc, "ROOT_DIR", tmp_path)
    monkeypatch.setenv("COVERAGE_THRESHOLD", "0")
    monkeypatch.setenv("BASELINE_FILE", "")
    monkeypatch.setattr(cuc, "get_backend_coverage", lambda: cov)
    monkeypatch.setattr(cuc, "get_frontend_coverage", lambda: cov)
    monkeypatch.setattr(cuc, "get_scripts_coverage", lambda: cov)

    # Simulate 'if __name__ == "__main__"' by calling main() directly
    with pytest.raises(SystemExit) as exc:
        cuc.main()
    assert exc.value.code == 0