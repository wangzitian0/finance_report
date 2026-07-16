"""CLI entrypoint (runs all checks)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from common.testing.lint_doc_consistency import _base
from common.testing.lint_doc_consistency._checks import (
    check_code_owned_coverage_threshold_doc,
    check_epic_anchors,
    check_epic_to_registry,
    check_frontend_raw_fetch_usage,
    check_generated_analysis_snapshots_absent,
    check_mkdocs_nav_coverage,
    check_module_readmes_are_thin,
    check_no_ac_test_exceptions,
    check_no_e2e_product_test_exceptions,
    check_orphan_vision_anchors,
    check_proof_placement_policy,
    check_reconciliation_thresholds_are_code_owned,
    check_registry_to_epic,
    check_registry_to_tests,
    check_test_id_epic_alignment,
)
from common.testing.lint_doc_consistency._parsing import (
    collect_ac_refs_in_epics,
    collect_ac_refs_in_tests,
    list_epic_files,
    load_registry_acs,
    parse_vision_anchors,
)
from common.testing.lint_doc_consistency._types import Violation


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Lint vision <-> EPIC <-> AC registry <-> test consistency.")
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print summary statistics even on success.",
    )
    args = parser.parse_args(argv)

    if not _base.VISION_PATH.exists():
        print(f"ERROR: vision.md not found at {_base.VISION_PATH}", file=sys.stderr)
        return 1
    if not _base.EPIC_DIR.exists():
        print(f"ERROR: EPIC directory not found at {_base.EPIC_DIR}", file=sys.stderr)
        return 1

    vision_text = _base.VISION_PATH.read_text(encoding="utf-8")
    vision_anchors = parse_vision_anchors(vision_text)

    epic_files = list_epic_files()
    if not epic_files:
        print(
            f"ERROR: no EPIC-*.md files matched in {_base.EPIC_DIR}",
            file=sys.stderr,
        )
        return 1

    feature_acs = load_registry_acs(_base.AC_REGISTRY)
    infra_acs = load_registry_acs(_base.INFRA_REGISTRY)
    all_acs = feature_acs + infra_acs
    registry_ids = {ac["id"] for ac in all_acs if ac.get("id")}

    epic_refs = collect_ac_refs_in_epics(epic_files)
    test_refs = collect_ac_refs_in_tests(_base.TEST_ROOTS)

    violations: list[Violation] = []

    check1, epic_to_slug = check_epic_anchors(epic_files, vision_anchors)
    violations.extend(check1)
    violations.extend(check_orphan_vision_anchors(vision_anchors, epic_to_slug))
    violations.extend(check_registry_to_epic(all_acs, epic_refs))
    violations.extend(check_epic_to_registry(epic_refs, registry_ids))
    violations.extend(check_registry_to_tests(all_acs, test_refs))
    violations.extend(check_test_id_epic_alignment(all_acs, test_refs))
    violations.extend(check_proof_placement_policy())
    violations.extend(check_no_ac_test_exceptions())
    violations.extend(check_no_e2e_product_test_exceptions())
    violations.extend(check_code_owned_coverage_threshold_doc())
    violations.extend(check_mkdocs_nav_coverage())
    violations.extend(check_module_readmes_are_thin())
    violations.extend(check_generated_analysis_snapshots_absent())
    violations.extend(check_reconciliation_thresholds_are_code_owned())
    violations.extend(check_frontend_raw_fetch_usage())

    if args.verbose or violations:
        print("=" * 72)
        print("Doc consistency lint (tools/lint_doc_consistency.py)")
        print("=" * 72)
        print(f"  EPIC files scanned         : {len(epic_files)}")
        print(f"  vision.md HTML anchors     : {len(vision_anchors)}")
        print(f"  Feature ACs in registry    : {len(feature_acs)}")
        print(f"  Infra ACs in registry      : {len(infra_acs)}")
        print(f"  Distinct AC IDs in EPICs   : {len(epic_refs)}")
        print(f"  Distinct AC IDs in tests   : {len(test_refs)}")
        print()

    if not violations:
        if args.verbose:
            print("OK: doc consistency lint passed.")
        return 0

    grouped: dict[str, list[Violation]] = {}
    for violation in violations:
        grouped.setdefault(violation.check, []).append(violation)

    print(
        f"FAIL: doc consistency lint found {len(violations)} violation(s) "
        f"across {len(grouped)} check(s).",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    for check_name in sorted(grouped):
        items = grouped[check_name]
        print(f"[{check_name}] {len(items)} violation(s):", file=sys.stderr)
        for violation in items:
            print(f"  - {violation.message}", file=sys.stderr)
        print("", file=sys.stderr)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
