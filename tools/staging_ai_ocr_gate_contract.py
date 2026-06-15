#!/usr/bin/env python3
"""Emit the staging AI/OCR gate file list and replay counters."""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


REPO_ROOT = ROOT_DIR

SUPPLEMENTAL_LLM_FILES = [
    "tests/e2e/test_statement_upload_e2e.py",
]

REPLAY_COUNTERS = {
    "tests/e2e/test_statement_full_journey.py": {
        "uploads": 1,
        "parse_completions": 1,
        "brokerage_imports": 0,
        "report_verifications": 0,
    },
    "tests/e2e/test_brokerage_upload_to_portfolio_value.py": {
        "uploads": 2,
        "parse_completions": 2,
        "brokerage_imports": 2,
        "report_verifications": 0,
    },
    "tests/e2e/test_four_asset_net_worth_golden_path.py": {
        "uploads": 2,
        "parse_completions": 2,
        "brokerage_imports": 1,
        "report_verifications": 1,
    },
    "tests/e2e/test_personal_financial_report_package.py": {
        "uploads": 2,
        "parse_completions": 2,
        "brokerage_imports": 1,
        "report_verifications": 1,
    },
    "tests/e2e/test_statement_upload_e2e.py": {
        "uploads": 2,
        "parse_completions": 2,
        "brokerage_imports": 0,
        "report_verifications": 0,
    },
}


def _load_matrix() -> dict[str, Any]:
    """Build the critical proof matrix payload in-memory from the AC graph.

    The matrix is a derived (not committed) view of the one AC-keyed graph, so
    the llm-marked post-merge proofs that drive the staging gate come straight
    from the co-located ``@ac_proof`` decorators (a pure static AST scan, no test
    imports), not from a checked-in YAML file.
    """
    from common.ssot.ac_graph import build_ac_graph
    from common.ssot.generate_critical_proof_matrix import build_matrix_from_graph

    return build_matrix_from_graph(build_ac_graph(REPO_ROOT))


def gate_files() -> list[str]:
    matrix = _load_matrix()
    proof_files = {
        proof["file"]
        for proof in matrix.get("proofs", [])
        if proof.get("ci_tier") == "post_merge_environment" and "llm" in proof.get("required_markers", [])
    }
    files = sorted(proof_files | set(SUPPLEMENTAL_LLM_FILES))
    missing_counters = [path for path in files if path not in REPLAY_COUNTERS]
    if missing_counters:
        raise SystemExit("Missing staging AI/OCR replay counters for: " + ", ".join(sorted(missing_counters)))
    return files


def totals(files: list[str]) -> dict[str, int]:
    keys = ("uploads", "parse_completions", "brokerage_imports", "report_verifications")
    return {key: sum(REPLAY_COUNTERS[path][key] for path in files) for key in keys}


def emit_shell() -> str:
    files = gate_files()
    counts = totals(files)
    quoted_files = " ".join(shlex.quote(path) for path in files)
    lines = [
        f"STAGING_AI_OCR_TESTS=({quoted_files})",
        f"STAGING_AI_OCR_EXPECTED_UPLOADS={counts['uploads']}",
        f"STAGING_AI_OCR_EXPECTED_PARSE_COMPLETIONS={counts['parse_completions']}",
        f"STAGING_AI_OCR_EXPECTED_BROKERAGE_IMPORTS={counts['brokerage_imports']}",
        f"STAGING_AI_OCR_EXPECTED_REPORT_VERIFICATIONS={counts['report_verifications']}",
    ]
    return "\n".join(lines)


def summarize_junit(xml_paths: list[Path]) -> dict[str, Any]:
    """Summarize JUnit XML results into pass/fail counts + the failed test names.

    The gate previously reported a binary "Failures observed: 1+" with all verified
    counts "unknown" on any failure (#1089), so a red gate gave no signal about
    *which* of the corpus docs failed. This parses the JUnit output the gate already
    writes so the summary is actionable.
    """
    total = passed = failed = skipped = 0
    failed_tests: list[str] = []
    for path in xml_paths:
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        # Handle both <testsuites><testsuite>... and a bare <testsuite> root.
        suites = root.iter("testsuite")
        for suite in suites:
            for case in suite.iter("testcase"):
                total += 1
                failure = case.find("failure")
                error = case.find("error")
                if case.find("skipped") is not None:
                    skipped += 1
                elif failure is not None or error is not None:
                    failed += 1
                    name = case.get("classname", "")
                    case_name = case.get("name", "<unknown>")
                    failed_tests.append(f"{name}::{case_name}" if name else case_name)
                else:
                    passed += 1
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "failed_tests": failed_tests,
    }


def render_junit_summary(summary: dict[str, Any]) -> str:
    """Render a markdown block of the JUnit summary for the GitHub step summary."""
    lines = [
        "### Staging AI/OCR gate — observed results",
        "",
        f"- Tests: {summary['total']} | passed: {summary['passed']} "
        f"| failed: {summary['failed']} | skipped: {summary['skipped']}",
    ]
    if summary["failed_tests"]:
        lines.append("- Failed:")
        lines.extend(f"  - `{name}`" for name in summary["failed_tests"])
    else:
        lines.append("- Failed: none")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell", action="store_true", help="Emit bash assignments.")
    parser.add_argument(
        "--summarize-junit",
        nargs="+",
        type=Path,
        metavar="XML",
        help="Summarize JUnit result XML into pass/fail counts + failed test names.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.shell:
        print(emit_shell())
        return 0

    if args.summarize_junit:
        print(render_junit_summary(summarize_junit(args.summarize_junit)))
        return 0

    files = gate_files()
    counts = totals(files)
    print("Staging AI/OCR gate files:")
    for path in files:
        print(f"- {path}")
    print("Expected replay counters:")
    for key, value in counts.items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
