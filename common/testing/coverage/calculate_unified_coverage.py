#!/usr/bin/env python3
"""Unified LCOV line-coverage calculator."""

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from common.meta.extension.coverage.policy import (
    COMPONENT_BY_NAME,
    COMPONENTS,
    CoverageComponent,
    get_component,
)
from common.testing.coverage.lcov import parse_lcov_summaries

ROOT_DIR = Path(__file__).resolve().parents[3]
PREFLIGHT_COMPONENTS: tuple[CoverageComponent, ...] = ()
REQUIRED_COMPONENTS_ENV = "COVERAGE_REQUIRED_COMPONENTS"
GATE_COMPONENTS_ENV = "COVERAGE_GATE_COMPONENTS"
RATCHET_MODE_ENV = "COVERAGE_RATCHET_MODE"
RATCHET_MODES = ("block", "report")
REGRESSION_EPSILON_PCT = 0.05

BACKEND_DIR = ROOT_DIR / "apps" / "backend"
FRONTEND_DIR = ROOT_DIR / "apps" / "frontend"
TOOLS_DIR = ROOT_DIR / "tools"
COMMON_DIR = ROOT_DIR / "common"
_COMPONENT_ORDER = ("backend", "frontend", "common", "tools")


def count_policy_files(component: CoverageComponent) -> dict:
    expected_sources = component.expected_sources(ROOT_DIR)
    return {
        "file_count": len(expected_sources),
        "files": [{"path": path} for path in sorted(expected_sources)[:10]],
    }


def _coverage_percent(covered_lines: int, total_lines: int) -> float:
    return round(covered_lines / max(total_lines, 1) * 100, 2) if total_lines > 0 else 0


def parse_lcov_records(
    lcov_path: Path,
    component: CoverageComponent | None = None,
    repo_root: Path = ROOT_DIR,
) -> list[dict]:
    """Parse LCOV and return per-source line coverage records."""
    if not lcov_path.exists():
        return []
    normalize = (
        (lambda src: component.normalize_lcov_source(src, repo_root))
        if component is not None
        else (lambda src: src.replace("\\", "/"))
    )
    summaries = parse_lcov_summaries(lcov_path, normalize_source=normalize)
    return [
        {
            "path": source,
            "covered_lines": counts["covered_lines"],
            "total_lines": counts["total_lines"],
            "coverage_percent": _coverage_percent(
                counts["covered_lines"], counts["total_lines"]
            ),
        }
        for source, counts in summaries.items()
    ]


def parse_lcov_file(lcov_path: Path) -> dict:
    """Parse LCOV coverage file and extract accumulated covered/measured line counts."""
    records = parse_lcov_records(lcov_path)
    return {
        "covered_lines": sum(r["covered_lines"] for r in records),
        "total_measured_lines": sum(r["total_lines"] for r in records),
    }


def required_artifacts_preflight(
    components: tuple[CoverageComponent, ...] = PREFLIGHT_COMPONENTS,
    repo_root: Path = ROOT_DIR,
) -> list[str]:
    """Return explicit errors for missing or empty CI-critical coverage artifacts."""
    errors: list[str] = []
    for component in components:
        if not component.is_ci_critical:
            continue
        lcov_path = component.lcov_path(repo_root)
        rel = component.ci_lcov_path
        if not lcov_path.exists():
            errors.append(
                f"{component.name}: required coverage artifact is missing "
                f"(expected {rel}); the {component.tier} component cannot be "
                "aggregated without it"
            )
        elif parse_lcov_file(lcov_path)["total_measured_lines"] <= 0:
            errors.append(
                f"{component.name}: required coverage artifact {rel} is empty "
                "(no measured lines); refusing to aggregate a misleading 0%"
            )
    return errors


def resolve_required_components(names: str | None) -> tuple[CoverageComponent, ...]:
    """Resolve a comma-separated component name list into preflight components."""
    if not names:
        return ()
    requested = [token.strip() for token in names.split(",") if token.strip()]
    if not requested:
        return ()
    if requested == ["all"]:
        return COMPONENTS
    unknown = [name for name in requested if name not in COMPONENT_BY_NAME]
    if unknown:
        valid = ", ".join(sorted(COMPONENT_BY_NAME))
        raise ValueError(
            f"unknown coverage component(s) {unknown!r}; valid names: {valid} (or 'all')"
        )
    return tuple(COMPONENT_BY_NAME[name] for name in requested)


def get_component_coverage(component: CoverageComponent) -> dict:
    coverage_data = parse_lcov_file(component.lcov_path(ROOT_DIR))
    total_lines = coverage_data["total_measured_lines"]
    return {
        "total_lines": total_lines,
        "covered_lines": coverage_data["covered_lines"],
        "coverage_percent": _coverage_percent(
            coverage_data["covered_lines"], total_lines
        ),
        "file_count": count_policy_files(component)["file_count"],
    }


def get_backend_coverage() -> dict:
    return get_component_coverage(get_component("backend"))


def get_frontend_coverage() -> dict:
    return get_component_coverage(get_component("frontend"))


def get_common_coverage() -> dict:
    return get_component_coverage(get_component("common"))


def get_tools_coverage() -> dict:
    return get_component_coverage(get_component("tools"))


def calculate_unified_coverage(
    backend: dict,
    frontend: dict,
    common: dict | None = None,
    tools: dict | None = None,
) -> dict:
    """Calculate unified coverage across all components."""
    breakdown = {"backend": backend, "frontend": frontend}
    if common is not None:
        breakdown["common"] = common
    if tools is not None:
        breakdown["tools"] = tools
    total_lines = sum(c["total_lines"] for c in breakdown.values())
    covered_lines = sum(c["covered_lines"] for c in breakdown.values())
    return {
        "total_lines": total_lines,
        "covered_lines": covered_lines,
        "coverage_percent": _coverage_percent(covered_lines, total_lines),
        "breakdown": breakdown,
    }


def _repo_relative_path(
    component: CoverageComponent, component_relative_path: str
) -> str:
    return (
        f"{component.component_root}/{component_relative_path}"
        if component.component_root
        else component_relative_path
    )


def collect_low_coverage_files(
    threshold: float,
    repo_root: Path = ROOT_DIR,
    components: tuple[CoverageComponent, ...] = COMPONENTS,
) -> list[dict]:
    """Return file-level LCOV records below threshold using the shared policy."""
    rows = [
        {
            "component": component.name,
            "path": _repo_relative_path(component, record["path"]),
            "covered_lines": record["covered_lines"],
            "total_lines": record["total_lines"],
            "coverage_percent": record["coverage_percent"],
        }
        for component in components
        for record in parse_lcov_records(
            component.lcov_path(repo_root), component, repo_root
        )
        if record["total_lines"] > 0 and record["coverage_percent"] < threshold
    ]
    return sorted(
        rows, key=lambda row: (row["coverage_percent"], row["component"], row["path"])
    )


def print_low_coverage_files(rows: list[dict], threshold: float) -> None:
    print(f"\n{'=' * 60}\nLOW COVERAGE FILES (< {threshold:g}%)\n{'=' * 60}")
    if not rows:
        print(f"✅ No files below {threshold:g}%")
        return
    print(f"{'Component':<10} {'Coverage':>9} {'Lines':>11}  File\n{'-' * 60}")
    for row in rows:
        lines = f"{row['covered_lines']}/{row['total_lines']}"
        print(
            f"{row['component']:<10} {row['coverage_percent']:>8.2f}% {lines:>11}  {row['path']}"
        )


def _format_regression_error(
    *,
    baseline_path: Path,
    regressions: list[tuple[str, float, float]],
) -> str:
    lines = [
        "❌ Coverage regression detected by local deterministic gate "
        f"(beyond the ±{REGRESSION_EPSILON_PCT:g}% jitter epsilon).",
        f"   Baseline: {baseline_path}",
    ]
    for name, current, baseline in regressions:
        source = (
            "coverage/unified.lcov"
            if name == "unified"
            else get_component(name).ci_lcov_path
        )
        lines.append(
            f"   - {name}: current={current:.2f}% baseline={baseline:.2f}% "
            f"delta={round(current - baseline, 2):.2f}% source={source}"
        )
    return "\n".join(lines)


def _format_line_ratio(data: dict) -> str:
    return (
        f"{int(data.get('covered_lines', 0))}/{int(data.get('total_lines', 0))} "
        f"({float(data.get('coverage_percent', 0)):.2f}%)"
    )


def print_baseline_comparison(*, current_unified: dict, baseline: dict) -> None:
    """Print raw line counts used by the no-regression comparison."""
    print(f"\n{'=' * 60}\nBASELINE COMPARISON\n{'=' * 60}")
    print(
        f"   unified: current={_format_line_ratio(current_unified)} "
        f"baseline={_format_line_ratio(baseline)}"
    )
    current_breakdown = current_unified.get("breakdown", {})
    baseline_breakdown = baseline.get("breakdown", {})
    for name in _COMPONENT_ORDER:
        if name in current_breakdown and name in baseline_breakdown:
            print(
                f"   {name}: current={_format_line_ratio(current_breakdown[name])} "
                f"baseline={_format_line_ratio(baseline_breakdown[name])}"
            )


def write_unified_coverage(unified: dict, output_path: Path) -> None:
    output_path.write_text(json.dumps(unified, indent=2), encoding="utf-8")
    print(f"\n📄 Report saved to: {output_path}")


def _opt_or_env(flag_val: str | None, env_var: str) -> str | None:
    return (
        flag_val
        if flag_val is not None
        else (os.environ.get(env_var, "").strip() or None)
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calculate unified LCOV coverage.")
    parser.add_argument("--list-low-files", action="store_true")
    parser.add_argument("--threshold", type=float, default=90.0)
    parser.add_argument("--require-artifacts", default=None, metavar="COMPONENTS")
    parser.add_argument("--gate-components", default=None, metavar="COMPONENTS")
    parser.add_argument("--ratchet-mode", choices=RATCHET_MODES, default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1

    print(f"{'=' * 60}\nUnified Coverage Calculator\n{'=' * 60}")

    required_spec = _opt_or_env(args.require_artifacts, REQUIRED_COMPONENTS_ENV)
    if required_spec is not None:
        try:
            preflight_components = resolve_required_components(required_spec)
        except ValueError as exc:
            print(
                f"\n❌ Invalid --require-artifacts/{REQUIRED_COMPONENTS_ENV}: {exc}",
                file=sys.stderr,
            )
            return 2
    else:
        preflight_components = PREFLIGHT_COMPONENTS

    gate_spec = _opt_or_env(args.gate_components, GATE_COMPONENTS_ENV)
    gate_component_names: set[str] | None = None
    if gate_spec is not None:
        try:
            gate_component_names = {
                c.name for c in resolve_required_components(gate_spec)
            }
        except ValueError as exc:
            print(
                f"\n❌ Invalid --gate-components/{GATE_COMPONENTS_ENV}: {exc}",
                file=sys.stderr,
            )
            return 2

    ratchet_mode = _opt_or_env(args.ratchet_mode, RATCHET_MODE_ENV) or "block"
    if ratchet_mode not in RATCHET_MODES:
        print(
            f"\n❌ Invalid --ratchet-mode/{RATCHET_MODE_ENV}: {ratchet_mode!r}; "
            f"valid modes: {', '.join(RATCHET_MODES)}",
            file=sys.stderr,
        )
        return 2

    preflight_errors = required_artifacts_preflight(preflight_components, ROOT_DIR)
    if preflight_errors:
        print(
            "\n❌ Coverage artifact preflight failed: required component "
            "artifact(s) missing or empty.",
            file=sys.stderr,
        )
        for error in preflight_errors:
            print(f"   - {error}", file=sys.stderr)
        return 1

    getters = {
        "backend": get_backend_coverage,
        "frontend": get_frontend_coverage,
        "common": get_common_coverage,
        "tools": get_tools_coverage,
    }
    component_results: dict[str, dict] = {}
    for name in _COMPONENT_ORDER:
        print(f"\n📊 {name.capitalize()} Coverage...")
        data = getters[name]()
        component_results[name] = data
        print(f"   Total lines: {data['total_lines']:,}")
        print(f"   Covered lines: {data['covered_lines']:,}")
        print(f"   Coverage: {data['coverage_percent']}%")

    unified = calculate_unified_coverage(
        component_results["backend"],
        component_results["frontend"],
        component_results["common"],
        component_results["tools"],
    )

    if args.list_low_files:
        print_low_coverage_files(
            collect_low_coverage_files(args.threshold, ROOT_DIR), args.threshold
        )

    baseline_file = (
        os.environ.get("BASELINE_FILE", "").strip() or "unified-coverage.json"
    )
    baseline_path = ROOT_DIR / baseline_file
    regression_error = ""
    try:
        if baseline_path.exists():
            with baseline_path.open(encoding="utf-8") as f:
                baseline = json.load(f)
            print_baseline_comparison(current_unified=unified, baseline=baseline)
            baseline_breakdown = baseline.get("breakdown", {})
            regressions: list[tuple[str, float, float]] = []
            unified_current = round(unified["coverage_percent"], 2)
            unified_floor = round(float(baseline.get("coverage_percent", 0)), 2)
            if gate_component_names is None and unified_current < round(
                unified_floor - REGRESSION_EPSILON_PCT, 2
            ):
                regressions.append(("unified", unified_current, unified_floor))

            components_to_check = [
                (name, component_results[name], baseline_breakdown[name])
                for name in _COMPONENT_ORDER
                if name in baseline_breakdown
            ]
            if gate_component_names is not None:
                out_of_scope = [
                    name
                    for name, _, _ in components_to_check
                    if name not in gate_component_names
                ]
                components_to_check = [
                    entry
                    for entry in components_to_check
                    if entry[0] in gate_component_names
                ]
                print(
                    f"\n🔧 #1689 coverage gate scoped to: "
                    f"{', '.join(sorted(gate_component_names)) or '(none)'} "
                    f"(informational-only for: {', '.join(out_of_scope) or '(none)'})"
                )

            for name, current_data, baseline_data in components_to_check:
                current_pct = round(float(current_data["coverage_percent"]), 2)
                baseline_pct = round(float(baseline_data["coverage_percent"]), 2)
                if current_pct < round(baseline_pct - REGRESSION_EPSILON_PCT, 2):
                    regressions.append((name, current_pct, baseline_pct))

            if regressions:
                regression_error = _format_regression_error(
                    baseline_path=baseline_path, regressions=regressions
                )
            else:
                print("✅ No regression: all coverage at or above baseline")
        else:
            print(f"⚠️  Baseline file not found: {baseline_path}", file=sys.stderr)
            print("⚠️  Continuing with coverage threshold check...", file=sys.stderr)
    except json.JSONDecodeError:
        print(f"⚠️  Invalid baseline file: {baseline_path}", file=sys.stderr)
        print("⚠️  Continuing with coverage threshold check...", file=sys.stderr)
    except Exception as exc:
        print(f"⚠️  Error reading baseline file: {exc}", file=sys.stderr)
        print("⚠️  Continuing with coverage threshold check...", file=sys.stderr)

    print(
        f"\n{'=' * 60}\n🎯 UNIFIED COVERAGE\n{'=' * 60}\n\n"
        f"   Total lines: {unified['total_lines']:,}\n"
        f"   Covered lines: {unified['covered_lines']:,}\n"
        f"   Coverage: {unified['coverage_percent']}%\n\n{'-' * 60}"
    )
    write_unified_coverage(unified, ROOT_DIR / "unified-coverage.json")

    if regression_error:
        if ratchet_mode == "report":
            print(
                "📣 REPORT-ONLY (#1810): the component ratchet does not block "
                "this run (ratchet-mode=report; PR lane). The blocking PR "
                "coverage verdict is the diff-coverage gate "
                "(tools/check_diff_coverage.py); main pushes still block on "
                "this ratchet.",
                file=sys.stderr,
            )
            print(regression_error, file=sys.stderr)
        else:
            print(regression_error, file=sys.stderr)
            return 1

    threshold = int(os.environ.get("COVERAGE_THRESHOLD", "0"))
    if unified["coverage_percent"] >= threshold:
        print(
            f"✅ Coverage ({unified['coverage_percent']}%) meets threshold ({threshold}%)"
        )
        return 0
    print(
        f"❌ Coverage ({unified['coverage_percent']}%) below threshold ({threshold}%)"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
