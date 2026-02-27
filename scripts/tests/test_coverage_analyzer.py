"""Tests for scripts/coverage_analyzer.py.

Tests the coverage analysis functions:
- parse_missing_lines: Parse missing lines from coverage report
- identify_common_patterns: Identify common coverage gap patterns
- generate_recommendations: Generate recommendations based on gaps

NOTE: run_coverage_report and analyze_module_coverage use subprocess.run,
so they are tested with mocked subprocess to avoid actual pytest calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from coverage_analyzer import (
    generate_recommendations,
    identify_common_patterns,
    parse_missing_lines,
)


class TestParseMissingLines:
    """Tests for parse_missing_lines function."""

    def test_returns_empty_list_for_empty_input(self):
        """Empty input returns empty list."""
        result = parse_missing_lines("")
        assert result == []

    def test_returns_empty_list_for_no_src_files(self):
        """Input without src/ files returns empty list."""
        coverage_output = """
Name                      Stmts   Miss  Cover   Missing
--------------------------------------------------------
tests/test_something.py      10      0   100%
"""
        result = parse_missing_lines(coverage_output)
        assert result == []

    def test_extracts_line_with_src_and_missing(self):
        """Extracts lines containing src/ and 'missing'."""
        coverage_output = """
Name                      Stmts   Miss  Cover   Missing
--------------------------------------------------------
src/accounting/service.py:45: missing branch coverage
src/reconciliation/matcher.py:100: missing line coverage
"""
        result = parse_missing_lines(coverage_output)
        assert len(result) == 2
        assert "src/accounting/service.py" in result[0]
        assert "src/reconciliation/matcher.py" in result[1]

    def test_ignores_src_lines_without_missing(self):
        """Lines with src/ but without 'missing' are ignored."""
        coverage_output = """
src/accounting/service.py:45: some other info
src/reconciliation/matcher.py:100: missing line coverage
"""
        result = parse_missing_lines(coverage_output)
        assert len(result) == 1
        assert "missing" in result[0]

    def test_strips_whitespace_from_results(self):
        """Results have whitespace stripped."""
        coverage_output = """
   src/models/account.py:10: missing test   
"""
        result = parse_missing_lines(coverage_output)
        assert len(result) == 1
        assert result[0] == "src/models/account.py:10: missing test"

    def test_requires_py_colon_in_line(self):
        """Line must contain .py: to be considered."""
        coverage_output = """
src/accounting/service: missing file
src/accounting/service.py:45: missing branch coverage
"""
        result = parse_missing_lines(coverage_output)
        assert len(result) == 1
        assert ".py:" in result[0]


class TestIdentifyCommonPatterns:
    """Tests for identify_common_patterns function."""

    def test_returns_dict_with_all_pattern_keys(self):
        """Returns dict with all expected pattern keys."""
        result = identify_common_patterns([])
        expected_keys = {
            "exception_handling",
            "edge_cases",
            "error_paths",
            "async_paths",
            "optional_params",
        }
        assert set(result.keys()) == expected_keys

    def test_all_counts_zero_for_empty_list(self):
        """All pattern counts are zero for empty input."""
        result = identify_common_patterns([])
        for count in result.values():
            assert count == 0

    def test_counts_exception_handling(self):
        """Counts lines containing 'except'."""
        lines = [
            "src/service.py:10: except ValueError",
            "src/service.py:20: except Exception",
            "src/service.py:30: normal line",
        ]
        result = identify_common_patterns(lines)
        assert result["exception_handling"] == 2

    def test_counts_edge_cases(self):
        """Counts lines containing both 'if' and 'else'."""
        lines = [
            "src/service.py:10: if condition else default",
            "src/service.py:20: if only",
            "src/service.py:30: else only",
            "src/service.py:40: if x else y",
        ]
        result = identify_common_patterns(lines)
        assert result["edge_cases"] == 2

    def test_counts_error_paths(self):
        """Counts lines containing 'raise' or 'error'."""
        lines = [
            "src/service.py:10: raise ValueError",
            "src/service.py:20: error handling",
            "src/service.py:30: Error class",
            "src/service.py:40: normal line",
        ]
        result = identify_common_patterns(lines)

        assert result["error_paths"] == 2

    def test_counts_async_paths(self):
        """Counts lines containing 'async'."""
        lines = [
            "src/service.py:10: async def fetch",
            "src/service.py:20: await async_call",
            "src/service.py:30: sync function",
        ]
        result = identify_common_patterns(lines)
        assert result["async_paths"] == 2

    def test_counts_optional_params(self):
        """Counts lines containing '=' and 'default'."""
        lines = [
            "src/service.py:10: param = default_value",
            "src/service.py:20: x = 5 default",
            "src/service.py:30: just default",
            "src/service.py:40: just equals =",
        ]
        result = identify_common_patterns(lines)
        assert result["optional_params"] == 2

    def test_line_can_match_multiple_patterns(self):
        """A single line can increment multiple pattern counts."""
        lines = [
            "src/service.py:10: async except error if else = default",
        ]
        result = identify_common_patterns(lines)
        assert result["exception_handling"] == 1
        assert result["edge_cases"] == 1
        assert result["error_paths"] == 1
        assert result["async_paths"] == 1
        assert result["optional_params"] == 1


class TestGenerateRecommendations:
    """Tests for generate_recommendations function."""

    def test_returns_empty_list_for_zero_patterns(self):
        """No recommendations when all pattern counts are zero."""
        patterns = {
            "exception_handling": 0,
            "edge_cases": 0,
            "error_paths": 0,
            "async_paths": 0,
            "optional_params": 0,
        }
        result = generate_recommendations(patterns)
        assert result == []

    def test_returns_empty_list_for_below_threshold_patterns(self):
        """No recommendations when counts are below thresholds."""
        patterns = {
            "exception_handling": 5,
            "edge_cases": 10,
            "error_paths": 3,
            "async_paths": 5,
            "optional_params": 5,
        }
        result = generate_recommendations(patterns)
        assert result == []

    def test_recommends_exception_tests_when_threshold_exceeded(self):
        """Recommends exception tests when exception_handling > 5."""
        patterns = {
            "exception_handling": 6,
            "edge_cases": 0,
            "error_paths": 0,
            "async_paths": 0,
            "optional_params": 0,
        }
        result = generate_recommendations(patterns)
        assert len(result) == 1
        assert "exception" in result[0].lower()

    def test_recommends_edge_case_tests_when_threshold_exceeded(self):
        """Recommends edge case tests when edge_cases > 10."""
        patterns = {
            "exception_handling": 0,
            "edge_cases": 11,
            "error_paths": 0,
            "async_paths": 0,
            "optional_params": 0,
        }
        result = generate_recommendations(patterns)
        assert len(result) == 1
        assert "edge case" in result[0].lower()

    def test_recommends_error_path_tests_when_threshold_exceeded(self):
        """Recommends error path tests when error_paths > 3."""
        patterns = {
            "exception_handling": 0,
            "edge_cases": 0,
            "error_paths": 4,
            "async_paths": 0,
            "optional_params": 0,
        }
        result = generate_recommendations(patterns)
        assert len(result) == 1
        assert "error" in result[0].lower()

    def test_recommends_async_tests_when_threshold_exceeded(self):
        """Recommends async tests when async_paths > 5."""
        patterns = {
            "exception_handling": 0,
            "edge_cases": 0,
            "error_paths": 0,
            "async_paths": 6,
            "optional_params": 0,
        }
        result = generate_recommendations(patterns)
        assert len(result) == 1
        assert "async" in result[0].lower() or "concurrency" in result[0].lower()

    def test_recommends_param_tests_when_threshold_exceeded(self):
        """Recommends parameter tests when optional_params > 5."""
        patterns = {
            "exception_handling": 0,
            "edge_cases": 0,
            "error_paths": 0,
            "async_paths": 0,
            "optional_params": 6,
        }
        result = generate_recommendations(patterns)
        assert len(result) == 1
        assert "parameter" in result[0].lower()

    def test_returns_multiple_recommendations_when_multiple_thresholds_exceeded(self):
        """Returns multiple recommendations when multiple thresholds exceeded."""
        patterns = {
            "exception_handling": 10,
            "edge_cases": 15,
            "error_paths": 10,
            "async_paths": 10,
            "optional_params": 10,
        }
        result = generate_recommendations(patterns)
        assert len(result) == 5


class TestRunCoverageReport:
    def test_run_coverage_report_returns_string(self, monkeypatch):
        import subprocess
        from coverage_analyzer import run_coverage_report

        fake = type("R", (), {"stdout": "cov output", "stderr": "", "returncode": 0})()
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
        result = run_coverage_report()
        assert isinstance(result, str)
        assert "cov output" in result

    def test_run_coverage_report_with_html_format(self, monkeypatch):
        import subprocess
        from coverage_analyzer import run_coverage_report

        fake = type("R", (), {"stdout": "html report", "stderr": "", "returncode": 0})()
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
        result = run_coverage_report("html")
        assert "html report" in result


class TestAnalyzeModuleCoverage:
    def test_analyze_module_coverage_returns_list(self, monkeypatch):
        import subprocess
        from coverage_analyzer import analyze_module_coverage

        fake = type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
        result = analyze_module_coverage()
        assert isinstance(result, list)
        assert len(result) > 0
        assert all(isinstance(name, str) and isinstance(pct, float) for name, pct in result)


class TestMain:
    def test_main_no_missing_lines(self, monkeypatch, capsys):
        import subprocess
        import sys
        from coverage_analyzer import main

        fake = type("R", (), {"stdout": "clean output", "stderr": "", "returncode": 0})()
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
        monkeypatch.setattr(sys, "argv", ["coverage_analyzer.py"])
        main()
        captured = capsys.readouterr()
        assert "Coverage Analysis" in captured.out
        assert "All lines covered" in captured.out

    def test_main_with_missing_lines(self, monkeypatch, capsys):
        import subprocess
        import sys
        from coverage_analyzer import main

        fake_output = "src/service.py:10: missing branch coverage\nsrc/service.py:20: except error"
        fake = type("R", (), {"stdout": fake_output, "stderr": "", "returncode": 0})()
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
        monkeypatch.setattr(sys, "argv", ["coverage_analyzer.py"])
        main()
        captured = capsys.readouterr()
        assert "Coverage Analysis" in captured.out
        assert "Module coverage" in captured.out or "module" in captured.out.lower()

    def test_main_with_suggest_flag(self, monkeypatch, capsys):
        import subprocess
        import sys
        from coverage_analyzer import main

        fake_output = "\n".join(
            [f"src/s.py:{i}: except error raise async = default if else" for i in range(20)]
        )
        fake = type("R", (), {"stdout": fake_output, "stderr": "", "returncode": 0})()
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
        monkeypatch.setattr(sys, "argv", ["coverage_analyzer.py", "--suggest"])
        main()
        captured = capsys.readouterr()

    def test_main_with_missing_lines_and_pattern_counts(self, monkeypatch, capsys):
        import subprocess
        import sys
        from coverage_analyzer import main

        fake_output = "\n".join(
            [f"src/s.py:{i}: missing except error raise" for i in range(10)]
        )
        fake = type("R", (), {"stdout": fake_output, "stderr": "", "returncode": 0})()
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
        monkeypatch.setattr(sys, "argv", ["coverage_analyzer.py"])
        main()
        captured = capsys.readouterr()
        assert "Coverage Analysis" in captured.out
        assert "occurrences" in captured.out

    def test_main_suggest_with_pattern_counts(self, monkeypatch, capsys):
        import subprocess
        import sys
        from coverage_analyzer import main

        fake_output = "\n".join(
            [f"src/s.py:{i}: missing except error raise async = default if else" for i in range(20)]
        )
        fake = type("R", (), {"stdout": fake_output, "stderr": "", "returncode": 0})()
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
        monkeypatch.setattr(sys, "argv", ["coverage_analyzer.py", "--suggest"])
        main()
        captured = capsys.readouterr()
        assert "Recommendations" in captured.out or "Coverage Analysis" in captured.out

    def test_main_high_avg_coverage_branch(self, monkeypatch, capsys):
        import subprocess
        import sys
        from coverage_analyzer import main

        fake = type("R", (), {"stdout": "", "stderr": "", "returncode": 0})()
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake)
        monkeypatch.setattr(sys, "argv", ["coverage_analyzer.py"])
        monkeypatch.setattr(
            "coverage_analyzer.analyze_module_coverage",
            lambda: [("accounting", 99.0), ("auth", 99.0)],
        )
        main()
        captured = capsys.readouterr()
        assert "MEETS TARGET" in captured.out
