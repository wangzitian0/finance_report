#!/usr/bin/env python3
"""Unified LCOV line-coverage calculator.

The CI gate uses component LCOV reports for backend, frontend, common, and
tools. LCOV ``LF`` is the denominator and ``LH`` is the numerator; filesystem
line counts are diagnostic helpers only and do not define the enforced metric.

Scope is deny-list based inside each governed source root: every file matching
the component extensions is expected in LCOV unless it is explicitly excluded
by ``common.meta.extension.coverage.policy``. New source roots are caught by the CI metrics
contract before this calculator runs.

Output: unified-coverage.json with:
- backend: {total_lines, covered_lines, coverage_percent}
- frontend: {total_lines, covered_lines, coverage_percent}
- tools: {total_lines, covered_lines, coverage_percent}
- common: {total_lines, covered_lines, coverage_percent}
- unified: {total_lines, covered_lines, coverage_percent}
"""

import argparse
import json
import os
import sys
from pathlib import Path

from common.meta.extension.coverage.policy import (
    COMPONENT_BY_NAME,
    COMPONENTS,
    CoverageComponent,
    get_component,
)

# Configuration
ROOT_DIR = Path(__file__).resolve().parents[3]

# Components subject to the artifact preflight (#414).
#
# IMPORTANT (CI parity): the preflight is **opt-in**. The always-run CI
# "Calculate unified coverage" step deliberately tolerates legitimately-absent
# artifacts (a PR may not touch every coverage-producing shard), so an
# unconditional preflight would abort that step. The default is therefore empty
# (lenient: a missing artifact is reported as 0%, not a hard abort — the
# historical behavior). Callers opt into the strict gate by naming exactly which
# components must be present, via ``--require-artifacts`` or the
# ``COVERAGE_REQUIRED_COMPONENTS`` env var. The preflight then enforces presence
# only for the named CI-critical tiers (#923); best-effort components (e.g.
# tools) are skipped even when named.
PREFLIGHT_COMPONENTS: tuple[CoverageComponent, ...] = ()

# Env var naming the components that MUST have a present, non-empty artifact.
# Comma-separated component names (e.g. "backend,frontend,common"). Overridden by
# the ``--require-artifacts`` CLI flag when that is supplied.
REQUIRED_COMPONENTS_ENV = "COVERAGE_REQUIRED_COMPONENTS"

# #1689 (gate re-architecture Phase 3 "cost-right"): comma-separated component
# names (or "all") whose no-regression check BLOCKS this run. Every component is
# still computed and written to unified-coverage.json regardless; scoping only
# narrows which regressions fail the job. Omitted -> None -> "all" (unchanged,
# strict) behavior — this is the safe default main-branch pushes always get.
# Overridden by the ``--gate-components`` CLI flag when that is supplied.
GATE_COMPONENTS_ENV = "COVERAGE_GATE_COMPONENTS"

BACKEND_DIR = ROOT_DIR / "apps" / "backend"
FRONTEND_DIR = ROOT_DIR / "apps" / "frontend"
TOOLS_DIR = ROOT_DIR / "tools"
COMMON_DIR = ROOT_DIR / "common"

# Blacklist patterns (these are NOT counted as code)
BLACKLIST_PATTERNS = [
    "/test/",
    "/__tests__/",
    "/tests/",
    "/node_modules/",
    "/.next/",
    "/coverage/",
    "/.venv/",
    "/venv/",
    "__pycache__",
    ".pyc",
    "_test.py",
    ".test.ts",
    ".test.tsx",
    ".spec.ts",
    ".spec.tsx",
    "conftest.py",
    "vitest.setup.ts",
    "vitest.config.ts",
    "vite.config.ts",
    "jest.config.",
    "pytest.ini",
    "pyproject.toml",
    "setup.py",
]


def is_test_file(file_path: str) -> bool:
    """Check if a file should be excluded from code coverage calculation."""
    path = file_path.replace("\\", "/")
    basename = path.rsplit("/", 1)[-1]

    for pattern in BLACKLIST_PATTERNS:
        if pattern in path:
            return True
    if basename.startswith("test_"):
        return True
    return False


def count_lines(file_path: Path) -> int:
    """Count total lines in a file."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def count_code_lines(directory: Path, extensions: list[str]) -> dict:
    """Count total lines of code in directory, excluding test files."""
    total_lines = 0
    file_count = 0
    files_detail = []

    for ext in extensions:
        for file_path in directory.rglob(f"*{ext}"):
            relative_path = str(file_path.relative_to(ROOT_DIR))

            if is_test_file(relative_path):
                continue

            lines = count_lines(file_path)
            if lines > 0:
                total_lines += lines
                file_count += 1
                files_detail.append({"path": relative_path, "lines": lines})

    return {
        "total_lines": total_lines,
        "file_count": file_count,
        "files": files_detail[:10],  # Only keep first 10 for summary
    }


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

    records: dict[str, dict] = {}
    current_source = ""
    current_file_covered = 0
    current_file_total = 0
    in_record = False

    def flush_record() -> None:
        nonlocal current_source, current_file_covered, current_file_total, in_record
        if not in_record or not current_source:
            return
        source = (
            component.normalize_lcov_source(current_source, repo_root)
            if component is not None
            else current_source.replace("\\", "/")
        )
        record = records.setdefault(
            source,
            {
                "path": source,
                "covered_lines": 0,
                "total_lines": 0,
            },
        )
        record["covered_lines"] += current_file_covered
        record["total_lines"] += current_file_total
        current_source = ""
        current_file_covered = 0
        current_file_total = 0
        in_record = False

    with open(lcov_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("SF:"):
                flush_record()
                in_record = True
                current_source = line[3:]
                current_file_covered = 0
                current_file_total = 0
            elif line.startswith("LH:"):
                try:
                    current_file_covered = int(line[3:])
                except ValueError:
                    pass
            elif line.startswith("LF:"):
                try:
                    current_file_total = int(line[3:])
                except ValueError:
                    pass
            elif line == "end_of_record":
                flush_record()

    flush_record()

    return [
        {
            **record,
            "coverage_percent": _coverage_percent(
                record["covered_lines"], record["total_lines"]
            ),
        }
        for record in records.values()
    ]


def parse_lcov_file(lcov_path: Path) -> dict:
    """Parse lcov coverage file and extract covered line counts.

    LCOV format has per-file records with LH/LF summaries.
    We must accumulate LH/LF from each file, not override.
    """
    records = parse_lcov_records(lcov_path)
    total_covered = sum(record["covered_lines"] for record in records)
    total_measured = sum(record["total_lines"] for record in records)
    return {
        "covered_lines": total_covered,
        "total_measured_lines": total_measured,
    }


def required_artifacts_preflight(
    components: tuple[CoverageComponent, ...] = PREFLIGHT_COMPONENTS,
    repo_root: Path = ROOT_DIR,
) -> list[str]:
    """Return explicit errors for missing/empty CI-critical coverage artifacts.

    #414: a missing artifact must surface as a named failure, not silently
    collapse to 0% and skew the unified number. #923: only ``ci-critical``
    components are enforced; ``best-effort`` trees (e.g. tools) are skipped so a
    missing best-effort artifact does not hard-fail the aggregation.

    Each returned string names the component and its expected LCOV path so CI
    output identifies exactly which artifact is missing or empty.
    """
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
            continue
        measured = parse_lcov_file(lcov_path)["total_measured_lines"]
        if measured <= 0:
            errors.append(
                f"{component.name}: required coverage artifact {rel} is empty "
                "(no measured lines); refusing to aggregate a misleading 0%"
            )
    return errors


def resolve_required_components(
    names: str | None,
) -> tuple[CoverageComponent, ...]:
    """Resolve a comma-separated component name list into preflight components.

    ``names`` is the raw value from ``--require-artifacts`` or
    ``COVERAGE_REQUIRED_COMPONENTS``. ``None``/empty -> no enforced components
    (lenient). ``"all"`` -> the full policy set. Unknown names raise ``ValueError``
    so a typo fails loudly instead of silently disabling the gate.
    """
    if not names:
        return ()
    requested = [token.strip() for token in names.split(",") if token.strip()]
    if not requested:
        return ()
    if requested == ["all"]:
        return COMPONENTS
    resolved: list[CoverageComponent] = []
    unknown: list[str] = []
    for name in requested:
        if name in COMPONENT_BY_NAME:
            resolved.append(COMPONENT_BY_NAME[name])
        else:
            unknown.append(name)
    if unknown:
        valid = ", ".join(sorted(COMPONENT_BY_NAME))
        raise ValueError(
            f"unknown coverage component(s) {unknown!r}; valid names: {valid} (or 'all')"
        )
    return tuple(resolved)


def get_component_coverage(component: CoverageComponent) -> dict:
    lcov_path = component.lcov_path(ROOT_DIR)
    coverage_data = parse_lcov_file(lcov_path)
    policy_stats = count_policy_files(component)
    total_lines = coverage_data["total_measured_lines"]
    return {
        "total_lines": total_lines,
        "covered_lines": coverage_data["covered_lines"],
        "coverage_percent": _coverage_percent(
            coverage_data["covered_lines"], total_lines
        ),
        "file_count": policy_stats["file_count"],
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
    breakdown = {
        "backend": backend,
        "frontend": frontend,
    }
    if common is not None:
        breakdown["common"] = common
    if tools is not None:
        breakdown["tools"] = tools

    total_lines = sum(component["total_lines"] for component in breakdown.values())
    covered_lines = sum(component["covered_lines"] for component in breakdown.values())

    return {
        "total_lines": total_lines,
        "covered_lines": covered_lines,
        "coverage_percent": _coverage_percent(covered_lines, total_lines),
        "breakdown": breakdown,
    }


def _repo_relative_path(
    component: CoverageComponent, component_relative_path: str
) -> str:
    if component.component_root:
        return f"{component.component_root}/{component_relative_path}"
    return component_relative_path


def collect_low_coverage_files(
    threshold: float,
    repo_root: Path = ROOT_DIR,
    components: tuple[CoverageComponent, ...] = COMPONENTS,
) -> list[dict]:
    """Return file-level LCOV records below threshold using the shared policy."""
    rows = []
    for component in components:
        for record in parse_lcov_records(
            component.lcov_path(repo_root), component, repo_root
        ):
            total_lines = record["total_lines"]
            coverage_percent = record["coverage_percent"]
            if total_lines > 0 and coverage_percent < threshold:
                rows.append(
                    {
                        "component": component.name,
                        "path": _repo_relative_path(component, record["path"]),
                        "covered_lines": record["covered_lines"],
                        "total_lines": total_lines,
                        "coverage_percent": coverage_percent,
                    }
                )
    return sorted(
        rows, key=lambda row: (row["coverage_percent"], row["component"], row["path"])
    )


def print_low_coverage_files(rows: list[dict], threshold: float) -> None:
    print("\n" + "=" * 60)
    print(f"LOW COVERAGE FILES (< {threshold:g}%)")
    print("=" * 60)
    if not rows:
        print(f"✅ No files below {threshold:g}%")
        return
    print(f"{'Component':<10} {'Coverage':>9} {'Lines':>11}  File")
    print("-" * 60)
    for row in rows:
        lines = f"{row['covered_lines']}/{row['total_lines']}"
        print(
            f"{row['component']:<10} "
            f"{row['coverage_percent']:>8.2f}% "
            f"{lines:>11}  "
            f"{row['path']}"
        )


# Run-to-run measurement jitter: one covered line in an ~11k-line component
# moves the rounded percent by 0.01 — enough to flip a strict `current <
# baseline` compare and red a main run with no code change (seen after the
# #1631 re-baseline: common flapped 93.46<->93.47). Dips within this epsilon
# are noise, not regressions; the baseline-PR bot quantizes its rises the same
# way (ci.yml "Open unified coverage baseline PR").
REGRESSION_EPSILON_PCT = 0.05


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
        delta = round(current - baseline, 2)
        if name == "unified":
            source = "coverage/unified.lcov"
        else:
            source = get_component(name).ci_lcov_path
        lines.append(
            "   "
            + f"- {name}: current={current:.2f}% baseline={baseline:.2f}% "
            + f"delta={delta:.2f}% source={source}"
        )
    return "\n".join(lines)


def _format_line_ratio(data: dict) -> str:
    covered = int(data.get("covered_lines", 0))
    total = int(data.get("total_lines", 0))
    percent = float(data.get("coverage_percent", 0))
    return f"{covered}/{total} ({percent:.2f}%)"


def print_baseline_comparison(
    *,
    current_unified: dict,
    baseline: dict,
) -> None:
    """Print raw line counts used by the no-regression comparison."""
    print("\n" + "=" * 60)
    print("BASELINE COMPARISON")
    print("=" * 60)
    print(
        "   unified: "
        f"current={_format_line_ratio(current_unified)} "
        f"baseline={_format_line_ratio(baseline)}"
    )

    current_breakdown = current_unified.get("breakdown", {})
    baseline_breakdown = baseline.get("breakdown", {})
    for component_name in ("backend", "frontend", "common", "tools"):
        if (
            component_name not in current_breakdown
            or component_name not in baseline_breakdown
        ):
            continue
        print(
            f"   {component_name}: "
            f"current={_format_line_ratio(current_breakdown[component_name])} "
            f"baseline={_format_line_ratio(baseline_breakdown[component_name])}"
        )


def write_unified_coverage(unified: dict, output_path: Path) -> None:
    with open(output_path, "w") as f:
        json.dump(unified, f, indent=2)
    print(f"\n📄 Report saved to: {output_path}")


def parse_args(argv: list[str] | tuple[str, ...]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calculate unified LCOV coverage.")
    parser.add_argument(
        "--list-low-files",
        action="store_true",
        help="Print files below the file-level LCOV threshold.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=90.0,
        help=(
            "File-level threshold for --list-low-files only; "
            "does not affect the coverage gate."
        ),
    )
    parser.add_argument(
        "--require-artifacts",
        default=None,
        metavar="COMPONENTS",
        help=(
            "Opt-in strict artifact preflight (#414): comma-separated component "
            "names that MUST have a present, non-empty LCOV (e.g. "
            "'backend,frontend,common', or 'all'). Only CI-critical tiers are "
            "enforced. Omitted -> lenient (missing artifact reported, not a hard "
            f"abort); falls back to the {REQUIRED_COMPONENTS_ENV} env var."
        ),
    )
    parser.add_argument(
        "--gate-components",
        default=None,
        metavar="COMPONENTS",
        help=(
            "#1689: comma-separated component names (e.g. 'backend,tools', or "
            "'all') whose no-regression check BLOCKS this run. Components "
            "outside the set are still computed and written to "
            "unified-coverage.json, but a regression there is reported, not "
            "gate-failing (main-branch push still catches it via the full "
            "unscoped run). Omitted -> 'all' (unchanged, strict); falls back "
            f"to the {GATE_COMPONENTS_ENV} env var."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | tuple[str, ...] = ()) -> None:
    """Main entry point."""
    args = parse_args(argv)

    print("=" * 60)
    print("Unified Coverage Calculator")
    print("=" * 60)

    # Artifact preflight (#414/#923): fail fast and name the offending artifact
    # before aggregating or writing unified-coverage.json, so a *required* input
    # never collapses to a silent, misleading 0%. The gate is opt-in (CI parity):
    # the always-run CI calculate step tolerates legitimately-absent artifacts, so
    # by default nothing is enforced. A caller names exactly which components are
    # required via --require-artifacts or COVERAGE_REQUIRED_COMPONENTS; if neither
    # is given, PREFLIGHT_COMPONENTS (empty by default) is used.
    required_spec = args.require_artifacts
    if required_spec is None:
        required_spec = os.environ.get(REQUIRED_COMPONENTS_ENV, "").strip() or None
    if required_spec is not None:
        try:
            preflight_components = resolve_required_components(required_spec)
        except ValueError as exc:
            print(
                f"\n❌ Invalid --require-artifacts/{REQUIRED_COMPONENTS_ENV}: {exc}",
                file=sys.stderr,
            )
            sys.exit(2)
    else:
        preflight_components = PREFLIGHT_COMPONENTS

    # #1689: resolve the gate scope. None means "gate everything" (the
    # unchanged, strict default every caller gets unless it opts in) — reusing
    # resolve_required_components since it is a general comma-list/"all" name
    # resolver, not preflight-specific despite the function name.
    gate_spec = args.gate_components
    if gate_spec is None:
        gate_spec = os.environ.get(GATE_COMPONENTS_ENV, "").strip() or None
    gate_component_names: set[str] | None
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
            sys.exit(2)
    else:
        gate_component_names = None

    preflight_errors = required_artifacts_preflight(preflight_components, ROOT_DIR)
    if preflight_errors:
        print(
            "\n❌ Coverage artifact preflight failed: required component "
            "artifact(s) missing or empty.",
            file=sys.stderr,
        )
        for error in preflight_errors:
            print(f"   - {error}", file=sys.stderr)
        sys.exit(1)

    # Get coverage for each component
    print("\n📊 Backend Coverage...")
    backend = get_backend_coverage()
    print(f"   Total lines: {backend['total_lines']:,}")
    print(f"   Covered lines: {backend['covered_lines']:,}")
    print(f"   Coverage: {backend['coverage_percent']}%")

    print("\n📊 Frontend Coverage...")
    frontend = get_frontend_coverage()
    print(f"   Total lines: {frontend['total_lines']:,}")
    print(f"   Covered lines: {frontend['covered_lines']:,}")
    print(f"   Coverage: {frontend['coverage_percent']}%")

    print("\n📊 Common Coverage...")
    common = get_common_coverage()
    print(f"   Total lines: {common['total_lines']:,}")
    print(f"   Covered lines: {common['covered_lines']:,}")
    print(f"   Coverage: {common['coverage_percent']}%")

    print("\n📊 Tools Coverage...")
    tools = get_tools_coverage()
    print(f"   Total lines: {tools['total_lines']:,}")
    print(f"   Covered lines: {tools['covered_lines']:,}")
    print(f"   Coverage: {tools['coverage_percent']}%")

    # Calculate unified coverage
    unified = calculate_unified_coverage(backend, frontend, common, tools)

    if args.list_low_files:
        print_low_coverage_files(
            collect_low_coverage_files(args.threshold, ROOT_DIR),
            args.threshold,
        )

    # Baseline comparison
    baseline_file = os.environ.get("BASELINE_FILE", "").strip()
    if not baseline_file:
        baseline_file = "unified-coverage.json"
    baseline_path = ROOT_DIR / baseline_file

    regression_error = ""
    try:
        if baseline_path.exists():
            with open(baseline_path, "r") as f:
                baseline = json.load(f)

            print_baseline_comparison(current_unified=unified, baseline=baseline)

            # Compare each component against baseline
            baseline_breakdown = baseline.get("breakdown", {})
            baseline_unified = baseline.get("coverage_percent", 0)

            regressions: list[tuple[str, float, float]] = []
            unified_current = round(unified["coverage_percent"], 2)
            unified_floor = round(float(baseline_unified), 2)
            # #1689: the blended "unified" total mixes every component, so a
            # scoped gate (PR touched only some components) cannot fairly
            # attribute a total dip to THIS run — skip it when scoped; an
            # unscoped (None = "all") run keeps checking it, unchanged.
            if (
                gate_component_names is None
                and unified_current < unified_floor - REGRESSION_EPSILON_PCT
            ):
                regressions.append(("unified", unified_current, unified_floor))

            # Component breakdown comparison (if available)
            components_to_check = []
            if "backend" in baseline_breakdown:
                components_to_check.append(
                    ("backend", backend, baseline_breakdown["backend"])
                )
            if "frontend" in baseline_breakdown:
                components_to_check.append(
                    ("frontend", frontend, baseline_breakdown["frontend"])
                )
            if "common" in baseline_breakdown:
                components_to_check.append(
                    ("common", common, baseline_breakdown["common"])
                )
            if "tools" in baseline_breakdown:
                components_to_check.append(
                    ("tools", tools, baseline_breakdown["tools"])
                )

            if gate_component_names is not None:
                out_of_scope = [
                    name
                    for name, _current, _baseline in components_to_check
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

            for component_name, current_data, baseline_data in components_to_check:
                current_percent = round(float(current_data["coverage_percent"]), 2)
                baseline_percent = round(float(baseline_data["coverage_percent"]), 2)
                if current_percent < baseline_percent - REGRESSION_EPSILON_PCT:
                    regressions.append(
                        (component_name, current_percent, baseline_percent)
                    )

            if regressions:
                regression_error = _format_regression_error(
                    baseline_path=baseline_path,
                    regressions=regressions,
                )

            if not regression_error:
                print("✅ No regression: all coverage at or above baseline")
        else:
            print(f"⚠️  Baseline file not found: {baseline_path}", file=sys.stderr)
            print("⚠️  Continuing with coverage threshold check...", file=sys.stderr)

    except FileNotFoundError:
        print(f"⚠️  Baseline file not found: {baseline_path}", file=sys.stderr)
        print("⚠️  Continuing with coverage threshold check...", file=sys.stderr)
    except json.JSONDecodeError:
        print(f"⚠️  Invalid baseline file: {baseline_path}", file=sys.stderr)
        print("⚠️  Continuing with coverage threshold check...", file=sys.stderr)
    except Exception as e:
        print(f"⚠️  Error reading baseline file: {e}", file=sys.stderr)
        print("⚠️  Continuing with coverage threshold check...", file=sys.stderr)

    print("\n" + "=" * 60)
    print("🎯 UNIFIED COVERAGE")
    print("=" * 60)
    print(f"\n   Total lines: {unified['total_lines']:,}")
    print(f"   Covered lines: {unified['covered_lines']:,}")
    print(f"   Coverage: {unified['coverage_percent']}%")
    print("\n" + "-" * 60)

    # Write output JSON before exiting on regressions so CI artifacts can show
    # the exact raw line counts that failed the gate.
    output_path = ROOT_DIR / "unified-coverage.json"
    write_unified_coverage(unified, output_path)

    if regression_error:
        print(regression_error, file=sys.stderr)
        sys.exit(1)

    # Exit with appropriate code (safety net after baseline check)
    threshold = int(os.environ.get("COVERAGE_THRESHOLD", "0"))
    if unified["coverage_percent"] >= threshold:
        print(
            f"✅ Coverage ({unified['coverage_percent']}%) meets threshold ({threshold}%)"
        )
        sys.exit(0)
    else:
        print(
            f"❌ Coverage ({unified['coverage_percent']}%) below threshold ({threshold}%)"
        )
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
