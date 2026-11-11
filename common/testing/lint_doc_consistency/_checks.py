"""Doc-consistency check functions."""

from __future__ import annotations

import re
from pathlib import Path

from common.meta.base.gate_util import display_path
from common.testing.check_ac_traceability import is_deprecated
from common.testing.lint_doc_consistency import _base, _parsing
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
    _is_excluded_path,
    _required_mkdocs_nav_docs,
    collect_mkdocs_nav_docs,
    discover_no_ac_test_files,
    load_traceability_exception_paths,
    parse_epic_anchor,
)
from common.testing.lint_doc_consistency._types import Violation

BACKEND_COVERAGE_COPY_RE = re.compile(
    r"backend[^.\n]*(?:coverage|source-coverage|pytest)[^.\n]*\b\d{2,3}%",
    re.IGNORECASE,
)


def _v(check: str, message: str) -> Violation:
    return Violation(check=check, message=message)


def _default_exception_path(exception_path: Path | None) -> Path:
    return exception_path or (
        _base.REPO_ROOT / "docs" / "project" / "traceability-exceptions.md"
    )


def _read_utf8(
    path: Path, check: str, label: str, *, noun: str = "file"
) -> tuple[str | None, Violation | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except OSError as exc:
        return None, _v(check, f"{label}: cannot read {noun} ({exc})")


def check_no_ac_test_exceptions(
    no_ac_files: list[Path] | None = None,
    exception_path: Path | None = None,
) -> list[Violation]:
    exception_paths = load_traceability_exception_paths(
        _default_exception_path(exception_path)
    )
    files = discover_no_ac_test_files() if no_ac_files is None else no_ac_files
    return [
        _v(
            "check8_no_ac_test_exceptions",
            f"{rel}: test/support file has no AC reference and is "
            "not classified in docs/project/traceability-exceptions.md",
        )
        for path in files
        if (rel := display_path(path, _base.REPO_ROOT)) not in exception_paths
    ]


def check_no_e2e_product_test_exceptions(
    exception_path: Path | None = None,
) -> list[Violation]:
    paths = sorted(
        load_traceability_exception_paths(_default_exception_path(exception_path))
    )
    return [
        _v(
            "check9_no_e2e_product_test_exceptions",
            f"{rel}: product E2E tests cannot be classified as "
            "traceability exceptions; attach EPIC/AC IDs or remove "
            "the obsolete test",
        )
        for rel in paths
        if "*" not in rel
        and rel.endswith(".py")
        and rel.startswith(E2E_PRODUCT_TEST_EXCEPTION_PREFIXES)
    ]


def check_epic_anchors(
    epic_files: list[Path],
    vision_anchors: set[str],
) -> tuple[list[Violation], dict[str, str]]:
    violations: list[Violation] = []
    epic_to_slug: dict[str, str] = {}
    for path in epic_files:
        text, err = _read_utf8(path, "check1_epic_anchor", path.name)
        if err is not None or text is None:
            if err is not None:
                violations.append(err)
            continue
        slug = parse_epic_anchor(text)
        if slug is None:
            violations.append(
                _v(
                    "check1_epic_anchor",
                    f"{path.name}: missing 'Vision Anchor: `<slug>`' metadata line in header",
                )
            )
            continue
        epic_to_slug[path.name] = slug
        if slug not in vision_anchors:
            violations.append(
                _v(
                    "check1_epic_anchor",
                    f"{path.name}: Vision Anchor slug `{slug}` does not "
                    f'resolve to any <a id="{slug}"></a> in vision.md',
                )
            )
    return violations, epic_to_slug


def check_orphan_vision_anchors(
    vision_anchors: set[str],
    epic_to_slug: dict[str, str],
) -> list[Violation]:
    return [
        _v(
            "check2_orphan_vision_anchor",
            f"vision.md anchor `{slug}` is not referenced by any "
            "EPIC's Vision Anchor metadata line",
        )
        for slug in sorted(vision_anchors - set(epic_to_slug.values()))
    ]


def check_registry_to_epic(
    registry_acs: list[dict],
    epic_refs: dict[str, set[str]],
) -> list[Violation]:
    return [
        _v(
            "check3_registry_to_epic",
            f"{ac_id}: present in registry but not referenced by any docs/project/EPIC-*.md",
        )
        for ac in registry_acs
        if not is_deprecated(str(ac.get("description", "")))
        and not str(ac.get("epic_name", "")).startswith("pkg-")
        and (ac_id := ac.get("id"))
        and ac_id not in epic_refs
    ]


def check_code_owned_coverage_threshold_doc(
    doc_path: Path | None = None,
) -> list[Violation]:
    target = TDD_SSOT if doc_path is None else doc_path
    rel = display_path(target, _base.REPO_ROOT)
    text, err = _read_utf8(target, "check10_code_owned_coverage_threshold_doc", rel)
    if err is not None or text is None:
        return [err] if err else []
    if BACKEND_COVERAGE_COPY_RE.search(text):
        return [
            _v(
                "check10_code_owned_coverage_threshold_doc",
                f"{rel}: backend coverage threshold must be code-owned by "
                "apps/backend/pyproject.toml `--cov-fail-under`, not copied as a mutable percentage",
            )
        ]
    return []


def check_epic_to_registry(
    epic_refs: dict[str, set[str]],
    registry_ids: set[str],
) -> list[Violation]:
    return [
        _v(
            "check4_epic_to_registry",
            f"{ac_id}: referenced in EPIC files ({', '.join(sorted(sources))}) "
            "but not present in docs/ac_registry.yaml or docs/infra_registry.yaml",
        )
        for ac_id, sources in sorted(epic_refs.items())
        if ac_id not in registry_ids
    ]


def check_registry_to_tests(
    registry_acs: list[dict],
    test_refs: dict[str, set[str]],
) -> list[Violation]:
    return [
        _v(
            "check5_registry_to_tests",
            f"{ac_id}: present in registry but not referenced by any test under "
            "apps/backend/tests/, apps/frontend/src/__tests__/, "
            "apps/frontend/playwright/, or tests/tooling/",
        )
        for ac in registry_acs
        if not is_deprecated(str(ac.get("description", "")))
        and ac.get("mandatory", True)
        and (ac_id := ac.get("id"))
        and ac_id not in test_refs
    ]


def check_test_id_epic_alignment(
    registry_acs: list[dict],
    test_refs: dict[str, set[str]],
) -> list[Violation]:
    violations: list[Violation] = []
    registry_by_id = {ac["id"]: ac for ac in registry_acs if ac.get("id")}
    for ac_id in sorted(test_refs):
        if ac_id in CHECK6_FIXTURE_EXCLUDE:
            continue
        match = AC_PATTERN.match(ac_id)
        if not match or match.group("epic") is None:
            continue
        entry = registry_by_id.get(ac_id)
        if entry is None:
            continue
        expected_epic = int(match.group("epic"))
        actual_epic = entry.get("epic")
        try:
            actual_epic_int = int(actual_epic)
        except (TypeError, ValueError):
            violations.append(
                _v(
                    "check6_test_id_epic_alignment",
                    f"{ac_id}: registry entry has non-integer epic field {actual_epic!r}",
                )
            )
            continue
        if actual_epic_int != expected_epic:
            files_str = ", ".join(sorted(test_refs[ac_id])) or "<unknown>"
            violations.append(
                _v(
                    "check6_test_id_epic_alignment",
                    f"{ac_id}: ID prefix implies EPIC-{expected_epic:03d} but registry "
                    f"assigns it to EPIC-{actual_epic_int:03d} (referenced by: {files_str})",
                )
            )
    return violations


def check_mkdocs_nav_coverage(
    mkdocs_path: Path = MKDOCS_CONFIG,
) -> list[Violation]:
    if not mkdocs_path.exists():
        return [
            _v(
                "check11_mkdocs_nav_coverage",
                f"{display_path(mkdocs_path, _base.REPO_ROOT)}: missing MkDocs config",
            )
        ]
    missing = sorted(_required_mkdocs_nav_docs() - collect_mkdocs_nav_docs(mkdocs_path))
    return [
        _v(
            "check11_mkdocs_nav_coverage",
            f"{doc}: required public doc is missing from mkdocs.yml nav",
        )
        for doc in missing
    ]


def check_module_readmes_are_thin() -> list[Violation]:
    violations: list[Violation] = []
    forbidden_headings = set(THIN_README_FORBIDDEN_HEADINGS)
    for rel_path, max_lines in _parsing.THIN_README_LIMITS.items():
        text, err = _read_utf8(
            _base.REPO_ROOT / rel_path,
            "check12_module_readmes_are_thin",
            rel_path,
            noun="README",
        )
        if err is not None or text is None:
            if err is not None:
                violations.append(err)
            continue
        lines = text.splitlines()
        if len(lines) > max_lines:
            violations.append(
                _v(
                    "check12_module_readmes_are_thin",
                    f"{rel_path}: {len(lines)} lines exceeds {max_lines}",
                )
            )
        headings = {line.strip() for line in lines if line.startswith("## ")}
        for heading in sorted(headings & forbidden_headings):
            violations.append(
                _v(
                    "check12_module_readmes_are_thin",
                    f"{rel_path}: duplicates SSOT-style section {heading!r}",
                )
            )
    return violations


def check_generated_analysis_snapshots_absent(
    paths: tuple[Path, ...] = GENERATED_ANALYSIS_SNAPSHOTS,
) -> list[Violation]:
    return [
        _v(
            "check13_generated_analysis_snapshots_absent",
            f"{display_path(path, _base.REPO_ROOT)}: generated analysis snapshots "
            "must not be checked in; use the live tool output or CI artifact instead",
        )
        for path in paths
        if path.exists()
    ]


def check_reconciliation_thresholds_are_code_owned(
    doc_path: Path = RECONCILIATION_SSOT,
) -> list[Violation]:
    rel = display_path(doc_path, _base.REPO_ROOT)
    text, err = _read_utf8(
        doc_path, "check14_reconciliation_thresholds_code_owned", rel
    )
    if err is not None or text is None:
        return [err] if err else []

    violations: list[Violation] = []
    lower_text = text.lower()
    for token in RECONCILIATION_THRESHOLD_FORBIDDEN_TOKENS:
        if token.lower() in lower_text:
            violations.append(
                _v(
                    "check14_reconciliation_thresholds_code_owned",
                    f"{rel}: reconciliation thresholds must not claim Markdown prose "
                    "is the single authority; point to code/config owners instead",
                )
            )
    for token in RECONCILIATION_THRESHOLD_REQUIRED_TOKENS:
        if token not in text:
            violations.append(
                _v(
                    "check14_reconciliation_thresholds_code_owned",
                    f"{rel}: missing code/config owner token {token!r} for reconciliation thresholds",
                )
            )
    return violations


def check_frontend_raw_fetch_usage(
    source_root: Path = FRONTEND_SRC,
    allowed_files: set[Path] = FRONTEND_RAW_FETCH_ALLOWED_FILES,
) -> list[Violation]:
    if not source_root.exists():
        return []
    violations: list[Violation] = []
    suffixes = {".ts", ".tsx", ".js", ".jsx"}
    for path in sorted(source_root.rglob("*")):
        if (
            not path.is_file()
            or path.suffix not in suffixes
            or _is_excluded_path(path)
            or "__tests__" in path.parts
            or path in allowed_files
        ):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = display_path(path, _base.REPO_ROOT)
        for line_no, line in enumerate(text.splitlines(), start=1):
            if RAW_FETCH_PATTERN.search(line):
                violations.append(
                    _v(
                        "check15_frontend_raw_fetch_usage",
                        f"{rel}:{line_no}: raw fetch() is only allowed in "
                        "apps/frontend/src/lib/api.ts; use the API wrapper instead",
                    )
                )
    return violations


def check_proof_placement_policy(ci_cd_path: Path | None = None) -> list[Violation]:
    target = ci_cd_path or (_base.REPO_ROOT / "common" / "testing" / "ci-cd.md")
    text, err = _read_utf8(target, "check7_proof_placement_policy", str(target))
    if err is not None or text is None:
        return [err] if err else []
    rel = display_path(target, _base.REPO_ROOT)
    return [
        _v(
            "check7_proof_placement_policy",
            f"{rel}: missing proof placement token {token!r}",
        )
        for token in PROOF_PLACEMENT_REQUIRED_TOKENS
        if token not in text
    ]
