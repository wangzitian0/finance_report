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

# The minimal production-promotion AI/OCR canary corpus (issue #1232, AC8.13.156).
# This is a hand-curated SUBSET of the derived llm post-merge corpus (gate_files):
# the smallest set that proves the real-provider upload -> parse -> import -> value
# liveness path users need in production, with NO broad audit assertions. The
# brokerage journey is the only single test that exercises `import`
# (report_verifications == 0), so it is the canary on its own. Everything else in
# the derived corpus is audit-replay (audit_replay_files = gate_files - canary),
# so a newly-added heavy `@ac_proof` journey defaults to audit-replay and can
# never silently creep into the blocking path (AC8.13.159).
CANARY_FILES = [
    "tests/e2e/test_brokerage_upload_to_portfolio_value.py",
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
    "tests/e2e/test_institution_statement_journeys.py": {
        "uploads": 4,
        "parse_completions": 4,
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

    The gate only reads ``matrix["proofs"]``, so it uses the lightweight
    ``build_proofs_only`` path (proofs + outcomes), skipping the AC-reference
    scan and the vision build the full graph performs. The observable
    proofs/outcomes payload is identical, only the startup cost is lower.
    """
    from common.testing.ac_graph import build_proofs_only
    from common.testing.generate_critical_proof_matrix import build_matrix_from_graph

    return build_matrix_from_graph(build_proofs_only(REPO_ROOT))


def gate_files() -> list[str]:
    matrix = _load_matrix()
    proof_files = {
        proof["file"]
        for proof in matrix.get("proofs", [])
        if proof.get("ci_tier") == "post_merge_environment"
        and "llm" in proof.get("required_markers", [])
    }
    files = sorted(proof_files | set(SUPPLEMENTAL_LLM_FILES))
    missing_counters = [path for path in files if path not in REPLAY_COUNTERS]
    if missing_counters:
        raise SystemExit(
            "Missing staging AI/OCR replay counters for: "
            + ", ".join(sorted(missing_counters))
        )
    return files


def canary_files() -> list[str]:
    """The minimal blocking-path AI/OCR canary corpus (AC8.13.156).

    A hand-curated subset of ``gate_files()``; fail-closed against both the
    derived corpus (every canary file must be a real llm post-merge proof or a
    supplemental) and the replay-counter source.
    """
    derived = set(gate_files())
    canary = sorted(CANARY_FILES)
    missing_from_corpus = [path for path in canary if path not in derived]
    if missing_from_corpus:
        raise SystemExit(
            "Canary files are not in the derived AI/OCR corpus: "
            + ", ".join(sorted(missing_from_corpus))
        )
    missing_counters = [path for path in canary if path not in REPLAY_COUNTERS]
    if missing_counters:
        raise SystemExit(
            "Missing staging AI/OCR replay counters for: "
            + ", ".join(sorted(missing_counters))
        )
    return canary


def audit_replay_files() -> list[str]:
    """The comprehensive nightly/manual audit-replay corpus (AC8.13.157).

    Derived by subtraction (``gate_files() - canary_files()``) so a newly-added
    heavy llm post-merge proof lands here automatically and never in the blocking
    canary (AC8.13.159).
    """
    canary = set(canary_files())
    return [path for path in gate_files() if path not in canary]


def corpus_files(corpus: str) -> list[str]:
    selectors = {
        "all": gate_files,
        "canary": canary_files,
        "audit_replay": audit_replay_files,
    }
    if corpus not in selectors:
        raise SystemExit(
            f"Unknown corpus {corpus!r}; expected one of {sorted(selectors)}"
        )
    return selectors[corpus]()


def totals(files: list[str]) -> dict[str, int]:
    keys = ("uploads", "parse_completions", "brokerage_imports", "report_verifications")
    return {key: sum(REPLAY_COUNTERS[path][key] for path in files) for key in keys}


def emit_shell(files: list[str] | None = None) -> str:
    if files is None:
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


# ── Failure attribution (#1806, AC-testing.deploy-gates.37–39) ──────────────
#
# The gate used to collapse every pytest failure into one label
# (`regression-failed`) with a hardcoded "parse quality dropped" alert body,
# although triaged reds (#1781) were FX-data gaps, provider latency, and test
# bugs — zero extraction regressions. Classify each failed case from its JUnit
# failure text so the alert carries the class, transients get one bounded
# retry, and environment-data gaps are never reported as regressions.
#
# Patterns are matched against the lowercased failure/error message + text.
# Vocabulary sources: tests/e2e conftest/journeys (parse-wait + provider
# wording) and apps/backend fx_revaluation ("Missing FX rate for ...").
TRANSIENT_FAILURE_PATTERNS = (
    "did not reach parsed within",  # provider/queue parse latency at the ceiling
    "ai service may be unavailable",  # app-side provider connectivity
    "readtimeout",
    "connecttimeout",
    "connection reset",
    "connecterror",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
)
PRECONDITION_FAILURE_PATTERNS = (
    "missing fx rate",  # FX coverage gap (the #1779 class): retry cannot fix
    "fx rate missing",
)

FAILURE_CLASS_STATUS = {
    "regression": "regression-failed",
    "precondition": "precondition-failed",
    "transient": "provider-transient",
}


def _classify_failure_text(text: str) -> str:
    lowered = text.lower()
    if any(pattern in lowered for pattern in PRECONDITION_FAILURE_PATTERNS):
        return "precondition"
    if any(pattern in lowered for pattern in TRANSIENT_FAILURE_PATTERNS):
        return "transient"
    return "regression"


def _case_file(case: ET.Element) -> str | None:
    """Best-effort repo-relative test file for a JUnit case (for targeted retry)."""
    file_attr = case.get("file")
    if file_attr and (REPO_ROOT / file_attr).exists():
        return file_attr
    classname = case.get("classname", "")
    if classname:
        candidate = classname.replace(".", "/") + ".py"
        if (REPO_ROOT / candidate).exists():
            return candidate
    return None


def classify_junit(xml_paths: list[Path]) -> dict[str, Any]:
    """Attribute every failed JUnit case to regression | precondition | transient.

    Returns the per-class case lists, the retry file targets (transient cases
    only — the only class where one bounded retry is legitimate), and the
    overall status. Precedence when classes mix: regression > precondition >
    transient — a real regression must never be masked by co-occurring noise.
    """
    cases: list[dict[str, str]] = []
    for path in xml_paths:
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError):
            continue
        for suite in root.iter("testsuite"):
            for case in suite.iter("testcase"):
                report = case.find("failure")
                if report is None:
                    report = case.find("error")
                if report is None:
                    continue
                text = f"{report.get('message', '')}\n{report.text or ''}"
                name = case.get("classname", "")
                case_name = case.get("name", "<unknown>")
                cases.append(
                    {
                        "test": f"{name}::{case_name}" if name else case_name,
                        "class": _classify_failure_text(text),
                        "file": _case_file(case) or "",
                    }
                )
    by_class = {
        key: [case for case in cases if case["class"] == key]
        for key in ("regression", "precondition", "transient")
    }
    if by_class["regression"]:
        overall = "regression"
    elif by_class["precondition"]:
        overall = "precondition"
    elif by_class["transient"]:
        overall = "transient"
    else:
        overall = "passed"
    retry_targets = sorted(
        {case["file"] for case in by_class["transient"] if case["file"]}
    )
    return {
        "cases": cases,
        "by_class": by_class,
        "overall": overall,
        "status": FAILURE_CLASS_STATUS.get(overall, "passed"),
        "retry_targets": retry_targets,
    }


_CLASS_EXPLANATIONS = {
    "regression": "app/extraction regression — needs human judgment",
    "precondition": "environment-data precondition (e.g. FX coverage) — fix the environment, not the extractor",
    "transient": "provider/queue transient (timeout / 5xx) — bounded single retry applies",
}


def render_alert_body(
    classification: dict[str, Any],
    *,
    run_id: str = "?",
    expected_sha: str = "?",
    app_url: str = "?",
) -> str:
    """Alert-issue body generated from the JUnit attribution (#1806).

    Replaces the previous hardcoded "parse quality dropped" claim, which the
    #1781 triage proved wrong for every failure it labeled.
    """
    lines = [
        f"Post-merge staging AI/OCR gate failed (`{classification['status']}`) "
        f"on {app_url} at run {run_id} ({expected_sha}).",
        "",
        "Machine attribution of every failed case (from JUnit output):",
        "",
    ]
    for key in ("regression", "precondition", "transient"):
        cases = classification["by_class"][key]
        if not cases:
            continue
        lines.append(f"- **{key}** — {_CLASS_EXPLANATIONS[key]}:")
        lines.extend(f"  - `{case['test']}`" for case in cases)
    lines += [
        "",
        "See the run's step summary for full counts. A green gate run "
        "auto-closes this issue.",
    ]
    return "\n".join(lines)


def emit_classification_shell(classification: dict[str, Any]) -> str:
    """Bash assignments the gate step evals after a red corpus run."""
    quoted_targets = " ".join(
        shlex.quote(path) for path in classification["retry_targets"]
    )
    return "\n".join(
        [
            f"AI_OCR_FAILURE_CLASS={shlex.quote(classification['status'])}",
            f"AI_OCR_RETRY_TESTS=({quoted_targets})",
        ]
    )


def preflight(base_url: str, *, timeout_seconds: float = 30.0) -> tuple[bool, str]:
    """Deployed-surface preflight (#1806): read /api/health, never recompute.

    Queries the app's own health surface (the manifest-required dependencies
    already fail closed there) so the gate adds no parallel environment
    checks — the #1435 lesson. Returns (ok, reason).
    """
    import json as json_module
    import urllib.error
    import urllib.request

    url = f"{base_url.rstrip('/')}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            payload = json_module.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return False, f"health endpoint unreachable or unparseable: {exc}"
    status = payload.get("status")
    if status != "healthy":
        return False, f"health status is {status!r}, expected 'healthy'"
    failed_checks = sorted(
        name for name, ok in (payload.get("checks") or {}).items() if not ok
    )
    if failed_checks:
        return False, f"required dependency checks failing: {', '.join(failed_checks)}"
    return True, "healthy"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell", action="store_true", help="Emit bash assignments.")
    parser.add_argument(
        "--corpus",
        choices=("all", "canary", "audit_replay"),
        default="all",
        help=(
            "Which corpus to emit: 'all' (default, full derived corpus), "
            "'canary' (minimal blocking liveness), or 'audit_replay' "
            "(comprehensive nightly journeys)."
        ),
    )
    parser.add_argument(
        "--summarize-junit",
        nargs="+",
        type=Path,
        metavar="XML",
        help="Summarize JUnit result XML into pass/fail counts + failed test names.",
    )
    parser.add_argument(
        "--classify-junit",
        nargs="+",
        type=Path,
        metavar="XML",
        help=(
            "Attribute JUnit failures to regression | precondition | transient "
            "(#1806); emits bash assignments (AI_OCR_FAILURE_CLASS, "
            "AI_OCR_RETRY_TESTS) and writes the attributed alert body."
        ),
    )
    parser.add_argument(
        "--alert-body-out",
        type=Path,
        default=None,
        metavar="PATH",
        help="Where --classify-junit writes the attributed alert-issue body.",
    )
    parser.add_argument(
        "--run-id", default="?", help="GitHub run id for the alert body."
    )
    parser.add_argument(
        "--expected-sha", default="?", help="Deployed version_ref for the alert body."
    )
    parser.add_argument(
        "--app-url", default="?", help="Gate target URL for the alert body."
    )
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Query the deployed /api/health surface; nonzero exit on any miss.",
    )
    parser.add_argument(
        "--base-url", default="", help="Deployed app base URL for --preflight."
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.shell:
        print(emit_shell(corpus_files(args.corpus)))
        return 0

    if args.preflight:
        if not args.base_url:
            print("--preflight requires --base-url", file=sys.stderr)
            return 2
        ok, reason = preflight(args.base_url)
        print(f"preflight: {reason}", file=sys.stderr)
        return 0 if ok else 1

    if args.classify_junit:
        classification = classify_junit(args.classify_junit)
        if args.alert_body_out is not None:
            args.alert_body_out.parent.mkdir(parents=True, exist_ok=True)
            args.alert_body_out.write_text(
                render_alert_body(
                    classification,
                    run_id=args.run_id,
                    expected_sha=args.expected_sha,
                    app_url=args.app_url,
                ),
                encoding="utf-8",
            )
        print(emit_classification_shell(classification))
        return 0

    if args.summarize_junit:
        print(render_junit_summary(summarize_junit(args.summarize_junit)))
        return 0

    files = corpus_files(args.corpus)
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
