"""Contract: stale documentation stays consolidated/archived (issue #350).

The consolidation moves/merges/renames were completed in prior PRs and are
guarded by ``tools/check_ssot_ownership.py``. This test pins two guarantees:

1. Every retired/merged/renamed stale doc stays absent.
2. Every ``.md`` target referenced by the mkdocs ``nav`` resolves to a real file
   under ``docs/`` (no dangling internal links after the moves).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

from common.ssot import check_ssot_ownership as cso

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
MKDOCS = ROOT / "mkdocs.yml"

# Stale docs that #350 consolidated; they must never reappear.
STALE_ABSENT = [
    DOCS / "project" / "AC-AUDIT-2026-02-25.md",
    DOCS / "project" / "AC-TEST-TRACEABILITY-AUDIT.md",
    DOCS / "project" / "EPIC-ENCODING-SUMMARY.md",
    DOCS / "project" / "TEST-COVERAGE-PLAN.md",
    DOCS / "project" / "archive",
    DOCS / "project" / "EPIC-016-IMPLEMENTATION-PLAN.md",
    DOCS / "ssot" / "coverage-verification.md",
    DOCS / "ssot" / "observability.logging-improvements.md",
    DOCS / "project" / "DECISIONS_ZH.md",
]


def test_AC8_13_134_stale_consolidated_docs_stay_absent() -> None:
    """AC8.13.134: archived/merged/renamed stale docs do not reappear."""
    present = [str(path.relative_to(ROOT)) for path in STALE_ABSENT if path.exists()]
    assert present == [], f"stale docs must stay absent: {present}"


def test_AC8_13_134_ownership_guard_enforces_absence() -> None:
    """AC8.13.134: the ownership guard owns the absence guarantee."""
    violations = cso.check_retired_archive_roots() + cso.check_must_be_absent()
    assert violations == [], "\n".join(v.message for v in violations)


def _iter_nav_md_targets(node: object) -> list[str]:
    targets: list[str] = []
    if isinstance(node, str):
        if node.endswith(".md"):
            targets.append(node)
    elif isinstance(node, list):
        for item in node:
            targets.extend(_iter_nav_md_targets(item))
    elif isinstance(node, dict):
        for value in node.values():
            targets.extend(_iter_nav_md_targets(value))
    return targets


def test_AC8_13_134_mkdocs_nav_links_resolve() -> None:
    """AC8.13.134: every mkdocs nav .md target resolves under docs/."""
    # mkdocs uses non-standard YAML tags (e.g. !!python). Strip the emoji /
    # plain nav by loading with a permissive loader limited to the nav block.
    raw = MKDOCS.read_text(encoding="utf-8")
    # Drop any custom python tags that SafeLoader would choke on.
    raw = re.sub(r"!![\w/.]+", "", raw)
    config = yaml.safe_load(raw)
    nav = config.get("nav", [])
    targets = _iter_nav_md_targets(nav)
    assert targets, "mkdocs nav must declare markdown pages"
    missing = [
        target
        for target in targets
        if not (DOCS / target).is_file() and not _is_build_generated(DOCS / target)
    ]
    assert missing == [], f"mkdocs nav references missing files: {missing}"


def _is_build_generated(path: Path) -> bool:
    """Return True if *path* is a git-ignored build-time generated page.

    mkdocs nav legitimately references pages produced at build time (e.g.
    ``reference/db-schema.md``) that are absent from a clean checkout.
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path)],
        cwd=ROOT,
        capture_output=True,
    )
    return result.returncode == 0
