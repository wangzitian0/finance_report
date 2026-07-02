#!/usr/bin/env python3
"""Audit cross-EPIC AC mismatches in test files.

For each ACx.y.z reference in a test file, verify that it exists in the
union of ac_registry.yaml + infra_registry.yaml under EPIC-x.

Outputs a structured report grouped by file with suggested action per ref:
  - RELOCATE-FILE: file references many ACs from another single epic; move file
  - RENUMBER-REF:  AC id likely renumbered or stale; fix the ref
  - EXTEND-REGISTRY: ref is plausible but missing from registry
  - FIXTURE-EXCLUDE: synthetic test-of-tests fixture; exclude from lint scope
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path

from common.testing.ac_registry_format import load_registry_entries

ROOT = Path(__file__).resolve().parents[2]
AC_RE = re.compile(r"\bAC(\d+)\.(\d+)\.(\d+)\b")
EXCL_DIRS = {
    "node_modules",
    "__pycache__",
    ".next",
    "dist",
    ".cache",
    ".git",
    ".venv",
    "venv",
    "_ac_stubs",
    "tmp",
}
TEST_SUFFIXES = ("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")
TEST_PREFIXES = ("test_",)


def load_registry() -> dict[int, set[str]]:
    valid: dict[int, set[str]] = defaultdict(set)
    for fname in ("ac_registry.yaml", "infra_registry.yaml"):
        for ac in load_registry_entries(ROOT / "docs" / fname):
            valid[int(ac["epic"])].add(ac["id"])
    return valid


def is_test_file(p: Path) -> bool:
    n = p.name
    return n.startswith(TEST_PREFIXES) or n.endswith(TEST_SUFFIXES)


def walk_tests() -> list[Path]:
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT)
        if any(part in EXCL_DIRS for part in rel.parts):
            continue
        if not is_test_file(p):
            continue
        out.append(p)
    return out


def is_fixture_test_file(path: Path) -> bool:
    """Return True for tooling tests that intentionally embed fake AC IDs."""
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        return False
    return len(rel.parts) >= 2 and rel.parts[0] == "tests" and rel.parts[1] == "tooling"


def print_rows(
    rows: list[tuple[Path, Counter]],
    file_alt_epic: dict[Path, Counter],
) -> None:
    for f, ctr in rows:
        rel = f.relative_to(ROOT)
        bad_total = sum(ctr.values())
        unique_bad = len(ctr)
        ref_epics = {int(k.split(".")[0][2:]) for k in ctr}
        primary_epic = next(iter(ref_epics)) if len(ref_epics) == 1 else None
        alt = file_alt_epic[f]
        suggest = ""
        if is_fixture_test_file(f):
            suggest = "FIXTURE-EXCLUDE"
        elif (
            primary_epic is not None
            and alt
            and alt.most_common(1)[0][1] >= bad_total * 0.6
        ):
            tgt = alt.most_common(1)[0][0]
            suggest = f"RELOCATE-FILE -> EPIC-{tgt} (or RENUMBER refs to EPIC-{tgt})"
        elif primary_epic is not None:
            suggest = f"EXTEND-REGISTRY EPIC-{primary_epic} or RENUMBER-REF"
        else:
            suggest = "MIXED - per-ref decision"
        print(f"## `{rel}` — {bad_total} bad / {unique_bad} unique")
        print(f"- **Suggest**: {suggest}")
        if alt:
            alt_str = ", ".join(f"EPIC-{e}:{c}" for e, c in alt.most_common())
            print(f"- Alt-epic matches: {alt_str}")
        ids = sorted(ctr.keys(), key=lambda s: tuple(int(x) for x in s[2:].split(".")))
        print(f"- Bad IDs: {', '.join(ids)}")
        print()


def main() -> None:
    valid = load_registry()
    files = walk_tests()
    per_file: dict[Path, Counter] = defaultdict(Counter)
    fixture_per_file: dict[Path, Counter] = defaultdict(Counter)
    file_alt_epic: dict[Path, Counter] = defaultdict(Counter)
    total_refs = 0
    total_bad = 0
    fixture_bad = 0
    for f in files:
        try:
            text = f.read_text(errors="ignore")
        except Exception:
            continue
        for m in AC_RE.finditer(text):
            total_refs += 1
            epic, sec, item = int(m.group(1)), int(m.group(2)), int(m.group(3))
            ac_id = f"AC{epic}.{sec}.{item}"
            if ac_id in valid.get(epic, set()):
                continue
            if is_fixture_test_file(f):
                fixture_bad += 1
                fixture_per_file[f][ac_id] += 1
            else:
                total_bad += 1
                per_file[f][ac_id] += 1
            # which other epics contain this exact y.z?
            for other_epic, ids in valid.items():
                if other_epic == epic:
                    continue
                cand = f"AC{other_epic}.{sec}.{item}"
                if cand in ids:
                    file_alt_epic[f][other_epic] += 1
    # Sort files by bad-ref count desc
    rows = sorted(per_file.items(), key=lambda kv: -sum(kv[1].values()))
    fixture_rows = sorted(fixture_per_file.items(), key=lambda kv: -sum(kv[1].values()))
    print("# AC↔EPIC Mismatch Triage")
    print()
    print(f"- Total ACx.y.z refs scanned: **{total_refs}**")
    print(f"- Actionable mismatched refs: **{total_bad}**")
    print(f"- Fixture-only mismatched refs: **{fixture_bad}**")
    print(f"- Actionable files affected: **{len(per_file)}**")
    print(f"- Fixture-only files affected: **{len(fixture_per_file)}**")
    print()
    if rows:
        print("## Actionable Mismatches")
        print()
        print_rows(rows, file_alt_epic)
    if fixture_rows:
        print("## Fixture-Only Mismatches")
        print()
        print_rows(fixture_rows, file_alt_epic)


if __name__ == "__main__":
    main()
