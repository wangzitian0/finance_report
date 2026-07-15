"""Doc-consistency check functions."""

from __future__ import annotations

from common.testing.lint_doc_consistency import _parsing

from common.testing.lint_doc_consistency import _base

import re
from pathlib import Path


from common.testing.lint_doc_consistency._base import (
    AC_PATTERN,
    CHECK6_FIXTURE_EXCLUDE,
    E2E_PRODUCT_TEST_EXCEPTION_PREFIXES,
    FRONTEND_SRC,
    MKDOCS_CONFIG,
    RECONCILIATION_SSOT,
    TDD_SSOT,
)
from common.testing.lint_doc_consistency._parsing import (
    FRONTEND_RAW_FETCH_ALLOWED_FILES,
    GENERATED_ANALYSIS_SNAPSHOTS,
    PROOF_PLACEMENT_REQUIRED_TOKENS,
    RAW_FETCH_PATTERN,
    RECONCILIATION_THRESHOLD_FORBIDDEN_TOKENS,
    RECONCILIATION_THRESHOLD_REQUIRED_TOKENS,
    THIN_README_FORBIDDEN_HEADINGS,
    _display_path,
    _is_excluded_path,
    _required_mkdocs_nav_docs,
    collect_mkdocs_nav_docs,
    discover_no_ac_test_files,
    is_deprecated,
    load_traceability_exception_paths,
    parse_epic_anchor,
)
from common.testing.lint_doc_consistency._types import Violation


def check_no_ac_test_exceptions(
    no_ac_files: list[Path] | None = None,
    exception_path: Path | None = None,
) -> list[Violation]:
    """Check #8: no-AC test files must be explicitly classified."""
    if exception_path is None:
        exception_path = (
            _base.REPO_ROOT / "docs" / "project" / "traceability-exceptions.md"
        )
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
                        "not classified in docs/project/traceability-exceptions.md"
                    ),
                )
            )
    return violations


def check_no_e2e_product_test_exceptions(
    exception_path: Path | None = None,
) -> list[Violation]:
    """Check #9: product E2E tests must be owned by AC IDs, not exceptions."""
    if exception_path is None:
        exception_path = (
            _base.REPO_ROOT / "docs" / "project" / "traceability-exceptions.md"
        )

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
    """Check #3: every non-deprecated AC ID is referenced by some EPIC.

    Package-roadmap ACs (``epic_name: pkg-<name>``, sourced from
    ``common/<pkg>/contract.py``) are exempt: the contract roadmap IS their
    home — each resolves to an anchoring test there, and ``check_epic_package_dual``
    forbids a second EPIC-table home — so requiring an EPIC back-reference would
    only force EPIC stubs to mirror the id list (pure duplication).
    """
    violations: list[Violation] = []
    for ac in registry_acs:
        if is_deprecated(ac):
            continue
        if str(ac.get("epic_name", "")).startswith("pkg-"):
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
        if not match or match.group("epic") is None:
            # Package-scoped ids (AC-{package}.…) carry no EPIC number to
            # cross-check against the registry's epic field; skip them here.
            continue
        expected_epic = int(match.group("epic"))
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
    for rel_path, max_lines in _parsing.THIN_README_LIMITS.items():
        path = _base.REPO_ROOT / rel_path
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


def check_generated_analysis_snapshots_absent(
    paths: tuple[Path, ...] = GENERATED_ANALYSIS_SNAPSHOTS,
) -> list[Violation]:
    """Check #13: generated reports are produced live, not checked in."""
    violations: list[Violation] = []
    for path in paths:
        if path.exists():
            violations.append(
                Violation(
                    check="check13_generated_analysis_snapshots_absent",
                    message=(
                        f"{_display_path(path)}: generated analysis snapshots "
                        "must not be checked in; use the live tool output or CI "
                        "artifact instead"
                    ),
                )
            )
    return violations


def check_reconciliation_thresholds_are_code_owned(
    doc_path: Path = RECONCILIATION_SSOT,
) -> list[Violation]:
    """Check #14: reconciliation thresholds stay code/config-owned."""
    try:
        text = doc_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            Violation(
                check="check14_reconciliation_thresholds_code_owned",
                message=f"{_display_path(doc_path)}: cannot read file ({exc})",
            )
        ]

    violations: list[Violation] = []
    lower_text = text.lower()
    for token in RECONCILIATION_THRESHOLD_FORBIDDEN_TOKENS:
        if token.lower() in lower_text:
            violations.append(
                Violation(
                    check="check14_reconciliation_thresholds_code_owned",
                    message=(
                        f"{_display_path(doc_path)}: reconciliation thresholds "
                        "must not claim Markdown prose is the single authority; "
                        "point to code/config owners instead"
                    ),
                )
            )

    for token in RECONCILIATION_THRESHOLD_REQUIRED_TOKENS:
        if token not in text:
            violations.append(
                Violation(
                    check="check14_reconciliation_thresholds_code_owned",
                    message=(
                        f"{_display_path(doc_path)}: missing code/config owner "
                        f"token {token!r} for reconciliation thresholds"
                    ),
                )
            )
    return violations


def check_frontend_raw_fetch_usage(
    source_root: Path = FRONTEND_SRC,
    allowed_files: set[Path] = FRONTEND_RAW_FETCH_ALLOWED_FILES,
) -> list[Violation]:
    """Check #15: frontend API calls go through lib/api.ts."""
    if not source_root.exists():
        return []

    violations: list[Violation] = []
    suffixes = {".ts", ".tsx", ".js", ".jsx"}
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if _is_excluded_path(path) or "__tests__" in path.parts:
            continue
        if path in allowed_files:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if RAW_FETCH_PATTERN.search(line):
                violations.append(
                    Violation(
                        check="check15_frontend_raw_fetch_usage",
                        message=(
                            f"{_display_path(path)}:{line_no}: raw fetch() is "
                            "only allowed in apps/frontend/src/lib/api.ts; "
                            "use the API wrapper instead"
                        ),
                    )
                )
    return violations


def check_proof_placement_policy(ci_cd_path: Path | None = None) -> list[Violation]:
    """Check #7: CI/CD SSOT defines pre-merge vs post-merge proof placement."""
    if ci_cd_path is None:
        ci_cd_path = _base.REPO_ROOT / "common" / "testing" / "ci-cd.md"
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
