"""Markdown rendering + CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - CLI guard
    yaml = None


from common.ssot.governance_report._base import (
    GATE_EXCEPTION_PATH,
    GATE_HLS_RULE,
    GATE_ISSUE,
    HLS_ISSUE,
    SOURCE_ISSUE,
)
from common.ssot.governance_report._gate import (
    _load_changed_files,
    evaluate_incremental_gate,
)
from common.ssot.governance_report._report import build_report


def _join_sample(values: object, limit: int = 5) -> str:
    if not isinstance(values, list) or not values:
        return "-"
    rendered: list[str] = []
    for item in values[:limit]:
        if isinstance(item, Mapping):
            rendered.append(str(item.get("owner") or item))
        else:
            rendered.append(str(item))
    return ", ".join(rendered)


def render_markdown(report: Mapping[str, object]) -> str:
    """Render a concise Markdown report for CI step summary."""

    lines = [
        "# SSOT Governance Report",
        "",
        f"Report-only baseline for [{SOURCE_ISSUE.rsplit('/', 1)[-1]}]({SOURCE_ISSUE}); "
        f"HLS direction is tracked in [{HLS_ISSUE.rsplit('/', 1)[-1]}]({HLS_ISSUE}).",
        "Baseline metrics are advisory. The optional Incremental Gate section can fail CI for changed-surface violations or protected governance regressions.",
        "",
        "| System | Entries | Owners | Duplicate owners | Orphan SSOT files | Missing family | Missing kind | Machine missing proof | High-risk missing proof |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for source in report.get("sources", []):
        if not isinstance(source, Mapping):
            continue
        field_coverage = source.get("field_coverage")
        machine = source.get("machine_owner_entries")
        high_risk = source.get("high_risk_entries")
        if not isinstance(field_coverage, Mapping):
            field_coverage = {}
        if not isinstance(machine, Mapping):
            machine = {}
        if not isinstance(high_risk, Mapping):
            high_risk = {}
        family = field_coverage.get("family", {})
        kind = field_coverage.get("kind", {})
        if not isinstance(family, Mapping):
            family = {}
        if not isinstance(kind, Mapping):
            kind = {}

        lines.append(
            "| {system} | {entries} | {owners} | {duplicates} | {orphans} | "
            "{missing_family} | {missing_kind} | {machine_missing} | {risk_missing} |".format(
                system=source.get("system", "unknown"),
                entries=source.get("entry_count", 0),
                owners=source.get("owner_count", 0),
                duplicates=len(source.get("duplicate_owner_groups", [])),
                orphans=len(source.get("orphan_ssot_files", [])),
                missing_family=family.get("missing", 0),
                missing_kind=kind.get("missing", 0),
                machine_missing=len(machine.get("missing_proof", [])),
                risk_missing=len(high_risk.get("missing_proof", [])),
            )
        )

    gate = report.get("gate")
    if isinstance(gate, Mapping):
        violations = gate.get("violations", [])
        if not isinstance(violations, list):
            violations = []
        lines.extend(
            [
                "",
                "## Incremental Gate",
                "",
                f"- Issue: [{GATE_ISSUE.rsplit('/', 1)[-1]}]({GATE_ISSUE})",
                f"- HLS rule: {gate.get('hls_rule', GATE_HLS_RULE)}",
                f"- Changed files: {gate.get('changed_file_count', 0)}",
                f"- Trend checks: {gate.get('trend_check_count', 0)}",
                f"- Exception registry: `{gate.get('exception_path', GATE_EXCEPTION_PATH.as_posix())}`",
                f"- Exceptions used: {gate.get('exception_count', 0)}",
                f"- Result: {'PASS' if not violations else 'FAIL'}",
            ]
        )
        if violations:
            lines.append("- Violations:")
            for violation in violations[:20]:
                if not isinstance(violation, Mapping):
                    continue
                lines.append(
                    "  - `{code}` `{target}`: {message}".format(
                        code=violation.get("code", "unknown"),
                        target=violation.get("target", "unknown"),
                        message=violation.get("message", ""),
                    )
                )

    for source in report.get("sources", []):
        if not isinstance(source, Mapping):
            continue
        lines.extend(
            [
                "",
                f"## {source.get('system', 'unknown')}",
                "",
                f"- Manifest: `{source.get('manifest', '-')}`",
                f"- Entry key: `{source.get('entry_key', '-')}`",
                f"- Kind distribution: `{source.get('kind_distribution', {})}`",
                f"- Inferred family distribution: `{source.get('inferred_family_distribution', {})}`",
            ]
        )

        errors = source.get("errors", [])
        if isinstance(errors, list) and errors:
            lines.append(f"- Report errors: `{errors}`")

        candidates = source.get("future_gate_candidates", [])
        if isinstance(candidates, list):
            lines.append("- Future gate candidates:")
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    continue
                lines.append(
                    "  - `{code}`: {count} (sample: {sample})".format(
                        code=candidate.get("code", "unknown"),
                        count=candidate.get("count", 0),
                        sample=_join_sample(candidate.get("sample")),
                    )
                )

    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate SSOT governance metrics and optional incremental gates."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root. Defaults to the current working directory.",
    )
    parser.add_argument(
        "--no-infra2",
        action="store_true",
        help="Only report the finance_report manifest.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional path for machine-readable JSON output.",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        help="Optional path for Markdown output.",
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit non-zero only when the report itself cannot parse a manifest.",
    )
    parser.add_argument(
        "--changed-files",
        type=Path,
        help="Optional newline-delimited changed-files list for #823 incremental gates.",
    )
    parser.add_argument(
        "--base-ref",
        help="Optional base git ref used to compare changed manifest entries.",
    )
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="Exit non-zero when #823 incremental gate violations are found.",
    )
    parser.add_argument(
        "--exceptions",
        type=Path,
        default=GATE_EXCEPTION_PATH,
        help="Path to SSOT governance gate exceptions, relative to repo root.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_report(args.repo_root, include_infra2=not args.no_infra2)
        changed_files = _load_changed_files(args.changed_files)
        if changed_files:
            report["gate"] = evaluate_incremental_gate(
                args.repo_root,
                changed_files,
                base_ref=args.base_ref,
                include_infra2=not args.no_infra2,
                exceptions_path=args.exceptions,
            )
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    rendered = render_markdown(report)
    print(rendered, end="")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.markdown_out:
        args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_out.write_text(rendered, encoding="utf-8")

    if args.fail_on_error and report["overall"]["errors"]:
        return 1
    gate = report.get("gate")
    if (
        args.fail_on_gate
        and isinstance(gate, Mapping)
        and int(gate.get("violation_count", 0)) > 0
    ):
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
