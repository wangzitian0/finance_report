"""No duplicate definitions of the single-homed FE helpers (AC-meta.fe-contract-types.4, #1868 S5 PR-B).

`countLabel`/`pnlColorClass`(formerly `getPnlColor`)/`formatPeriod`/`isActive`
were each duplicated 2-3x across component files, with `formatPeriod`
already having diverged (a "→" vs "to" separator) and `getPnlColor`
byte-identical only by luck. They are now single-homed in `lib/statusLabels.ts`,
`lib/date.ts`, and `components/navigation.ts`. This gate keeps a re-duplication
from silently coming back. `formatCurrency` collided in name (not meaning)
with an amount formatter in `lib/audit/money/format.ts` — the local copy is
renamed `currencyCodeOrDash`. The amount formatter had no caller and is deleted
(#2685), so a `formatCurrency` definition anywhere would be that collision
returning.
`readinessVariant` (also unified in PR-B, from two near-duplicate
definitions whose "unhandled"/default branches assigned conflicting Badge
colors — the two source enums don't actually overlap on which states hit
that default, see `lib/statusLabels.ts`) was covered by a color-pinning
test but never by a single-definition gate — added here on #1868
root-issue closure review so G-one-readiness-language's "grep gate" half
of its guarantee is actually locked, not just true by inspection.
"""

from __future__ import annotations

import re
from pathlib import Path

from common.testing.ac_proof import ac_proof

REPO = Path(__file__).resolve().parents[2]
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
    "pnlColorClass": re.compile(
        r"^\s*(?:export\s+)?(?:function\s+pnlColorClass\(|const\s+pnlColorClass\s*=)",
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
    "readinessVariant": re.compile(
        r"^\s*(?:export\s+)?(?:function\s+readinessVariant\(|const\s+readinessVariant\s*=)",
        re.MULTILINE,
    ),
    "statementDisplayTitle": re.compile(
        r"^\s*(?:export\s+)?(?:function\s+statementDisplayTitle\(|const\s+statementDisplayTitle\s*=)",
        re.MULTILINE,
    ),
    "PARSING_POLL_MS": re.compile(
        r"^\s*(?:export\s+)?const\s+PARSING_POLL_MS\s*=",
        re.MULTILINE,
    ),
    "canImportBrokerageStatement": re.compile(
        r"^\s*(?:export\s+)?(?:function\s+canImportBrokerageStatement\(|const\s+canImportBrokerageStatement\s*=)",
        re.MULTILINE,
    ),
}

# The one canonical home each helper is allowed to be defined in
# (repo-relative, POSIX-style).
_CANONICAL_HOME = {
    "countLabel": "apps/frontend/src/lib/statusLabels.ts",
    "getPnlColor": None,  # renamed to pnlColorClass; zero definitions allowed anywhere
    "pnlColorClass": "apps/frontend/src/lib/statusLabels.ts",
    "formatPeriod": "apps/frontend/src/lib/date.ts",
    "isActive": "apps/frontend/src/components/navigation.ts",
    "formatCurrency": None,  # renamed to currencyCodeOrDash; zero definitions allowed anywhere
    "readinessVariant": "apps/frontend/src/lib/statusLabels.ts",
    "statementDisplayTitle": "apps/frontend/src/lib/statusLabels.ts",
    "PARSING_POLL_MS": "apps/frontend/src/lib/statusLabels.ts",
    "canImportBrokerageStatement": "apps/frontend/src/lib/statusLabels.ts",
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


def test_brokerage_aliases_match_between_frontend_and_backend():
    """AC-extraction.fe-stage1-review.28: frontend BROKERAGE_ALIASES matches backend _BROKER_ALIASES."""
    fe_text = (FRONTEND_SRC / "lib" / "statusLabels.ts").read_text(encoding="utf-8")
    fe_match = re.search(r"const\s+BROKERAGE_ALIASES\s*=\s*\[([^\]]+)\]", fe_text)
    assert fe_match is not None, (
        "BROKERAGE_ALIASES missing in apps/frontend/src/lib/statusLabels.ts"
    )
    fe_aliases = tuple(re.findall(r'"([^"]+)"', fe_match.group(1)))

    be_path = (
        REPO
        / "apps"
        / "backend"
        / "src"
        / "extraction"
        / "extension"
        / "brokerage_positions.py"
    )
    be_text = be_path.read_text(encoding="utf-8")
    be_match = re.search(r"_BROKER_ALIASES\s*=\s*\(([\s\S]*?)\n\)", be_text)
    assert be_match is not None, "_BROKER_ALIASES missing in brokerage_positions.py"
    be_aliases: list[str] = []
    for line in be_match.group(1).splitlines():
        tokens = re.findall(r'"([^"]+)"', line)
        if len(tokens) > 1:
            be_aliases.extend(tokens[1:])

    assert fe_aliases == tuple(be_aliases), (
        f"Frontend BROKERAGE_ALIASES {fe_aliases} drifted from backend _BROKER_ALIASES {tuple(be_aliases)}"
    )
