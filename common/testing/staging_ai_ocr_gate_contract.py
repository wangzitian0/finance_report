#!/usr/bin/env python3
"""Emit the staging AI/OCR gate file list and replay counters."""

from __future__ import annotations

import argparse
import functools
import json
import re
import shlex
import sys
import urllib.error
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from common.audit.base.trace import (  # noqa: E402
    TraceAuthorityProfile,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceScopeKind,
    TraceTargetClass,
    VersionedTraceRef,
)
from common.audit.extension.trace_codec import TraceRecordCodec  # noqa: E402
from common.testing.coverage.junit import iter_testcases  # noqa: E402

REPO_ROOT = ROOT_DIR

SUPPLEMENTAL_LLM_FILES = ["tests/e2e/test_statement_upload_e2e.py"]
CANARY_FILES = [
    "tests/e2e/test_brokerage_upload_to_portfolio_value.py",
    "tests/e2e/test_institution_statement_journeys.py",
]
CORE_JOURNEY_MAP_PATH = ROOT_DIR / "common/testing/data/core-journey-checkpoints.json"
CORE_JOURNEY_LAST = ("tests/e2e/test_twelve_month_journey.py",)

REPLAY_COUNTERS_PATH = (
    ROOT_DIR / "common/testing/data/staging-ai-ocr-replay-counters.json"
)
REPLAY_COUNTERS: dict[str, dict[str, int]] = json.loads(
    REPLAY_COUNTERS_PATH.read_text(encoding="utf-8")
)


@functools.lru_cache(maxsize=1)
def _load_matrix() -> dict[str, Any]:
    from common.testing.ac_graph import build_proofs_only
    from common.testing.generate_critical_proof_matrix import build_matrix_from_graph

    return build_matrix_from_graph(build_proofs_only(REPO_ROOT))


def _require_counters(
    items: Sequence[str], *, allow_file_fallback: bool = False
) -> None:
    missing = [
        item
        for item in items
        if item not in REPLAY_COUNTERS
        and (not allow_file_fallback or item.split("::", 1)[0] not in REPLAY_COUNTERS)
    ]
    if missing:
        raise SystemExit(
            "Missing staging AI/OCR replay counters for: " + ", ".join(sorted(missing))
        )


def gate_files() -> list[str]:
    proof_files = {
        proof["file"]
        for proof in _load_matrix().get("proofs", [])
        if proof.get("ci_tier") == "post_merge_environment"
        and "llm" in proof.get("required_markers", [])
    }
    files = sorted(proof_files | set(SUPPLEMENTAL_LLM_FILES))
    _require_counters(files)
    return files


def canary_files() -> list[str]:
    """Return the minimal blocking-path AI/OCR canary corpus (AC8.13.156)."""
    derived = set(gate_files())
    canary = sorted(CANARY_FILES)
    missing_from_corpus = [path for path in canary if path not in derived]
    if missing_from_corpus:
        raise SystemExit(
            "Canary files are not in the derived AI/OCR corpus: "
            + ", ".join(sorted(missing_from_corpus))
        )
    _require_counters(canary)
    return canary


def audit_replay_files() -> list[str]:
    """Return the nightly/manual audit-replay corpus (AC8.13.157)."""
    canary = set(canary_files())
    return [path for path in gate_files() if path not in canary]


def _counter(test: str) -> dict[str, int]:
    return REPLAY_COUNTERS.get(test) or REPLAY_COUNTERS[test.split("::", 1)[0]]


def core_journey_tests() -> list[str]:
    """Return the non-blocking post-deploy core-journey corpus (#2370)."""
    data = json.loads(CORE_JOURNEY_MAP_PATH.read_text(encoding="utf-8"))
    tests = sorted(
        (
            f"{proof['file']}::{proof['test'].split('::', 1)[1]}"
            for proof in data["proofs"]
        ),
        key=lambda node: (node.split("::", 1)[0] in CORE_JOURNEY_LAST, node),
    )
    _require_counters(tests, allow_file_fallback=True)
    return tests


def corpus_files(corpus: str) -> list[str]:
    selectors = {
        "all": gate_files,
        "canary": canary_files,
        "audit_replay": audit_replay_files,
        "core_journey": core_journey_tests,
    }
    if corpus not in selectors:
        raise SystemExit(
            f"Unknown corpus {corpus!r}; expected one of {sorted(selectors)}"
        )
    return selectors[corpus]()


def totals(files: list[str]) -> dict[str, int]:
    keys = ("uploads", "parse_completions", "brokerage_imports", "report_verifications")
    return {key: sum(_counter(path)[key] for path in files) for key in keys}


def emit_shell(files: list[str] | None = None) -> str:
    if files is None:
        files = gate_files()
    counts = totals(files)
    quoted_files = " ".join(shlex.quote(path) for path in files)
    return "\n".join(
        [
            f"STAGING_AI_OCR_TESTS=({quoted_files})",
            f"STAGING_AI_OCR_EXPECTED_UPLOADS={counts['uploads']}",
            f"STAGING_AI_OCR_EXPECTED_PARSE_COMPLETIONS={counts['parse_completions']}",
            f"STAGING_AI_OCR_EXPECTED_BROKERAGE_IMPORTS={counts['brokerage_imports']}",
            f"STAGING_AI_OCR_EXPECTED_REPORT_VERIFICATIONS={counts['report_verifications']}",
        ]
    )


def _case_node(case: ET.Element) -> str:
    name = case.get("classname", "")
    case_name = case.get("name", "<unknown>")
    return f"{name}::{case_name}" if name else case_name


def summarize_junit(xml_paths: list[Path]) -> dict[str, Any]:
    """Summarize JUnit XML results into pass/fail counts and failed test names."""
    total = passed = failed = skipped = 0
    failed_tests: list[str] = []
    for path in xml_paths:
        for case in iter_testcases(path):
            total += 1
            if case.find("skipped") is not None:
                skipped += 1
            elif case.find("failure") is not None or case.find("error") is not None:
                failed += 1
                failed_tests.append(_case_node(case))
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


TRANSIENT_FAILURE_PATTERNS = (
    "did not reach parsed within",
    "ai service may be unavailable",
    "readtimeout",
    "connecttimeout",
    "connection reset",
    "connecterror",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
)
PRECONDITION_FAILURE_PATTERNS = ("missing fx rate", "fx rate missing")

FAILURE_CLASS_STATUS = {
    "regression": "regression-failed",
    "precondition": "precondition-failed",
    "transient": "provider-transient",
}

_CLASS_EXPLANATIONS = {
    "regression": "app/extraction regression — needs human judgment",
    "precondition": "environment-data precondition (e.g. FX coverage) — fix the environment, not the extractor",
    "transient": "provider/queue transient (timeout / 5xx) — bounded single retry applies",
}


def _classify_failure_text(text: str) -> tuple[str, str]:
    lowered = text.lower()
    if any(pattern in lowered for pattern in PRECONDITION_FAILURE_PATTERNS):
        return "precondition", "environment-gap"
    if any(pattern in lowered for pattern in TRANSIENT_FAILURE_PATTERNS):
        return "transient", "provider-latency"
    if "assertionerror" in lowered or "assert " in lowered:
        return "regression", "app-assertion"
    return "regression", "extraction"


def _case_file(case: ET.Element) -> str | None:
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
    """Attribute failed JUnit cases to regression, precondition, or transient."""
    cases: list[dict[str, str]] = []
    for path in xml_paths:
        for case in iter_testcases(path):
            report = case.find("failure")
            if report is None:
                report = case.find("error")
            if report is None:
                continue
            failure_class, subtype = _classify_failure_text(
                f"{report.get('message', '')}\n{report.text or ''}"
            )
            cases.append(
                {
                    "test": _case_node(case),
                    "class": failure_class,
                    "subtype": subtype,
                    "file": _case_file(case) or "",
                }
            )
    by_class = {
        key: [case for case in cases if case["class"] == key]
        for key in ("regression", "precondition", "transient")
    }
    overall = next(
        (k for k in ("regression", "precondition", "transient") if by_class[k]),
        "passed",
    )
    return {
        "cases": cases,
        "by_class": by_class,
        "overall": overall,
        "status": FAILURE_CLASS_STATUS.get(overall, "passed"),
        "retry_targets": sorted(
            {case["file"] for case in by_class["transient"] if case["file"]}
        ),
    }


def render_alert_body(
    classification: dict[str, Any],
    *,
    run_id: str = "?",
    expected_sha: str = "?",
    app_url: str = "?",
    corpus: str = "canary",
) -> str:
    """Render alert-issue body generated from JUnit attribution (#1806)."""
    lines = [
        f"Post-merge staging AI/OCR gate failed (`{classification['status']}`) "
        f"on {app_url} at run {run_id} ({expected_sha}) [corpus={corpus}].",
        "",
        "Machine attribution of every failed case (from JUnit output):",
        "",
    ]
    for key in ("regression", "precondition", "transient"):
        cases = classification["by_class"][key]
        if not cases:
            continue
        lines.append(f"- **{key}** — {_CLASS_EXPLANATIONS[key]}:")
        for case in cases:
            subtype_str = f" [{case.get('subtype')}]" if case.get("subtype") else ""
            lines.append(f"  - `{case['test']}`{subtype_str}")
    lines += [
        "",
        "See the run's step summary for full counts. A green gate run "
        "auto-closes this issue.",
    ]
    return "\n".join(lines)


def to_trace_result(status: str) -> TraceResult:
    if status == "passed":
        return TraceResult.PASS
    if status in (
        "regression-failed",
        "precondition-failed",
        "provider-transient",
        "version-check-failed",
        "gate-timeout",
    ):
        return TraceResult.FAIL
    return TraceResult.ERROR


def build_evidence_manifest(
    *,
    environment: str = "staging",
    app_url: str = "?",
    run_id: str = "?",
    expected_sha: str = "?",
    corpus: str = "canary",
    status: str = "passed",
    exit_code: int = 0,
    classification: dict[str, Any] | None = None,
    preflight_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "version": 1,
        "environment": environment,
        "app_url": app_url,
        "run_id": str(run_id),
        "expected_sha": expected_sha,
        "corpus": corpus,
        "status": status,
        "exit_code": exit_code,
    }
    if classification:
        for key in ("cases", "by_class", "retry_targets"):
            manifest[key] = classification.get(key, [] if key != "by_class" else {})
    if preflight_details:
        manifest["preflight"] = preflight_details
    return manifest


def build_trace_observation(
    manifest: dict[str, Any],
    *,
    contract_path: Path | None = None,
) -> TraceRecord:
    """Build canonical TraceRecord observation for staging AI/OCR gate run (#1906)."""
    path = contract_path or (ROOT_DIR / "common" / "testing" / "contract.py")
    owner_digest = sha256(path.read_bytes()).hexdigest() if path.exists() else "0" * 64
    manifest_digest = sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    status = manifest.get("status", "passed")
    return TraceRecord.observation(
        scope=TraceScope(kind=TraceScopeKind.ENVIRONMENT, id="staging"),
        target=VersionedTraceRef(
            kind="staging_corpus",
            id=manifest.get("corpus", "canary"),
            version=manifest.get("expected_sha", "?"),
        ),
        target_class=TraceTargetClass.GENERAL,
        assertion=VersionedTraceRef(
            kind="ai_ocr_replay", id=status, version=owner_digest
        ),
        authority=TraceAuthorityProfile(
            package="testing",
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage="staging.provider_regression",
            assertion_owner_digest=owner_digest,
            producer_version="staging_ai_ocr_gate_contract@1.0",
        ),
        result=to_trace_result(status),
        execution_id=str(manifest.get("run_id", "?")),
        evidence_manifest_digest=manifest_digest,
        occurred_at=datetime.now(UTC),
        score=None,
        reason_code=status.replace("-", "_"),
    )


def can_close_alert(
    alert_body: str,
    current_corpus: str,
    current_version: str | None = None,
) -> bool:
    """Decide whether a green gate run with ``current_corpus`` may auto-close an alert."""
    del current_version
    if current_corpus == "all":
        return True
    match = re.search(r"corpus=([a-z_]+)", alert_body)
    if match:
        alert_corpus = match.group(1)
        return alert_corpus != "all" and current_corpus == alert_corpus

    body_lowered = alert_body.lower()
    has_canary = "test_brokerage_upload_to_portfolio_value" in body_lowered
    has_audit = any(
        ind in body_lowered
        for ind in (
            "test_statement_full_journey",
            "test_institution_statement_journeys",
            "test_personal_financial_report_package",
            "test_four_asset_net_worth_golden_path",
            "test_statement_upload_e2e",
        )
    )
    if current_corpus == "canary":
        return has_canary and not has_audit
    if current_corpus == "audit_replay":
        return has_audit and not has_canary
    return False


def emit_classification_shell(classification: dict[str, Any]) -> str:
    """Emit bash assignments for a red corpus run."""
    status = (
        "regression-failed"
        if classification["status"] == "passed"
        else classification["status"]
    )
    quoted_targets = " ".join(
        shlex.quote(path) for path in classification["retry_targets"]
    )
    return "\n".join(
        [
            f"AI_OCR_FAILURE_CLASS={shlex.quote(status)}",
            f"AI_OCR_RETRY_TESTS=({quoted_targets})",
        ]
    )


def preflight(base_url: str, *, timeout_seconds: float = 30.0) -> tuple[bool, str]:
    """Query deployed /api/health?full=1 without recomputing checks (#1806)."""
    url = f"{base_url.rstrip('/')}/api/health?full=1"
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
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


def _write_text_parent(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_gate_outputs(
    args: argparse.Namespace,
    *,
    status: str,
    exit_code: int,
    classification: dict[str, Any] | None,
) -> None:
    manifest = build_evidence_manifest(
        app_url=args.app_url,
        run_id=args.run_id,
        expected_sha=args.expected_sha,
        corpus=args.corpus,
        status=status,
        exit_code=exit_code,
        classification=classification,
    )
    if args.manifest_out is not None:
        _write_text_parent(
            args.manifest_out, json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        )
    if args.observation_out is not None:
        _write_text_parent(
            args.observation_out,
            TraceRecordCodec.encode(build_trace_observation(manifest)) + "\n",
        )
    if args.alert_body_out is not None:
        alert_text = (
            render_alert_body(
                classification,
                run_id=args.run_id,
                expected_sha=args.expected_sha,
                app_url=args.app_url,
                corpus=args.corpus,
            )
            if classification
            else (
                f"Post-merge staging AI/OCR gate failed (`{status}`) "
                f"on {args.app_url} at run {args.run_id} ({args.expected_sha}) [corpus={args.corpus}].\n\n"
                f"Status reason: {status}. See the run's step summary for full counts. "
                "A green gate run auto-closes this issue."
            )
        )
        _write_text_parent(args.alert_body_out, alert_text)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell", action="store_true")
    parser.add_argument(
        "--corpus",
        choices=("all", "canary", "audit_replay", "core_journey"),
        default="all",
    )
    parser.add_argument("--summarize-junit", nargs="+", type=Path, metavar="XML")
    parser.add_argument("--classify-junit", nargs="+", type=Path, metavar="XML")
    parser.add_argument("--alert-body-out", type=Path, default=None, metavar="PATH")
    parser.add_argument("--run-id", default="?")
    parser.add_argument("--expected-sha", default="?")
    parser.add_argument("--app-url", default="?")
    parser.add_argument("--manifest-out", type=Path, default=None, metavar="PATH")
    parser.add_argument("--observation-out", type=Path, default=None, metavar="PATH")
    parser.add_argument("--can-close-alert", default=None, metavar="ALERT_BODY_OR_PATH")
    parser.add_argument("--status", default=None)
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--base-url", default="")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    if args.shell:
        print(emit_shell(corpus_files(args.corpus)))
        return 0
    if args.can_close_alert is not None:
        body_path = Path(args.can_close_alert)
        body = (
            body_path.read_text(encoding="utf-8")
            if body_path.is_file()
            else args.can_close_alert
        )
        return (
            0
            if can_close_alert(
                body, current_corpus=args.corpus, current_version=args.expected_sha
            )
            else 1
        )
    if args.preflight:
        if not args.base_url:
            print("--preflight requires --base-url", file=sys.stderr)
            return 2
        ok, reason = preflight(args.base_url)
        print(f"preflight: {reason}", file=sys.stderr)
        return 0 if ok else 1
    if args.status is not None:
        classification = (
            classify_junit(args.classify_junit) if args.classify_junit else None
        )
        status = classification["status"] if classification else args.status
        _write_gate_outputs(
            args,
            status=status,
            exit_code=args.exit_code,
            classification=classification,
        )
        return 0
    if args.classify_junit:
        classification = classify_junit(args.classify_junit)
        exit_code = (
            args.exit_code
            if args.exit_code != 0
            else (1 if classification["status"] != "passed" else 0)
        )
        _write_gate_outputs(
            args,
            status=classification["status"],
            exit_code=exit_code,
            classification=classification,
        )
        print(emit_classification_shell(classification))
        return 0
    if args.summarize_junit:
        print(render_junit_summary(summarize_junit(args.summarize_junit)))
        return 0

    files = corpus_files(args.corpus)
    print("Staging AI/OCR gate files:")
    for path in files:
        print(f"- {path}")
    print("Expected replay counters:")
    for key, value in totals(files).items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
