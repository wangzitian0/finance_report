"""AC/anchor/registry parsing, test discovery, mkdocs nav helpers."""

from __future__ import annotations

from common.ssot.lint_doc_consistency import _base

import os
import re
import sys
from pathlib import Path

try:
    from common.ssot.ac_registry_format import load_registry_entries
except ImportError:  # pragma: no cover - environment guard
    print(
        "ERROR: PyYAML not installed. Run: pip install pyyaml",
        file=sys.stderr,
    )
    sys.exit(1)


from common.ssot.lint_doc_consistency._base import (
    AC_PATTERN,
    EXCLUDED_DIRS,
    MKDOCS_CONFIG,
    REMOVED_ANNOTATION_RE,
    TEST_FILE_SUFFIXES,
    TOTAL_AC_SUMMARY_TOKEN,
)


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
RAW_FETCH_PATTERN = re.compile(r"\bfetch\s*\(")

GENERATED_ANALYSIS_SNAPSHOTS = (
    _base.REPO_ROOT / "docs" / "project" / "ac-epic-mismatch-report.md",
    _base.REPO_ROOT / "docs" / "project" / "test-ac-coverage-report.md",
)

FRONTEND_RAW_FETCH_ALLOWED_FILES = {
    _base.REPO_ROOT / "apps" / "frontend" / "src" / "lib" / "api.ts",
}

RECONCILIATION_THRESHOLD_REQUIRED_TOKENS = (
    "apps/backend/config/reconciliation.yaml",
    "apps/backend/src/services/reconciliation.py",
    "DEFAULT_CONFIG",
    "load_reconciliation_config",
    "RECONCILIATION_AUTO_ACCEPT_THRESHOLD",
    "RECONCILIATION_REVIEW_THRESHOLD",
)

RECONCILIATION_THRESHOLD_FORBIDDEN_TOKENS = (
    "single authoritative definition of reconciliation score thresholds",
)


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
        for path in _base.EPIC_DIR.glob("EPIC-*.md")
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
                        str(fpath.relative_to(_base.REPO_ROOT))
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
            (_base.REPO_ROOT / "apps" / "backend" / "tests", ("**/*.py",)),
            (
                _base.REPO_ROOT / "apps" / "frontend" / "src",
                ("**/*.test.ts", "**/*.test.tsx"),
            ),
            (
                _base.REPO_ROOT / "apps" / "frontend" / "playwright",
                ("**/*.spec.ts", "**/*.spec.tsx"),
            ),
            (_base.REPO_ROOT / "tests" / "tooling", ("**/*.py",)),
            (_base.REPO_ROOT / "tests" / "e2e", ("**/*.py",)),
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


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(_base.REPO_ROOT))
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
        for path in (_base.REPO_ROOT / "docs").rglob("*.md")
        if path.is_file()
    }
    docs.update(MKDOCS_REQUIRED_STATIC_DOCS)
    return docs
