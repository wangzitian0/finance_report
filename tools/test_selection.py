#!/usr/bin/env python3
"""CLI over the test execution matrix (common/testing/matrix.py).

Workflows consume test selection at runtime instead of hardcoding lists
(EPIC-008 AC8.22, issues #1547/#1556):

    eval "$(python tools/test_selection.py --stage pr_preview_e2e --shell)"

Maintenance commands:

    python tools/test_selection.py --emit-matrix    # regenerate the SSOT view
    python tools/test_selection.py --check-matrix   # fail on drift (CI gate)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.testing import matrix  # noqa: E402

MATRIX_YAML = ROOT_DIR / "docs" / "ssot" / "test-execution-matrix.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", help="Selection stage to emit (e.g. pr_preview_e2e)."
    )
    parser.add_argument("--shell", action="store_true", help="Emit bash assignments.")
    parser.add_argument(
        "--emit-matrix",
        action="store_true",
        help="Write the generated docs/ssot/test-execution-matrix.yaml.",
    )
    parser.add_argument(
        "--check-matrix",
        action="store_true",
        help="Exit 1 if docs/ssot/test-execution-matrix.yaml drifted from the code.",
    )
    args = parser.parse_args()

    if args.check_matrix:
        expected = matrix.emit_execution_matrix_yaml()
        actual = MATRIX_YAML.read_text(encoding="utf-8") if MATRIX_YAML.exists() else ""
        if actual != expected:
            print(
                "ERROR: docs/ssot/test-execution-matrix.yaml drifted from "
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

    if not args.stage:
        parser.error("--stage is required unless using --emit-matrix/--check-matrix")

    selection = matrix.SELECTIONS.get(args.stage)
    if selection is None:
        known = ", ".join(sorted(matrix.SELECTIONS))
        print(
            f"ERROR: unknown selection stage {args.stage!r}; known stages: {known}",
            file=sys.stderr,
        )
        return 2

    if args.shell:
        print(matrix.emit_shell(args.stage))
        return 0

    for node in selection():
        print(node)
    return 0


if __name__ == "__main__":
    sys.exit(main())
