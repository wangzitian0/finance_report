#!/usr/bin/env python3
"""
Unified Coverage Calculator

Calculates unified test coverage across backend, frontend, scripts, tools, and common.
Uses blacklist approach: all .py/.ts/.sh files count as code UNLESS:
- Filename starts with 'test_'
- Path contains '/test/' or '__tests__/'

Output: unified-coverage.json with:
- backend: {total_lines, covered_lines, coverage_percent}
- frontend: {total_lines, covered_lines, coverage_percent}
- scripts: {total_lines, covered_lines, coverage_percent}
- tools: {total_lines, covered_lines, coverage_percent}
- common: {total_lines, covered_lines, coverage_percent}
- unified: {total_lines, covered_lines, coverage_percent}
"""

import argparse
import json
import os
import sys
from pathlib import Path

from common.coverage.policy import COMPONENTS, CoverageComponent, get_component

# Configuration
ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "apps" / "backend"
FRONTEND_DIR = ROOT_DIR / "apps" / "frontend"
SCRIPTS_DIR = ROOT_DIR / "scripts"
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


def get_scripts_coverage() -> dict:
    return get_component_coverage(get_component("scripts"))


def get_common_coverage() -> dict:
    return get_component_coverage(get_component("common"))


def get_tools_coverage() -> dict:
    return get_component_coverage(get_component("tools"))


def calculate_unified_coverage(
    backend: dict,
    frontend: dict,
    scripts: dict,
    common: dict | None = None,
    tools: dict | None = None,
) -> dict:
    """Calculate unified coverage across all components."""
    breakdown = {
        "backend": backend,
        "frontend": frontend,
        "scripts": scripts,
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


def _format_regression_error(
    *,
    baseline_path: Path,
    regressions: list[tuple[str, float, float]],
) -> str:
    lines = [
        "❌ Coverage regression detected by local deterministic gate.",
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
    return parser.parse_args(argv)


def main(argv: list[str] | tuple[str, ...] = ()) -> None:
    """Main entry point."""
    args = parse_args(argv)

    print("=" * 60)
    print("Unified Coverage Calculator")
    print("=" * 60)

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

    print("\n📊 Scripts Coverage...")
    scripts = get_scripts_coverage()
    print(f"   Total lines: {scripts['total_lines']:,}")
    print(f"   Covered lines: {scripts['covered_lines']:,}")
    print(f"   Coverage: {scripts['coverage_percent']}%")

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
    unified = calculate_unified_coverage(backend, frontend, scripts, common, tools)

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

    try:
        if baseline_path.exists():
            with open(baseline_path, "r") as f:
                baseline = json.load(f)

            # Compare each component against baseline
            baseline_breakdown = baseline.get("breakdown", {})
            baseline_unified = baseline.get("coverage_percent", 0)

            regressions: list[tuple[str, float, float]] = []
            unified_current = round(unified["coverage_percent"], 2)
            unified_floor = round(float(baseline_unified), 2)
            if unified_current < unified_floor:
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
            if "scripts" in baseline_breakdown:
                components_to_check.append(
                    ("scripts", scripts, baseline_breakdown["scripts"])
                )
            if "common" in baseline_breakdown:
                components_to_check.append(
                    ("common", common, baseline_breakdown["common"])
                )
            if "tools" in baseline_breakdown:
                components_to_check.append(
                    ("tools", tools, baseline_breakdown["tools"])
                )

            for component_name, current_data, baseline_data in components_to_check:
                current_percent = round(float(current_data["coverage_percent"]), 2)
                baseline_percent = round(float(baseline_data["coverage_percent"]), 2)
                if current_percent < baseline_percent:
                    regressions.append(
                        (component_name, current_percent, baseline_percent)
                    )

            if regressions:
                print(
                    _format_regression_error(
                        baseline_path=baseline_path,
                        regressions=regressions,
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)

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

    # Write output JSON
    output_path = ROOT_DIR / "unified-coverage.json"
    with open(output_path, "w") as f:
        json.dump(unified, f, indent=2)
    print(f"\n📄 Report saved to: {output_path}")

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
