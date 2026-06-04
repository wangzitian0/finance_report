#!/usr/bin/env python3
"""Doc consistency linter (closes issue #339).

Hard-fail checks enforced in CI:

  1. Every EPIC file under docs/project/EPIC-*.md MUST declare a
     ``Vision Anchor`` line whose slug resolves to an existing
     ``<a id="...">`` anchor in vision.md.
  2. Every ``<a id="...">`` anchor in vision.md MUST be referenced by at
     least one EPIC file (no orphan anchors).
  3. Every active AC ID listed in docs/ac_registry.yaml or
     docs/infra_registry.yaml MUST be referenced by at least one EPIC
     file (registry <-> EPIC linkage), unless the AC is marked
     ``deprecated``. Active stubs are not exempt.
  4. Every AC ID referenced in an EPIC file MUST exist in one of the
     two registries (no dangling AC IDs in EPIC docs).
  5. Every AC ID present in either registry MUST appear at least once
     under apps/backend/tests/, apps/frontend/src/__tests__/,
     apps/frontend/playwright/, tests/tooling/, or tests/e2e/, unless the
     AC is marked ``deprecated`` (full traceability).
  6. Every ``ACx.y.z`` referenced from a test file MUST exist in one of
     the two registries AND its ``epic`` field MUST equal ``x`` (the
     epic prefix of the AC ID). Test fixtures under ``tests/tooling/``
     are excluded from check #6 because they intentionally reference
     synthetic AC IDs (e.g. ``AC9.9.9``) that are not present in the
     registries.
  7. docs/ssot/ci-cd.md MUST keep the proof placement policy that
     distinguishes pre-merge behavioral tests from post-merge
     environment gates.
  8. Every test file without an ``ACx.y.z`` reference MUST be listed in
     docs/analysis/traceability-exceptions.md.
 9. Product E2E test files MUST NOT be listed as traceability exceptions;
     attach AC IDs to the test or remove the obsolete file instead.
10. Mutable backend coverage threshold numbers MUST be owned by
     apps/backend/pyproject.toml instead of copied into TDD SSOT prose.
 11. Checked-in Markdown under docs/ MUST be reachable from the MkDocs
     navigation.
 12. Module README files MUST stay as thin pointers to SSOT owners instead of
     duplicating API routes, page inventories, fixtures, or mapping tables.

The script exits 0 on success and 1 on any violation.

Run locally::

    python tools/lint_doc_consistency.py
    python tools/lint_doc_consistency.py --verbose

The Vision Anchor line tolerates three markdown variants observed in
the existing EPIC corpus:

    > **Vision Anchor**: `slug`
    **Vision Anchor**: `slug`
    > Vision Anchor: `slug`
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

try:
    from common.ssot.ac_registry_format import load_registry_entries
except ImportError:  # pragma: no cover - environment guard
    print(
        "ERROR: PyYAML not installed. Run: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parents[2]

VISION_PATH = REPO_ROOT / "vision.md"
EPIC_DIR = REPO_ROOT / "docs" / "project"
AC_REGISTRY = REPO_ROOT / "docs" / "ac_registry.yaml"
INFRA_REGISTRY = REPO_ROOT / "docs" / "infra_registry.yaml"
CI_CD_SSOT = REPO_ROOT / "docs" / "ssot" / "ci-cd.md"
TDD_SSOT = REPO_ROOT / "docs" / "ssot" / "tdd.md"
TRACEABILITY_EXCEPTIONS = REPO_ROOT / "docs" / "analysis" / "traceability-exceptions.md"
MKDOCS_CONFIG = REPO_ROOT / "mkdocs.yml"

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

# Reused from tools/check_ac_traceability.py. Matches the canonical
# AC ID form: ``ACx.y.z`` (epic.major.minor).
AC_PATTERN = re.compile(r"\bAC(\d+)\.(\d+)\.(\d+)\b")

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


def _line_is_ac_annotation(line: str) -> bool:
    """Return True if the line is a removed/duplicate annotation or
    a ``Total AC IDs:`` summary line whose AC IDs should be ignored
    by check #4.
    """
    if TOTAL_AC_SUMMARY_TOKEN in line:
        return True
    return bool(REMOVED_ANNOTATION_RE.search(line))


# EPIC files follow the ``EPIC-NNN.descriptive-name.md`` convention.
# The pattern matches any filename starting with ``EPIC-`` followed by exactly
# three digits (e.g. ``EPIC-016.two-stage-review-ui.md``).
EPIC_FILE_PATTERN = re.compile(r"^EPIC-\d{3}.*\.md$")

# Vision Anchor line. Three accepted markdown variants:
#   ``> **Vision Anchor**: `slug```  (16 EPIC files)
#   ``**Vision Anchor**: `slug```    (EPIC-011, EPIC-012)
#   ``> Vision Anchor: `slug```      (EPIC-013)
VISION_ANCHOR_PATTERN = re.compile(
    r"^\s*>?\s*(?:\*\*Vision Anchor\*\*|Vision Anchor)\s*:\s*"
    r"`(?P<slug>[a-z0-9][a-z0-9-]*)`",
    re.MULTILINE,
)

# HTML anchors in vision.md: ``<a id="slug"></a>``. Tolerates either
# quote style and optional whitespace.
HTML_ANCHOR_PATTERN = re.compile(
    r"""<a\s+id\s*=\s*["'](?P<slug>[a-z0-9][a-z0-9-]*)["']\s*>\s*</a>""",
    re.IGNORECASE,
)

PROOF_PLACEMENT_REQUIRED_TOKENS = (
    "### Proof Placement Policy",
    "| Behavioral tests | PR CI before merge |",
    "| Environment gates | Post-merge deploy workflows |",
    "| Reference traceability | PR and `main` CI |",
    "Behavioral tests should move left into PR CI",
    "Environment-dependent checks",
    "post-merge staging/production workflows",
    "must not be the first proof for deterministic business behavior",
)

MKDOCS_REQUIRED_STATIC_DOCS = {
    "docs/agents/orchestration.md",
    "docs/agents/red-lines.md",
    "docs/contributing/branch-policy.md",
    "docs/project/README.md",
    "docs/project/AUDITS.md",
    "docs/project/AC-AUDIT-2026-05-04.md",
    "docs/project/DECISIONS.md",
    "docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md",
    "docs/reference/api-overview.md",
    "docs/reference/api.md",
}

THIN_README_LIMITS = {
    "apps/backend/README.md": 35,
    "apps/frontend/README.md": 35,
    "apps/backend/tests/README.md": 35,
}

THIN_README_FORBIDDEN_HEADINGS = (
    "## API Endpoints",
    "## Key Pages",
    "## Architecture",
    "## SSOT",
    "## Fixtures",
    "## Directory Structure",
)

MARKDOWN_CODE_SPAN_PATTERN = re.compile(r"`([^`]+)`")


class Violation(NamedTuple):
    check: str
    message: str


def load_registry_acs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return load_registry_entries(path)


def is_deprecated(ac: dict) -> bool:
    status = str(ac.get("status", "")).lower()
    if status == "deprecated":
        return True
    description = str(ac.get("description", "")).strip()
    if (
        description.startswith("~~")
        and description.endswith("~~")
        and description[2:-2].strip()
    ):
        return True
    return bool(ac.get("deprecated"))


def is_stub(ac: dict) -> bool:
    return str(ac.get("status", "")).lower() == "stub"


def list_epic_files() -> list[Path]:
    return sorted(
        path
        for path in EPIC_DIR.glob("EPIC-*.md")
        if EPIC_FILE_PATTERN.match(path.name)
    )


def parse_vision_anchors(vision_text: str) -> set[str]:
    return {m.group("slug") for m in HTML_ANCHOR_PATTERN.finditer(vision_text)}


def parse_epic_anchor(epic_text: str) -> str | None:
    match = VISION_ANCHOR_PATTERN.search(epic_text)
    return match.group("slug") if match else None


def collect_ac_refs_in_epics(epic_files: list[Path]) -> dict[str, set[str]]:
    """Return AC ID -> set of EPIC file basenames that reference it."""
    refs: dict[str, set[str]] = {}
    for path in epic_files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Skip annotation lines that document removed/duplicate/canonical AC IDs
        # or summary "Total AC IDs:" lines, which should not count as references.
        for line in text.splitlines():
            if _line_is_ac_annotation(line):
                continue
            for match in AC_PATTERN.finditer(line):
                refs.setdefault(match.group(0), set()).add(path.name)
    return refs


def collect_ac_refs_in_tests(test_roots: list[Path]) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for base in test_roots:
        if not base.exists():
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            for fname in files:
                if not (
                    fname.startswith("test_") or fname.endswith(TEST_FILE_SUFFIXES)
                ):
                    continue
                fpath = Path(root) / fname
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                for match in AC_PATTERN.finditer(text):
                    refs.setdefault(match.group(0), set()).add(
                        str(fpath.relative_to(REPO_ROOT))
                    )
    return refs


def _is_excluded_path(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def discover_no_ac_test_files(
    scan_targets: tuple[tuple[Path, tuple[str, ...]], ...] | None = None,
) -> list[Path]:
    """Return test/support files under test roots that contain no AC reference."""
    if scan_targets is None:
        scan_targets = (
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

    candidates: set[Path] = set()
    for base, patterns in scan_targets:
        if not base.exists():
            continue
        for pattern in patterns:
            candidates.update(path for path in base.glob(pattern) if path.is_file())

    no_ac_files: list[Path] = []
    for path in sorted(candidates):
        if _is_excluded_path(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if not AC_PATTERN.search(text):
            no_ac_files.append(path)
    return no_ac_files


def load_traceability_exception_paths(exception_path: Path) -> set[str]:
    """Extract path-like Markdown code spans from traceability exceptions."""
    if not exception_path.exists():
        return set()
    text = exception_path.read_text(encoding="utf-8")
    return {
        value
        for value in MARKDOWN_CODE_SPAN_PATTERN.findall(text)
        if "/" in value and not value.startswith("docs/*")
    }


def check_no_ac_test_exceptions(
    no_ac_files: list[Path] | None = None,
    exception_path: Path | None = None,
) -> list[Violation]:
    """Check #8: no-AC test files must be explicitly classified."""
    if exception_path is None:
        exception_path = REPO_ROOT / "docs" / "analysis" / "traceability-exceptions.md"
    if no_ac_files is None:
        no_ac_files = discover_no_ac_test_files()

    exception_paths = load_traceability_exception_paths(exception_path)
    violations: list[Violation] = []
    for path in no_ac_files:
        rel = _display_path(path)
        if rel not in exception_paths:
            violations.append(
                Violation(
                    check="check8_no_ac_test_exceptions",
                    message=(
                        f"{rel}: test/support file has no AC reference and is "
                        "not classified in docs/analysis/traceability-exceptions.md"
                    ),
                )
            )
    return violations


def check_no_e2e_product_test_exceptions(
    exception_path: Path | None = None,
) -> list[Violation]:
    """Check #9: product E2E tests must be owned by AC IDs, not exceptions."""
    if exception_path is None:
        exception_path = REPO_ROOT / "docs" / "analysis" / "traceability-exceptions.md"

    violations: list[Violation] = []
    for rel in sorted(load_traceability_exception_paths(exception_path)):
        if "*" in rel:
            continue
        if rel.endswith(".py") and rel.startswith(E2E_PRODUCT_TEST_EXCEPTION_PREFIXES):
            violations.append(
                Violation(
                    check="check9_no_e2e_product_test_exceptions",
                    message=(
                        f"{rel}: product E2E tests cannot be classified as "
                        "traceability exceptions; attach EPIC/AC IDs or remove "
                        "the obsolete test"
                    ),
                )
            )
    return violations


def check_epic_anchors(
    epic_files: list[Path],
    vision_anchors: set[str],
) -> tuple[list[Violation], dict[str, str]]:
    """Check #1: every EPIC declares a Vision Anchor that exists in vision.md.

    Returns ``(violations, epic_to_slug)`` where ``epic_to_slug`` is
    populated only for EPICs whose anchor parsed successfully (used by
    check #2).
    """
    violations: list[Violation] = []
    epic_to_slug: dict[str, str] = {}
    for path in epic_files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            violations.append(
                Violation(
                    check="check1_epic_anchor",
                    message=f"{path.name}: cannot read file ({exc})",
                )
            )
            continue
        slug = parse_epic_anchor(text)
        if slug is None:
            violations.append(
                Violation(
                    check="check1_epic_anchor",
                    message=(
                        f"{path.name}: missing 'Vision Anchor: `<slug>`' "
                        "metadata line in header"
                    ),
                )
            )
            continue
        epic_to_slug[path.name] = slug
        if slug not in vision_anchors:
            violations.append(
                Violation(
                    check="check1_epic_anchor",
                    message=(
                        f"{path.name}: Vision Anchor slug `{slug}` does not "
                        f'resolve to any <a id="{slug}"></a> in vision.md'
                    ),
                )
            )
    return violations, epic_to_slug


def check_orphan_vision_anchors(
    vision_anchors: set[str],
    epic_to_slug: dict[str, str],
) -> list[Violation]:
    """Check #2: every <a id> in vision.md is referenced by some EPIC."""
    referenced = set(epic_to_slug.values())
    orphans = sorted(vision_anchors - referenced)
    return [
        Violation(
            check="check2_orphan_vision_anchor",
            message=(
                f"vision.md anchor `{slug}` is not referenced by any "
                "EPIC's Vision Anchor metadata line"
            ),
        )
        for slug in orphans
    ]


def check_registry_to_epic(
    registry_acs: list[dict],
    epic_refs: dict[str, set[str]],
) -> list[Violation]:
    """Check #3: every non-deprecated AC ID is referenced by some EPIC."""
    violations: list[Violation] = []
    for ac in registry_acs:
        if is_deprecated(ac):
            continue
        ac_id = ac.get("id")
        if not ac_id:
            continue
        if ac_id not in epic_refs:
            violations.append(
                Violation(
                    check="check3_registry_to_epic",
                    message=(
                        f"{ac_id}: present in registry but not referenced "
                        "by any docs/project/EPIC-*.md"
                    ),
                )
            )
    return violations


BACKEND_COVERAGE_COPY_RE = re.compile(
    r"backend[^.\n]*(?:coverage|source-coverage|pytest)[^.\n]*\b\d{2,3}%",
    re.IGNORECASE,
)


def check_code_owned_coverage_threshold_doc(
    doc_path: Path | None = None,
) -> list[Violation]:
    """Check #10: backend coverage threshold docs point to the code owner."""
    if doc_path is None:
        doc_path = TDD_SSOT
    try:
        text = doc_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            Violation(
                check="check10_code_owned_coverage_threshold_doc",
                message=f"{_display_path(doc_path)}: cannot read file ({exc})",
            )
        ]

    if BACKEND_COVERAGE_COPY_RE.search(text):
        return [
            Violation(
                check="check10_code_owned_coverage_threshold_doc",
                message=(
                    f"{_display_path(doc_path)}: backend coverage threshold "
                    "must be code-owned by apps/backend/pyproject.toml "
                    "`--cov-fail-under`, not copied as a mutable percentage"
                ),
            )
        ]
    return []


def check_epic_to_registry(
    epic_refs: dict[str, set[str]],
    registry_ids: set[str],
) -> list[Violation]:
    """Check #4: every AC ID referenced in EPIC docs exists in a registry."""
    violations: list[Violation] = []
    for ac_id, sources in sorted(epic_refs.items()):
        if ac_id not in registry_ids:
            sources_str = ", ".join(sorted(sources))
            violations.append(
                Violation(
                    check="check4_epic_to_registry",
                    message=(
                        f"{ac_id}: referenced in EPIC files ({sources_str}) "
                        "but not present in docs/ac_registry.yaml or "
                        "docs/infra_registry.yaml"
                    ),
                )
            )
    return violations


def check_registry_to_tests(
    registry_acs: list[dict],
    test_refs: dict[str, set[str]],
) -> list[Violation]:
    """Check #5: every non-deprecated AC ID has at least one test reference."""
    violations: list[Violation] = []
    for ac in registry_acs:
        if is_deprecated(ac):
            continue
        if not ac.get("mandatory", True):
            continue
        ac_id = ac.get("id")
        if not ac_id:
            continue
        if ac_id not in test_refs:
            violations.append(
                Violation(
                    check="check5_registry_to_tests",
                    message=(
                        f"{ac_id}: present in registry but not referenced "
                        "by any test under apps/backend/tests/, "
                        "apps/frontend/src/__tests__/, apps/frontend/playwright/, "
                        "or tests/tooling/"
                    ),
                )
            )
    return violations


def check_test_id_epic_alignment(
    registry_acs: list[dict],
    test_refs: dict[str, set[str]],
) -> list[Violation]:
    """Check #6: every AC ID referenced by a test must live in the
    registry under the EPIC implied by its ``ACx.y.z`` prefix.

    For ``ACx.y.z``, the registry entry's ``epic`` field MUST equal
    ``x``. IDs in :data:`CHECK6_FIXTURE_EXCLUDE` are skipped because
    they intentionally appear only in synthetic fixtures.
    """
    violations: list[Violation] = []
    registry_by_id: dict[str, dict] = {
        ac["id"]: ac for ac in registry_acs if ac.get("id")
    }
    for ac_id in sorted(test_refs):
        if ac_id in CHECK6_FIXTURE_EXCLUDE:
            continue
        match = AC_PATTERN.match(ac_id)
        if not match:
            continue
        expected_epic = int(match.group(1))
        entry = registry_by_id.get(ac_id)
        if entry is None:
            # Missing registry entries are surfaced by check #4
            # (epic-to-registry); avoid double-reporting here.
            continue
        actual_epic = entry.get("epic")
        try:
            actual_epic_int = int(actual_epic)
        except (TypeError, ValueError):
            violations.append(
                Violation(
                    check="check6_test_id_epic_alignment",
                    message=(
                        f"{ac_id}: registry entry has non-integer "
                        f"epic field {actual_epic!r}"
                    ),
                )
            )
            continue
        if actual_epic_int != expected_epic:
            files_str = ", ".join(sorted(test_refs[ac_id])) or "<unknown>"
            violations.append(
                Violation(
                    check="check6_test_id_epic_alignment",
                    message=(
                        f"{ac_id}: ID prefix implies EPIC-"
                        f"{expected_epic:03d} but registry assigns it "
                        f"to EPIC-{actual_epic_int:03d} "
                        f"(referenced by: {files_str})"
                    ),
                )
            )
    return violations


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def collect_mkdocs_nav_docs(mkdocs_path: Path = MKDOCS_CONFIG) -> set[str]:
    """Return repository-relative Markdown paths referenced by MkDocs nav."""
    text = mkdocs_path.read_text(encoding="utf-8")
    refs = re.findall(r"(?<![A-Za-z0-9_./-])([A-Za-z0-9_./-]+\.md)", text)
    docs: set[str] = set()
    for ref in refs:
        if ref.startswith("docs/"):
            docs.add(ref)
        else:
            docs.add(f"docs/{ref}")
    return docs


def _required_mkdocs_nav_docs() -> set[str]:
    docs = {
        _display_path(path)
        for path in (REPO_ROOT / "docs").rglob("*.md")
        if path.is_file()
    }
    docs.update(MKDOCS_REQUIRED_STATIC_DOCS)
    return docs


def check_mkdocs_nav_coverage(
    mkdocs_path: Path = MKDOCS_CONFIG,
) -> list[Violation]:
    """Check #11: checked-in docs are reachable from MkDocs."""
    if not mkdocs_path.exists():
        return [
            Violation(
                check="check11_mkdocs_nav_coverage",
                message=f"{_display_path(mkdocs_path)}: missing MkDocs config",
            )
        ]

    nav_docs = collect_mkdocs_nav_docs(mkdocs_path)
    required = _required_mkdocs_nav_docs()
    violations: list[Violation] = []
    for doc in sorted(required - nav_docs):
        violations.append(
            Violation(
                check="check11_mkdocs_nav_coverage",
                message=f"{doc}: required public doc is missing from mkdocs.yml nav",
            )
        )
    return violations


def check_module_readmes_are_thin() -> list[Violation]:
    """Check #12: module READMEs point to SSOT instead of duplicating facts."""
    violations: list[Violation] = []
    forbidden_headings = set(THIN_README_FORBIDDEN_HEADINGS)
    for rel_path, max_lines in THIN_README_LIMITS.items():
        path = REPO_ROOT / rel_path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            violations.append(
                Violation(
                    check="check12_module_readmes_are_thin",
                    message=f"{rel_path}: cannot read README ({exc})",
                )
            )
            continue
        line_count = len(text.splitlines())
        if line_count > max_lines:
            violations.append(
                Violation(
                    check="check12_module_readmes_are_thin",
                    message=f"{rel_path}: {line_count} lines exceeds {max_lines}",
                )
            )
        headings = {
            line.strip() for line in text.splitlines() if line.startswith("## ")
        }
        for heading in sorted(headings & forbidden_headings):
            violations.append(
                Violation(
                    check="check12_module_readmes_are_thin",
                    message=f"{rel_path}: duplicates SSOT-style section {heading!r}",
                )
            )
    return violations


def check_proof_placement_policy(ci_cd_path: Path | None = None) -> list[Violation]:
    """Check #7: CI/CD SSOT defines pre-merge vs post-merge proof placement."""
    if ci_cd_path is None:
        ci_cd_path = REPO_ROOT / "docs" / "ssot" / "ci-cd.md"
    try:
        text = ci_cd_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            Violation(
                check="check7_proof_placement_policy",
                message=f"{ci_cd_path}: cannot read file ({exc})",
            )
        ]

    violations: list[Violation] = []
    for token in PROOF_PLACEMENT_REQUIRED_TOKENS:
        if token not in text:
            violations.append(
                Violation(
                    check="check7_proof_placement_policy",
                    message=(
                        f"{_display_path(ci_cd_path)}: missing proof "
                        f"placement token {token!r}"
                    ),
                )
            )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description=("Lint vision <-> EPIC <-> AC registry <-> test consistency.")
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print summary statistics even on success.",
    )
    args = parser.parse_args()

    if not VISION_PATH.exists():
        print(f"ERROR: vision.md not found at {VISION_PATH}", file=sys.stderr)
        return 1
    if not EPIC_DIR.exists():
        print(f"ERROR: EPIC directory not found at {EPIC_DIR}", file=sys.stderr)
        return 1

    vision_text = VISION_PATH.read_text(encoding="utf-8")
    vision_anchors = parse_vision_anchors(vision_text)

    epic_files = list_epic_files()
    if not epic_files:
        print(
            f"ERROR: no EPIC-*.md files matched in {EPIC_DIR}",
            file=sys.stderr,
        )
        return 1

    feature_acs = load_registry_acs(AC_REGISTRY)
    infra_acs = load_registry_acs(INFRA_REGISTRY)
    all_acs = feature_acs + infra_acs
    registry_ids = {ac["id"] for ac in all_acs if ac.get("id")}

    epic_refs = collect_ac_refs_in_epics(epic_files)
    test_refs = collect_ac_refs_in_tests(TEST_ROOTS)

    violations: list[Violation] = []

    check1, epic_to_slug = check_epic_anchors(epic_files, vision_anchors)
    violations.extend(check1)
    violations.extend(check_orphan_vision_anchors(vision_anchors, epic_to_slug))
    violations.extend(check_registry_to_epic(all_acs, epic_refs))
    violations.extend(check_epic_to_registry(epic_refs, registry_ids))
    violations.extend(check_registry_to_tests(all_acs, test_refs))
    violations.extend(check_test_id_epic_alignment(all_acs, test_refs))
    violations.extend(check_proof_placement_policy())
    violations.extend(check_no_ac_test_exceptions())
    violations.extend(check_no_e2e_product_test_exceptions())
    violations.extend(check_code_owned_coverage_threshold_doc())
    violations.extend(check_mkdocs_nav_coverage())
    violations.extend(check_module_readmes_are_thin())

    if args.verbose or violations:
        print("=" * 72)
        print("Doc consistency lint (tools/lint_doc_consistency.py)")
        print("=" * 72)
        print(f"  EPIC files scanned         : {len(epic_files)}")
        print(f"  vision.md HTML anchors     : {len(vision_anchors)}")
        print(f"  Feature ACs in registry    : {len(feature_acs)}")
        print(f"  Infra ACs in registry      : {len(infra_acs)}")
        print(f"  Distinct AC IDs in EPICs   : {len(epic_refs)}")
        print(f"  Distinct AC IDs in tests   : {len(test_refs)}")
        print()

    if not violations:
        if args.verbose:
            print("OK: doc consistency lint passed.")
        return 0

    grouped: dict[str, list[Violation]] = {}
    for violation in violations:
        grouped.setdefault(violation.check, []).append(violation)

    print(
        f"FAIL: doc consistency lint found {len(violations)} violation(s) "
        f"across {len(grouped)} check(s).",
        file=sys.stderr,
    )
    print("", file=sys.stderr)
    for check_name in sorted(grouped):
        items = grouped[check_name]
        print(f"[{check_name}] {len(items)} violation(s):", file=sys.stderr)
        for violation in items:
            print(f"  - {violation.message}", file=sys.stderr)
        print("", file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
