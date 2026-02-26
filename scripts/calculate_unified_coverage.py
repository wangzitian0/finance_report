#!/usr/bin/env python3
"""
Unified Coverage Calculator

Calculates unified test coverage across backend, frontend, and scripts.
Uses blacklist approach: all .py/.ts/.sh files count as code UNLESS:
- Filename starts with 'test_'
- Path contains '/test/' or '__tests__/'

Output: unified-coverage.json with:
- backend: {total_lines, covered_lines, coverage_percent}
- frontend: {total_lines, covered_lines, coverage_percent}
- scripts: {total_lines, covered_lines, coverage_percent}
- unified: {total_lines, covered_lines, coverage_percent}
"""

import json
import os
import subprocess
import sys
from pathlib import Path


# Configuration
ROOT_DIR = Path(__file__).parent.parent
BACKEND_DIR = ROOT_DIR / "apps" / "backend"
FRONTEND_DIR = ROOT_DIR / "apps" / "frontend"
SCRIPTS_DIR = ROOT_DIR / "scripts"

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
    "test_",
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
    
    for pattern in BLACKLIST_PATTERNS:
        if pattern in path:
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
                files_detail.append({
                    "path": relative_path,
                    "lines": lines
                })
    
    return {
        "total_lines": total_lines,
        "file_count": file_count,
        "files": files_detail[:10]  # Only keep first 10 for summary
    }


def parse_lcov_file(lcov_path: Path) -> dict:
    """Parse lcov coverage file and extract covered line counts."""
    if not lcov_path.exists():
        return {"covered_lines": 0, "total_measured_lines": 0}
    
    covered_lines = 0
    total_measured_lines = 0
    current_file = None
    file_lines_covered = {}
    
    with open(lcov_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            
            if line.startswith("SF:"):
                current_file = line[3:].strip()
                if current_file and current_file not in file_lines_covered:
                    file_lines_covered[current_file] = {"covered": 0, "total": 0}
            elif line.startswith("DA:"):
                # DA:data_file_path,line_number
                parts = line[3:].split(",")
                if len(parts) >= 2 and current_file:
                    try:
                        line_num = int(parts[1])
                        file_lines_covered[current_file]["total"] += 1
                        total_measured_lines += 1
                    except ValueError:
                        pass
            elif line.startswith("LF:"):
                # LF:data_file_path,line_number,hit_count
                parts = line[3:].split(",")
                if len(parts) >= 3 and current_file:
                    try:
                        hit_count = int(parts[2])
                        if hit_count > 0:
                            file_lines_covered[current_file]["covered"] += 1
                            covered_lines += 1
                    except ValueError:
                        pass
    
    return {
        "covered_lines": covered_lines,
        "total_measured_lines": total_measured_lines,
        "files_detail": file_lines_covered
    }


def get_backend_coverage() -> dict:
    """Get backend coverage from pytest-cov output."""
    # Check both local and CI paths
    lcov_path = BACKEND_DIR / "coverage.lcov"
    ci_lcov_path = ROOT_DIR / "coverage" / "backend.lcov"
    if ci_lcov_path.exists():
        lcov_path = ci_lcov_path
    coverage_data = parse_lcov_file(lcov_path)
    
    # Get total backend code lines
    code_stats = count_code_lines(BACKEND_DIR / "src", [".py"])
    
    return {
        "total_lines": code_stats["total_lines"],
        "covered_lines": coverage_data["covered_lines"],
        "coverage_percent": round(coverage_data["covered_lines"] / max(code_stats["total_lines"], 1) * 100, 2) if code_stats["total_lines"] > 0 else 0,
        "file_count": code_stats["file_count"],
    }


def get_frontend_coverage() -> dict:
    """Get frontend coverage from vitest output."""
    # Check both local and CI paths
    lcov_path = FRONTEND_DIR / "coverage" / "lcov.info"
    ci_lcov_path = ROOT_DIR / "coverage" / "frontend.lcov"
    if ci_lcov_path.exists():
        lcov_path = ci_lcov_path
    coverage_data = parse_lcov_file(lcov_path)
    
    # Get total frontend code lines
    code_stats = count_code_lines(FRONTEND_DIR / "src", [".ts", ".tsx"])
    
    return {
        "total_lines": code_stats["total_lines"],
        "covered_lines": coverage_data["covered_lines"],
        "coverage_percent": round(coverage_data["covered_lines"] / max(code_stats["total_lines"], 1) * 100, 2) if code_stats["total_lines"] > 0 else 0,
        "file_count": code_stats["file_count"],
    }


def get_scripts_coverage() -> dict:
    """Get scripts coverage (run with pytest-cov if tests exist)."""
    lcov_path = ROOT_DIR / "coverage-scripts.lcov"
    coverage_data = parse_lcov_file(lcov_path)
    
    # Get total scripts code lines
    code_stats = count_code_lines(SCRIPTS_DIR, [".py", ".sh"])
    
    return {
        "total_lines": code_stats["total_lines"],
        "covered_lines": coverage_data["covered_lines"],
        "coverage_percent": round(coverage_data["covered_lines"] / max(code_stats["total_lines"], 1) * 100, 2) if code_stats["total_lines"] > 0 else 0,
        "file_count": code_stats["file_count"],
    }


def calculate_unified_coverage(backend: dict, frontend: dict, scripts: dict) -> dict:
    """Calculate unified coverage across all components."""
    total_lines = backend["total_lines"] + frontend["total_lines"] + scripts["total_lines"]
    covered_lines = backend["covered_lines"] + frontend["covered_lines"] + scripts["covered_lines"]
    
    return {
        "total_lines": total_lines,
        "covered_lines": covered_lines,
        "coverage_percent": round(covered_lines / max(total_lines, 1) * 100, 2) if total_lines > 0 else 0,
        "breakdown": {
            "backend": backend,
            "frontend": frontend,
            "scripts": scripts,
        },
    }


def main():
    """Main entry point."""
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
    
    # Calculate unified coverage
    unified = calculate_unified_coverage(backend, frontend, scripts)
    
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
    
    # Exit with appropriate code
    threshold = int(os.environ.get("COVERAGE_THRESHOLD", "80"))
    if unified["coverage_percent"] >= threshold:
        print(f"✅ Coverage ({unified['coverage_percent']}%) meets threshold ({threshold}%)")
        sys.exit(0)
    else:
        print(f"❌ Coverage ({unified['coverage_percent']}%) below threshold ({threshold}%)")
        sys.exit(1)


if __name__ == "__main__":
    main()
