import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.testing import change_classifier as classifier  # noqa: E402
from common.testing.change_classifier import (  # noqa: E402
    ENV_STAGE_MATRIX,
    Environment,
    PipelineStage,
    classify_changed_paths,
    is_pr_preview_relevant,
    is_staging_ai_ocr_relevant,
    is_staging_relevant,
)


def _check_result(
    result,
    *,
    heavy: bool | None = None,
    heavy_files: tuple[str, ...] | None = None,
    reason: str | None = None,
    preview: bool | None = None,
    preview_files: tuple[str, ...] | None = None,
    preview_reason: str | None = None,
    staging: bool | None = None,
    staging_files: tuple[str, ...] | None = None,
    staging_reason: str | None = None,
    ai_ocr: bool | None = None,
    ai_ocr_files: tuple[str, ...] | None = None,
    ai_ocr_reason: str | None = None,
    image_build: bool | None = None,
    image_build_files: tuple[str, ...] | None = None,
) -> None:
    if heavy is not None:
        assert result.heavy_required is heavy
    if heavy_files is not None:
        assert result.heavy_files == heavy_files
    if reason is not None:
        assert result.reason == reason
    if preview is not None:
        assert result.pr_preview_required is preview
    if preview_files is not None:
        assert result.pr_preview_files == preview_files
    if preview_reason is not None:
        assert result.pr_preview_reason == preview_reason
    if staging is not None:
        assert result.staging_required is staging
    if staging_files is not None:
        assert result.staging_files == staging_files
    if staging_reason is not None:
        assert result.staging_reason == staging_reason
    if ai_ocr is not None:
        assert result.staging_ai_ocr_required is ai_ocr
    if ai_ocr_files is not None:
        assert result.staging_ai_ocr_files == ai_ocr_files
    if ai_ocr_reason is not None:
        assert result.staging_ai_ocr_reason == ai_ocr_reason
    if image_build is not None:
        assert result.image_build_required is image_build
    if image_build_files is not None:
        assert result.image_build_files == image_build_files


def test_AC8_13_20_docs_and_docs_workflow_are_lightweight() -> None:
    """AC8.13.20: Documentation-only changes skip heavy CI."""
    result = classify_changed_paths(
        [
            "README.md",
            "docs/ssot/README.md",
            ".github/workflows/docs.yml",
            ".github/ISSUE_TEMPLATE/bug.md",
        ]
    )
    _check_result(
        result,
        heavy=False,
        heavy_files=(),
        reason="lightweight-docs-or-docs-workflow-only",
        preview=False,
        preview_files=(),
        preview_reason="no-pr-preview-paths-changed",
        staging=False,
        staging_files=(),
        staging_reason="no-staging-paths-changed",
        ai_ocr=False,
        ai_ocr_files=(),
        ai_ocr_reason="no-staging-ai-ocr-paths-changed",
        image_build=False,
        image_build_files=(),
    )


def test_AC8_13_20_image_build_required_tracks_build_context_only() -> None:
    """AC8.13.20: container-images is right-moved to build-context changes."""
    src_only = classify_changed_paths(
        ["apps/backend/src/main.py", "apps/frontend/src/app/page.tsx"]
    )
    assert src_only.heavy_required is True
    assert src_only.image_build_required is False
    assert src_only.image_build_files == ()

    for path in (
        "apps/backend/.dockerignore",
        "apps/backend/Dockerfile",
        "apps/backend/uv.lock",
        "apps/backend/pyproject.toml",
        "apps/frontend/.dockerignore",
        "apps/frontend/Dockerfile",
        "apps/frontend/package-lock.json",
        "apps/frontend/tsconfig.json",
        "apps/backend/scripts/entrypoint.sh",
    ):
        res = classify_changed_paths([path])
        assert res.image_build_required is True, path
        assert res.image_build_files == (path,)

    assert classify_changed_paths(["README.md"]).image_build_required is False
    assert classify_changed_paths([]).image_build_required is True


def test_AC8_13_20_image_build_required_emitted_to_github_output(
    tmp_path: Path,
) -> None:
    """AC8.13.20: the image_build_required scalar is written for ci.yml to consume."""
    out = tmp_path / "gh_output"
    classifier.write_github_outputs(
        classify_changed_paths(["apps/backend/src/main.py"]), out
    )
    assert "image_build_required=false\n" in out.read_text(encoding="utf-8")
    out.unlink()
    classifier.write_github_outputs(
        classify_changed_paths(["apps/backend/uv.lock"]), out
    )
    assert "image_build_required=true\n" in out.read_text(encoding="utf-8")


def test_AC8_13_20_multi_commit_runtime_path_requires_heavy_ci() -> None:
    """AC8.13.20: Multi-commit push ranges stay heavy when any runtime path changes."""
    result = classify_changed_paths(
        [
            "docs/ssot/README.md",
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
    """AC-testing.classifier.2: AC8.13.20: Runtime CI workflow changes cannot be hidden by docs-only rules."""
    assert classify_changed_paths([".github/workflows/ci.yml"]).heavy_required is True
    assert (
        classify_changed_paths([".github/workflows/deploy.yml"]).heavy_required is True
    )
    assert (
        classify_changed_paths([".github/workflows/docs.yml"]).heavy_required is False
    )


def test_AC8_13_20_markdown_under_runtime_trees_is_heavy() -> None:
    """AC8.13.20: Documentation inside runtime component trees triggers heavy CI."""
    result = classify_changed_paths(["apps/backend/README.md"])
    assert result.heavy_required is True
    assert result.heavy_files == ("apps/backend/README.md",)
    assert result.reason == "runtime-or-ci-paths-changed"


def test_AC8_13_20_empty_change_set_requires_heavy_ci() -> None:
    """AC8.13.20: Empty change sets (e.g., initial commit or diff failure) run heavy CI safely."""
    _check_result(
        classify_changed_paths([]),
        heavy=True,
        reason="no-changed-files-detected",
        heavy_files=(),
        preview=True,
        preview_files=(),
        preview_reason="no-changed-files-detected",
        staging=True,
        staging_reason="no-changed-files-detected",
        ai_ocr=True,
        ai_ocr_reason="no-changed-files-detected",
    )


def test_AC8_13_20_pr_preview_only_runs_for_app_e2e_or_compose_changes() -> None:
    """AC8.13.20: PR preview deploys are scoped to runtime, E2E, and compose changes."""
    for p in (
        "apps/backend/src/routers/statements.py",
        "apps/backend/pyproject.toml",
        "apps/frontend/src/app/page.tsx",
        "apps/frontend/src/lib/api.ts",
        "apps/frontend/package-lock.json",
        "tests/e2e/test_bench_v2_ui_golden_paths.py",
        "docker-compose.yml",
        "docker-compose.pr-preview.yml",
        "tools/generate_pdf_fixtures.py",
        "common/testing/fixtures/pdf/generators/dbs_generator.py",
        "common/testing/fixtures/pdf/templates/dbs_template.yaml",
    ):
        assert is_pr_preview_relevant(p) is True

    for p in (
        "common/testing/fixtures/pdf/README.md",
        "common/testing/fixtures/pdf/FONT_HANDLING.md",
        "common/testing/fixtures/pdf/analyzers/README.md",
        "apps/backend/tests/reporting/test_reports.py",
        "apps/backend/README.md",
        "apps/frontend/src/lib/api.test.ts",
        "apps/frontend/src/__tests__/processingSummaryCard.test.tsx",
        "apps/frontend/README.md",
        "common/testing/ac_traceability_refs.py",
        ".github/workflows/ci.yml",
    ):
        assert is_pr_preview_relevant(p) is False

    result = classify_changed_paths(
        [
            "common/testing/ac_traceability_refs.py",
            "docs/ssot/README.md",
            ".github/workflows/ci.yml",
        ]
    )
    _check_result(
        result,
        heavy=True,
        preview=False,
        preview_reason="no-pr-preview-paths-changed",
        staging=True,
        staging_files=(".github/workflows/ci.yml",),
        staging_reason="staging-paths-changed",
        ai_ocr=False,
    )

    app_res = classify_changed_paths(
        [
            "apps/backend/tests/reporting/test_reports.py",
            "apps/frontend/src/lib/api.test.ts",
            "apps/frontend/README.md",
        ]
    )
    _check_result(app_res, heavy=True, preview=False, staging=False)


def test_AC8_13_96_pr_preview_classifier_includes_preview_infrastructure_paths() -> (
    None
):
    """AC-testing.classifier.3: AC8.13.96: PR preview workflow and lifecycle changes exercise preview proof."""
    for p in (
        ".github/workflows/preview.yml",
        ".github/workflows/maintenance.yml",
        ".github/actions/setup-e2e-tests/action.yml",
        "docker-compose.pr-preview.yml",
        "tools/pr_preview_lifecycle.py",
        "tools/_lib/dev/pr_preview_lifecycle.py",
    ):
        assert is_pr_preview_relevant(p) is True

    for p in (
        "docs/ssot/README.md",
        "docs/project/archive/AC-TEST-TRACEABILITY-AUDIT.md",
        "apps/backend/tests/reporting/test_reports.py",
        "apps/frontend/src/lib/api.test.ts",
    ):
        assert is_pr_preview_relevant(p) is False

    result = classify_changed_paths(
        [
            "docs/ssot/README.md",
            ".github/workflows/preview.yml",
            "tools/_lib/dev/pr_preview_lifecycle.py",
        ]
    )
    _check_result(
        result,
        heavy=True,
        preview=True,
        preview_files=(
            ".github/workflows/preview.yml",
            "tools/_lib/dev/pr_preview_lifecycle.py",
        ),
        preview_reason="pr-preview-paths-changed",
        staging=False,
        ai_ocr=False,
    )
    assert is_staging_relevant("docker-compose.pr-preview.yml") is False


def test_AC8_13_20_pdf_fixture_docs_do_not_trigger_preview_or_staging() -> None:
    """AC8.13.20: PDF fixture MkDocs/doc entrypoint changes do not deploy previews."""
    result = classify_changed_paths(
        [
            "common/testing/readme.md",
            "mkdocs.yml",
            "common/testing/fixtures/pdf/README.md",
            "common/testing/fixtures/pdf/FONT_HANDLING.md",
            "common/testing/fixtures/pdf/analyzers/README.md",
            "tests/tooling/test_pdf_fixture_epic009_behavior.py",
        ]
    )
    _check_result(
        result,
        heavy=True,
        preview=False,
        preview_files=(),
        preview_reason="no-pr-preview-paths-changed",
        staging=False,
        staging_files=(),
        staging_reason="no-staging-paths-changed",
        ai_ocr=False,
    )


def test_AC8_13_104_staging_ai_ocr_runs_only_for_provider_risk_paths() -> None:
    """AC-testing.classifier.5: AC8.13.104: Provider-backed staging proof is risk-triggered."""
    for p in (
        ".github/workflows/deploy.yml",
        "apps/backend/src/config.py",
        "apps/backend/src/extraction/extension/prompts/statement.py",
        "apps/backend/src/extraction/extension/service.py",
        "apps/backend/src/extraction/extension/statement_parsing_supervisor.py",
        "apps/backend/src/advisor/extension/service.py",
        "apps/backend/src/routers/statements.py",
        "tests/e2e/test_statement_full_journey.py",
        "tests/e2e/test_personal_financial_report_package.py",
        "tools/staging_ai_ocr_gate_contract.py",
        "common/testing/fixtures/pdf/generators/moomoo_generator.py",
        "common/llm/ai.md",
        "common/testing/data/critical-proof-outcomes.yaml",
    ):
        assert is_staging_ai_ocr_relevant(p) is True

    for p in (
        ".github/workflows/ci.yml",
        "apps/backend/src/services/reporting.py",
        "apps/backend/tests/extraction/test_extraction.py",
        "apps/frontend/src/app/page.tsx",
        "docker-compose.yml",
        "tools/health_check.sh",
        "docs/ssot/README.md",
    ):
        assert is_staging_ai_ocr_relevant(p) is False

    runtime_res = classify_changed_paths(
        [
            "docs/ssot/README.md",
            ".github/workflows/preview.yml",
            "apps/backend/src/extraction/extension/prompts/statement.py",
        ]
    )
    _check_result(
        runtime_res,
        heavy=True,
        preview=True,
        staging=True,
        ai_ocr=True,
        ai_ocr_files=("apps/backend/src/extraction/extension/prompts/statement.py",),
        ai_ocr_reason="staging-ai-ocr-paths-changed",
    )

    docs_res = classify_changed_paths(["docs/ssot/README.md"])
    _check_result(
        docs_res,
        ai_ocr=False,
        ai_ocr_files=(),
        ai_ocr_reason="no-staging-ai-ocr-paths-changed",
    )


def test_AC8_13_55_staging_only_runs_for_runtime_deploy_or_e2e_changes() -> None:
    """AC-testing.deploy-gates.14: AC-testing.classifier.1: AC8.13.55: Staging deploys are scoped to paths that can change deploy risk."""
    for p in (
        ".github/workflows/deploy.yml",
        ".github/workflows/ci.yml",
        ".github/actions/setup-e2e-tests/action.yml",
        "docker-compose.yml",
        "apps/backend/src/routers/statements.py",
        "apps/backend/src/services/reporting.py",
        "apps/backend/migrations/versions/0001_initial_schema.py",
        "apps/backend/pyproject.toml",
        "apps/frontend/src/app/page.tsx",
        "apps/frontend/src/lib/api.ts",
        "apps/frontend/public/icon.svg",
        "apps/frontend/package-lock.json",
        "tests/e2e/test_bench_v2_ui_golden_paths.py",
        "tests/e2e/test_statement_upload_e2e.py",
        "tools/health_check.sh",
        "tools/smoke_test.sh",
        "tools/generate_pdf_fixtures.py",
        "tools/check_ghcr_image_tag.sh",
        "common/testing/fixtures/pdf/generators/dbs_generator.py",
        "common/testing/fixtures/pdf/templates/dbs_template.yaml",
        "toolchain.toml",
        ".python-version",
        ".node-version",
    ):
        assert is_staging_relevant(p) is True

    for p in (
        "apps/backend/tests/reporting/test_reports.py",
        "apps/backend/README.md",
        "apps/frontend/src/lib/api.test.ts",
        "apps/frontend/src/__tests__/processingSummaryCard.test.tsx",
        "apps/frontend/README.md",
        "docs/project/archive/AC-TEST-TRACEABILITY-AUDIT.md",
        "docs/ssot/README.md",
        "common/meta/extension/check_ssot_ownership.py",
        "common/testing/build_ac_traceability.py",
        "tests/tooling/test_check_ssot_ownership.py",
        "common/testing/fixtures/pdf/README.md",
        "common/testing/fixtures/pdf/FONT_HANDLING.md",
        "common/testing/fixtures/pdf/analyzers/README.md",
        ".github/workflows/docs.yml",
    ):
        assert is_staging_relevant(p) is False

    result = classify_changed_paths(
        [
            "docs/project/archive/AC-TEST-TRACEABILITY-AUDIT.md",
            "docs/ssot/README.md",
            "common/meta/extension/check_ssot_ownership.py",
            "tests/tooling/test_check_ssot_ownership.py",
        ]
    )
    _check_result(
        result,
        heavy=True,
        staging=False,
        staging_files=(),
        staging_reason="no-staging-paths-changed",
    )


def test_AC8_13_20_github_outputs_and_summary_include_heavy_files(
    tmp_path: Path,
) -> None:
    """AC8.13.20: Classifier writes GitHub outputs and actionable summaries."""
    result = classify_changed_paths(
        ["docs/ssot/README.md", "tools/ci_change_classifier.py"]
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
    # Legacy per-env scalar outputs are retired: the structured matrix above is
    # the sole machine-readable gate contract (AC8.13.110).
    assert "pr_preview_required" not in output_lines
    assert "pr_preview_reason" not in output_lines
    assert "staging_required" not in output_lines
    assert "staging_reason" not in output_lines
    assert "staging_ai_ocr_required" not in output_lines
    assert "staging_ai_ocr_reason" not in output_lines
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
            "tests/e2e/test_bench_v2_ui_golden_paths.py",
        ]
    )
    summary = tmp_path / "github-summary.md"

    classifier.write_github_summary(result, summary)

    summary_text = summary.read_text(encoding="utf-8")
    assert "PR preview-triggering files:" in summary_text
    assert "- `apps/frontend/src/app/page.tsx`" in summary_text
    assert "- `tests/e2e/test_bench_v2_ui_golden_paths.py`" in summary_text
    assert "Staging-triggering files:" in summary_text


def test_AC8_13_20_cli_writes_outputs_summary_and_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC8.13.20: CLI entrypoint matches the workflow contract."""
    changed_files = tmp_path / "changed-files.txt"
    github_output = tmp_path / "github-output.txt"
    github_summary = tmp_path / "github-summary.md"
    changed_files.write_text(
        "docs/ssot/README.md\n.github/workflows/docs.yml\n", encoding="utf-8"
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
    for s in (
        "heavy_required=false",
        "reason=lightweight-docs-or-docs-workflow-only",
        "env_stage_required=",
        "changed_files=2",
    ):
        assert s in stdout
    assert "pr_preview_required=" not in stdout and "staging_required=" not in stdout

    github_output_text = github_output.read_text(encoding="utf-8")
    assert "heavy_required=false" in github_output_text
    assert "env_stage_required=" in github_output_text
    assert "pr_preview_required=" not in github_output_text
    assert "staging_required=" not in github_output_text
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
    for stage in (
        PipelineStage.FULL_UNIT,
        PipelineStage.INTEGRATION,
        PipelineStage.IMAGE_BUILD,
    ):
        assert stage in ENV_STAGE_MATRIX[Environment.PR]
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
    """AC-testing.classifier.4: AC8.13.97: Shared runtime paths cannot drift between preview and staging classifiers."""
    for path in classifier.COMMON_DEPLOY_RUNTIME_EXACT:
        assert is_pr_preview_relevant(path) is True
        assert is_staging_relevant(path) is True

    for prefix in classifier.COMMON_DEPLOY_RUNTIME_PREFIXES:
        p = f"{prefix}sentinel.py"
        assert is_pr_preview_relevant(p) is True
        assert is_staging_relevant(p) is True

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
    """AC-testing.classifier.6: AC8.13.110: GitHub outputs expose Env x Stage JSON as the primary contract."""
    result = classify_changed_paths(
        [
            "apps/backend/src/services/reporting.py",
            ".github/workflows/preview.yml",
            "docs/ssot/README.md",
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
    expected_files = [
        "apps/backend/src/services/reporting.py",
        ".github/workflows/preview.yml",
    ]
    assert json.loads(lines["env_stage_files"]) == {
        "local": expected_files + ["docs/ssot/README.md"],
        "pr": expected_files,
        "pr-preview": expected_files,
        "staging": ["apps/backend/src/services/reporting.py"],
        "prd": [],
    }
    assert json.loads(lines["provider_gate_required"]) == {"staging": False}
    for k in ("pr_preview_required", "staging_required", "staging_ai_ocr_required"):
        assert k not in lines


def test_AC8_13_111_structured_env_stage_outputs_cover_complete_environment_axis() -> (
    None
):
    """AC8.13.111: Structured Env x Stage outputs cover every environment."""
    result = classify_changed_paths(["docs/ssot/README.md"])
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
    assert files["local"] == ["docs/ssot/README.md"]
    assert files["pr"] == []


def test_AC8_13_111_static_stage_rejects_non_static_environments() -> None:
    """AC-testing.classifier.7: AC8.13.111: Static env helper is limited to local and production cells."""
    with pytest.raises(ValueError, match="Unsupported static environment: staging"):
        classifier._classify_static_stage((), Environment.STAGING)


def test_AC8_13_110_summary_prints_env_stage_matrix(tmp_path: Path) -> None:
    """AC8.13.110: Summaries make env/stage decisions visible as a matrix."""
    result = classify_changed_paths(["docs/ssot/README.md"])
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


def test_AC8_13_111_summary_prints_staging_provider_gate_files(tmp_path: Path) -> None:
    """AC8.13.111: Provider-gate staging proof remains visible in summaries."""
    result = classify_changed_paths(
        [
            "apps/backend/src/extraction/extension/service.py",
            "tests/e2e/test_statement_full_journey.py",
        ]
    )
    summary = tmp_path / "github-summary.md"
    classifier.write_github_summary(result, summary)

    summary_text = summary.read_text(encoding="utf-8")
    assert "Staging AI/OCR-triggering files:" in summary_text
    assert "- `apps/backend/src/extraction/extension/service.py`" in summary_text
    assert "- `tests/e2e/test_statement_full_journey.py`" in summary_text


def test_in_runner_stack_and_selection_ssot_trigger_preview_gate() -> None:
    """#1547 follow-up: changing in-runner stack or selection SSOT runs Preview E2E gate."""
    for path in (
        "docker-compose.ci-e2e.yml",
        "tools/ci/e2e-nginx.conf",
        "common/testing/matrix.py",
        "tools/test_selection.py",
    ):
        assert is_pr_preview_relevant(path), path


def test_AC8_13_161_component_changed_isolates_a_single_component() -> None:
    """AC-testing.classifier.10: AC8.13.161: a backend-only diff flags only backend as changed."""
    result = classify_changed_paths(
        ["apps/backend/src/services/reporting/cash_flow.py"]
    )
    assert result.component_changed == {
        "backend": True,
        "frontend": False,
        "tools": False,
        "common": False,
    }


def test_AC8_13_161_component_changed_flags_every_touched_component() -> None:
    result = classify_changed_paths(
        [
            "apps/frontend/src/app/page.tsx",
            "common/testing/matrix.py",
            "tools/foo.py",
            "tests/tooling/test_foo.py",
        ]
    )
    assert result.component_changed == {
        "backend": False,
        "frontend": True,
        "tools": True,
        "common": True,
    }


def test_AC8_13_161_component_changed_fails_closed_on_unknown_diff() -> None:
    """An empty diff must not silently scope OUT every component."""
    result = classify_changed_paths([])
    assert result.component_changed == {
        "backend": True,
        "frontend": True,
        "tools": True,
        "common": True,
    }


def test_AC8_13_161_component_changed_is_false_for_root_only_config() -> None:
    """A change to a root-level file reports every component as untouched."""
    result = classify_changed_paths(["docker-compose.yml"])
    assert result.component_changed == {
        "backend": False,
        "frontend": False,
        "tools": False,
        "common": False,
    }


def test_AC8_13_161_component_changed_fails_closed_on_ci_definition_change() -> None:
    """A change to the CI workflow definition forces all components True."""
    for path in (
        ".github/workflows/ci.yml",
        "common/testing/change_classifier.py",
        "tools/ci_change_classifier.py",
    ):
        result = classify_changed_paths([path])
        assert result.component_changed == {
            "backend": True,
            "frontend": True,
            "tools": True,
            "common": True,
        }

    mixed = classify_changed_paths(
        ["apps/backend/src/services/reporting/cash_flow.py", ".github/workflows/ci.yml"]
    )
    assert mixed.component_changed == {
        "backend": True,
        "frontend": True,
        "tools": True,
        "common": True,
    }


def test_AC8_13_161_github_outputs_include_component_changed_scalars(
    tmp_path: Path,
) -> None:
    result = classify_changed_paths(
        ["apps/backend/src/services/reporting/cash_flow.py", "tools/foo.py"]
    )
    output = tmp_path / "github-output.txt"
    classifier.write_github_outputs(result, output)
    lines = dict(
        line.split("=", maxsplit=1)
        for line in output.read_text(encoding="utf-8").splitlines()
    )
    assert lines["backend_changed"] == "true"
    assert lines["frontend_changed"] == "false"
    assert lines["tools_changed"] == "true"
    assert lines["common_changed"] == "false"
    assert lines["coverage_gate_components"] == "backend,tools"


def test_AC8_13_161_summary_includes_component_changed_table(tmp_path: Path) -> None:
    result = classify_changed_paths(["apps/frontend/src/app/page.tsx"])
    summary = tmp_path / "github-summary.md"
    classifier.write_github_summary(result, summary)
    summary_text = summary.read_text(encoding="utf-8")
    for name, changed in result.component_changed.items():
        assert f"| `{name}` | `{str(changed).lower()}` |" in summary_text
