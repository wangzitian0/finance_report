"""No duplicate definitions of the single-homed FE helpers (AC-meta.fe-contract-types.4, #1868 S5 PR-B).

`countLabel`/`pnlColorClass`(formerly `getPnlColor`)/`formatPeriod`/`isActive`
were each duplicated 2-3x across component files, with `formatPeriod`
already having diverged (a "→" vs "to" separator) and `getPnlColor`
byte-identical only by luck. They are now single-homed in `lib/statusLabels.ts`,
`lib/date.ts`, and `components/navigation.ts`. This gate keeps a re-duplication
from silently coming back. `formatCurrency` collided in name (not meaning)
with `lib/audit/money/format.ts`'s amount formatter — the local copy is
renamed `currencyCodeOrDash`, so a bare `formatCurrency` definition anywhere
outside `lib/audit/money/format.ts` would be exactly that collision returning.
"""

from __future__ import annotations

import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO / "apps" / "backend" / ".." / "frontend" / "src"
FRONTEND_SRC = (REPO / "apps" / "frontend" / "src").resolve()

# Line-anchored (not raw substring), matching both `function foo(` and
# `const foo = (` styles — the async-aware-regex lesson from
# tests/tooling/test_safe_error_message_ssot.py (#1864 S1, PR #1871 review).
_HELPER_DEFS = {
    "countLabel": re.compile(
        r"^\s*(?:export\s+)?(?:function\s+countLabel\(|const\s+countLabel\s*=)",
        re.MULTILINE,
    ),
    "getPnlColor": re.compile(
        r"^\s*(?:export\s+)?(?:function\s+getPnlColor\(|const\s+getPnlColor\s*=)",
        re.MULTILINE,
    ),
    "formatPeriod": re.compile(
        r"^\s*(?:export\s+)?(?:function\s+formatPeriod\(|const\s+formatPeriod\s*=)",
        re.MULTILINE,
    ),
    "isActive": re.compile(
        r"^\s*(?:export\s+)?(?:function\s+isActive\(|const\s+isActive\s*=)",
        re.MULTILINE,
    ),
    "formatCurrency": re.compile(
        r"^\s*(?:export\s+)?(?:function\s+formatCurrency\(|const\s+formatCurrency\s*=)",
        re.MULTILINE,
    ),
}

# The one canonical home each helper is allowed to be defined in
# (repo-relative, POSIX-style).
_CANONICAL_HOME = {
    "countLabel": "apps/frontend/src/lib/statusLabels.ts",
    "getPnlColor": None,  # renamed to pnlColorClass; zero definitions allowed anywhere
    "formatPeriod": "apps/frontend/src/lib/date.ts",
    "isActive": "apps/frontend/src/components/navigation.ts",
    "formatCurrency": "apps/frontend/src/lib/audit/money/format.ts",
}


def _frontend_source_files() -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.ts", "*.tsx"):
        for path in FRONTEND_SRC.rglob(pattern):
            if "node_modules" in path.parts:
                continue
            files.append(path)
    return files


@ac_proof(
    proof_id="test_fe_helper_ssot_single_definition_per_helper",
    ac_ids=["AC-meta.fe-contract-types.4"],
    ci_tier="pr_ci",
)
def test_AC_fe_helper_ssot_1_each_helper_defined_at_most_once():
    """AC-meta.fe-contract-types.4: each single-homed helper has ≤1 definition, at its canonical home."""
    files = _frontend_source_files()
    violations: list[str] = []
    for name, pattern in _HELPER_DEFS.items():
        canonical = _CANONICAL_HOME[name]
        hits = [
            str(path.relative_to(REPO))
            for path in files
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        if canonical is None:
            if hits:
                violations.append(
                    f"{name}: must not be redefined anywhere (found in {hits})"
                )
            continue
        offenders = [h for h in hits if h != canonical]
        if offenders:
            violations.append(
                f"{name}: defined outside its canonical home {canonical}: {offenders}"
            )
        if canonical not in hits:
            violations.append(
                f"{name}: canonical home {canonical} no longer defines it (moved or renamed?)"
            )

    assert not violations, "helper single-homing regressed:\n" + "\n".join(violations)
