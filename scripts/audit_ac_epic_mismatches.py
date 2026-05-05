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

import yaml

ROOT = Path(__file__).resolve().parent.parent
AC_RE = re.compile(r"\bAC(\d+)\.(\d+)\.(\d+)\b")
EXCL_DIRS = {"node_modules", "__pycache__", ".next", "dist", ".cache", ".git", ".venv", "venv", "_ac_stubs"}
TEST_SUFFIXES = ("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")
TEST_PREFIXES = ("test_",)


def load_registry() -> dict[int, set[str]]:
    valid: dict[int, set[str]] = defaultdict(set)
    for fname in ("ac_registry.yaml", "infra_registry.yaml"):
        data = yaml.safe_load((ROOT / "docs" / fname).read_text())
        for ac in data.get("acs", []):
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
        if any(part in EXCL_DIRS for part in p.parts):
            continue
        if not is_test_file(p):
            continue
        out.append(p)
    return out


def main() -> None:
    valid = load_registry()
    files = walk_tests()
    per_file: dict[Path, Counter] = defaultdict(Counter)
    file_alt_epic: dict[Path, Counter] = defaultdict(Counter)
    total_refs = 0
    total_bad = 0
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
    print(f"# AC↔EPIC Mismatch Triage")
    print()
    print(f"- Total ACx.y.z refs scanned: **{total_refs}**")
    print(f"- Mismatched refs: **{total_bad}**")
    print(f"- Files affected: **{len(per_file)}**")
    print()
    for f, ctr in rows:
        rel = f.relative_to(ROOT)
        bad_total = sum(ctr.values())
        unique_bad = len(ctr)
        # Suggest action
        ref_epics = {int(k.split(".")[0][2:]) for k in ctr}
        primary_epic = next(iter(ref_epics)) if len(ref_epics) == 1 else None
        alt = file_alt_epic[f]
        suggest = ""
        if "scripts/tests/" in str(rel):
            suggest = "FIXTURE-EXCLUDE"
        elif primary_epic is not None and alt and alt.most_common(1)[0][1] >= bad_total * 0.6:
            tgt = alt.most_common(1)[0][0]
            suggest = f"RELOCATE-FILE → EPIC-{tgt} (or RENUMBER refs to EPIC-{tgt})"
        elif primary_epic is not None:
            suggest = f"EXTEND-REGISTRY EPIC-{primary_epic} or RENUMBER-REF"
        else:
            suggest = "MIXED — per-ref decision"
        print(f"## `{rel}` — {bad_total} bad / {unique_bad} unique")
        print(f"- **Suggest**: {suggest}")
        if alt:
            alt_str = ", ".join(f"EPIC-{e}:{c}" for e, c in alt.most_common())
            print(f"- Alt-epic matches: {alt_str}")
        ids = sorted(ctr.keys(), key=lambda s: tuple(int(x) for x in s[2:].split(".")))
        print(f"- Bad IDs: {', '.join(ids)}")
        print()


if __name__ == "__main__":
    main()
