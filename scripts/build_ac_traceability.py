#!/usr/bin/env python3
"""Mechanical regenerator for ``docs/project/AC-TEST-TRACEABILITY-AUDIT.md``.

Joins the feature and infra AC registries against every test reference found
in the configured test directories and emits a complete Markdown report.

The output is fully mechanical: running this script twice must produce an
identical file (modulo the generation date) when run with the same
registries and test directories.  CI calls it in ``--check`` mode; the
date line is normalised away during comparison so re-running CI on a
later day does not create spurious failures.

Usage::

    # Regenerate the audit doc in place
    python scripts/build_ac_traceability.py

    # CI mode: fail (exit 1) if the file would change (date-line ignored)
    python scripts/build_ac_traceability.py --check

    # Write to a different path (for diffing/preview)
    python scripts/build_ac_traceability.py --output /tmp/audit.md
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import NamedTuple

try:
    import yaml
except ImportError:  # pragma: no cover - import guard
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration (mirrors scripts/check_ac_traceability.py)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_FEATURE_REGISTRY = REPO_ROOT / "docs" / "ac_registry.yaml"
DEFAULT_INFRA_REGISTRY = REPO_ROOT / "docs" / "infra_registry.yaml"
DEFAULT_TEST_DIRS = (
    REPO_ROOT / "apps" / "backend" / "tests",
    REPO_ROOT / "apps" / "frontend" / "src",
    REPO_ROOT / "scripts" / "tests",
)
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "project" / "AC-TEST-TRACEABILITY-AUDIT.md"

AC_PATTERN = re.compile(r"\bAC(\d+)\.(\d+)\.(\d+)\b")
EXCLUDED_DIRS = {"node_modules", "__pycache__", ".next", "dist", ".cache"}

_DATE_LINE_RE = re.compile(r"^> \*\*Generated\*\*: \d{4}-\d{2}-\d{2}")
TEST_FILE_SUFFIXES = ("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")

# Heuristic: treat ACs whose description mentions any of these tokens as
# "manual verification" so the executive summary can surface them.
MANUAL_TOKENS = (
    "manual verification",
    "manual check",
    "manually verify",
    "manually verified",
    "deployment",
    "production deploy",
)


class AC(NamedTuple):
    id: str
    epic: int
    epic_name: str
    description: str
    mandatory: bool


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_registry(path: Path) -> list[AC]:
    if not path.exists():
        print(f"ERROR: registry not found: {path}", file=sys.stderr)
        sys.exit(1)
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    out: list[AC] = []
    for entry in data.get("acs", []):
        out.append(
            AC(
                id=entry["id"],
                epic=int(entry["epic"]),
                epic_name=str(entry.get("epic_name", "")),
                description=str(entry.get("description", "")),
                mandatory=bool(entry.get("mandatory", True)),
            )
        )
    return out


def load_all_acs(feature_registry: Path, infra_registry: Path) -> list[AC]:
    """Load both registries, deduplicated by AC ID (feature wins on conflict)."""
    seen: set[str] = set()
    combined: list[AC] = []
    for path in (feature_registry, infra_registry):
        for ac in _load_registry(path):
            if ac.id in seen:
                continue
            seen.add(ac.id)
            combined.append(ac)
    return combined


# ---------------------------------------------------------------------------
# Test discovery
# ---------------------------------------------------------------------------


def find_test_files(test_dirs: list[Path]) -> list[Path]:
    found: list[Path] = []
    for base in test_dirs:
        if not base.exists():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            for fname in files:
                if fname.startswith("test_") or fname.endswith(TEST_FILE_SUFFIXES):
                    found.append(Path(root) / fname)
    return sorted(found)


def collect_references(test_files: list[Path]) -> dict[str, list[Path]]:
    """Return ``{ac_id: [test_file_path, ...]}`` (each path appears at most once per AC)."""
    refs: dict[str, set[Path]] = defaultdict(set)
    for fpath in test_files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in AC_PATTERN.finditer(content):
            refs[m.group(0)].add(fpath)
    # Convert to sorted lists for deterministic output.
    return {ac_id: sorted(paths) for ac_id, paths in refs.items()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ac_sort_key(ac_id: str) -> tuple[int, ...]:
    """Sort ACs numerically (AC1.2.10 after AC1.2.9)."""
    return tuple(int(p) for p in ac_id[2:].split("."))


def _is_manual(ac: AC) -> bool:
    desc = ac.description.lower()
    return any(tok in desc for tok in MANUAL_TOKENS)


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _md_escape(text: str) -> str:
    """Escape characters that would break a Markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _slug(epic_num: int, epic_name: str) -> str:
    base = f"epic-{epic_num:03d}"
    if epic_name:
        suffix = re.sub(r"[^a-z0-9]+", "-", epic_name.lower()).strip("-")
        if suffix:
            return f"{base}-{suffix}"
    return base


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_document(
    acs: list[AC],
    references: dict[str, list[Path]],
    test_dirs: list[Path],
    today: str,
) -> str:
    # Group ACs by EPIC.
    by_epic: dict[int, list[AC]] = defaultdict(list)
    for ac in acs:
        by_epic[ac.epic].append(ac)
    for epic_acs in by_epic.values():
        epic_acs.sort(key=lambda a: _ac_sort_key(a.id))

    # Resolve a canonical EPIC name per epic number (first non-empty, else "EPIC-NNN").
    epic_names: dict[int, str] = {}
    for epic_num, epic_acs in by_epic.items():
        for ac in epic_acs:
            if ac.epic_name:
                epic_names[epic_num] = ac.epic_name
                break
        epic_names.setdefault(epic_num, f"EPIC-{epic_num:03d}")

    total_acs = len(acs)
    mandatory_acs = [ac for ac in acs if ac.mandatory]
    covered_ids = {ac.id for ac in mandatory_acs if ac.id in references}
    missing_ids = {ac.id for ac in mandatory_acs if ac.id not in references}
    manual_count = sum(1 for ac in acs if _is_manual(ac))
    test_files_referenced = sorted({p for paths in references.values() for p in paths})
    coverage_pct = (
        (len(covered_ids) / len(mandatory_acs) * 100.0) if mandatory_acs else 100.0
    )

    lines: list[str] = []

    # ---- Header ----
    lines.append("# AC-to-Test Traceability Audit")
    lines.append("")
    lines.append(
        f"> **Generated**: {today} (mechanically by "
        "`scripts/build_ac_traceability.py`)"
    )
    lines.append(
        "> **Purpose**: Complete mapping of every Acceptance Criterion "
        "(`ACx.y.z`) declared in `docs/ac_registry.yaml` + "
        "`docs/infra_registry.yaml` to the test file(s) that reference it."
    )
    lines.append(
        "> **Scope**: All EPICs in `docs/project/`. Test scan: "
        + ", ".join(f"`{_rel(d)}`" for d in test_dirs)
        + "."
    )
    lines.append("")
    lines.append(
        "> ⚙️ **Do not edit this file by hand.** It is regenerated by "
        "`scripts/build_ac_traceability.py` and verified in CI via "
        "`scripts/build_ac_traceability.py --check`. Update the registries "
        "or add an `ACx.y.z` reference inside a test file, then re-run the "
        "builder."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- Executive summary ----
    lines.append("## 📊 Executive Summary")
    lines.append("")
    lines.append("| Metric | Count | Percentage |")
    lines.append("|--------|-------|------------|")
    lines.append(f"| **Total EPICs** | {len(by_epic)} | 100% |")
    lines.append(f"| **Total ACs (registries)** | {total_acs} | 100% |")
    lines.append(f"| **Mandatory ACs** | {len(mandatory_acs)} | "
                 f"{len(mandatory_acs) / total_acs * 100:.1f}% |"
                 if total_acs else "| **Mandatory ACs** | 0 | 0% |")
    lines.append(
        f"| **Mandatory ACs with test reference** | {len(covered_ids)} | "
        f"{coverage_pct:.1f}% |"
    )
    lines.append(
        f"| **Mandatory ACs without test reference** | {len(missing_ids)} | "
        f"{(100.0 - coverage_pct):.1f}% |"
    )
    lines.append(
        f"| **Test files referenced** | {len(test_files_referenced)} | - |"
    )
    manual_pct = (manual_count / total_acs * 100.0) if total_acs else 0.0
    lines.append(
        f"| **ACs flagged as manual verification (heuristic)** | "
        f"{manual_count} | {manual_pct:.1f}% |"
    )
    lines.append("")

    # ---- Per-EPIC coverage table ----
    lines.append("### Coverage by EPIC")
    lines.append("")
    lines.append(
        "| EPIC | Name | Total ACs | Mandatory | With Test Ref | Coverage |"
    )
    lines.append(
        "|------|------|-----------|-----------|---------------|----------|"
    )
    for epic_num in sorted(by_epic):
        epic_acs = by_epic[epic_num]
        mand = [ac for ac in epic_acs if ac.mandatory]
        cov = sum(1 for ac in mand if ac.id in references)
        pct = (cov / len(mand) * 100.0) if mand else 100.0
        slug = _slug(epic_num, epic_names[epic_num])
        lines.append(
            f"| [EPIC-{epic_num:03d}](#{slug}) | "
            f"{_md_escape(epic_names[epic_num])} | "
            f"{len(epic_acs)} | {len(mand)} | {cov} | {pct:.1f}% |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- Per-EPIC detailed tables ----
    for epic_num in sorted(by_epic):
        epic_acs = by_epic[epic_num]
        mand = [ac for ac in epic_acs if ac.mandatory]
        cov = sum(1 for ac in mand if ac.id in references)
        pct = (cov / len(mand) * 100.0) if mand else 100.0
        slug = _slug(epic_num, epic_names[epic_num])

        lines.append(f"## 📋 EPIC-{epic_num:03d}: {epic_names[epic_num]}")
        lines.append("")
        lines.append(f"<a id=\"{slug}\"></a>")
        lines.append("")
        lines.append(f"- **Total ACs**: {len(epic_acs)}")
        lines.append(f"- **Mandatory ACs**: {len(mand)}")
        lines.append(f"- **Mandatory ACs with test reference**: {cov} ({pct:.1f}%)")
        lines.append("")
        lines.append("| AC ID | Mandatory | Description | Test References | Status |")
        lines.append("|-------|-----------|-------------|-----------------|--------|")
        for ac in epic_acs:
            paths = references.get(ac.id, [])
            if paths:
                refs_cell = "<br>".join(f"`{_rel(p)}`" for p in paths)
                if ac.mandatory:
                    status = "✅"
                else:
                    status = "✅ (optional)"
            else:
                refs_cell = "_none_"
                if not ac.mandatory:
                    status = "⚪ (optional, no ref)"
                elif _is_manual(ac):
                    status = "🟡 manual"
                else:
                    status = "❌ missing"
            mandatory_cell = "yes" if ac.mandatory else "no"
            lines.append(
                f"| {ac.id} | {mandatory_cell} | "
                f"{_md_escape(ac.description)} | {refs_cell} | {status} |"
            )
        lines.append("")
        lines.append("---")
        lines.append("")

    # ---- Footer ----
    lines.append("## 🔁 Regeneration")
    lines.append("")
    lines.append("```bash")
    lines.append("# Regenerate this file")
    lines.append("python scripts/build_ac_traceability.py")
    lines.append("")
    lines.append("# CI guard (exit 1 if the file would change)")
    lines.append("python scripts/build_ac_traceability.py --check")
    lines.append("```")
    lines.append("")
    lines.append(
        "Source registries: `docs/ac_registry.yaml`, "
        "`docs/infra_registry.yaml`. "
        "AC reference pattern: `ACx.y.z` (matched by `scripts/check_ac_traceability.py`)."
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Mechanically regenerate the AC -> test traceability audit document."
    )
    p.add_argument(
        "--feature-registry",
        type=Path,
        default=DEFAULT_FEATURE_REGISTRY,
        help="Path to docs/ac_registry.yaml",
    )
    p.add_argument(
        "--infra-registry",
        type=Path,
        default=DEFAULT_INFRA_REGISTRY,
        help="Path to docs/infra_registry.yaml",
    )
    p.add_argument(
        "--test-dir",
        type=Path,
        action="append",
        default=None,
        help=(
            "Directory to scan for test files (repeatable). "
            "Defaults to apps/backend/tests + apps/frontend/src + scripts/tests."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output Markdown path",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit 1 if the output file would change.",
    )
    p.add_argument(
        "--today",
        default=date.today().isoformat(),
        help="Override the generation date (for reproducible CI runs).",
    )
    return p.parse_args()


def _strip_date(text: str) -> str:
    return "\n".join(
        _DATE_LINE_RE.sub("> **Generated**: DATE", line)
        for line in text.splitlines()
    )


def main() -> int:
    args = parse_args()
    test_dirs = list(args.test_dir) if args.test_dir else list(DEFAULT_TEST_DIRS)

    acs = load_all_acs(args.feature_registry, args.infra_registry)
    test_files = find_test_files(test_dirs)
    references = collect_references(test_files)

    rendered = render_document(acs, references, test_dirs, args.today)

    if args.check:
        if not args.output.exists():
            print(
                f"ERROR: {args.output} does not exist. Run: "
                "python scripts/build_ac_traceability.py",
                file=sys.stderr,
            )
            return 1
        existing = args.output.read_text(encoding="utf-8")
        if _strip_date(existing) != _strip_date(rendered):
            print(
                f"ERROR: {args.output} is stale.\n"
                "  Run: python scripts/build_ac_traceability.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK: {args.output} is up to date.")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(
        f"Wrote {args.output} "
        f"({len(acs)} ACs across {len({ac.epic for ac in acs})} EPICs, "
        f"{len(test_files)} test files scanned)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
