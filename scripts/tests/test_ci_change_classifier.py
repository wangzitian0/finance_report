import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ci_change_classifier import classify_changed_paths, is_lightweight  # noqa: E402


def test_AC8_13_20_docs_and_docs_workflow_are_lightweight() -> None:
    """AC8.13.20: Documentation-only changes skip heavy CI."""
    result = classify_changed_paths(
        [
            "README.md",
            "docs/ssot/ci-cd.md",
            ".github/workflows/docs.yml",
            ".github/ISSUE_TEMPLATE/bug.md",
        ]
    )

    assert result.heavy_required is False
    assert result.heavy_files == ()
    assert result.reason == "lightweight-docs-or-docs-workflow-only"


def test_AC8_13_20_multi_commit_runtime_path_requires_heavy_ci() -> None:
    """AC8.13.20: Multi-commit push ranges stay heavy when any runtime path changes."""
    result = classify_changed_paths(
        [
            "docs/ssot/ci-cd.md",
            "apps/backend/src/services/reporting.py",
            "apps/frontend/src/app/page.tsx",
        ]
    )

    assert result.heavy_required is True
    assert result.reason == "runtime-or-ci-paths-changed"
    assert result.heavy_files == (
        "apps/backend/src/services/reporting.py",
        "apps/frontend/src/app/page.tsx",
    )


def test_AC8_13_20_ci_workflow_changes_are_heavy_except_docs_workflow() -> None:
    """AC8.13.20: Runtime CI workflow changes cannot be hidden by docs-only rules."""
    assert is_lightweight(".github/workflows/docs.yml") is True
    assert is_lightweight(".github/workflows/ci.yml") is False
    assert classify_changed_paths([".github/workflows/ci.yml"]).heavy_required is True


def test_AC8_13_20_markdown_under_runtime_trees_is_heavy() -> None:
    """AC8.13.20: Markdown outside the documented lightweight trees is not globally skipped."""
    result = classify_changed_paths(["apps/backend/README.md", "scripts/pdf_fixtures/README.md"])

    assert result.heavy_required is True
    assert result.heavy_files == ("apps/backend/README.md", "scripts/pdf_fixtures/README.md")
