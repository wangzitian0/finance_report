"""CLI over the test execution matrix (common/testing/matrix.py)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.testing import matrix  # noqa: E402

MATRIX_YAML = ROOT_DIR / "common" / "testing" / "data" / "test-execution-matrix.yaml"


def main(argv: Sequence[str] | None = None) -> int:
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
        if args.shell:
            print(matrix.emit_touched_e2e_shell(args.touched_files))
            return 0
        for node in matrix.select_touched_e2e(args.touched_files):
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
