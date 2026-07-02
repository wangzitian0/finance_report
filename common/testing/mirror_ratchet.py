"""Mirror-assertion ratchet (issue #1558, root #1435).

A "mirror assertion" string-matches a literal against another artifact's text
(``assert "..." in workflow``) instead of testing behavior against a contract.
The stock (~1,100+, measured 2026-06-25) shatters on any rename/reformat and
grows with every fix. This ratchet stops the accretion: the count over
``tests/tooling/`` may only DECREASE relative to the committed baseline.

The heuristic counts ``assert``/``assert not`` of a string literal with ``in``
on the same logical line. It intentionally over-approximates (some hits are
legitimate contract asserts) — the ratchet compares like against like, so only
the trend matters, not the absolute number.

Update after paying down mirrors::

    python -m common.testing.mirror_ratchet --update   # only-goes-down
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLING_DIR = REPO_ROOT / "tests" / "tooling"
BASELINE_PATH = Path(__file__).parent / "mirror-assertion-baseline.json"

_MIRROR_RE = re.compile(
    r"""assert\s+(?:not\s+)?f?["'].*?["']\s+(?:not\s+)?in\s+""",
    re.VERBOSE,
)


def _logical_lines(text: str) -> list[str]:
    """Join implicit (bracket) and explicit (backslash) continuations enough
    for the assert-literal-in pattern to land on one line."""
    joined = re.sub(r"\\\n\s*", " ", text)
    joined = re.sub(r"\(\s*\n\s*", "(", joined)
    return joined.splitlines()


def count_mirror_assertions() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(TOOLING_DIR.glob("*.py")):
        n = sum(
            1
            for line in _logical_lines(path.read_text(encoding="utf-8"))
            if _MIRROR_RE.search(line)
        )
        if n:
            counts[path.name] = n
    return counts


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    total = sum(count_mirror_assertions().values())
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["total"]

    if "--update" in args:
        if total > baseline:
            print(
                f"REFUSED: current {total} > baseline {baseline}; the ratchet "
                "only goes down.",
                file=sys.stderr,
            )
            return 1
        BASELINE_PATH.write_text(
            json.dumps({"total": total}, indent=2) + "\n", encoding="utf-8"
        )
        print(f"mirror-assertion baseline updated: {baseline} -> {total}")
        return 0

    if total > baseline:
        print(
            f"ERROR: mirror-assertion count grew ({baseline} -> {total}). Do not "
            "add new text-mirror assertions — encode the property as a matrix/"
            "behavior contract instead (see common/testing/matrix.py and #1435).",
            file=sys.stderr,
        )
        return 1
    print(f"mirror-assertion ratchet: {total} <= baseline {baseline}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
