"""Behavioral tests for the diff-scoped PR coverage gate (#1810).

ACs: AC-testing.diff-coverage.1 / .2 / .3 (common/testing/contract.py roadmap).

Every test here is behavioral per the #1435 mirror-assertion discipline: it
feeds a diff (``--diff-file``) plus a temporary LCOV tree into the module's
functions or the ``tools/check_diff_coverage.py`` CLI and asserts on returned
structures, exit codes, and output shape — never on another artifact's text.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.testing.coverage import diff_coverage as dc  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "tools" / "check_diff_coverage.py"


# ---------------------------------------------------------------------------
# parse_unified_diff
# ---------------------------------------------------------------------------


def test_parse_unified_diff_multi_file_multi_hunk():
    diff = "\n".join(
        [
            "diff --git a/common/pkg/mod.py b/common/pkg/mod.py",
            "index 1111111..2222222 100644",
            "--- a/common/pkg/mod.py",
            "+++ b/common/pkg/mod.py",
            "@@ -10,2 +12,3 @@ def foo():",
            "+a = 1",
            "+b = 2",
            "+c = 3",
            "@@ -40 +45,2 @@ def bar():",
            "+d = 4",
            "+e = 5",
            "diff --git a/tools/new_tool.py b/tools/new_tool.py",
            "new file mode 100644",
            "index 0000000..3333333",
            "--- /dev/null",
            "+++ b/tools/new_tool.py",
            "@@ -0,0 +1,2 @@",
            "+import sys",
            "+print(sys.argv)",
            "",
        ]
    )
    assert dc.parse_unified_diff(diff) == {
        "common/pkg/mod.py": {12, 13, 14, 45, 46},
        "tools/new_tool.py": {1, 2},
    }


def test_parse_unified_diff_count_defaults_to_one():
    diff = "\n".join(
        [
            "--- a/common/x.py",
            "+++ b/common/x.py",
            "@@ -3 +7 @@",
            "+changed = True",
            "",
        ]
    )
    assert dc.parse_unified_diff(diff) == {"common/x.py": {7}}


def test_parse_unified_diff_handles_quoted_and_unprefixed_targets():
    diff = "\n".join(
        [
            '--- "a/common/spaced name.py"',
            '+++ "b/common/spaced name.py"',
            "@@ -1 +1 @@",
            "+x = 1",
            "--- common/noprefix.py",
            "+++ common/noprefix.py",
            "@@ -1 +2 @@",
            "+y = 2",
            "",
        ]
    )
    assert dc.parse_unified_diff(diff) == {
        "common/spaced name.py": {1},
        "common/noprefix.py": {2},
    }


def test_parse_unified_diff_zero_count_hunk_adds_no_lines():
    # A pure-deletion hunk (`+4,0`) touches no new-side lines.
    diff = "\n".join(
        [
            "--- a/common/x.py",
            "+++ b/common/x.py",
            "@@ -5,3 +4,0 @@",
            "-gone = 1",
            "-gone = 2",
            "-gone = 3",
            "",
        ]
    )
    assert dc.parse_unified_diff(diff) == {}


def test_parse_unified_diff_ignores_deletions_and_pure_renames():
    diff = "\n".join(
        [
            "diff --git a/common/old.py b/common/old.py",
            "deleted file mode 100644",
            "--- a/common/old.py",
            "+++ /dev/null",
            "@@ -1,3 +0,0 @@",
            "-x = 1",
            "-y = 2",
            "-z = 3",
            "diff --git a/common/before.py b/common/after.py",
            "similarity index 100%",
            "rename from common/before.py",
            "rename to common/after.py",
            "",
        ]
    )
    assert dc.parse_unified_diff(diff) == {}


# ---------------------------------------------------------------------------
# resolve_component — scope rules over the shared coverage policy
# ---------------------------------------------------------------------------


def test_resolve_component_maps_paths_to_policy_components():
    resolved = dc.resolve_component("apps/backend/src/services/foo.py")
    assert resolved is not None
    component, relative = resolved
    assert component.name == "backend"
    assert relative == "src/services/foo.py"

    resolved = dc.resolve_component("common/testing/coverage/diff_coverage.py")
    assert resolved is not None
    assert resolved[0].name == "common"
    assert resolved[1] == "common/testing/coverage/diff_coverage.py"

    resolved = dc.resolve_component("tools/check_diff_coverage.py")
    assert resolved is not None
    assert resolved[0].name == "tools"

    resolved = dc.resolve_component("apps/frontend/src/lib/api.ts")
    assert resolved is not None
    assert resolved[0].name == "frontend"
    assert resolved[1] == "src/lib/api.ts"


def test_resolve_component_rejects_out_of_scope_paths():
    # Docs, tests, workflows, wrong extensions, and policy-excluded files are
    # out of scope for the diff gate.
    assert dc.resolve_component("common/testing/coverage.md") is None
    assert dc.resolve_component("tests/tooling/test_diff_coverage.py") is None
    assert dc.resolve_component(".github/workflows/ci.yml") is None
    assert dc.resolve_component("apps/backend/src/notes.txt") is None
    assert dc.resolve_component("apps/backend/src/__init__.py") is None
    assert dc.resolve_component("apps/backend/README.md") is None
    assert dc.resolve_component("common/testing/__init__.py") is None
    assert dc.resolve_component("apps/frontend/src/__tests__/page.test.tsx") is None


# ---------------------------------------------------------------------------
# parse_lcov_line_hits
# ---------------------------------------------------------------------------


def test_parse_lcov_line_hits_sums_duplicates_and_normalizes_paths(tmp_path):
    lcov = tmp_path / "common.lcov"
    lcov.write_text(
        "\n".join(
            [
                "SF:common/pkg/mod.py",
                "DA:1,1",
                "DA:2,0",
                "DA:5,3",
                "end_of_record",
                # Duplicate record for the same source (e.g. merged shards):
                # hits must accumulate, mirroring flush_record semantics.
                "SF:common/pkg/mod.py",
                "DA:2,2",
                "DA:9,0",
                # Malformed DA records are skipped, not fatal.
                "DA:bad,1",
                "DA:7",
                "end_of_record",
            ]
        )
    )
    component = dc.get_component("common")
    hits = dc.parse_lcov_line_hits(lcov, component, tmp_path)
    assert hits == {"common/pkg/mod.py": {1: 1, 2: 2, 5: 3, 9: 0}}


def test_parse_lcov_line_hits_missing_file_returns_empty(tmp_path):
    component = dc.get_component("common")
    assert dc.parse_lcov_line_hits(tmp_path / "no.lcov", component, tmp_path) == {}


# ---------------------------------------------------------------------------
# evaluate_diff_coverage — verdict math on a temporary repo tree
# ---------------------------------------------------------------------------


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _common_lcov(root: Path, records: str) -> None:
    _write(root, "coverage/common.lcov", records)


def test_verdict_covered_uncovered_and_nonexecutable_lines(tmp_path):
    _common_lcov(
        tmp_path,
        "\n".join(
            [
                "SF:common/pkg/mod.py",
                "DA:10,1",
                "DA:11,0",
                "DA:13,2",
                "end_of_record",
                "",
            ]
        ),
    )
    # Changed lines: 10 (covered), 11 (uncovered), 12 (absent from the present
    # record -> non-executable, skipped), 13 (covered).
    report = dc.evaluate_diff_coverage(
        {"common/pkg/mod.py": {10, 11, 12, 13}}, tmp_path
    )
    assert report.skipped_components == ()
    assert len(report.files) == 1
    verdict = report.files[0]
    assert verdict.path == "common/pkg/mod.py"
    assert verdict.component == "common"
    assert verdict.covered_lines == (10, 13)
    assert verdict.uncovered_lines == (11,)
    assert verdict.missing_from_lcov is False
    assert report.measurable_lines == 3
    assert report.covered_count == 2


def test_file_absent_from_present_lcov_is_conservatively_uncovered(tmp_path):
    # The component artifact exists but has no record for the changed file —
    # the "new file with zero tests" hole. Its added non-blank, non-comment
    # lines count as uncovered.
    _common_lcov(
        tmp_path,
        "SF:common/pkg/other.py\nDA:1,1\nend_of_record\n",
    )
    _write(
        tmp_path,
        "common/pkg/newmod.py",
        "\n".join(
            [
                '"""Docstring."""',  # line 1: significant
                "",  # line 2: blank
                "# a comment",  # line 3: comment
                "import sys",  # line 4: significant
                "",  # line 5: blank
                "print(sys.argv)",  # line 6: significant
            ]
        ),
    )
    # Line 99 is beyond EOF (defensive: a stale diff) and is skipped; an
    # entry with no changed lines contributes nothing.
    report = dc.evaluate_diff_coverage(
        {
            "common/pkg/newmod.py": {1, 2, 3, 4, 5, 6, 99},
            "common/pkg/untouched.py": set(),
        },
        tmp_path,
    )
    assert len(report.files) == 1
    verdict = report.files[0]
    assert verdict.missing_from_lcov is True
    assert verdict.covered_lines == ()
    assert verdict.uncovered_lines == (1, 4, 6)
    assert report.measurable_lines == 3
    assert report.covered_count == 0


def test_significant_lines_fall_back_to_all_lines_when_unreadable(tmp_path):
    # read_text failing (e.g. the path is a directory) keeps the rule
    # conservative: every added line counts as uncovered.
    assert dc._significant_lines(tmp_path, {2, 1}) == (1, 2)


def test_out_of_scope_files_and_absent_artifacts_are_lenient(tmp_path, capfd):
    """AC-testing.diff-coverage.3: docs/tests/config changes and absent
    component artifacts never produce a blocking verdict."""
    # No coverage/ artifacts exist at all in this tree.
    _write(tmp_path, "tools/some_tool.py", "x = 1\n")
    changed = {
        "common/testing/coverage.md": {1, 2},
        "tests/tooling/test_something.py": {5},
        ".github/workflows/ci.yml": {100},
        "tools/some_tool.py": {1},
    }
    report = dc.evaluate_diff_coverage(changed, tmp_path)
    # Docs/tests/workflow changes resolve to no component; the tools file's
    # component artifact is absent -> the component is skipped, loudly.
    assert report.files == ()
    assert report.skipped_components == ("tools",)
    assert report.measurable_lines == 0
    assert report.percent is None

    # CLI parity: the same situation exits 0 and says so explicitly.
    diff = "\n".join(
        [
            "--- a/tools/some_tool.py",
            "+++ b/tools/some_tool.py",
            "@@ -0,0 +1 @@",
            "+x = 1",
            "",
        ]
    )
    diff_file = _write(tmp_path, "changes.diff", diff)
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--repo-root",
            str(tmp_path),
            "--diff-file",
            str(diff_file),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert re.search(r"(?i)warning.*tools", result.stdout + result.stderr)
    assert re.search(r"(?i)no measurable changed lines", result.stdout)


# ---------------------------------------------------------------------------
# format_line_ranges
# ---------------------------------------------------------------------------


def test_format_line_ranges_collapses_runs():
    assert dc.format_line_ranges([45, 46, 47, 48, 92]) == "45-48, 92"
    assert dc.format_line_ranges([7]) == "7"
    assert dc.format_line_ranges([3, 1, 2, 9]) == "1-3, 9"
    assert dc.format_line_ranges([]) == ""


# ---------------------------------------------------------------------------
# CLI — subprocess, the exact surface CI invokes
# ---------------------------------------------------------------------------


def _cli_fixture(tmp_path: Path) -> Path:
    """A tree where common/pkg/mod.py has 4 covered + 1 uncovered changed
    lines and common/pkg/newmod.py (2 code lines) is absent from LCOV:
    4/7 measurable changed lines covered = 57.1%."""
    _common_lcov(
        tmp_path,
        "\n".join(
            [
                "SF:common/pkg/mod.py",
                "DA:45,0",
                "DA:50,1",
                "DA:51,1",
                "DA:52,2",
                "DA:60,4",
                "end_of_record",
                "",
            ]
        ),
    )
    _write(tmp_path, "common/pkg/newmod.py", "import sys\nprint(sys.argv)\n")
    diff = "\n".join(
        [
            "--- a/common/pkg/mod.py",
            "+++ b/common/pkg/mod.py",
            "@@ -44,0 +45 @@",
            "+bad = 1",
            "@@ -49,2 +50,3 @@",
            "+ok = 1",
            "+ok = 2",
            "+ok = 3",
            "@@ -59 +60 @@",
            "+ok = 4",
            "--- /dev/null",
            "+++ b/common/pkg/newmod.py",
            "@@ -0,0 +1,2 @@",
            "+import sys",
            "+print(sys.argv)",
            "",
        ]
    )
    return _write(tmp_path, "changes.diff", diff)


def _run_cli(tmp_path: Path, diff_file: Path, *args: str, env: dict | None = None):
    import os

    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    return subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--repo-root",
            str(tmp_path),
            "--diff-file",
            str(diff_file),
            *args,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=merged_env,
    )


def test_cli_blocks_below_threshold_and_passes_at_or_above(tmp_path):
    """AC-testing.diff-coverage.1: verdict is computed from the diff plus the
    LCOV tree alone and gates on the threshold."""
    diff_file = _cli_fixture(tmp_path)

    red = _run_cli(tmp_path, diff_file, "--threshold", "85")
    assert red.returncode == 1
    # Summary states percent, covered/measurable counts, and the threshold.
    assert re.search(
        r"diff coverage: 57\.1% \(4/7 measurable changed lines covered\)",
        red.stdout,
    )
    assert re.search(r"threshold 85", red.stdout)

    green = _run_cli(tmp_path, diff_file, "--threshold", "50")
    assert green.returncode == 0

    # Exactly at the threshold passes.
    at_threshold = _run_cli(tmp_path, diff_file, "--threshold", "57.1")
    assert at_threshold.returncode == 0

    # DIFF_COVERAGE_THRESHOLD env is the fallback when the flag is absent.
    env_red = _run_cli(tmp_path, diff_file, env={"DIFF_COVERAGE_THRESHOLD": "90"})
    assert env_red.returncode == 1
    env_green = _run_cli(tmp_path, diff_file, env={"DIFF_COVERAGE_THRESHOLD": "50"})
    assert env_green.returncode == 0


def test_red_verdict_lists_uncovered_line_ranges_and_new_file_hole(tmp_path):
    """AC-testing.diff-coverage.2: a red verdict names file:line ranges and
    flags files absent from LCOV."""
    diff_file = _cli_fixture(tmp_path)
    result = _run_cli(tmp_path, diff_file, "--threshold", "85")
    assert result.returncode == 1
    assert re.search(r"common/pkg/mod\.py: uncovered lines 45", result.stdout)
    assert re.search(r"common/pkg/newmod\.py: uncovered lines 1-2", result.stdout)
    # The new-file hole is called out as such, not silently folded in.
    assert re.search(r"(?i)not in .*lcov|zero tests", result.stdout)


def _tiny_git_repo(tmp_path: Path) -> Path:
    """A real two-commit repo: feature adds lines 2-3 of common/pkg/mod.py."""
    root = tmp_path / "repo"
    root.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            env={
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.com",
                "PATH": __import__("os").environ["PATH"],
                "HOME": str(tmp_path),
            },
        )

    git("init", "-b", "main")
    _write(root, "common/pkg/mod.py", "a = 1\n")
    git("add", ".")
    git("commit", "-m", "base")
    git("checkout", "-b", "feature")
    _write(root, "common/pkg/mod.py", "a = 1\nb = 2\nc = 3\n")
    git("add", ".")
    git("commit", "-m", "change")
    _common_lcov(
        root,
        "SF:common/pkg/mod.py\nDA:1,1\nDA:2,1\nDA:3,1\nend_of_record\n",
    )
    return root


def test_cli_git_mode_diffs_against_merge_base(tmp_path):
    """Without --diff-file the CLI derives the diff from git itself."""
    root = _tiny_git_repo(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--repo-root",
            str(root),
            "--base",
            "main",
            "--threshold",
            "85",
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0
    assert re.search(
        r"diff coverage: 100\.0% \(2/2 measurable changed lines covered\)",
        result.stdout,
    )


def test_cli_missing_diff_file_is_a_usage_error(tmp_path):
    result = _run_cli(tmp_path, tmp_path / "does-not-exist.diff")
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# main() — in-process drives. The subprocess tests above prove the real
# command surface; these drive the same flows in-process so the CI tooling
# LCOV measures the module's own lines (subprocesses are not instrumented) —
# which is exactly what this PR's diff-coverage gate demands of itself.
# ---------------------------------------------------------------------------


def _main_code(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as exc:
        dc.main(argv)
    return exc.value.code


def test_main_red_then_green_thresholds(tmp_path, capfd):
    diff_file = _cli_fixture(tmp_path)
    base_args = ["--repo-root", str(tmp_path), "--diff-file", str(diff_file)]

    assert _main_code([*base_args, "--threshold", "85"]) == 1
    out = capfd.readouterr().out
    assert re.search(
        r"diff coverage: 57\.1% \(4/7 measurable changed lines covered\)", out
    )
    assert re.search(r"common/pkg/mod\.py: uncovered lines 45", out)
    assert re.search(r"common/pkg/newmod\.py: uncovered lines 1-2", out)
    assert re.search(r"(?i)zero tests", out)

    assert _main_code([*base_args, "--threshold", "50"]) == 0
    assert re.search(r"✅ diff coverage", capfd.readouterr().out)


def test_main_env_threshold_fallback_and_validation(tmp_path, monkeypatch):
    diff_file = _cli_fixture(tmp_path)
    base_args = ["--repo-root", str(tmp_path), "--diff-file", str(diff_file)]

    monkeypatch.setenv("DIFF_COVERAGE_THRESHOLD", "90")
    assert _main_code(base_args) == 1
    monkeypatch.setenv("DIFF_COVERAGE_THRESHOLD", "50")
    assert _main_code(base_args) == 0
    monkeypatch.setenv("DIFF_COVERAGE_THRESHOLD", "not-a-number")
    assert _main_code(base_args) == 2


def test_main_no_measurable_lines_passes_with_warning(tmp_path, capfd):
    _write(tmp_path, "tools/some_tool.py", "x = 1\n")
    diff_file = _write(
        tmp_path,
        "changes.diff",
        "\n".join(
            [
                "--- a/tools/some_tool.py",
                "+++ b/tools/some_tool.py",
                "@@ -0,0 +1 @@",
                "+x = 1",
                "",
            ]
        ),
    )
    code = _main_code(["--repo-root", str(tmp_path), "--diff-file", str(diff_file)])
    out = capfd.readouterr().out
    assert code == 0
    assert re.search(r"(?i)warning.*tools", out)
    assert re.search(r"(?i)no measurable changed lines", out)


def test_main_git_mode_and_bad_base(tmp_path, capfd, monkeypatch):
    root = _tiny_git_repo(tmp_path)

    monkeypatch.setenv("DIFF_COVERAGE_BASE", "main")
    assert _main_code(["--repo-root", str(root), "--threshold", "85"]) == 0
    assert re.search(
        r"diff coverage: 100\.0% \(2/2 measurable changed lines covered\)",
        capfd.readouterr().out,
    )

    monkeypatch.delenv("DIFF_COVERAGE_BASE")
    code = _main_code(
        ["--repo-root", str(root), "--base", "no-such-ref", "--threshold", "85"]
    )
    assert code == 2
    assert re.search(
        r"(?i)git diff against 'no-such-ref' failed", capfd.readouterr().err
    )


def test_main_missing_diff_file_is_a_usage_error(tmp_path):
    code = _main_code(
        ["--repo-root", str(tmp_path), "--diff-file", str(tmp_path / "nope.diff")]
    )
    assert code == 2
