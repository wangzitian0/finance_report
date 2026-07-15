#!/usr/bin/env python3
"""Classify changed paths for CI job selection."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Environment(StrEnum):
    LOCAL = "local"
    PR = "pr"
    PR_PREVIEW = "pr-preview"
    STAGING = "staging"
    PRODUCTION = "prd"


class PipelineStage(StrEnum):
    CHANGED_UNIT = "changed-unit"
    STATIC = "static"
    FULL_UNIT = "full-unit"
    INTEGRATION = "integration"
    REGRESSION = "regression"
    E2E = "e2e"
    IMAGE_BUILD = "image-build"
    DEPLOY_SMOKE = "deploy-smoke"
    PROVIDER_GATE = "provider-gate"
    RELEASE_INTEGRITY = "release-integrity"


ENV_STAGE_MATRIX: dict[Environment, tuple[PipelineStage, ...]] = {
    Environment.LOCAL: (PipelineStage.CHANGED_UNIT, PipelineStage.STATIC),
    Environment.PR: (
        PipelineStage.STATIC,
        PipelineStage.FULL_UNIT,
        PipelineStage.INTEGRATION,
        PipelineStage.REGRESSION,
        PipelineStage.E2E,
        PipelineStage.IMAGE_BUILD,
    ),
    Environment.PR_PREVIEW: (
        PipelineStage.IMAGE_BUILD,
        PipelineStage.DEPLOY_SMOKE,
        PipelineStage.E2E,
    ),
    Environment.STAGING: (
        PipelineStage.IMAGE_BUILD,
        PipelineStage.DEPLOY_SMOKE,
        PipelineStage.E2E,
        PipelineStage.PROVIDER_GATE,
    ),
    Environment.PRODUCTION: (
        PipelineStage.RELEASE_INTEGRITY,
        PipelineStage.DEPLOY_SMOKE,
    ),
}

LIGHTWEIGHT_EXACT = {
    "AGENTS.md",
    "README.md",
    "vision.md",
    ".github/copilot-instructions.md",
    ".github/workflows/docs.yml",
}
LIGHTWEIGHT_PREFIXES = (
    "docs/",
    ".github/ISSUE_TEMPLATE/",
)

COMMON_DEPLOY_RUNTIME_EXACT = frozenset(
    {
        "apps/backend/Dockerfile",
        "apps/backend/alembic.ini",
        "apps/backend/pyproject.toml",
        "apps/backend/uv.lock",
        "apps/frontend/Dockerfile",
        "apps/frontend/next.config.mjs",
        "apps/frontend/package-lock.json",
        "apps/frontend/package.json",
        "apps/frontend/postcss.config.mjs",
        "apps/frontend/tailwind.config.ts",
        "apps/frontend/tsconfig.json",
        "docker-compose.yml",
        "tools/generate_pdf_fixtures.py",
        "tools/smoke_test.sh",
    }
)
COMMON_DEPLOY_RUNTIME_PREFIXES = (
    "apps/backend/config/",
    "apps/backend/migrations/",
    "apps/backend/scripts/",
    "apps/backend/src/",
    "apps/frontend/public/",
    "apps/frontend/src/",
    ".github/actions/setup-e2e-tests/",
    "tests/e2e/",
)

# Files whose change can alter a Docker IMAGE build result: Dockerfiles,
# .dockerignore (changes what is sent in the build context), dependency
# manifests/locks, build/runtime config copied into the image, and entrypoint/build
# scripts. A pure app-source change is COPY'd into the image and is already proven
# by frontend-build (tsc + next build) and the backend test jobs, so it does not
# need a fresh image build. Used to right-move the container-images CI job so it
# runs only when the build context actually changed (see ci-cd.md Key CI Property).
IMAGE_BUILD_EXACT = frozenset(
    {
        "apps/backend/.dockerignore",
        "apps/backend/Dockerfile",
        "apps/backend/alembic.ini",
        "apps/backend/pyproject.toml",
        "apps/backend/uv.lock",
        "apps/frontend/.dockerignore",
        "apps/frontend/Dockerfile",
        "apps/frontend/next.config.mjs",
        "apps/frontend/package-lock.json",
        "apps/frontend/package.json",
        "apps/frontend/postcss.config.mjs",
        "apps/frontend/tailwind.config.ts",
        "apps/frontend/tsconfig.json",
    }
)
IMAGE_BUILD_PREFIXES = ("apps/backend/scripts/",)


def is_image_build_relevant(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized in IMAGE_BUILD_EXACT or normalized.startswith(
        IMAGE_BUILD_PREFIXES
    )


# Per-component change signal (#1689, gate re-architecture Phase 3 "cost-right").
# Component names match common.meta.extension.coverage.policy.COMPONENT_BY_NAME
# (backend/frontend/tools/common) so a PR's coverage gate can narrow its floor
# comparison to only the components it actually touched. Broader than that
# policy's coverage-instrumented source dirs on purpose: this answers "did the
# PR touch this component's job-relevant surface at all" (tests, config, fixtures
# included), not "is this file coverage-instrumented".
COMPONENT_PREFIXES: dict[str, tuple[str, ...]] = {
    "backend": ("apps/backend/",),
    "frontend": ("apps/frontend/",),
    "tools": ("tools/", "tests/tooling/"),
    "common": ("common/",),
}


def _classify_components(files: tuple[str, ...]) -> dict[str, bool]:
    # Fail closed when the diff is unknown (no files detected), matching
    # heavy_required/image_build_required's convention elsewhere in this module.
    if not files:
        return dict.fromkeys(COMPONENT_PREFIXES, True)
    return {
        name: any(path.startswith(prefixes) for path in files)
        for name, prefixes in COMPONENT_PREFIXES.items()
    }


PR_PREVIEW_ONLY_EXACT = frozenset(
    {
        ".github/workflows/maintenance.yml",
        ".github/workflows/preview.yml",
        "docker-compose.pr-preview.yml",
        "tools/pr_preview_lifecycle.py",
        "tools/_lib/dev/pr_preview_lifecycle.py",
        # The in-runner preview stack itself and the selection SSOT it runs
        # (#1547 follow-up): changing what the gate runs, or the stack it
        # runs on, must run the gate.
        "docker-compose.ci-e2e.yml",
        "tools/ci/e2e-nginx.conf",
        "common/testing/matrix.py",
        "tools/test_selection.py",
    }
)
STAGING_ONLY_EXACT = frozenset(
    {
        ".github/workflows/ci.yml",
        ".github/workflows/deploy.yml",
        ".node-version",
        ".python-version",
        "tools/check_ghcr_image_tag.sh",
        "tools/health_check.sh",
        "toolchain.toml",
        "repo",
    }
)

PR_PREVIEW_EXACT = COMMON_DEPLOY_RUNTIME_EXACT | PR_PREVIEW_ONLY_EXACT
PR_PREVIEW_PREFIXES = COMMON_DEPLOY_RUNTIME_PREFIXES

PDF_FIXTURE_RUNTIME_EXACT = {
    "common/testing/fixtures/pdf/__init__.py",
    "common/testing/fixtures/pdf/generate_pdf_fixtures.py",
}
PDF_FIXTURE_RUNTIME_PREFIXES = (
    "common/testing/fixtures/pdf/data/",
    "common/testing/fixtures/pdf/generators/",
    "common/testing/fixtures/pdf/templates/",
    "common/testing/fixtures/pdf/validators/",
)

STAGING_EXACT = COMMON_DEPLOY_RUNTIME_EXACT | STAGING_ONLY_EXACT
STAGING_PREFIXES = COMMON_DEPLOY_RUNTIME_PREFIXES

STAGING_AI_OCR_EXACT = frozenset(
    {
        ".github/workflows/deploy.yml",
        "apps/backend/src/config.py",
        "apps/backend/src/extraction/extension/prompts/statement.py",
        "common/llm/ai.md",
        # The critical-proof matrix is no longer committed; it is a derived view
        # of the AC graph. Adding/removing an llm-marked post-merge @ac_proof
        # edits its OWN e2e test file, and every such file is already a staging
        # trigger below, so the staging gate still fires on the real change.
        "common/testing/data/critical-proof-outcomes.yaml",
        "common/extraction/readme.md",
        "tests/e2e/test_brokerage_upload_to_portfolio_value.py",
        "tests/e2e/test_four_asset_net_worth_golden_path.py",
        "tests/e2e/test_personal_financial_report_package.py",
        "tests/e2e/test_statement_full_journey.py",
        "tests/e2e/test_statement_upload_e2e.py",
        "tools/staging_ai_ocr_gate_contract.py",
    }
)
STAGING_AI_OCR_PREFIXES = (
    # The advisor package carved out of services/ai_advisor (#1671 Wave B);
    # its chat path is provider-backed, so it stays a staging AI-OCR trigger.
    "apps/backend/src/advisor",
    "apps/backend/src/extraction",
    "apps/backend/src/routers/ai",
    "apps/backend/src/routers/statements",
    "common/testing/fixtures/pdf/data/",
    "common/testing/fixtures/pdf/generators/",
    "common/testing/fixtures/pdf/templates/",
    "common/testing/fixtures/pdf/validators/",
)


@dataclass(frozen=True)
class EnvStageRule:
    environment: Environment
    stages: tuple[PipelineStage, ...]
    exact: frozenset[str]
    prefixes: tuple[str, ...]
    changed_reason: str
    unchanged_reason: str
    fail_closed_on_empty: bool = True
    exclude_app_tests_and_docs: bool = True
    include_pdf_fixture_runtime: bool = True


ENV_STAGE_RULES: dict[Environment, EnvStageRule] = {
    Environment.PR_PREVIEW: EnvStageRule(
        environment=Environment.PR_PREVIEW,
        stages=ENV_STAGE_MATRIX[Environment.PR_PREVIEW],
        exact=frozenset(PR_PREVIEW_EXACT),
        prefixes=PR_PREVIEW_PREFIXES,
        changed_reason="pr-preview-paths-changed",
        unchanged_reason="no-pr-preview-paths-changed",
    ),
    Environment.STAGING: EnvStageRule(
        environment=Environment.STAGING,
        stages=ENV_STAGE_MATRIX[Environment.STAGING],
        exact=frozenset(STAGING_EXACT),
        prefixes=STAGING_PREFIXES,
        changed_reason="staging-paths-changed",
        unchanged_reason="no-staging-paths-changed",
    ),
}

LEGACY_ENV_OUTPUTS = (
    (Environment.PR_PREVIEW, "pr_preview", "PR preview", "PR preview", "PR preview"),
    (Environment.STAGING, "staging", "Staging deploy", "Staging", "Staging"),
)


def _json_output(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _env_stage_required(classification: ChangeClassification) -> dict[str, bool]:
    return {
        environment.value: env_result.required
        for environment, env_result in classification.envs.items()
    }


def _env_stage_reasons(classification: ChangeClassification) -> dict[str, str]:
    return {
        environment.value: env_result.reason
        for environment, env_result in classification.envs.items()
    }


def _env_stage_stages(
    classification: ChangeClassification,
) -> dict[str, list[str]]:
    return {
        environment.value: [stage.value for stage in env_result.stages]
        for environment, env_result in classification.envs.items()
    }


def _env_stage_files(classification: ChangeClassification) -> dict[str, list[str]]:
    return {
        environment.value: list(env_result.files)
        for environment, env_result in classification.envs.items()
    }


def _provider_gate_required(
    classification: ChangeClassification,
) -> dict[str, bool]:
    return {
        environment.value: env_result.provider_gate.required
        for environment, env_result in classification.envs.items()
        if PipelineStage.PROVIDER_GATE in env_result.stages
    }


def _provider_gate_reasons(classification: ChangeClassification) -> dict[str, str]:
    return {
        environment.value: env_result.provider_gate.reason
        for environment, env_result in classification.envs.items()
        if PipelineStage.PROVIDER_GATE in env_result.stages
    }


def _provider_gate_files(
    classification: ChangeClassification,
) -> dict[str, list[str]]:
    return {
        environment.value: list(env_result.provider_gate.files)
        for environment, env_result in classification.envs.items()
        if PipelineStage.PROVIDER_GATE in env_result.stages
    }


@dataclass(frozen=True)
class ChangeClassification:
    files: tuple[str, ...]
    heavy_files: tuple[str, ...]
    heavy_required: bool
    reason: str
    envs: Mapping[Environment, EnvStageClassification]
    image_build_files: tuple[str, ...]
    image_build_required: bool
    component_changed: Mapping[str, bool]

    @property
    def pr_preview_files(self) -> tuple[str, ...]:
        return self.envs[Environment.PR_PREVIEW].files

    @property
    def pr_preview_required(self) -> bool:
        return self.envs[Environment.PR_PREVIEW].required

    @property
    def pr_preview_reason(self) -> str:
        return self.envs[Environment.PR_PREVIEW].reason

    @property
    def staging_files(self) -> tuple[str, ...]:
        return self.envs[Environment.STAGING].files

    @property
    def staging_required(self) -> bool:
        return self.envs[Environment.STAGING].required

    @property
    def staging_reason(self) -> str:
        return self.envs[Environment.STAGING].reason

    @property
    def staging_ai_ocr_files(self) -> tuple[str, ...]:
        return self.envs[Environment.STAGING].provider_gate.files

    @property
    def staging_ai_ocr_required(self) -> bool:
        return self.envs[Environment.STAGING].provider_gate.required

    @property
    def staging_ai_ocr_reason(self) -> str:
        return self.envs[Environment.STAGING].provider_gate.reason


@dataclass(frozen=True)
class EnvStageClassification:
    files: tuple[str, ...]
    required: bool
    reason: str
    stages: tuple[PipelineStage, ...]
    provider_gate: ProviderGateClassification


@dataclass(frozen=True)
class ProviderGateClassification:
    files: tuple[str, ...]
    required: bool
    reason: str


def normalize_path(path: str) -> str:
    return path.strip().replace("\\", "/")


def is_lightweight(path: str) -> bool:
    normalized = normalize_path(path)
    if normalized in LIGHTWEIGHT_EXACT:
        return True
    return normalized.startswith(LIGHTWEIGHT_PREFIXES)


def _is_app_test_or_doc_path(path: str) -> bool:
    if not path.startswith(("apps/backend/", "apps/frontend/")):
        return False

    file_name = path.rsplit("/", maxsplit=1)[-1]
    suffix = file_name.rsplit(".", maxsplit=1)[-1].lower()
    stem_parts = file_name.split(".")

    if suffix in {"md", "mdx"}:
        return True
    if "/tests/" in path or "/__tests__/" in path:
        return True
    return len(stem_parts) >= 3 and stem_parts[-2] in {"test", "spec"}


def _is_pdf_fixture_runtime_path(path: str) -> bool:
    return path in PDF_FIXTURE_RUNTIME_EXACT or path.startswith(
        PDF_FIXTURE_RUNTIME_PREFIXES
    )


def _matches_env_stage_rule(path: str, rule: EnvStageRule) -> bool:
    normalized = normalize_path(path)
    if normalized in rule.exact:
        return True
    if rule.exclude_app_tests_and_docs and _is_app_test_or_doc_path(normalized):
        return False
    if rule.include_pdf_fixture_runtime and _is_pdf_fixture_runtime_path(normalized):
        return True
    return normalized.startswith(rule.prefixes)


def is_pr_preview_relevant(path: str) -> bool:
    return _matches_env_stage_rule(path, ENV_STAGE_RULES[Environment.PR_PREVIEW])


def is_staging_relevant(path: str) -> bool:
    return _matches_env_stage_rule(path, ENV_STAGE_RULES[Environment.STAGING])


def is_staging_ai_ocr_relevant(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized in STAGING_AI_OCR_EXACT or normalized.startswith(
        STAGING_AI_OCR_PREFIXES
    )


def _classify_staging_provider_gate(
    files: tuple[str, ...],
) -> ProviderGateClassification:
    matched_files = tuple(path for path in files if is_staging_ai_ocr_relevant(path))
    required = bool(matched_files or not files)
    reason = (
        "staging-ai-ocr-paths-changed"
        if matched_files
        else "no-changed-files-detected"
        if not files
        else "no-staging-ai-ocr-paths-changed"
    )
    return ProviderGateClassification(
        files=matched_files,
        required=required,
        reason=reason,
    )


def _empty_provider_gate() -> ProviderGateClassification:
    return ProviderGateClassification(
        files=(),
        required=False,
        reason="not-a-staging-provider-gate",
    )


def _classify_pr_stage(
    files: tuple[str, ...], heavy_files: tuple[str, ...], heavy_required: bool
) -> EnvStageClassification:
    reason = (
        "runtime-or-ci-paths-changed"
        if heavy_files
        else "no-changed-files-detected"
        if not files
        else "lightweight-docs-or-docs-workflow-only"
    )
    return EnvStageClassification(
        files=heavy_files,
        required=heavy_required,
        reason=reason,
        stages=ENV_STAGE_MATRIX[Environment.PR],
        provider_gate=_empty_provider_gate(),
    )


def _classify_static_stage(
    files: tuple[str, ...], environment: Environment
) -> EnvStageClassification:
    if environment == Environment.LOCAL:
        return EnvStageClassification(
            files=files,
            required=True,
            reason="local-advisory-default",
            stages=ENV_STAGE_MATRIX[environment],
            provider_gate=_empty_provider_gate(),
        )
    if environment == Environment.PRODUCTION:
        return EnvStageClassification(
            files=(),
            required=False,
            reason="production-release-dispatch-only",
            stages=ENV_STAGE_MATRIX[environment],
            provider_gate=_empty_provider_gate(),
        )
    raise ValueError(f"Unsupported static environment: {environment}")


def _classify_env_stage(
    files: tuple[str, ...], environment: Environment
) -> EnvStageClassification:
    rule = ENV_STAGE_RULES[environment]
    matched_files = tuple(path for path in files if _matches_env_stage_rule(path, rule))
    required = bool(matched_files or (not files and rule.fail_closed_on_empty))
    reason = (
        rule.changed_reason
        if matched_files
        else "no-changed-files-detected"
        if not files and rule.fail_closed_on_empty
        else rule.unchanged_reason
    )
    return EnvStageClassification(
        files=matched_files,
        required=required,
        reason=reason,
        stages=rule.stages,
        provider_gate=(
            _classify_staging_provider_gate(files)
            if environment == Environment.STAGING
            else _empty_provider_gate()
        ),
    )


def classify_changed_paths(paths: Iterable[str]) -> ChangeClassification:
    files = tuple(path for raw in paths if (path := normalize_path(raw)))
    heavy_files = tuple(path for path in files if not is_lightweight(path))
    heavy_required = bool(heavy_files or not files)
    image_build_files = tuple(path for path in files if is_image_build_relevant(path))
    # Fail closed when the diff is unknown (no files detected).
    image_build_required = bool(image_build_files or not files)
    reason = (
        "runtime-or-ci-paths-changed"
        if heavy_files
        else "no-changed-files-detected"
        if not files
        else "lightweight-docs-or-docs-workflow-only"
    )
    envs: dict[Environment, EnvStageClassification] = {
        Environment.LOCAL: _classify_static_stage(files, Environment.LOCAL),
        Environment.PR: _classify_pr_stage(files, heavy_files, heavy_required),
        Environment.PR_PREVIEW: _classify_env_stage(files, Environment.PR_PREVIEW),
        Environment.STAGING: _classify_env_stage(files, Environment.STAGING),
        Environment.PRODUCTION: _classify_static_stage(files, Environment.PRODUCTION),
    }
    return ChangeClassification(
        files=files,
        heavy_files=heavy_files,
        heavy_required=heavy_required,
        reason=reason,
        envs=envs,
        image_build_files=image_build_files,
        image_build_required=image_build_required,
        component_changed=_classify_components(files),
    )


def write_github_outputs(
    classification: ChangeClassification, output_path: Path
) -> None:
    with output_path.open("a", encoding="utf-8") as fh:
        fh.write(f"heavy_required={str(classification.heavy_required).lower()}\n")
        fh.write(
            f"image_build_required={str(classification.image_build_required).lower()}\n"
        )
        fh.write(f"reason={classification.reason}\n")
        fh.write(
            f"env_stage_required={_json_output(_env_stage_required(classification))}\n"
        )
        fh.write(
            f"env_stage_reasons={_json_output(_env_stage_reasons(classification))}\n"
        )
        fh.write(
            f"env_stage_stages={_json_output(_env_stage_stages(classification))}\n"
        )
        fh.write(f"env_stage_files={_json_output(_env_stage_files(classification))}\n")
        fh.write(
            f"provider_gate_required={_json_output(_provider_gate_required(classification))}\n"
        )
        fh.write(
            f"provider_gate_reasons={_json_output(_provider_gate_reasons(classification))}\n"
        )
        fh.write(
            f"provider_gate_files={_json_output(_provider_gate_files(classification))}\n"
        )
        # #1689: per-component change flags (plain scalars, matching
        # image_build_required's convention — a single fact per component, not a
        # per-environment matrix, so no JSON blob/fromJSON() needed by consumers).
        for name in COMPONENT_PREFIXES:
            changed = classification.component_changed[name]
            fh.write(f"{name}_changed={str(changed).lower()}\n")
        changed_components = ",".join(
            name
            for name in COMPONENT_PREFIXES
            if classification.component_changed[name]
        )
        fh.write(f"coverage_gate_components={changed_components}\n")
        # The structured Env x Stage / provider-gate JSON above is the sole
        # machine-readable gate contract. Every workflow consumer (ci.yml,
        # preview.yml) normalizes its own scalar from that matrix, so the legacy
        # per-env scalar outputs (`pr_preview_required`, `staging_required`,
        # `staging_ai_ocr_required`, ...) are no longer emitted (AC8.13.110).
        # Human-readable per-env lines still appear in write_github_summary.


def write_github_summary(
    classification: ChangeClassification, summary_path: Path
) -> None:
    with summary_path.open("a", encoding="utf-8") as fh:
        fh.write("## Change Classification\n\n")
        fh.write(
            f"- Heavy CI required: `{str(classification.heavy_required).lower()}`\n"
        )
        fh.write(f"- Reason: `{classification.reason}`\n")
        for (
            environment,
            _output_prefix,
            required_label,
            reason_label,
            _files_label,
        ) in LEGACY_ENV_OUTPUTS:
            env_result = classification.envs[environment]
            fh.write(
                f"- {required_label} required: `{str(env_result.required).lower()}`\n"
            )
            fh.write(f"- {reason_label} reason: `{env_result.reason}`\n")
        fh.write(
            f"- Staging AI/OCR required: `{str(classification.staging_ai_ocr_required).lower()}`\n"
        )
        fh.write(f"- Staging AI/OCR reason: `{classification.staging_ai_ocr_reason}`\n")
        fh.write(f"- Changed files: `{len(classification.files)}`\n")
        fh.write("\n### Env x Stage Matrix\n\n")
        fh.write("| Environment | Required | Reason | Stages | Changed files |\n")
        fh.write("|---|---|---|---|---|\n")
        for environment, env_result in classification.envs.items():
            stages = ", ".join(stage.value for stage in env_result.stages)
            fh.write(
                f"| `{environment.value}` | `{str(env_result.required).lower()}` | "
                f"`{env_result.reason}` | `{stages}` | `{len(env_result.files)}` |\n"
            )
        provider_gate = classification.envs[Environment.STAGING].provider_gate
        fh.write("\n### Provider Gate Matrix\n\n")
        fh.write("| Environment | Required | Reason | Changed files |\n")
        fh.write("|---|---|---|---|\n")
        fh.write(
            f"| `{Environment.STAGING.value}` | "
            f"`{str(provider_gate.required).lower()}` | "
            f"`{provider_gate.reason}` | `{len(provider_gate.files)}` |\n"
        )
        if classification.heavy_files:
            fh.write("\nHeavy-triggering files:\n\n")
            for path in classification.heavy_files[:50]:
                fh.write(f"- `{path}`\n")
        for (
            environment,
            _output_prefix,
            _required_label,
            _reason_label,
            files_label,
        ) in LEGACY_ENV_OUTPUTS:
            env_result = classification.envs[environment]
            if env_result.files:
                fh.write(f"\n{files_label}-triggering files:\n\n")
                for path in env_result.files[:50]:
                    fh.write(f"- `{path}`\n")
        if classification.staging_ai_ocr_files:
            fh.write("\nStaging AI/OCR-triggering files:\n\n")
            for path in classification.staging_ai_ocr_files[:50]:
                fh.write(f"- `{path}`\n")
        fh.write("\n### Component Changed (#1689 coverage-gate scoping)\n\n")
        fh.write("| Component | Changed |\n")
        fh.write("|---|---|\n")
        for name in COMPONENT_PREFIXES:
            changed = classification.component_changed[name]
            fh.write(f"| `{name}` | `{str(changed).lower()}` |\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--github-summary", type=Path)
    args = parser.parse_args()

    classification = classify_changed_paths(
        args.changed_files.read_text(encoding="utf-8").splitlines()
    )

    if args.github_output:
        write_github_outputs(classification, args.github_output)
    if args.github_summary:
        write_github_summary(classification, args.github_summary)

    print(f"heavy_required={str(classification.heavy_required).lower()}")
    print(f"reason={classification.reason}")
    print(f"env_stage_required={_json_output(_env_stage_required(classification))}")
    print(f"env_stage_reasons={_json_output(_env_stage_reasons(classification))}")
    print(f"env_stage_stages={_json_output(_env_stage_stages(classification))}")
    print(
        f"provider_gate_required={_json_output(_provider_gate_required(classification))}"
    )
    print(f"component_changed={_json_output(dict(classification.component_changed))}")
    print(f"changed_files={len(classification.files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
