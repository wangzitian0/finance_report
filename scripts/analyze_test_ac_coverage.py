#!/usr/bin/env python3
"""
Analyze test functions for AC (Acceptance Criteria) coverage.

This script scans all test files in apps/backend/tests/ and identifies:
1. Test functions without AC numbers in docstrings
2. Suggested AC categorization based on file location and function name
3. Summary statistics by EPIC/domain

AC Pattern: "ACx.y.z" or "[ACx.y.z]" in docstrings
"""

import ast
import re
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List

# AC pattern (e.g., AC2.2.1, [AC4.3.1], AC13.1.2)
AC_PATTERN = re.compile(r"\[?AC\d+\.\d+\.\d+\]?")

# EPIC mapping based on test file location and keywords
EPIC_MAPPING = {
    "accounting": {
        "epic": "EPIC-002",
        "name": "Double-Entry Bookkeeping Core",
        "ac_prefix": "AC2",
        "keywords": [
            "journal",
            "entry",
            "balance",
            "debit",
            "credit",
            "account",
            "equation",
            "voided",
        ],
    },
    "extraction": {
        "epic": "EPIC-003",
        "name": "Smart Statement Parsing",
        "ac_prefix": "AC3",
        "keywords": [
            "parse",
            "extract",
            "statement",
            "pdf",
            "upload",
            "institution",
            "balance",
            "transaction",
        ],
    },
    "reconciliation": {
        "epic": "EPIC-004",
        "name": "Reconciliation Engine & Matching",
        "ac_prefix": "AC4",
        "keywords": [
            "match",
            "reconcile",
            "score",
            "confidence",
            "review",
            "queue",
            "accept",
            "reject",
        ],
    },
    "reporting": {
        "epic": "EPIC-005",
        "name": "Financial Reports & Visualization",
        "ac_prefix": "AC5",
        "keywords": [
            "report",
            "balance_sheet",
            "income",
            "statement",
            "trend",
            "analysis",
            "visualization",
        ],
    },
    "ai": {
        "epic": "EPIC-006",
        "name": "AI Financial Advisor",
        "ac_prefix": "AC6",
        "keywords": ["ai", "advisor", "chat", "openrouter", "model", "streaming"],
    },
    "auth": {
        "epic": "EPIC-001",
        "name": "Infrastructure & Authentication",
        "ac_prefix": "AC1",
        "keywords": ["auth", "login", "user", "session", "token", "permission"],
    },
    "infra": {
        "epic": "EPIC-001",
        "name": "Infrastructure & Authentication",
        "ac_prefix": "AC1",
        "keywords": [
            "config",
            "logger",
            "migration",
            "schema",
            "rate_limit",
            "exception",
        ],
    },
    "api": {
        "epic": "EPIC-001",
        "name": "Infrastructure & Authentication",
        "ac_prefix": "AC1",
        "keywords": ["router", "endpoint", "schema", "validation"],
    },
    "assets": {
        "epic": "EPIC-011",
        "name": "Asset Lifecycle Management",
        "ac_prefix": "AC11",
        "keywords": ["asset", "depreciation", "purchase", "disposal"],
    },
    "market_data": {
        "epic": "EPIC-005",
        "name": "Financial Reports & Visualization (FX support)",
        "ac_prefix": "AC5",
        "keywords": ["fx", "exchange", "rate", "currency"],
    },
    "services": {
        "epic": "EPIC-005",
        "name": "Financial Reports & Visualization (Services)",
        "ac_prefix": "AC5",
        "keywords": ["fx_service", "anomaly"],
    },
}


@dataclass
class TestFunction:
    """Represents a test function."""

    file_path: str
    function_name: str
    docstring: str
    has_ac: bool
    suggested_ac: str
    domain: str
    epic: str


def extract_test_functions(file_path: Path) -> List[TestFunction]:
    """Extract all test functions from a Python file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        tree = ast.parse(content)
        functions = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                docstring = ast.get_docstring(node) or ""
                has_ac = bool(AC_PATTERN.search(docstring))

                # Determine domain from file path (derive repo root from __file__)
                script_dir = Path(__file__).resolve().parent
                repo_root = script_dir.parent
                tests_dir = repo_root / "apps" / "backend" / "tests"
                try:
                    rel_path = file_path.relative_to(tests_dir)
                except ValueError:
                    rel_path = file_path
                parts = rel_path.parts
                domain = parts[0] if len(parts) > 1 else "root"

                # Map domain to EPIC
                epic_info = EPIC_MAPPING.get(
                    domain,
                    {
                        "epic": "EPIC-001",
                        "name": "Infrastructure & Authentication (Root Tests)",
                        "ac_prefix": "AC1",
                        "keywords": [],
                    },
                )

                # Suggest AC based on domain and function name
                suggested_ac = suggest_ac(node.name, domain, epic_info)

                functions.append(
                    TestFunction(
                        file_path=str(file_path.relative_to(repo_root)),
                        function_name=node.name,
                        docstring=docstring.split("\n")[0] if docstring else "",
                        has_ac=has_ac,
                        suggested_ac=suggested_ac,
                        domain=domain,
                        epic=epic_info["epic"],
                    )
                )

        return functions
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
        return []


def suggest_ac(function_name: str, domain: str, epic_info: Dict) -> str:
    """Suggest an AC number based on function name and domain."""
    ac_prefix = epic_info["ac_prefix"]
    # Try to match keywords to subcategories
    name_lower = function_name.lower()

    # Domain-specific AC suggestions
    if domain == "accounting":
        if "balance" in name_lower or "equation" in name_lower:
            return f"{ac_prefix}.2.x (Balance Validation)"
        if "voided" in name_lower or "void" in name_lower:
            return f"{ac_prefix}.3.x (Entry Lifecycle - Voiding)"
        if "journal" in name_lower or "entry" in name_lower:
            return f"{ac_prefix}.1.x (Journal Entry Creation)"
        return f"{ac_prefix}.x.x (Accounting Core)"

    elif domain == "extraction":
        if "balance" in name_lower and "valid" in name_lower:
            return f"{ac_prefix}.1.x (Balance Validation)"
        if "confidence" in name_lower or "score" in name_lower:
            return f"{ac_prefix}.2.x (Confidence Scoring)"
        if "parse" in name_lower or "extract" in name_lower:
            return f"{ac_prefix}.3.x (Statement Parsing)"
        if "upload" in name_lower or "storage" in name_lower:
            return f"{ac_prefix}.4.x (File Upload & Storage)"
        return f"{ac_prefix}.x.x (Statement Parsing)"

    elif domain == "reconciliation":
        if "score" in name_lower or "confidence" in name_lower:
            return f"{ac_prefix}.2.x (Match Scoring)"
        if "accept" in name_lower or "reject" in name_lower:
            return f"{ac_prefix}.3.x (Auto-Accept/Review Queue)"
        if "match" in name_lower:
            return f"{ac_prefix}.1.x (Matching Engine)"
        if "anomaly" in name_lower:
            return f"{ac_prefix}.4.x (Anomaly Detection)"
        return f"{ac_prefix}.x.x (Reconciliation)"

    elif domain == "reporting":
        if "balance_sheet" in name_lower or "balance" in name_lower:
            return f"{ac_prefix}.1.x (Balance Sheet)"
        if "income" in name_lower or "profit" in name_lower or "loss" in name_lower:
            return f"{ac_prefix}.2.x (Income Statement)"
        if "fx" in name_lower or "currency" in name_lower:
            return f"{ac_prefix}.3.x (Multi-Currency Support)"
        if "snapshot" in name_lower:
            return f"{ac_prefix}.4.x (Financial Snapshots)"
        return f"{ac_prefix}.x.x (Reporting)"

    elif domain == "ai":
        if "chat" in name_lower:
            return f"{ac_prefix}.1.x (Chat Interface)"
        if "model" in name_lower:
            return f"{ac_prefix}.2.x (Model Management)"
        if "streaming" in name_lower:
            return f"{ac_prefix}.3.x (Streaming Responses)"
        if "advisor" in name_lower:
            return f"{ac_prefix}.4.x (Financial Advisory)"
        return f"{ac_prefix}.x.x (AI Features)"

    elif domain == "assets":
        if "depreciation" in name_lower:
            return f"{ac_prefix}.2.x (Depreciation)"
        if "purchase" in name_lower or "acquisition" in name_lower:
            return f"{ac_prefix}.1.x (Asset Acquisition)"
        if "disposal" in name_lower:
            return f"{ac_prefix}.3.x (Asset Disposal)"
        return f"{ac_prefix}.x.x (Asset Management)"

    elif domain in ["auth", "infra", "api"]:
        if "auth" in name_lower or "login" in name_lower:
            return f"{ac_prefix}.1.x (Authentication)"
        if "config" in name_lower:
            return f"{ac_prefix}.2.x (Configuration)"
        if "migration" in name_lower or "schema" in name_lower:
            return f"{ac_prefix}.3.x (Database Schema)"
        if "rate_limit" in name_lower:
            return f"{ac_prefix}.4.x (Rate Limiting)"
        return f"{ac_prefix}.x.x (Infrastructure)"

    # Default
    return f"{ac_prefix}.x.x (Uncategorized)"


def main():
    """Main analysis function."""
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    tests_dir = repo_root / "apps" / "backend" / "tests"

    # Collect all test files
    test_files = list(tests_dir.rglob("test_*.py"))

    print(f"🔍 Scanning {len(test_files)} test files...\n")

    all_functions = []
    for test_file in test_files:
        functions = extract_test_functions(test_file)
        all_functions.extend(functions)

    if not all_functions:
        print("❌ No test functions found. Exiting.")
        return

    # Categorize
    functions_with_ac = [f for f in all_functions if f.has_ac]
    functions_without_ac = [f for f in all_functions if not f.has_ac]

    # Statistics by EPIC
    epic_stats: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"total": 0, "with_ac": 0, "without_ac": 0}
    )
    for func in all_functions:
        epic_stats[func.epic]["total"] += 1
        if func.has_ac:
            epic_stats[func.epic]["with_ac"] += 1
        else:
            epic_stats[func.epic]["without_ac"] += 1

    # Print summary
    print("=" * 80)
    print("📊 TEST AC COVERAGE SUMMARY")
    print("=" * 80)
    print(f"Total test functions: {len(all_functions)}")
    print(
        f"✅ With AC numbers: {len(functions_with_ac)} ({len(functions_with_ac) / len(all_functions) * 100:.1f}%)"
    )
    print(
        f"❌ Without AC numbers: {len(functions_without_ac)} ({len(functions_without_ac) / len(all_functions) * 100:.1f}%)"
    )
    print()

    # Statistics by EPIC
    print("=" * 80)
    print("📈 COVERAGE BY EPIC")
    print("=" * 80)
    for epic in sorted(epic_stats.keys()):
        stats = epic_stats[epic]
        coverage = (
            (stats["with_ac"] / stats["total"] * 100) if stats["total"] > 0 else 0
        )
        print(
            f"{epic}: {stats['with_ac']}/{stats['total']} ({coverage:.1f}%) | Missing: {stats['without_ac']}"
        )
    print()

    # Print tests without AC
    print("=" * 80)
    print("❌ TESTS WITHOUT AC NUMBERS")
    print("=" * 80)

    # Group by domain
    by_domain: Dict[str, List[TestFunction]] = defaultdict(list)
    for func in functions_without_ac:
        by_domain[func.domain].append(func)

    for domain in sorted(by_domain.keys()):
        funcs = by_domain[domain]
        epic = funcs[0].epic if funcs else "Unknown"
        print(f"\n📁 {domain.upper()} ({epic}) - {len(funcs)} tests")
        print("-" * 80)

        for func in sorted(funcs, key=lambda x: (x.file_path, x.function_name)):
            print(f"  • {func.function_name}")
            print(f"    File: {func.file_path}")
            print(f"    Suggested AC: {func.suggested_ac}")
            if func.docstring:
                print(f"    Docstring: {func.docstring[:70]}...")
            print()

    # Summary table
    print("=" * 80)
    print("📋 SUMMARY TABLE")
    print("=" * 80)
    print(
        f"{'Domain':<20} {'EPIC':<12} {'Total':<8} {'With AC':<10} {'Without AC':<12} {'Coverage':<10}"
    )
    print("-" * 80)

    domain_stats: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"total": 0, "with_ac": 0, "without_ac": 0}
    )
    for func in all_functions:
        domain_stats[func.domain]["total"] += 1
        if func.has_ac:
            domain_stats[func.domain]["with_ac"] += 1
        else:
            domain_stats[func.domain]["without_ac"] += 1

    for domain in sorted(domain_stats.keys()):
        stats = domain_stats[domain]
        epic = EPIC_MAPPING.get(domain, {}).get("epic", "EPIC-001")
        coverage = (
            (stats["with_ac"] / stats["total"] * 100) if stats["total"] > 0 else 0
        )
        print(
            f"{domain:<20} {epic:<12} {stats['total']:<8} {stats['with_ac']:<10} {stats['without_ac']:<12} {coverage:>6.1f}%"
        )

    print()
    print("=" * 80)
    print("✅ Analysis complete!")
    print("=" * 80)


if __name__ == "__main__":
    main()
