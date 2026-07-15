"""Direct api-wrapper call-site ratchet (#1868 S5 PR-C, G-fetch-ratchet).

`hooks/useApiQuery.ts` is the designed react-query base hook, but pages and
components still hand-roll `apiFetch`/`apiStream`/`apiDelete`/`apiUpload` +
`useState`/`useEffect` loading/error/retry orchestration at 87 call sites
across 33 files (measured 2026-07-15; two earlier reviews under-/over-counted
this — 33 was an over-count, a later "21" only matched the bare `apiFetch(`
substring and missed every generic `apiFetch<T>(...)` call). Exhaustive
migration of all 87 sites is not this issue's mechanism — the ratchet is:
the count of direct call sites under `components/`+`app/` (tests excluded)
may only shrink relative to the committed baseline, so the debt cannot
silently grow back while migration happens incrementally over time.

Counting heuristic (generic-aware, unlike a naive `"apiFetch("` substring
scan): a call site is any `apiFetch(`, `apiFetch<...>(`, `apiStream(`,
`apiStream<...>(`, `apiDelete(`, `apiDelete<...>(`, `apiUpload(`, or
`apiUpload<...>(` occurrence.

Update after migrating call sites to `useApiQuery`::

    python -m common.testing.fe_fetch_ratchet --update   # only-goes-down
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "apps" / "frontend" / "src"
BASELINE_PATH = Path(__file__).parent / "fe-fetch-ratchet-baseline.json"

_CALL_PATTERN = re.compile(
    r"\b(?:apiFetch|apiStream|apiDelete|apiUpload)(?:<[^>(]*>)?\("
)
_SCAN_ROOTS = ("components", "app")


def count_call_sites() -> dict[str, int]:
    counts: dict[str, int] = {}
    for root in _SCAN_ROOTS:
        for path in sorted((FRONTEND_SRC / root).rglob("*.ts")) + sorted(
            (FRONTEND_SRC / root).rglob("*.tsx")
        ):
            if "__tests__" in path.parts:
                continue
            if path.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
                continue
            text = path.read_text(encoding="utf-8")
            n = len(_CALL_PATTERN.findall(text))
            if n:
                try:
                    key = str(path.relative_to(REPO_ROOT))
                except ValueError:  # monkeypatched sandbox roots in tests
                    key = str(path)
                counts[key] = n
    return counts


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    total = sum(count_call_sites().values())
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
        print(f"fe-fetch-ratchet baseline updated: {baseline} -> {total}")
        return 0

    if total > baseline:
        print(
            f"ERROR: direct api-wrapper call-site count grew ({baseline} -> {total}). "
            "New GET-render call sites should use hooks/useApiQuery.ts instead of "
            "hand-rolled apiFetch + useState/useEffect orchestration "
            "(#1868 S5 G-fetch-ratchet).",
            file=sys.stderr,
        )
        return 1
    print(f"fe-fetch-ratchet: {total} <= baseline {baseline}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
