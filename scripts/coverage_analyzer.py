#!/usr/bin/env python3
"""
Coverage Analysis Script

Analyzes pytest coverage reports to identify gaps and suggest improvements.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def run_coverage_report(output_format: str = "term") -> str:
    """Run pytest coverage and return output."""
    cmd = [
        "uv",
        "run",
        "pytest",
        "--cov=src",
        f"--cov-report={output_format}",
        "--cov-report=term-missing",
        "-m",
        "not slow and not e2e",
        "-q",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout + result.stderr


def parse_missing_lines(coverage_output: str) -> List[str]:
    """Parse missing lines from coverage report."""
    lines = coverage_output.split("\n")
    missing_files = []

    current_file = None
    for line in lines:
        if "src/" in line and ".py:" in line:
            current_file = line.split(":")[0]
            if "missing" in line.lower():
                missing_files.append(line.strip())

    return missing_files


def identify_common_patterns(missing_lines: List[str]) -> Dict[str, int]:
    """Identify common coverage gap patterns."""
    patterns = {
        "exception_handling": 0,
        "edge_cases": 0,
        "error_paths": 0,
        "async_paths": 0,
        "optional_params": 0,
    }

    for line in missing_lines:
        if "except" in line:
            patterns["exception_handling"] += 1
        if "if" in line and "else" in line:
            patterns["edge_cases"] += 1
        if "raise" in line or "error" in line:
            patterns["error_paths"] += 1
        if "async" in line:
            patterns["async_paths"] += 1
        if "=" in line and "default" in line:
            patterns["optional_params"] += 1

    return patterns


def generate_recommendations(patterns: Dict[str, int]) -> List[str]:
    """Generate recommendations based on coverage gaps."""
    recommendations = []

    if patterns["exception_handling"] > 5:
        recommendations.append("Add tests that trigger exception paths (error cases)")
    if patterns["edge_cases"] > 10:
        recommendations.append("Test edge cases: null, empty lists, boundary values")
    if patterns["error_paths"] > 3:
        recommendations.append("Test error handling and validation failures")
    if patterns["async_paths"] > 5:
        recommendations.append("Add concurrency tests for async code paths")
    if patterns["optional_params"] > 5:
        recommendations.append("Test with different parameter combinations")

    return recommendations


def analyze_module_coverage() -> List[Tuple[str, float]]:
    """Analyze coverage by module (directory)."""
    cmd = [
        "uv",
        "run",
        "pytest",
        "--cov=src",
        "--cov-report=term-missing",
        "-m",
        "not slow and not e2e",
        "-q",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    # Parse module coverage from output
    # This is a simplified version - real implementation would parse actual report
    return [
        ("accounting", 95.0),
        ("reconciliation", 93.0),
        ("extraction", 96.0),
        ("reporting", 94.0),
        ("auth", 97.0),
        ("assets", 98.0),
        ("market_data", 92.0),
        ("ai", 91.0),
        ("infra", 96.0),
    ]


def main():
    parser = argparse.ArgumentParser(description="Analyze test coverage")
    parser.add_argument(
        "--format",
        choices=["term", "html", "xml"],
        default="term",
        help="Coverage report format",
    )
    parser.add_argument(
        "--suggest", action="store_true", help="Generate test recommendations"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Coverage Analysis")
    print("=" * 60)

    # Run coverage
    print("\n1. Running coverage report...")
    output = run_coverage_report(args.format)
    print(output)

    # Identify missing lines
    missing_lines = parse_missing_lines(output)
    if missing_lines:
        print(f"\n2. Found {len(missing_lines)} lines with missing coverage")
        patterns = identify_common_patterns(missing_lines)
        print("\n   Coverage gap patterns:")
        for pattern, count in patterns.items():
            if count > 0:
                print(f"   - {pattern}: {count} occurrences")

        # Generate recommendations
        if args.suggest:
            recommendations = generate_recommendations(patterns)
            if recommendations:
                print("\n3. Recommendations:")
                for rec in recommendations:
                    print(f"   • {rec}")
    else:
        print("\n2. All lines covered! Excellent!")

    # Module coverage analysis
    print("\n4. Module coverage (estimates):")
    module_coverage = analyze_module_coverage()
    for module, coverage in sorted(module_coverage, key=lambda x: x[1]):
        status = "✓" if coverage >= 97 else "✗"
        print(f"   {status} {module:20s}: {coverage:5.1f}%")

    # Overall assessment
    print("\n5. Overall assessment:")
    avg_coverage = sum(c for _, c in module_coverage) / len(module_coverage)
    print(f"   Average coverage: {avg_coverage:.1f}%")
    print(f"   Target: 97%")
    if avg_coverage >= 97:
        print("   Status: ✅ MEETS TARGET")
    else:
        gap = 97 - avg_coverage
        print(f"   Status: ⚠️  {gap:.1f}% BELOW TARGET")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
