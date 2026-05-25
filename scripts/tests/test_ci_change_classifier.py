import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import ci_change_classifier as classifier  # noqa: E402
from ci_change_classifier import (
    classify_changed_paths,
    is_lightweight,
    is_pr_preview_relevant,
)  # noqa: E402


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
    assert result.pr_preview_required is False
    assert result.pr_preview_files == ()
    assert result.pr_preview_reason == "no-pr-preview-paths-changed"


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
    assert result.pr_preview_required is True
    assert result.pr_preview_files == (
        "apps/backend/src/services/reporting.py",
        "apps/frontend/src/app/page.tsx",
    )


def test_AC8_13_20_ci_workflow_changes_are_heavy_except_docs_workflow() -> None:
    """AC8.13.20: Runtime CI workflow changes cannot be hidden by docs-only rules."""
    assert is_lightweight(".github/workflows/docs.yml") is True
    assert is_lightweight(".github/workflows/ci.yml") is False
    assert classify_changed_paths([".github/workflows/ci.yml"]).heavy_required is True
    assert (
        classify_changed_paths([".github/workflows/ci.yml"]).pr_preview_required
        is False
    )


def test_AC8_13_20_markdown_under_runtime_trees_is_heavy() -> None:
    """AC8.13.20: Markdown outside the documented lightweight trees is not globally skipped."""
    result = classify_changed_paths(
        ["apps/backend/README.md", "scripts/pdf_fixtures/README.md"]
    )

    assert result.heavy_required is True
    assert result.heavy_files == (
        "apps/backend/README.md",
        "scripts/pdf_fixtures/README.md",
    )


def test_AC8_13_20_empty_change_set_requires_heavy_ci() -> None:
    """AC8.13.20: Empty changed-file detection fails closed into heavy CI."""
    result = classify_changed_paths(["", "   "])

    assert result.files == ()
    assert result.heavy_required is True
    assert result.reason == "no-changed-files-detected"
    assert result.pr_preview_required is True
    assert result.pr_preview_reason == "no-changed-files-detected"


def test_AC8_13_20_pr_preview_only_runs_for_app_e2e_or_compose_changes() -> None:
    """AC8.13.20: PR preview deploys are scoped to app, E2E, and compose changes."""
    assert is_pr_preview_relevant("apps/backend/src/routers/statements.py") is True
    assert is_pr_preview_relevant("apps/frontend/src/app/page.tsx") is True
    assert is_pr_preview_relevant("tests/e2e/test_core_journeys.py") is True
    assert is_pr_preview_relevant("docker-compose.yml") is True
    assert is_pr_preview_relevant("scripts/ac_traceability_refs.py") is False
    assert is_pr_preview_relevant(".github/workflows/ci.yml") is False

    result = classify_changed_paths(
        [
            "scripts/ac_traceability_refs.py",
            "docs/ssot/ci-cd.md",
            ".github/workflows/ci.yml",
        ]
    )

    assert result.heavy_required is True
    assert result.pr_preview_required is False
    assert result.pr_preview_reason == "no-pr-preview-paths-changed"


def test_AC8_13_20_github_outputs_and_summary_include_heavy_files(
    tmp_path: Path,
) -> None:
    """AC8.13.20: Classifier writes GitHub outputs and actionable summaries."""
    result = classify_changed_paths(
        ["docs/ssot/ci-cd.md", "scripts/ci_change_classifier.py"]
    )
    output = tmp_path / "github-output.txt"
    summary = tmp_path / "github-summary.md"

    classifier.write_github_outputs(result, output)
    classifier.write_github_summary(result, summary)

    assert output.read_text(encoding="utf-8").splitlines() == [
        "heavy_required=true",
        "reason=runtime-or-ci-paths-changed",
        "pr_preview_required=false",
        "pr_preview_reason=no-pr-preview-paths-changed",
    ]
    summary_text = summary.read_text(encoding="utf-8")
    assert "## Change Classification" in summary_text
    assert "- Heavy CI required: `true`" in summary_text
    assert "- PR preview required: `false`" in summary_text
    assert "- `scripts/ci_change_classifier.py`" in summary_text


def test_AC8_13_20_summary_includes_pr_preview_files(tmp_path: Path) -> None:
    """AC8.13.20: PR preview-triggering files are visible in the summary."""
    result = classify_changed_paths(
        [
            "apps/frontend/src/app/page.tsx",
            "tests/e2e/test_core_journeys.py",
        ]
    )
    summary = tmp_path / "github-summary.md"

    classifier.write_github_summary(result, summary)

    summary_text = summary.read_text(encoding="utf-8")
    assert "PR preview-triggering files:" in summary_text
    assert "- `apps/frontend/src/app/page.tsx`" in summary_text
    assert "- `tests/e2e/test_core_journeys.py`" in summary_text


def test_AC8_13_20_cli_writes_outputs_summary_and_stdout(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    """AC8.13.20: CLI entrypoint matches the workflow contract."""
    changed_files = tmp_path / "changed-files.txt"
    github_output = tmp_path / "github-output.txt"
    github_summary = tmp_path / "github-summary.md"
    changed_files.write_text(
        "docs/ssot/ci-cd.md\n.github/workflows/docs.yml\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ci_change_classifier.py",
            "--changed-files",
            str(changed_files),
            "--github-output",
            str(github_output),
            "--github-summary",
            str(github_summary),
        ],
    )

    assert classifier.main() == 0

    stdout = capsys.readouterr().out
    assert "heavy_required=false" in stdout
    assert "reason=lightweight-docs-or-docs-workflow-only" in stdout
    assert "pr_preview_required=false" in stdout
    assert "pr_preview_reason=no-pr-preview-paths-changed" in stdout
    assert "changed_files=2" in stdout
    assert "heavy_required=false" in github_output.read_text(encoding="utf-8")
    assert "pr_preview_required=false" in github_output.read_text(encoding="utf-8")
    assert "Changed files: `2`" in github_summary.read_text(encoding="utf-8")
