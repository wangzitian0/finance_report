#!/usr/bin/env python3
"""Mechanical generator for AC-to-test traceability audit artifacts.

Joins the feature and infra AC registries against every test reference found
in the configured test directories and emits a complete Markdown report.
This is a reference metric, not behavioral coverage: a referenced AC proves
traceability only, while the owning test still has to assert the real behavior.

The output is fully mechanical: running this script twice must produce an
identical artifact (modulo the generation date) when run with the same
registries and test directories. CI uploads the generated audit as an artifact;
``--check`` remains available for local artifact validation.

Usage::

    # Generate an ignored local audit artifact
    python scripts/build_ac_traceability.py

    # Local guard: fail (exit 1) if the chosen artifact would change
    # (date-line ignored)
    python scripts/build_ac_traceability.py --output tmp/AC-TEST-TRACEABILITY-AUDIT.md --check

    # Write to a different path, as CI does for uploaded artifacts
    python scripts/build_ac_traceability.py --output /tmp/audit.md
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import NamedTuple

from ac_traceability_refs import AC_PATTERN, classify_reference_file

try:
    from ac_registry_format import load_registry_entries
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
    REPO_ROOT / "tests" / "e2e",
)
DEFAULT_OUTPUT = REPO_ROOT / "tmp" / "AC-TEST-TRACEABILITY-AUDIT.md"

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


@dataclass
class ACReferenceStats:
    real_files: set[Path] = field(default_factory=set)
    placeholder_files: set[Path] = field(default_factory=set)
    stub_files: set[Path] = field(default_factory=set)

    @property
    def all_files(self) -> set[Path]:
        return self.real_files | self.placeholder_files | self.stub_files

    def files_for_report(self) -> list[tuple[str, Path]]:
        rows: list[tuple[str, Path]] = []
        rows.extend(("real", path) for path in sorted(self.real_files))
        rows.extend(("placeholder", path) for path in sorted(self.placeholder_files))
        rows.extend(("stub", path) for path in sorted(self.stub_files))
        return rows


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_registry(path: Path) -> list[AC]:
    if not path.exists():
        print(f"ERROR: registry not found: {path}", file=sys.stderr)
        sys.exit(1)
    out: list[AC] = []
    for entry in load_registry_entries(path):
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


def collect_references(test_files: list[Path]) -> dict[str, ACReferenceStats]:
    """Return reference stats keyed by AC ID."""
    refs: dict[str, ACReferenceStats] = defaultdict(ACReferenceStats)
    for fpath in test_files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        kind = classify_reference_file(fpath, content)
        for m in AC_PATTERN.finditer(content):
            stats = refs[m.group(0)]
            if kind == "stub":
                stats.stub_files.add(fpath)
            elif kind == "placeholder":
                stats.placeholder_files.add(fpath)
            else:
                stats.real_files.add(fpath)
    return dict(refs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ac_sort_key(ac_id: str) -> tuple[int, ...]:
    """Sort ACs numerically (AC1.2.10 after AC1.2.9)."""
    return tuple(int(p) for p in ac_id[2:].split("."))


_DEPRECATED_PATTERN = re.compile(r"^~~.+~~$", re.DOTALL)


def _is_deprecated(ac: AC) -> bool:
    """Return True if the AC description uses Markdown strikethrough (~~text~~)."""
    return bool(_DEPRECATED_PATTERN.match(ac.description.strip()))


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
    references: dict[str, ACReferenceStats],
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
    deprecated_ids = {ac.id for ac in acs if _is_deprecated(ac)}
    mandatory_acs = [ac for ac in acs if ac.mandatory and ac.id not in deprecated_ids]
    deprecated_count = len(deprecated_ids)
    real_covered_ids = {
        ac.id
        for ac in mandatory_acs
        if references.get(ac.id) and references[ac.id].real_files
    }
    placeholder_only_ids = {
        ac.id
        for ac in mandatory_acs
        if references.get(ac.id)
        and not references[ac.id].real_files
        and references[ac.id].placeholder_files
    }
    stub_only_ids = {
        ac.id
        for ac in mandatory_acs
        if references.get(ac.id)
        and not references[ac.id].real_files
        and not references[ac.id].placeholder_files
        and references[ac.id].stub_files
    }
    missing_ids = {
        ac.id
        for ac in mandatory_acs
        if not references.get(ac.id) or not references[ac.id].all_files
    }
    manual_count = sum(
        1 for ac in acs if _is_manual(ac) and ac.id not in deprecated_ids
    )
    test_files_referenced = sorted(
        {path for stats in references.values() for path in stats.all_files}
    )
    coverage_pct = (
        (len(real_covered_ids) / len(mandatory_acs) * 100.0) if mandatory_acs else 100.0
    )

    lines: list[str] = []

    # ---- Header ----
    lines.append("# AC-to-Test Traceability Audit")
    lines.append("")
    lines.append(
        f"> **Generated**: {today} (mechanically by `scripts/build_ac_traceability.py`)"
    )
    lines.append(
        "> **Purpose**: Complete mapping of every Acceptance Criterion "
        "(`ACx.y.z`) declared in `docs/ac_registry.yaml` + "
        "`docs/infra_registry.yaml` to the test file(s) that reference it. "
        "This is not behavioral coverage; it separates real test candidates "
        "from `_ac_stubs`, trivial placeholder assertions, pure `pass`, and "
        "pure skipped tests so product-level E2E evidence remains the source "
        "of behavioral proof."
    )
    lines.append(
        "> **Scope**: All EPICs in `docs/project/`. Test scan: "
        + ", ".join(f"`{_rel(d)}`" for d in test_dirs)
        + "."
    )
    lines.append("")
    lines.append(
        "> ⚙️ **Do not edit this artifact by hand.** It is regenerated by "
        "`scripts/build_ac_traceability.py`. CI uploads the generated audit "
        "as an artifact; retired checked-in snapshots are indexed in "
        "[#548](https://github.com/wangzitian0/finance_report/issues/548). "
        "Update the registries or add an `ACx.y.z` reference inside a test "
        "file, then re-run the builder when refreshing local proof output."
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
    lines.append(
        f"| **Mandatory ACs** | {len(mandatory_acs)} | "
        f"{len(mandatory_acs) / total_acs * 100:.1f}% |"
        if total_acs
        else "| **Mandatory ACs** | 0 | 0% |"
    )
    lines.append(
        f"| **Deprecated ACs** | {deprecated_count} | "
        f"{(deprecated_count / total_acs * 100.0) if total_acs else 0.0:.1f}% |"
    )
    lines.append(
        f"| **Mandatory ACs with real test reference** | {len(real_covered_ids)} | "
        f"{coverage_pct:.1f}% |"
    )
    lines.append(
        f"| **Mandatory ACs with only placeholder reference** | "
        f"{len(placeholder_only_ids)} | - |"
    )
    lines.append(
        f"| **Mandatory ACs with only stub reference** | {len(stub_only_ids)} | - |"
    )
    lines.append(
        f"| **Mandatory ACs without any test reference** | {len(missing_ids)} | - |"
    )
    lines.append(f"| **Test files referenced** | {len(test_files_referenced)} | - |")
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
        "| EPIC | Name | Total ACs | Deprecated | Mandatory | Real Ref | Placeholder-only | Stub-only | Missing | Real Coverage |"
    )
    lines.append(
        "|------|------|-----------|------------|-----------|----------|------------------|-----------|---------|---------------|"
    )
    for epic_num in sorted(by_epic):
        epic_acs = by_epic[epic_num]
        dep_count = sum(1 for ac in epic_acs if ac.id in deprecated_ids)
        mand = [ac for ac in epic_acs if ac.mandatory and ac.id not in deprecated_ids]
        real_cov = sum(
            1 for ac in mand if references.get(ac.id) and references[ac.id].real_files
        )
        placeholder_only = sum(1 for ac in mand if ac.id in placeholder_only_ids)
        stub_only = sum(1 for ac in mand if ac.id in stub_only_ids)
        missing = sum(1 for ac in mand if ac.id in missing_ids)
        pct = (real_cov / len(mand) * 100.0) if mand else 100.0
        slug = _slug(epic_num, epic_names[epic_num])
        lines.append(
            f"| [EPIC-{epic_num:03d}](#{slug}) | "
            f"{_md_escape(epic_names[epic_num])} | "
            f"{len(epic_acs)} | {dep_count} | {len(mand)} | {real_cov} | "
            f"{placeholder_only} | {stub_only} | {missing} | {pct:.1f}% |"
        )
    lines.append("")
    lines.append("---")
    lines.append("")

    # ---- Per-EPIC detailed tables ----
    for epic_num in sorted(by_epic):
        epic_acs = by_epic[epic_num]
        dep_in_epic = sum(1 for ac in epic_acs if ac.id in deprecated_ids)
        mand = [ac for ac in epic_acs if ac.mandatory and ac.id not in deprecated_ids]
        real_cov = sum(
            1 for ac in mand if references.get(ac.id) and references[ac.id].real_files
        )
        pct = (real_cov / len(mand) * 100.0) if mand else 100.0
        slug = _slug(epic_num, epic_names[epic_num])

        lines.append(f"## 📋 EPIC-{epic_num:03d}: {epic_names[epic_num]}")
        lines.append("")
        lines.append(f'<a id="{slug}"></a>')
        lines.append("")
        lines.append(f"- **Total ACs**: {len(epic_acs)}")
        if dep_in_epic:
            lines.append(f"- **Deprecated ACs**: {dep_in_epic}")
        lines.append(f"- **Mandatory ACs**: {len(mand)}")
        lines.append(
            f"- **Mandatory ACs with real test reference**: {real_cov} ({pct:.1f}%)"
        )
        lines.append(
            f"- **Mandatory ACs with only placeholder reference**: "
            f"{sum(1 for ac in mand if ac.id in placeholder_only_ids)}"
        )
        lines.append(
            f"- **Mandatory ACs with only stub reference**: "
            f"{sum(1 for ac in mand if ac.id in stub_only_ids)}"
        )
        lines.append(
            f"- **Mandatory ACs without any test reference**: "
            f"{sum(1 for ac in mand if ac.id in missing_ids)}"
        )
        lines.append("")
        lines.append("| AC ID | Mandatory | Description | Test References | Status |")
        lines.append("|-------|-----------|-------------|-----------------|--------|")
        for ac in epic_acs:
            if ac.id in deprecated_ids:
                refs_cell = "_n/a_"
                status = "🚫 deprecated"
                mandatory_cell = "deprecated"
            else:
                stats = references.get(ac.id, ACReferenceStats())
                report_paths = stats.files_for_report()
                if report_paths:
                    refs_cell = "<br>".join(
                        f"{kind}: `{_rel(path)}`" for kind, path in report_paths
                    )
                    if ac.mandatory:
                        if stats.real_files:
                            status = "✅ real"
                        elif stats.placeholder_files:
                            status = "🧪 placeholder-only"
                        else:
                            status = "🧱 stub-only"
                    else:
                        if stats.real_files:
                            status = "✅ real (optional)"
                        elif stats.placeholder_files:
                            status = "🧪 placeholder-only (optional)"
                        else:
                            status = "🧱 stub-only (optional)"
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
    lines.append("# Generate an ignored local artifact")
    lines.append("python scripts/build_ac_traceability.py")
    lines.append("")
    lines.append("# Local guard (exit 1 if the chosen artifact would change)")
    lines.append(
        "python scripts/build_ac_traceability.py --output tmp/AC-TEST-TRACEABILITY-AUDIT.md --check"
    )
    lines.append("")
    lines.append("# CI artifact preview")
    lines.append(
        "python scripts/build_ac_traceability.py --output /tmp/AC-TEST-TRACEABILITY-AUDIT.md"
    )
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
            "Defaults to apps/backend/tests + apps/frontend/src + scripts/tests + tests/e2e."
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
        _DATE_LINE_RE.sub("> **Generated**: DATE", line) for line in text.splitlines()
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
                f"python scripts/build_ac_traceability.py --output {args.output}",
                file=sys.stderr,
            )
            return 1
        existing = args.output.read_text(encoding="utf-8")
        if _strip_date(existing) != _strip_date(rendered):
            print(
                f"ERROR: {args.output} is stale.\n"
                f"  Run: python scripts/build_ac_traceability.py --output {args.output}",
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
