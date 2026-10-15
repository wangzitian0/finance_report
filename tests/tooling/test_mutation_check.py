"""Unit tests for the money/classification mutation reproof runner (#2448)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from common.testing import mutation_check

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_default_manifest_has_unique_anchors_in_target_files():
    """Every declared mutation in money-mutations.json must match its target file exactly once."""
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
