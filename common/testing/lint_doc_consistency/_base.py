"""Shared doc-consistency paths and config constants."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]

VISION_PATH = REPO_ROOT / "vision.md"
EPIC_DIR = REPO_ROOT / "docs" / "project"
AC_REGISTRY = REPO_ROOT / "docs" / "ac_registry.yaml"
INFRA_REGISTRY = REPO_ROOT / "docs" / "infra_registry.yaml"
CI_CD_SSOT = REPO_ROOT / "docs" / "ssot" / "ci-cd.md"
TDD_SSOT = REPO_ROOT / "docs" / "ssot" / "tdd.md"
TRACEABILITY_EXCEPTIONS = REPO_ROOT / "docs" / "project" / "traceability-exceptions.md"
MKDOCS_CONFIG = REPO_ROOT / "mkdocs.yml"
RECONCILIATION_SSOT = REPO_ROOT / "docs" / "ssot" / "reconciliation.md"
FRONTEND_SRC = REPO_ROOT / "apps" / "frontend" / "src"

TEST_ROOTS = [
    REPO_ROOT / "apps" / "backend" / "tests",
    REPO_ROOT / "apps" / "frontend" / "src" / "__tests__",
    REPO_ROOT / "apps" / "frontend" / "playwright",
    REPO_ROOT / "tests" / "tooling",
    REPO_ROOT / "tests" / "e2e",
]

NO_AC_SCAN_TARGETS: tuple[tuple[Path, tuple[str, ...]], ...] = (
    (REPO_ROOT / "apps" / "backend" / "tests", ("**/*.py",)),
    (
        REPO_ROOT / "apps" / "frontend" / "src",
        ("**/*.test.ts", "**/*.test.tsx"),
    ),
    (
        REPO_ROOT / "apps" / "frontend" / "playwright",
        ("**/*.spec.ts", "**/*.spec.tsx"),
    ),
    (REPO_ROOT / "tests" / "tooling", ("**/*.py",)),
    (REPO_ROOT / "tests" / "e2e", ("**/*.py",)),
)

CHECK6_TEST_ROOTS = [r for r in TEST_ROOTS if r != REPO_ROOT / "tests" / "tooling"]
E2E_PRODUCT_TEST_EXCEPTION_PREFIXES = (
    "tests/e2e/test_",
    "apps/backend/tests/e2e/test_",
)

# Allow-list of AC IDs that may appear in test fixtures without a
# matching registry entry. Keep this list tight; every entry should be
# justified by a fixture that intentionally references a synthetic ID.
CHECK6_FIXTURE_EXCLUDE: set[str] = {
    "AC1.1.9",
    "AC1.1.10",
    "AC1.99.1",
    "AC9.8.1",
    "AC9.8.2",
    "AC10.2.1",
}

EXCLUDED_DIRS = {
    "node_modules",
    "__pycache__",
    ".next",
    "dist",
    ".cache",
    ".pytest_cache",
}

TEST_FILE_SUFFIXES = (
    "_test.py",
    ".test.ts",
    ".test.tsx",
    ".spec.ts",
    ".spec.tsx",
)

# Matches BOTH AC id grammars (mirrors common.testing.ac_traceability_refs):
# legacy ``AC{epic}.{n}.{n}`` and package-scoped ``AC-{package}.{group}.{n}``,
# where ``group`` is either numeric or a word-entity slug (e.g. ``guardrail``,
# ``fx-transfer``). The ``epic`` group is set only for the legacy form (``pkg``
# for the package form), so consumers needing the EPIC number must check
# ``group("epic")`` is not None.
AC_PATTERN = re.compile(
    r"\bAC(?:(?P<epic>\d+)\.\d+\.\d+"
    r"|-(?P<pkg>[a-z][a-z0-9_]*)\.[a-z0-9][a-z0-9_-]*\.\d+)\b"
)

# Lines in EPIC docs that document AC IDs as removed/duplicated/
# canonicalised must NOT count as live references for check #4
# (epic-to-registry). Two legitimate annotation forms exist in the
# corpus:
#
#   *(AC10.2.1 removed - canonical copy is AC12.1.1 in EPIC-012)*
#   *(AC10.3.1 and AC10.3.2 removed - canonical copies are ...)*
#
# and summary roll-ups of the form:
#
#   - Total AC IDs: 52 (AC2.11.1-2.11.3, AC2.11.5-2.11.6 removed ...)
#
# Skip both at parse-time so the EPIC->registry check stays strict on
# real dangling references but tolerant of historical bookkeeping.
REMOVED_ANNOTATION_RE = re.compile(
    r"\*?\(\s*AC\d+\.\d+(?:\.\d+)?.*?(removed|duplicate|canonical)",
    re.IGNORECASE,
)
TOTAL_AC_SUMMARY_TOKEN = "Total AC IDs:"
