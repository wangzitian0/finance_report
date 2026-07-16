"""Hand-mocked-vector-endpoint ratchet (issue #1827, pattern from #1558).

The API response conformance vectors (``common/{reporting,ledger,extraction}/
conformance/vectors.json``, #1827) make contract drift for the vectored
endpoints (balance-sheet report, accounts list, statement upload/status) red a
gate. But a frontend test that HAND-writes JSON for those endpoints instead of
loading the vector fixture helper stays structurally blind to drift. This
ratchet stops the accretion: the number of frontend test files that still
hand-mock a vectored endpoint may only DECREASE relative to the committed
baseline — convert files to ``fixtures/apiVectors`` over time, never add new
hand-mockers.

Counting heuristic (like the mirror ratchet, it intentionally approximates —
the ratchet compares like against like, so only the trend matters): a file
under ``apps/frontend/src/**/*.test.{ts,tsx}`` counts when it

1. mocks the API module (``vi.mock("@/lib/api"``), and
2. references a vectored endpoint path or an unmistakable response-shape
   marker of one (``total_assets`` / ``is_system`` / ``balance_validated``), and
3. does not import the shared vector fixture helper
   (``__tests__/fixtures/apiVectors``).

Update after converting hand-mockers::

    python -m common.testing.fe_api_handmock_ratchet --update   # only-goes-down
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "apps" / "frontend" / "src"
BASELINE_PATH = Path(__file__).parent / "fe-api-handmock-baseline.json"
BASELINE_UPDATE_MODE = "shrink-only"

_API_MOCK_MARKERS = ('vi.mock("@/lib/api"', "vi.mock('@/lib/api'")
_VECTORED_MARKERS = (
    # Endpoint path literals (multi-endpoint tests switch on the path).
    "/api/reports/balance-sheet",
    "/api/accounts",
    "/api/statements",
    # Response-shape markers for single-endpoint tests that mock apiFetch
    # wholesale and never spell the path out.
    "total_assets",
    "is_system",
    "balance_validated",
)
_FIXTURE_IMPORT_MARKER = "fixtures/apiVectors"


def count_handmock_files() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(FRONTEND_SRC.rglob("*.test.ts")) + sorted(
        FRONTEND_SRC.rglob("*.test.tsx")
    ):
        text = path.read_text(encoding="utf-8")
        if not any(m in text for m in _API_MOCK_MARKERS):
            continue
        if _FIXTURE_IMPORT_MARKER in text:
            continue
        if any(m in text for m in _VECTORED_MARKERS):
            try:
                key = str(path.relative_to(REPO_ROOT))
            except ValueError:  # monkeypatched sandbox roots in tests
                key = str(path)
            counts[key] = 1
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    total = sum(count_handmock_files().values())
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["total"]

    if "--update" in args:
        if total > baseline:
            print(
                f"REFUSED: current {total} > baseline {baseline}; the ratchet only goes down.",
                file=sys.stderr,
            )
            return 1
        BASELINE_PATH.write_text(
            json.dumps({"total": total}, indent=2) + "\n", encoding="utf-8"
        )
        print(f"fe-api-handmock baseline updated: {baseline} -> {total}")
        return 0

    if total > baseline:
        print(
            f"ERROR: hand-mocked vectored-endpoint file count grew "
            f"({baseline} -> {total}). New tests for the vectored endpoints "
            "must load their mock data via apps/frontend/src/__tests__/"
            "fixtures/apiVectors.ts instead of hand-writing the response "
            "JSON (#1827 G-contract-reddens).",
            file=sys.stderr,
        )
        return 1
    print(f"fe-api-handmock ratchet: {total} <= baseline {baseline}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
