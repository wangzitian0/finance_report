"""Generate the README EPIC status pointer block.

EPIC status and completion are *derived* facts, not hand-written prose. The
per-EPIC numbers are a view of the one AC-keyed graph and are NOT committed: a
committed snapshot churns on every AC change. The README therefore carries only
a fixed pointer to the on-demand per-EPIC table of
:mod:`common.testing.build_ac_traceability`, whose classification comes from
:mod:`common.testing.check_ac_traceability` (the one classifier).

This module writes the pointer block into the README, or (with ``--check``)
fails CI when the committed block is missing or differs from the regenerated
one. Because the block is constant, ``--check`` never fails on a shifted AC
total.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "README.md"

BEGIN_MARKER = "<!-- BEGIN GENERATED: epic-status -->"
END_MARKER = "<!-- END GENERATED: epic-status -->"


def render_pointer_block() -> str:
    """Render the STABLE committed EPIC-status block (markers + on-demand pointer)."""
    return "\n".join(
        [
            BEGIN_MARKER,
            "",
            "> EPIC status is a DERIVED view of the one AC-keyed graph (see",
            '> [`common/testing/tdd.md`](common/testing/tdd.md) "Cross-Cutting Index Artifacts"). The',
            "> per-EPIC completion numbers are **not committed** here, because a committed",
            "> snapshot churns on every AC change and is the merge-train false-sharing",
            "> hotspot this model removes.",
            ">",
            "> Render the live per-EPIC table on demand:",
            ">",
            "> ```bash",
            "> python tools/build_ac_traceability.py --output tmp/AC-TEST-TRACEABILITY-AUDIT.md",
            "> ```",
            ">",
            '> Its "Coverage by EPIC" table reports real, placeholder-only, stub-only and',
            "> missing ACs per EPIC and excludes deprecated ACs. Consistency (no dangling /",
            "> missing proof) is gated by `python tools/check_ac_index.py`; live CI and",
            "> deploy run status are intentionally excluded.",
            "",
            END_MARKER,
        ]
    )


def splice_block(document: str, block: str) -> str:
    """Replace the delimited generated block inside ``document`` with ``block``.

    Raises ``ValueError`` if the markers are missing or malformed so a silently
    un-spliced document can never pass ``--check``.
    """
    start = document.find(BEGIN_MARKER)
    end = document.find(END_MARKER)
    if start == -1 or end == -1 or end < start:
        raise ValueError(
            f"EPIC status markers not found or malformed; expected {BEGIN_MARKER!r} ... {END_MARKER!r}"
        )
    end += len(END_MARKER)
    return document[:start] + block + document[end:]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Markdown document containing the generated EPIC-status block.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Fail only if the committed README EPIC-status pointer block is "
            "missing or malformed. The block is a stable on-demand pointer, so "
            "this never fails on a shifted AC total."
        ),
    )
    args = parser.parse_args(argv)

    output = args.output
    pointer = render_pointer_block()

    try:
        document = output.read_text(encoding="utf-8")
    except OSError:
        print(f"ERROR: EPIC status document is missing: {output}", file=sys.stderr)
        return 1

    try:
        updated = splice_block(document, pointer)
    except ValueError as exc:
        print(f"ERROR: {exc} in {output}", file=sys.stderr)
        return 1

    if args.check:
        if document != updated:
            diff = difflib.unified_diff(
                document.splitlines(),
                updated.splitlines(),
                fromfile=str(output),
                tofile="generated",
                lineterm="",
            )
            print(
                "ERROR: README EPIC-status pointer block is missing or malformed.",
                file=sys.stderr,
            )
            print("\n".join(diff), file=sys.stderr)
            print("  Run: python tools/generate_epic_status.py", file=sys.stderr)
            return 1
        print(f"OK: EPIC status pointer block is current: {output}")
        return 0

    output.write_text(updated, encoding="utf-8")
    print(f"Wrote EPIC status pointer block: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
