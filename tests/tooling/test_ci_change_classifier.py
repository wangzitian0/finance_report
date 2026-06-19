import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.ci import change_classifier as classifier  # noqa: E402
from common.ci.change_classifier import (
    ENV_STAGE_MATRIX,
    Environment,
    PipelineStage,
    classify_changed_paths,
    is_lightweight,
    is_pr_preview_relevant,
    is_staging_ai_ocr_relevant,
    is_staging_relevant,
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
    assert result.staging_required is False
    assert result.staging_files == ()
    assert result.staging_reason == "no-staging-paths-changed"
    assert result.staging_ai_ocr_required is False
    assert result.staging_ai_ocr_files == ()
    assert result.staging_ai_ocr_reason == "no-staging-ai-ocr-paths-changed"


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
    assert result.staging_required is True
    assert result.staging_files == (
        "apps/backend/src/services/reporting.py",
        "apps/frontend/src/app/page.tsx",
    )
    assert result.staging_ai_ocr_required is False
    assert result.staging_ai_ocr_reason == "no-staging-ai-ocr-paths-changed"


def test_AC8_13_20_ci_workflow_changes_are_heavy_except_docs_workflow() -> None:
    """AC8.13.20: Runtime CI workflow changes cannot be hidden by docs-only rules."""
    assert is_lightweight(".github/workflows/docs.yml") is True
    assert is_lightweight(".github/workflows/ci.yml") is False
    assert classify_changed_paths([".github/workflows/ci.yml"]).heavy_required is True
    assert classify_changed_paths([".github/workflows/ci.yml"]).staging_required is True
    assert (
        classify_changed_paths([".github/workflows/ci.yml"]).staging_ai_ocr_required
        is False
    )
    assert (
        classify_changed_paths([".github/workflows/ci.yml"]).pr_preview_required
        is False
    )


def test_AC8_13_20_markdown_under_runtime_trees_is_heavy() -> None:
    """AC8.13.20: Markdown outside the documented lightweight trees is not globally skipped."""
    result = classify_changed_paths(
        ["apps/backend/README.md", "tools/_lib/pdf_fixtures/README.md"]
    )

    assert result.heavy_required is True
    assert result.heavy_files == (
        "apps/backend/README.md",
        "tools/_lib/pdf_fixtures/README.md",
    )


def test_AC8_13_20_empty_change_set_requires_heavy_ci() -> None:
    """AC8.13.20: Empty changed-file detection fails closed into heavy CI."""
    result = classify_changed_paths(["", "   "])

    assert result.files == ()
    assert result.heavy_required is True
    assert result.reason == "no-changed-files-detected"
    assert result.pr_preview_required is True
    assert result.pr_preview_reason == "no-changed-files-detected"
    assert result.staging_required is True
    assert result.staging_reason == "no-changed-files-detected"
    assert result.staging_ai_ocr_required is True
    assert result.staging_ai_ocr_reason == "no-changed-files-detected"


def test_AC8_13_20_pr_preview_only_runs_for_app_e2e_or_compose_changes() -> None:
    """AC8.13.20: PR preview deploys are scoped to runtime, E2E, and compose changes."""
    assert is_pr_preview_relevant("apps/backend/src/routers/statements.py") is True
    assert is_pr_preview_relevant("apps/backend/pyproject.toml") is True
    assert is_pr_preview_relevant("apps/frontend/src/app/page.tsx") is True
    assert is_pr_preview_relevant("apps/frontend/src/lib/api.ts") is True
    assert is_pr_preview_relevant("apps/frontend/package-lock.json") is True
    assert is_pr_preview_relevant("tests/e2e/test_core_journeys.py") is True
    assert is_pr_preview_relevant("docker-compose.yml") is True
    assert is_pr_preview_relevant("docker-compose.pr-preview.yml") is True
    assert is_pr_preview_relevant("tools/generate_pdf_fixtures.py") is True
    assert (
        is_pr_preview_relevant("tools/_lib/pdf_fixtures/generators/dbs_generator.py")
        is True
    )
    assert (
        is_pr_preview_relevant("tools/_lib/pdf_fixtures/templates/dbs_template.yaml")
        is True
    )
    assert is_pr_preview_relevant("tools/_lib/pdf_fixtures/README.md") is False
    assert is_pr_preview_relevant("tools/_lib/pdf_fixtures/FONT_HANDLING.md") is False
    assert (
        is_pr_preview_relevant("tools/_lib/pdf_fixtures/analyzers/README.md") is False
    )
    assert (
        is_pr_preview_relevant("apps/backend/tests/reporting/test_reports.py") is False
    )
    assert is_pr_preview_relevant("apps/backend/README.md") is False
    assert is_pr_preview_relevant("apps/frontend/src/lib/api.test.ts") is False
    assert (
        is_pr_preview_relevant(
            "apps/frontend/src/components/__tests__/ProcessingSummaryCard.test.tsx"
        )
        is False
    )
    assert is_pr_preview_relevant("apps/frontend/README.md") is False
    assert is_pr_preview_relevant("common/ssot/ac_traceability_refs.py") is False
    assert is_pr_preview_relevant(".github/workflows/ci.yml") is False

    result = classify_changed_paths(
        [
            "common/ssot/ac_traceability_refs.py",
            "docs/ssot/ci-cd.md",
            ".github/workflows/ci.yml",
        ]
    )

    assert result.heavy_required is True
    assert result.pr_preview_required is False
    assert result.pr_preview_reason == "no-pr-preview-paths-changed"
    assert result.staging_required is True
    assert result.staging_files == (".github/workflows/ci.yml",)
    assert result.staging_reason == "staging-paths-changed"
    assert result.staging_ai_ocr_required is False

    app_test_or_doc_result = classify_changed_paths(
        [
            "apps/backend/tests/reporting/test_reports.py",
            "apps/frontend/src/lib/api.test.ts",
            "apps/frontend/README.md",
        ]
    )

    assert app_test_or_doc_result.heavy_required is True
    assert app_test_or_doc_result.pr_preview_required is False
    assert app_test_or_doc_result.staging_required is False


def test_AC8_13_96_pr_preview_classifier_includes_preview_infrastructure_paths() -> (
    None
):
    """AC8.13.96: PR preview workflow and lifecycle changes exercise preview proof."""
    for path in (
        ".github/workflows/pr-test.yml",
        ".github/workflows/pr-preview-cleanup.yml",
        ".github/actions/setup-e2e-tests/action.yml",
        "docker-compose.pr-preview.yml",
        "tools/pr_preview_lifecycle.py",
        "tools/_lib/dev/pr_preview_lifecycle.py",
    ):
        assert is_pr_preview_relevant(path) is True

    for path in (
        "docs/ssot/ci-cd.md",
        "docs/project/archive/AC-TEST-TRACEABILITY-AUDIT.md",
        "apps/backend/tests/reporting/test_reports.py",
        "apps/frontend/src/lib/api.test.ts",
    ):
        assert is_pr_preview_relevant(path) is False

    result = classify_changed_paths(
        [
            "docs/ssot/ci-cd.md",
            ".github/workflows/pr-test.yml",
            "tools/_lib/dev/pr_preview_lifecycle.py",
        ]
    )

    assert result.heavy_required is True
    assert result.pr_preview_required is True
    assert result.pr_preview_files == (
        ".github/workflows/pr-test.yml",
        "tools/_lib/dev/pr_preview_lifecycle.py",
    )
    assert result.pr_preview_reason == "pr-preview-paths-changed"
    assert result.staging_required is False
    assert is_staging_relevant("docker-compose.pr-preview.yml") is False
    assert result.staging_ai_ocr_required is False


def test_AC8_13_20_pdf_fixture_docs_do_not_trigger_preview_or_staging() -> None:
    """AC8.13.20: PDF fixture MkDocs/doc entrypoint changes do not deploy previews."""
    result = classify_changed_paths(
        [
            "docs/ssot/pdf-fixtures.md",
            "mkdocs.yml",
            "tools/_lib/pdf_fixtures/README.md",
            "tools/_lib/pdf_fixtures/FONT_HANDLING.md",
            "tools/_lib/pdf_fixtures/analyzers/README.md",
            "tests/tooling/test_pdf_fixture_epic009_behavior.py",
        ]
    )

    assert result.heavy_required is True
    assert result.pr_preview_required is False
    assert result.pr_preview_files == ()
    assert result.pr_preview_reason == "no-pr-preview-paths-changed"
    assert result.staging_required is False
    assert result.staging_files == ()
    assert result.staging_reason == "no-staging-paths-changed"
    assert result.staging_ai_ocr_required is False


def test_AC8_13_104_staging_ai_ocr_runs_only_for_provider_risk_paths() -> None:
    """AC8.13.104: Provider-backed staging proof is risk-triggered."""
    for path in (
        ".github/workflows/staging-deploy.yml",
        ".github/workflows/staging-ai-ocr-gate.yml",
        "apps/backend/src/config.py",
        "apps/backend/src/prompts/statement.py",
        "apps/backend/src/services/extraction.py",
        "apps/backend/src/services/statement_parsing_supervisor.py",
        "apps/backend/src/services/ai_advisor.py",
        "apps/backend/src/routers/statements.py",
        "tests/e2e/test_statement_full_journey.py",
        "tests/e2e/test_personal_financial_report_package.py",
        "tools/staging_ai_ocr_gate_contract.py",
        "tools/_lib/pdf_fixtures/generators/moomoo_generator.py",
        "docs/ssot/ai.md",
        # The critical-proof matrix is no longer committed; its hand-curated
        # macro-outcome source is the staging trigger that replaced it.
        "docs/ssot/critical-proof-outcomes.yaml",
    ):
        assert is_staging_ai_ocr_relevant(path) is True

    for path in (
        ".github/workflows/ci.yml",
        "apps/backend/src/services/reporting.py",
        "apps/backend/tests/extraction/test_extraction.py",
        "apps/frontend/src/app/page.tsx",
        "docker-compose.yml",
        "repo",
        "repo/tools/deploy_v2.py",
        "tools/health_check.sh",
        "docs/ssot/ci-cd.md",
    ):
        assert is_staging_ai_ocr_relevant(path) is False

    runtime_result = classify_changed_paths(
        [
            "apps/backend/src/services/reporting.py",
            "apps/frontend/src/app/page.tsx",
            "docker-compose.yml",
        ]
    )
    assert runtime_result.staging_required is True
    assert runtime_result.staging_ai_ocr_required is False
    assert runtime_result.staging_ai_ocr_reason == "no-staging-ai-ocr-paths-changed"

    provider_result = classify_changed_paths(
        [
            "apps/backend/src/services/extraction.py",
            "tests/e2e/test_statement_full_journey.py",
        ]
    )
    assert provider_result.staging_required is True
    assert provider_result.staging_ai_ocr_required is True
    assert provider_result.staging_ai_ocr_files == (
        "apps/backend/src/services/extraction.py",
        "tests/e2e/test_statement_full_journey.py",
    )
    assert provider_result.staging_ai_ocr_reason == "staging-ai-ocr-paths-changed"


def test_AC8_13_55_staging_only_runs_for_runtime_deploy_or_e2e_changes() -> None:
    """AC8.13.55: Staging deploys are scoped to paths that can change deploy risk."""
    for path in (
        "apps/backend/src/routers/statements.py",
        "apps/backend/migrations/versions/0001_initial_schema.py",
        "apps/backend/pyproject.toml",
        "apps/frontend/src/app/page.tsx",
        "apps/frontend/src/lib/api.ts",
        "apps/frontend/public/icon.svg",
        "apps/frontend/package-lock.json",
        "tests/e2e/test_core_journeys.py",
        "docker-compose.yml",
        ".github/workflows/staging-deploy.yml",
        ".github/workflows/staging-ai-ocr-gate.yml",
        ".github/workflows/release-images.yml",
        ".github/workflows/ci.yml",
        ".github/actions/setup-e2e-tests/action.yml",
        "tools/health_check.sh",
        "tools/smoke_test.sh",
        "tools/generate_pdf_fixtures.py",
        "tools/check_ghcr_image_tag.sh",
        "tools/_lib/pdf_fixtures/generators/dbs_generator.py",
        "tools/_lib/pdf_fixtures/templates/dbs_template.yaml",
        "toolchain.toml",
        ".python-version",
        ".node-version",
        "repo",
        "repo/tools/deploy_v2.py",
        "repo/docker-compose.yml",
    ):
        assert is_staging_relevant(path) is True

    for path in (
        "apps/backend/tests/reporting/test_reports.py",
        "apps/backend/README.md",
        "apps/frontend/src/lib/api.test.ts",
        "apps/frontend/src/components/__tests__/ProcessingSummaryCard.test.tsx",
        "apps/frontend/README.md",
        "docs/project/archive/AC-TEST-TRACEABILITY-AUDIT.md",
        "docs/ssot/ci-cd.md",
        "common/ssot/check_ssot_ownership.py",
        "common/ssot/build_ac_traceability.py",
        "tests/tooling/test_check_ssot_ownership.py",
        "tools/_lib/pdf_fixtures/README.md",
        "tools/_lib/pdf_fixtures/FONT_HANDLING.md",
        "tools/_lib/pdf_fixtures/analyzers/README.md",
        ".github/workflows/docs.yml",
        ".github/workflows/production-release.yml",
    ):
        assert is_staging_relevant(path) is False

    result = classify_changed_paths(
        [
            "docs/project/archive/AC-TEST-TRACEABILITY-AUDIT.md",
            "docs/ssot/ci-cd.md",
            "common/ssot/check_ssot_ownership.py",
            "tests/tooling/test_check_ssot_ownership.py",
        ]
    )

    assert result.heavy_required is True
    assert result.staging_required is False
    assert result.staging_files == ()
    assert result.staging_reason == "no-staging-paths-changed"


def test_AC8_13_20_github_outputs_and_summary_include_heavy_files(
    tmp_path: Path,
) -> None:
    """AC8.13.20: Classifier writes GitHub outputs and actionable summaries."""
    result = classify_changed_paths(
        ["docs/ssot/ci-cd.md", "tools/ci_change_classifier.py"]
    )
    output = tmp_path / "github-output.txt"
    summary = tmp_path / "github-summary.md"

    classifier.write_github_outputs(result, output)
    classifier.write_github_summary(result, summary)

    output_lines = dict(
        line.split("=", maxsplit=1)
        for line in output.read_text(encoding="utf-8").splitlines()
    )
    assert output_lines["heavy_required"] == "true"
    assert output_lines["reason"] == "runtime-or-ci-paths-changed"
    assert json.loads(output_lines["env_stage_required"]) == {
        "local": True,
        "pr": True,
        "pr-preview": False,
        "staging": False,
        "prd": False,
    }
    assert output_lines["pr_preview_required"] == "false"
    assert output_lines["pr_preview_reason"] == "no-pr-preview-paths-changed"
    assert output_lines["staging_required"] == "false"
    assert output_lines["staging_reason"] == "no-staging-paths-changed"
    assert output_lines["staging_ai_ocr_required"] == "false"
    assert output_lines["staging_ai_ocr_reason"] == "no-staging-ai-ocr-paths-changed"
    summary_text = summary.read_text(encoding="utf-8")
    assert "## Change Classification" in summary_text
    assert "- Heavy CI required: `true`" in summary_text
    assert "- PR preview required: `false`" in summary_text
    assert "- Staging deploy required: `false`" in summary_text
    assert "- Staging AI/OCR required: `false`" in summary_text
    assert "- `tools/ci_change_classifier.py`" in summary_text


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
    assert "Staging-triggering files:" in summary_text


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
    assert "staging_required=false" in stdout
    assert "staging_reason=no-staging-paths-changed" in stdout
    assert "changed_files=2" in stdout
    assert "heavy_required=false" in github_output.read_text(encoding="utf-8")
    assert "pr_preview_required=false" in github_output.read_text(encoding="utf-8")
    assert "staging_required=false" in github_output.read_text(encoding="utf-8")
    assert "Changed files: `2`" in github_summary.read_text(encoding="utf-8")


def test_AC8_13_97_env_stage_matrix_keeps_environments_separate_from_pipeline_stages() -> (
    None
):
    """AC8.13.97: CI classification is modeled as sparse env x stage rules."""
    assert set(ENV_STAGE_MATRIX) == {
        Environment.LOCAL,
        Environment.PR,
        Environment.PR_PREVIEW,
        Environment.STAGING,
        Environment.PRODUCTION,
    }
    assert ENV_STAGE_MATRIX[Environment.LOCAL] == (
        PipelineStage.CHANGED_UNIT,
        PipelineStage.STATIC,
    )
    assert PipelineStage.FULL_UNIT in ENV_STAGE_MATRIX[Environment.PR]
    assert PipelineStage.INTEGRATION in ENV_STAGE_MATRIX[Environment.PR]
    assert PipelineStage.IMAGE_BUILD in ENV_STAGE_MATRIX[Environment.PR]
    assert PipelineStage.DEPLOY_SMOKE not in ENV_STAGE_MATRIX[Environment.PR]
    assert ENV_STAGE_MATRIX[Environment.PR_PREVIEW] == (
        PipelineStage.IMAGE_BUILD,
        PipelineStage.DEPLOY_SMOKE,
        PipelineStage.E2E,
    )
    assert PipelineStage.PROVIDER_GATE in ENV_STAGE_MATRIX[Environment.STAGING]
    assert PipelineStage.FULL_UNIT not in ENV_STAGE_MATRIX[Environment.STAGING]
    assert ENV_STAGE_MATRIX[Environment.PRODUCTION] == (
        PipelineStage.RELEASE_INTEGRITY,
        PipelineStage.DEPLOY_SMOKE,
    )


def test_AC8_13_97_deployed_env_classifiers_share_common_runtime_rules() -> None:
    """AC8.13.97: Shared runtime paths cannot drift between preview and staging classifiers."""
    for path in classifier.COMMON_DEPLOY_RUNTIME_EXACT:
        assert is_pr_preview_relevant(path) is True
        assert is_staging_relevant(path) is True

    for prefix in classifier.COMMON_DEPLOY_RUNTIME_PREFIXES:
        path = f"{prefix}sentinel.py"
        assert is_pr_preview_relevant(path) is True
        assert is_staging_relevant(path) is True

    assert classifier.ENV_STAGE_RULES[Environment.PR_PREVIEW].stages == (
        PipelineStage.IMAGE_BUILD,
        PipelineStage.DEPLOY_SMOKE,
        PipelineStage.E2E,
    )
    assert classifier.ENV_STAGE_RULES[Environment.STAGING].stages == (
        PipelineStage.IMAGE_BUILD,
        PipelineStage.DEPLOY_SMOKE,
        PipelineStage.E2E,
        PipelineStage.PROVIDER_GATE,
    )


def test_AC8_13_110_github_outputs_include_structured_env_stage_matrix(
    tmp_path: Path,
) -> None:
    """AC8.13.110: GitHub outputs expose Env x Stage JSON as the primary contract."""
    result = classify_changed_paths(
        [
            "apps/backend/src/services/reporting.py",
            ".github/workflows/pr-test.yml",
            "docs/ssot/ci-cd.md",
        ]
    )
    output = tmp_path / "github-output.txt"

    classifier.write_github_outputs(result, output)

    lines = dict(
        line.split("=", maxsplit=1)
        for line in output.read_text(encoding="utf-8").splitlines()
    )
    assert json.loads(lines["env_stage_required"]) == {
        "local": True,
        "pr": True,
        "pr-preview": True,
        "staging": True,
        "prd": False,
    }
    assert json.loads(lines["env_stage_reasons"]) == {
        "local": "local-advisory-default",
        "pr": "runtime-or-ci-paths-changed",
        "pr-preview": "pr-preview-paths-changed",
        "staging": "staging-paths-changed",
        "prd": "production-release-dispatch-only",
    }
    assert json.loads(lines["env_stage_stages"]) == {
        "local": ["changed-unit", "static"],
        "pr": [
            "static",
            "full-unit",
            "integration",
            "regression",
            "e2e",
            "image-build",
        ],
        "pr-preview": ["image-build", "deploy-smoke", "e2e"],
        "staging": ["image-build", "deploy-smoke", "e2e", "provider-gate"],
        "prd": ["release-integrity", "deploy-smoke"],
    }
    assert json.loads(lines["env_stage_files"]) == {
        "local": [
            "apps/backend/src/services/reporting.py",
            ".github/workflows/pr-test.yml",
            "docs/ssot/ci-cd.md",
        ],
        "pr": [
            "apps/backend/src/services/reporting.py",
            ".github/workflows/pr-test.yml",
        ],
        "pr-preview": [
            "apps/backend/src/services/reporting.py",
            ".github/workflows/pr-test.yml",
        ],
        "staging": ["apps/backend/src/services/reporting.py"],
        "prd": [],
    }
    assert json.loads(lines["provider_gate_required"]) == {"staging": False}

    # Legacy workflow outputs stay during migration.
    assert lines["pr_preview_required"] == "true"
    assert lines["staging_required"] == "true"
    assert lines["staging_ai_ocr_required"] == "false"


def test_AC8_13_111_structured_env_stage_outputs_cover_complete_environment_axis() -> (
    None
):
    """AC8.13.111: Structured Env x Stage outputs cover every environment."""
    result = classify_changed_paths(["docs/ssot/ci-cd.md"])
    required = classifier._env_stage_required(result)
    reasons = classifier._env_stage_reasons(result)
    files = classifier._env_stage_files(result)

    assert list(required) == ["local", "pr", "pr-preview", "staging", "prd"]
    assert required == {
        "local": True,
        "pr": False,
        "pr-preview": False,
        "staging": False,
        "prd": False,
    }
    assert reasons["local"] == "local-advisory-default"
    assert reasons["pr"] == "lightweight-docs-or-docs-workflow-only"
    assert reasons["prd"] == "production-release-dispatch-only"
    assert files["local"] == ["docs/ssot/ci-cd.md"]
    assert files["pr"] == []


def test_AC8_13_111_static_stage_rejects_non_static_environments() -> None:
    """AC8.13.111: Static env helper is limited to local and production cells."""
    with pytest.raises(ValueError, match="Unsupported static environment: staging"):
        classifier._classify_static_stage((), Environment.STAGING)


def test_AC8_13_110_summary_prints_env_stage_matrix(tmp_path: Path) -> None:
    """AC8.13.110: Summaries make env/stage decisions visible as a matrix."""
    result = classify_changed_paths(["docs/ssot/ci-cd.md"])
    summary = tmp_path / "github-summary.md"

    classifier.write_github_summary(result, summary)

    summary_text = summary.read_text(encoding="utf-8")
    assert "### Env x Stage Matrix" in summary_text
    assert (
        "| Environment | Required | Reason | Stages | Changed files |" in summary_text
    )
    assert (
        "| `local` | `true` | `local-advisory-default` | `changed-unit, static` | `1` |"
        in summary_text
    )
    assert (
        "| `pr` | `false` | `lightweight-docs-or-docs-workflow-only` | `static, full-unit, integration, regression, e2e, image-build` | `0` |"
        in summary_text
    )
    assert (
        "| `pr-preview` | `false` | `no-pr-preview-paths-changed` | `image-build, deploy-smoke, e2e` | `0` |"
        in summary_text
    )
    assert (
        "| `staging` | `false` | `no-staging-paths-changed` | `image-build, deploy-smoke, e2e, provider-gate` | `0` |"
        in summary_text
    )
    assert (
        "| `prd` | `false` | `production-release-dispatch-only` | `release-integrity, deploy-smoke` | `0` |"
        in summary_text
    )


def test_AC8_13_111_summary_prints_staging_provider_gate_files(
    tmp_path: Path,
) -> None:
    """AC8.13.111: Provider-gate staging proof remains visible in summaries."""
    result = classify_changed_paths(
        [
            "apps/backend/src/services/extraction.py",
            "tests/e2e/test_statement_full_journey.py",
        ]
    )
    summary = tmp_path / "github-summary.md"

    classifier.write_github_summary(result, summary)

    summary_text = summary.read_text(encoding="utf-8")
    assert "Staging AI/OCR-triggering files:" in summary_text
    assert "- `apps/backend/src/services/extraction.py`" in summary_text
    assert "- `tests/e2e/test_statement_full_journey.py`" in summary_text
