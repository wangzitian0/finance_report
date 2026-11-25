"""CLI over the test execution matrix (common/testing/matrix.py).

``--run`` runs pytest for a selection. Hook steps use it: infra2 runs each step with
``sh -lc``, which cannot eval the bash arrays of ``--shell`` (#2912).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.testing import matrix  # noqa: E402

MATRIX_YAML = ROOT_DIR / "common" / "testing" / "data" / "test-execution-matrix.yaml"


def _resolve_junit_path(
    explicit: Path | None,
    *,
    hook_artifacts_dir: str | None,
    stage: str | None,
    corpus: str | None,
) -> Path | None:
    if explicit is not None:
        return explicit
    if not hook_artifacts_dir:
        return None
    stem = (
        f"{stage}_{corpus}"
        if stage and corpus and corpus != "all"
        else (stage or "selection")
    )
    return Path(hook_artifacts_dir) / f"{stem}.junit.xml"


def run_pytest(
    nodes: Sequence[str],
    marker: str,
    *,
    stage_env: Mapping[str, str],
    junit_path: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    """Run ``python -m pytest`` in the repository root; return its exit code.

    Child env: stage env defaults, overridden by the parent env, plus the forced
    ``STRICT_E2E_GATES=1``: without it a rejected AI/OCR statement is a skip (#2914).
    """
    flags = ["-v", "--tb=short", "-o", "addopts=", "-m", marker]
    if junit_path is not None:
        junit_path.parent.mkdir(parents=True, exist_ok=True)
        flags.append(f"--junitxml={junit_path}")
    argv = [sys.executable, "-m", "pytest", *nodes, *flags]
    env = {**stage_env, **os.environ, "STRICT_E2E_GATES": "1"}
    return runner(argv, check=False, cwd=ROOT_DIR, env=env).returncode


def _resolve_touched_files(raw: Sequence[str]) -> list[str]:
    """Return CLI touched paths, or whitespace-split ``INFRA2_TOUCHED_FILES``."""
    return list(raw) if raw else os.environ.get("INFRA2_TOUCHED_FILES", "").split()


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", help="Selection stage to emit (e.g. staging_core_e2e)."
    )
    parser.add_argument(
        "--corpus",
        default="all",
        help="AI/OCR corpus selector when --stage=staging_ai_ocr (all, canary, audit_replay, core_journey).",
    )
    parser.add_argument("--shell", action="store_true", help="Emit bash assignments.")
    parser.add_argument(
        "--run", action="store_true", help="Run pytest on the selection."
    )
    parser.add_argument(
        "--junit-path",
        type=Path,
        default=None,
        help="Optional path for --junitxml when --run executes (defaults to HOOK_ARTIFACTS_DIR when set).",
    )
    parser.add_argument(
        "--emit-matrix",
        action="store_true",
        help="Write the generated common/testing/data/test-execution-matrix.yaml.",
    )
    parser.add_argument(
        "--check-matrix",
        action="store_true",
        help="Exit 1 if common/testing/data/test-execution-matrix.yaml drifted from the code.",
    )
    parser.add_argument(
        "--touched-files",
        nargs="*",
        default=None,
        help="Emit affected non-LLM staging_core_e2e journeys for the given changed repo-relative paths (#2670).",
    )
    args = parser.parse_args(argv)
    if args.run and args.shell:
        parser.error("--run cannot be combined with --shell")

    if args.check_matrix:
        expected = matrix.emit_execution_matrix_yaml()
        actual = MATRIX_YAML.read_text(encoding="utf-8") if MATRIX_YAML.exists() else ""
        if actual != expected:
            print(
                "ERROR: common/testing/data/test-execution-matrix.yaml drifted from "
                "common/testing/matrix.py.\n"
                "  Regenerate: python tools/test_selection.py --emit-matrix",
                file=sys.stderr,
            )
            return 1
        print("test-execution-matrix.yaml matches common/testing/matrix.py")
        return 0

    if args.emit_matrix:
        MATRIX_YAML.write_text(matrix.emit_execution_matrix_yaml(), encoding="utf-8")
        print(f"wrote {MATRIX_YAML.relative_to(ROOT_DIR)}")
        return 0

    if args.touched_files is not None:
        touched_files = _resolve_touched_files(args.touched_files)
        if args.run:
            nodes, marker = matrix.touched_e2e_selection(touched_files)
            if not nodes:
                print("no touched journey: pytest not started")
                return 0
            env = matrix.stage_env(matrix.STAGING_CORE_E2E_STAGE)
            junit_path = _resolve_junit_path(
                args.junit_path,
                hook_artifacts_dir=os.environ.get("HOOK_ARTIFACTS_DIR"),
                stage="touched_files",
                corpus=None,
            )
            return run_pytest(
                nodes, marker, stage_env=env, junit_path=junit_path, runner=runner
            )
        if args.shell:
            print(matrix.emit_touched_e2e_shell(touched_files))
            return 0
        for node in matrix.select_touched_e2e(touched_files):
            print(node)
        return 0

    if not args.stage:
        parser.error(
            "--stage is required unless using --emit-matrix/--check-matrix/--touched-files"
        )

    selection = matrix.SELECTIONS.get(args.stage)
    if selection is None:
        known = ", ".join(sorted(matrix.SELECTIONS))
        print(
            f"ERROR: unknown selection stage {args.stage!r}; known stages: {known}",
            file=sys.stderr,
        )
        return 2

    if args.run:
        try:
            nodes, marker = matrix.stage_selection(args.stage, corpus=args.corpus)
        except ValueError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
        env = matrix.stage_env(args.stage)
        junit_path = _resolve_junit_path(
            args.junit_path,
            hook_artifacts_dir=os.environ.get("HOOK_ARTIFACTS_DIR"),
            stage=args.stage,
            corpus=args.corpus if args.stage == matrix.STAGING_AI_OCR_STAGE else None,
        )
        return run_pytest(
            nodes, marker, stage_env=env, junit_path=junit_path, runner=runner
        )

    if args.shell:
        print(matrix.emit_shell(args.stage, corpus=args.corpus))
        return 0

    nodes = (
        selection(args.corpus)
        if args.stage == matrix.STAGING_AI_OCR_STAGE
        else selection()
    )
    for node in nodes:
        print(node)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
