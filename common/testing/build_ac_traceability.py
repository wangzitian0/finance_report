#!/usr/bin/env python3
"""Mechanical generator for AC-to-test traceability audit Markdown artifacts."""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from common.meta.base.gate_util import display_path
from common.meta.extension.generate_ac_registry import sort_key
from common.testing import ac_scan
from common.testing.check_ac_traceability import (
    AC,
    classify_references,
    is_deprecated,
    load_multiple_registries,
)
from common.testing.test_surface import DEFAULT_AC_TEST_DIRS, default_ac_test_dirs

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FEATURE_REGISTRY = REPO_ROOT / "docs" / "ac_registry.yaml"
DEFAULT_INFRA_REGISTRY = REPO_ROOT / "docs" / "infra_registry.yaml"
DEFAULT_TEST_DIRS = default_ac_test_dirs(REPO_ROOT)
DEFAULT_OUTPUT = REPO_ROOT / "tmp" / "AC-TEST-TRACEABILITY-AUDIT.md"

_DATE_LINE_RE = re.compile(r"^> \*\*Generated\*\*: \d{4}-\d{2}-\d{2}")

MANUAL_TOKENS = (
    "manual verification",
    "manual check",
    "manually verify",
    "manually verified",
    "deployment",
    "production deploy",
)

ACReferenceStats = ac_scan.ACReferenceStats
find_test_files = ac_scan.find_test_files
collect_references = ac_scan.collect_references
_ac_sort_key = sort_key

_REFERENCE_STATUS = {
    "real": "✅ real",
    "placeholder": "🧪 placeholder-only",
    "stub": "🧱 stub-only",
}


def _is_manual(ac: AC) -> bool:
    desc = ac.description.lower()
    return any(tok in desc for tok in MANUAL_TOKENS)


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _slug(epic_num: int, epic_name: str) -> str:
    base = f"epic-{epic_num:03d}"
    if epic_name and (
        suffix := re.sub(r"[^a-z0-9]+", "-", epic_name.lower()).strip("-")
    ):
        return f"{base}-{suffix}"
    return base


def render_document(
    acs: list[AC],
    references: dict[str, ACReferenceStats],
    test_dirs: list[Path],
    today: str,
) -> str:
    by_epic: dict[int, list[AC]] = defaultdict(list)
    for ac in acs:
        by_epic[ac.epic].append(ac)
    for epic_acs in by_epic.values():
        epic_acs.sort(key=lambda a: _ac_sort_key(a.id))

    epic_names = {
        epic_num: next(
            (ac.epic_name for ac in epic_acs if ac.epic_name), f"EPIC-{epic_num:03d}"
        )
        for epic_num, epic_acs in by_epic.items()
    }

    total_acs = len(acs)
    deprecated_ids = {ac.id for ac in acs if is_deprecated(ac.description)}
    mandatory_acs = [ac for ac in acs if ac.mandatory and ac.id not in deprecated_ids]
    deprecated_count = len(deprecated_ids)
    kinds = {ac.id: classify_references(references.get(ac.id)) for ac in mandatory_acs}
    real_covered_ids = {ac_id for ac_id, kind in kinds.items() if kind == "real"}
    placeholder_only_ids = {
        ac_id for ac_id, kind in kinds.items() if kind == "placeholder"
    }
    stub_only_ids = {ac_id for ac_id, kind in kinds.items() if kind == "stub"}
    missing_ids = {ac_id for ac_id, kind in kinds.items() if kind == "missing"}
    manual_count = sum(
        1 for ac in acs if _is_manual(ac) and ac.id not in deprecated_ids
    )
    test_files_referenced = sorted(
        {path for stats in references.values() for path in stats.all_files}
    )
    coverage_pct = (
        len(real_covered_ids) / len(mandatory_acs) * 100.0 if mandatory_acs else 100.0
    )

    epic_Rollups = {}
    for epic_num in sorted(by_epic):
        epic_acs = by_epic[epic_num]
        mand = [ac for ac in epic_acs if ac.mandatory and ac.id not in deprecated_ids]
        real_cov = sum(1 for ac in mand if ac.id in real_covered_ids)
        epic_Rollups[epic_num] = {
            "acs": epic_acs,
            "dep": sum(1 for ac in epic_acs if ac.id in deprecated_ids),
            "mand": mand,
            "real": real_cov,
            "placeholder": sum(1 for ac in mand if ac.id in placeholder_only_ids),
            "stub": sum(1 for ac in mand if ac.id in stub_only_ids),
            "missing": sum(1 for ac in mand if ac.id in missing_ids),
            "pct": (real_cov / len(mand) * 100.0) if mand else 100.0,
            "slug": _slug(epic_num, epic_names[epic_num]),
        }

    mand_row = (
        f"| **Mandatory ACs** | {len(mandatory_acs)} | {len(mandatory_acs) / total_acs * 100:.1f}% |"
        if total_acs
        else "| **Mandatory ACs** | 0 | 0% |"
    )
    dep_pct = (deprecated_count / total_acs * 100.0) if total_acs else 0.0
    manual_pct = (manual_count / total_acs * 100.0) if total_acs else 0.0

    lines: list[str] = [
        "# AC-to-Test Traceability Audit",
        "",
        f"> **Generated**: {today} (mechanically by `tools/build_ac_traceability.py`)",
        "> **Purpose**: Complete mapping of every Acceptance Criterion "
        "(`ACx.y.z`) declared in `docs/ac_registry.yaml` + "
        "`docs/infra_registry.yaml` to the test file(s) that reference it. "
        "This is not behavioral coverage; it separates real test candidates "
        "from `_ac_stubs`, trivial placeholder assertions, pure `pass`, and "
        "pure skipped tests so product-level E2E evidence remains the source "
        "of behavioral proof.",
        "> **Scope**: All EPICs in `docs/project/`. Test scan: "
        + ", ".join(f"`{display_path(d, REPO_ROOT)}`" for d in test_dirs)
        + ".",
        "",
        "> ⚙️ **Do not edit this file by hand.** It is generated by "
        "`tools/build_ac_traceability.py`. CI uploads the generated audit "
        "as an artifact instead of committing archive content. Update the "
        "registries or add an `ACx.y.z` reference inside a test file, then "
        "re-run the builder when intentionally refreshing the artifact.",
        "",
        "---",
        "",
        "## 📊 Executive Summary",
        "",
        "| Metric | Count | Percentage |",
        "|--------|-------|------------|",
        f"| **Total EPICs** | {len(by_epic)} | 100% |",
        f"| **Total ACs (registries)** | {total_acs} | 100% |",
        mand_row,
        f"| **Deprecated ACs** | {deprecated_count} | {dep_pct:.1f}% |",
        f"| **Mandatory ACs with real test reference** | {len(real_covered_ids)} | {coverage_pct:.1f}% |",
        f"| **Mandatory ACs with only placeholder reference** | {len(placeholder_only_ids)} | - |",
        f"| **Mandatory ACs with only stub reference** | {len(stub_only_ids)} | - |",
        f"| **Mandatory ACs without any test reference** | {len(missing_ids)} | - |",
        f"| **Test files referenced** | {len(test_files_referenced)} | - |",
        f"| **ACs flagged as manual verification (heuristic)** | {manual_count} | {manual_pct:.1f}% |",
        "",
        "### Coverage by EPIC",
        "",
        "| EPIC | Name | Total ACs | Deprecated | Mandatory | Real Ref | Placeholder-only | Stub-only | Missing | Real Coverage |",
        "|------|------|-----------|------------|-----------|----------|------------------|-----------|---------|---------------|",
    ]

    for epic_num, s in epic_Rollups.items():
        lines.append(
            f"| [EPIC-{epic_num:03d}](#{s['slug']}) | "
            f"{_md_escape(epic_names[epic_num])} | "
            f"{len(s['acs'])} | {s['dep']} | {len(s['mand'])} | {s['real']} | "
            f"{s['placeholder']} | {s['stub']} | {s['missing']} | {s['pct']:.1f}% |"
        )
    lines.extend(["", "---", ""])

    for epic_num, s in epic_Rollups.items():
        lines.extend(
            [
                f"## 📋 EPIC-{epic_num:03d}: {epic_names[epic_num]}",
                "",
                f'<a id="{s["slug"]}"></a>',
                "",
                f"- **Total ACs**: {len(s['acs'])}",
                *([f"- **Deprecated ACs**: {s['dep']}"] if s["dep"] else []),
                f"- **Mandatory ACs**: {len(s['mand'])}",
                f"- **Mandatory ACs with real test reference**: {s['real']} ({s['pct']:.1f}%)",
                f"- **Mandatory ACs with only placeholder reference**: {s['placeholder']}",
                f"- **Mandatory ACs with only stub reference**: {s['stub']}",
                f"- **Mandatory ACs without any test reference**: {s['missing']}",
                "",
                "| AC ID | Mandatory | Description | Test References | Status |",
                "|-------|-----------|-------------|-----------------|--------|",
            ]
        )
        for ac in s["acs"]:
            if ac.id in deprecated_ids:
                refs_cell, status, mandatory_cell = (
                    "_n/a_",
                    "🚫 deprecated",
                    "deprecated",
                )
            else:
                stats = references.get(ac.id, ACReferenceStats())
                report_paths = stats.files_for_report()
                if report_paths:
                    refs_cell = "<br>".join(
                        f"{kind}: `{display_path(path, REPO_ROOT)}`"
                        for kind, path in report_paths
                    )
                    status = _REFERENCE_STATUS[classify_references(stats)]
                    if not ac.mandatory:
                        status += " (optional)"
                else:
                    refs_cell = "_none_"
                    status = (
                        "⚪ (optional, no ref)"
                        if not ac.mandatory
                        else ("🟡 manual" if _is_manual(ac) else "❌ missing")
                    )
                mandatory_cell = "yes" if ac.mandatory else "no"
            lines.append(
                f"| {ac.id} | {mandatory_cell} | "
                f"{_md_escape(ac.description)} | {refs_cell} | {status} |"
            )
        lines.extend(["", "---", ""])

    lines.extend(
        [
            "## 🔁 Regeneration",
            "",
            "```bash",
            "# Regenerate the ignored local artifact",
            "python tools/build_ac_traceability.py",
            "",
            "# Local guard (exit 1 if the chosen artifact would change)",
            "python tools/build_ac_traceability.py --output tmp/AC-TEST-TRACEABILITY-AUDIT.md --check",
            "",
            "# CI artifact preview",
            "python tools/build_ac_traceability.py --output /tmp/AC-TEST-TRACEABILITY-AUDIT.md",
            "```",
            "",
            "Source registries: `docs/ac_registry.yaml`, "
            "`docs/infra_registry.yaml`. "
            "AC reference pattern: `ACx.y.z` (matched by "
            "`common.testing.ac_traceability_refs.AC_PATTERN`; gated by "
            "`tools/check_ac_index.py`).",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Mechanically regenerate the AC -> test traceability audit document."
    )
    p.add_argument("--feature-registry", type=Path, default=DEFAULT_FEATURE_REGISTRY)
    p.add_argument("--infra-registry", type=Path, default=DEFAULT_INFRA_REGISTRY)
    p.add_argument(
        "--test-dir",
        type=Path,
        action="append",
        default=None,
        help="Directory to scan for test files (Defaults to "
        + " + ".join(DEFAULT_AC_TEST_DIRS)
        + ").",
    )
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument("--check", action="store_true")
    p.add_argument("--today", default=date.today().isoformat())
    return p.parse_args(argv)


def _strip_date(text: str) -> str:
    return "\n".join(
        _DATE_LINE_RE.sub("> **Generated**: DATE", line) for line in text.splitlines()
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    test_dirs = list(args.test_dir) if args.test_dir else list(DEFAULT_TEST_DIRS)
    acs = load_multiple_registries([args.feature_registry, args.infra_registry])
    test_files = find_test_files(test_dirs)
    references = collect_references(test_files)
    rendered = render_document(acs, references, test_dirs, args.today)

    if args.check:
        if not args.output.exists():
            print(
                f"ERROR: {args.output} does not exist. Run: python tools/build_ac_traceability.py",
                file=sys.stderr,
            )
            return 1
        if _strip_date(args.output.read_text(encoding="utf-8")) != _strip_date(
            rendered
        ):
            print(
                f"ERROR: {args.output} is stale.\n  Run: python tools/build_ac_traceability.py",
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
    raise SystemExit(main())
