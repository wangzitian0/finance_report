"""Unit tests for the money/classification mutation reproof runner (#2448)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from common.testing import mutation_check

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_AC_testing_preflight_1_default_manifest_has_unique_anchors_in_target_files():
    """AC-testing.preflight.1: Every declared mutation in money-mutations.json matches its target file once."""
    mutations = mutation_check.load()
    assert len(mutations) >= 5
    for m in mutations:
        target = REPO_ROOT / m.file
        assert target.exists(), f"{m.id}: missing target file {m.file}"
        content = target.read_text(encoding="utf-8")
        assert content.count(m.find) == 1, (
            f"{m.id}: expected anchor once in {m.file}, found {content.count(m.find)}"
        )


def test_apply_and_run_catches_failing_mutation_and_restores_source(tmp_path: Path):
    """A mutation that makes its guard exit non-zero is reported as caught and restores the file."""
    src_file = tmp_path / "sample.py"
    original_code = "VALUE = 10\n"
    src_file.write_text(original_code, encoding="utf-8")

    mut = mutation_check.Mutation(
        id="sample/value-check",
        guard="inline-guard",
        file="sample.py",
        find="VALUE = 10",
        replace="VALUE = 99",
        command=(
            "{python}",
            "-c",
            "import sample, sys; sys.exit(0 if sample.VALUE == 10 else 1)",
        ),
        cwd=".",
    )

    caught, why = mutation_check.apply_and_run(
        mut, repo_root=tmp_path, python=sys.executable
    )
    assert caught is True
    assert why == ""
    assert src_file.read_text(encoding="utf-8") == original_code


def test_apply_and_run_flags_surviving_mutation_and_restores_source(tmp_path: Path):
    """A mutation whose guard still exits 0 is reported as inert and restores the file."""
    src_file = tmp_path / "sample.py"
    original_code = "VALUE = 10\n"
    src_file.write_text(original_code, encoding="utf-8")

    mut = mutation_check.Mutation(
        id="sample/inert-guard",
        guard="inline-guard",
        file="sample.py",
        find="VALUE = 10",
        replace="VALUE = 99",
        command=("{python}", "-c", "import sys; sys.exit(0)"),
        cwd=".",
    )

    caught, why = mutation_check.apply_and_run(
        mut, repo_root=tmp_path, python=sys.executable
    )
    assert caught is False
    assert "passed with the property broken" in why
    assert src_file.read_text(encoding="utf-8") == original_code


def test_apply_and_run_rejects_missing_or_ambiguous_anchor(tmp_path: Path):
    """Missing or duplicate anchors fail closed without modifying the file."""
    src_file = tmp_path / "sample.py"
    original_code = "X = 1\nX = 1\n"
    src_file.write_text(original_code, encoding="utf-8")

    missing = mutation_check.Mutation(
        id="sample/missing",
        guard="g",
        file="sample.py",
        find="Y = 2",
        replace="Y = 3",
        command=("{python}", "-c", "pass"),
        cwd=".",
    )
    caught_m, why_m = mutation_check.apply_and_run(
        missing, repo_root=tmp_path, python=sys.executable
    )
    assert caught_m is False
    assert "anchor not found" in why_m

    ambiguous = mutation_check.Mutation(
        id="sample/ambiguous",
        guard="g",
        file="sample.py",
        find="X = 1",
        replace="X = 2",
        command=("{python}", "-c", "pass"),
        cwd=".",
    )
    caught_a, why_a = mutation_check.apply_and_run(
        ambiguous, repo_root=tmp_path, python=sys.executable
    )
    assert caught_a is False
    assert "anchor matches 2 times" in why_a
    assert src_file.read_text(encoding="utf-8") == original_code


def test_run_strict_vs_advisory_exit_codes(tmp_path: Path, capsys):
    """Strict mode exits 1 on surviving mutation; --advisory emits ::warning:: and exits 0."""
    src_file = tmp_path / "sample.py"
    src_file.write_text("VALUE = 10\n", encoding="utf-8")
    manifest = tmp_path / "mutations.json"
    manifest.write_text(
        json.dumps(
            {
                "mutations": [
                    {
                        "id": "sample/inert",
                        "guard": "inline",
                        "file": "sample.py",
                        "find": "VALUE = 10",
                        "replace": "VALUE = 20",
                        "command": ["{python}", "-c", "import sys; sys.exit(0)"],
                        "cwd": ".",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rc_strict = mutation_check.run(
        advisory=False,
        manifest=manifest,
        repo_root=tmp_path,
        python=sys.executable,
    )
    assert rc_strict == 1

    rc_advisory = mutation_check.run(
        advisory=True,
        manifest=manifest,
        repo_root=tmp_path,
        python=sys.executable,
    )
    assert rc_advisory == 0
    captured = capsys.readouterr()
    assert "::warning::guard is inert: sample/inert" in captured.out


def test_apply_and_run_rejects_no_tests_collected_and_non_assertion_exit_codes(
    tmp_path: Path,
):
    """Pytest exit code 5 (no tests collected) and exit code 2 (collection error) must not count as caught."""
    src_file = tmp_path / "sample.py"
    original_code = "VALUE = 10\n"
    src_file.write_text(original_code, encoding="utf-8")

    no_tests = mutation_check.Mutation(
        id="sample/no-tests-collected",
        guard="inline",
        file="sample.py",
        find="VALUE = 10",
        replace="VALUE = 20",
        command=("{python}", "-c", "import sys; sys.exit(5)"),
        cwd=".",
    )
    caught_5, why_5 = mutation_check.apply_and_run(
        no_tests, repo_root=tmp_path, python=sys.executable
    )
    assert caught_5 is False
    assert "collected 0 tests (pytest exit code 5)" in why_5
    assert src_file.read_text(encoding="utf-8") == original_code

    collection_err = mutation_check.Mutation(
        id="sample/collection-error",
        guard="inline",
        file="sample.py",
        find="VALUE = 10",
        replace="VALUE = 20",
        command=("{python}", "-c", "import sys; sys.exit(2)"),
        cwd=".",
    )
    caught_2, why_2 = mutation_check.apply_and_run(
        collection_err, repo_root=tmp_path, python=sys.executable
    )
    assert caught_2 is False
    assert "status 2" in why_2
    assert src_file.read_text(encoding="utf-8") == original_code


def test_main_and_run_only_and_timeout_paths(tmp_path: Path, monkeypatch):
    """Exercise main(), --only filtering, unknown --only id, all-caught path, and timeout handling."""

    src_file = tmp_path / "sample.py"
    original_code = "VALUE = 10\n"
    src_file.write_text(original_code, encoding="utf-8")
    manifest = tmp_path / "mutations.json"
    manifest.write_text(
        json.dumps(
            {
                "mutations": [
                    {
                        "id": "sample/caught",
                        "guard": "inline",
                        "file": "sample.py",
                        "find": "VALUE = 10",
                        "replace": "VALUE = 20",
                        "command": ["{python}", "-c", "import sys; sys.exit(1)"],
                        "cwd": ".",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert (
        mutation_check.run(
            only="sample/caught",
            manifest=manifest,
            repo_root=tmp_path,
            python=sys.executable,
        )
        == 0
    )
    assert (
        mutation_check.run(
            only="no-such-id",
            manifest=manifest,
            repo_root=tmp_path,
            python=sys.executable,
        )
        == 1
    )

    monkeypatch.setattr(mutation_check, "REPO_ROOT", tmp_path)
    assert (
        mutation_check.main(["--manifest", str(manifest), "--only", "sample/caught"])
        == 0
    )

    slow_mut = mutation_check.Mutation(
        id="sample/slow",
        guard="inline",
        file="sample.py",
        find="VALUE = 10",
        replace="VALUE = 20",
        command=("{python}", "-c", "import time; time.sleep(5)"),
        cwd=".",
    )
    caught_t, why_t = mutation_check.apply_and_run(
        slow_mut,
        repo_root=tmp_path,
        python=sys.executable,
        timeout=0.1,
    )
    assert caught_t is False
    assert "did not finish within 0.1s" in why_t
    assert src_file.read_text(encoding="utf-8") == original_code


def test_sigkill_during_guard_leaves_repo_root_and_git_status_untouched(
    tmp_path: Path,
):
    """#2712: Sending SIGKILL to check_mutations.py while its guard runs never leaves a mutated file in repo_root."""
    import os
    import signal
    import subprocess
    import time

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    pkg_dir = tmp_path / "apps" / "backend" / "pkg"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    src_file = pkg_dir / "sample.py"
    original_code = "VALUE = 10\n"
    src_file.write_text(original_code, encoding="utf-8")

    marker_file = tmp_path / "guard_started.flag"
    manifest = tmp_path / "mutations.json"
    manifest.write_text(
        json.dumps(
            {
                "mutations": [
                    {
                        "id": "sample/sigkill-safety",
                        "guard": "inline",
                        "file": "apps/backend/pkg/sample.py",
                        "find": "VALUE = 10",
                        "replace": "VALUE = 999",
                        "command": [
                            "{python}",
                            "-c",
                            (
                                "import pathlib, time, pkg.sample; "
                                f"pathlib.Path({str(marker_file)!r}).write_text(str(pkg.sample.VALUE)); "
                                "time.sleep(30)"
                            ),
                        ],
                        "cwd": "apps/backend",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "add",
            "apps/backend/pkg/__init__.py",
            "apps/backend/pkg/sample.py",
            "mutations.json",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    runner_code = (
        "import sys; "
        f"sys.path.insert(0, {str(REPO_ROOT)!r}); "
        "from pathlib import Path; "
        "from common.testing import mutation_check; "
        f"mutation_check.run(manifest=Path({str(manifest)!r}), repo_root=Path({str(tmp_path)!r}), python=sys.executable)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", runner_code],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10.0
        while not marker_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker_file.exists(), "guard subprocess never started"
        assert marker_file.read_text(encoding="utf-8") == "999"
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        marker_file.unlink(missing_ok=True)

    assert src_file.read_text(encoding="utf-8") == original_code
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status == ""


def test_run_total_timeout_marks_remaining_mutations_unproven(tmp_path: Path, capsys):
    """#2712: When total_timeout is exhausted, remaining mutations report unproven (total deadline exceeded)."""
    src_file = tmp_path / "sample.py"
    src_file.write_text("VALUE = 10\n", encoding="utf-8")
    manifest = tmp_path / "mutations.json"
    manifest.write_text(
        json.dumps(
            {
                "mutations": [
                    {
                        "id": "sample/after-deadline",
                        "guard": "inline",
                        "file": "sample.py",
                        "find": "VALUE = 10",
                        "replace": "VALUE = 20",
                        "command": ["{python}", "-c", "import sys; sys.exit(1)"],
                        "cwd": ".",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rc = mutation_check.run(
        manifest=manifest,
        repo_root=tmp_path,
        python=sys.executable,
        total_timeout=0.0,
    )
    assert rc == 1
    captured = capsys.readouterr()
    assert "unproven (total deadline exceeded)" in captured.out
