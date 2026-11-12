#!/usr/bin/env python3
"""Classify changed paths for CI job selection."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from common.testing import matrix


class Environment(StrEnum):
    LOCAL = "local"
    PR = "pr"
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
LIGHTWEIGHT_PREFIXES = ("docs/",)

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

COMPONENT_PREFIXES: dict[str, tuple[str, ...]] = {
    "backend": ("apps/backend/",),
    "frontend": ("apps/frontend/",),
    "tools": ("tools/", "tests/tooling/"),
    "common": ("common/",),
}

CI_DEFINITION_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        "common/testing/change_classifier.py",
        "tools/ci_change_classifier.py",
    }
)

STAGING_ONLY_EXACT = frozenset(
    {
        ".github/workflows/ci.yml",
        ".node-version",
        ".python-version",
        "common/testing/matrix.py",
        "runtime-hooks.manifest.json",
        "tools/test_selection.py",
        "toolchain.toml",
    }
)

PDF_FIXTURE_RUNTIME_EXACT = {
    "common/testing/fixtures/pdf/__init__.py",
    "common/testing/fixtures/pdf/generate_pdf_fixtures.py",
}
PDF_FIXTURE_RUNTIME_PREFIXES = (
    "common/testing/fixtures/pdf/data/",
    "common/testing/fixtures/pdf/generators/",
    "common/testing/fixtures/pdf/templates/",
)

STAGING_EXACT = COMMON_DEPLOY_RUNTIME_EXACT | STAGING_ONLY_EXACT
STAGING_PREFIXES = COMMON_DEPLOY_RUNTIME_PREFIXES

STAGING_AI_OCR_EXACT = frozenset(
    {
        "apps/backend/src/config.py",
        "apps/backend/src/extraction/extension/prompts/statement.py",
        "common/llm/ai.md",
        "common/testing/data/critical-proof-outcomes.yaml",
        "common/extraction/readme.md",
        "runtime-hooks.manifest.json",
        "tests/e2e/test_brokerage_upload_to_portfolio_value.py",
        "tests/e2e/test_four_asset_net_worth_golden_path.py",
        "tests/e2e/test_personal_financial_report_package.py",
        "tests/e2e/test_statement_full_journey.py",
        "tests/e2e/test_statement_upload_e2e.py",
        "tools/staging_ai_ocr_gate_contract.py",
    }
)
STAGING_AI_OCR_PREFIXES = (
    "apps/backend/src/advisor",
    "apps/backend/src/extraction",
    "apps/backend/src/routers/ai",
    "apps/backend/src/routers/statements",
    "common/testing/fixtures/pdf/data/",
    "common/testing/fixtures/pdf/generators/",
    "common/testing/fixtures/pdf/templates/",
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
    (Environment.STAGING, "staging", "Staging deploy", "Staging", "Staging"),
)


@dataclass(frozen=True)
class ProviderGateClassification:
    files: tuple[str, ...]
    required: bool
    reason: str


@dataclass(frozen=True)
class EnvStageClassification:
    files: tuple[str, ...]
    required: bool
    reason: str
    stages: tuple[PipelineStage, ...]
    provider_gate: ProviderGateClassification


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
    touched_e2e_tests: tuple[str, ...] = ()

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


def _json_output(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _project_envs(
    classification: ChangeClassification,
    fn: Callable[[EnvStageClassification], Any],
    *,
    provider_only: bool = False,
) -> dict[str, Any]:
    return {
        env.value: fn(res)
        for env, res in classification.envs.items()
        if not provider_only or PipelineStage.PROVIDER_GATE in res.stages
    }


def _env_stage_required(classification: ChangeClassification) -> dict[str, bool]:
    return _project_envs(classification, lambda r: r.required)


def _env_stage_reasons(classification: ChangeClassification) -> dict[str, str]:
    return _project_envs(classification, lambda r: r.reason)


def _env_stage_stages(classification: ChangeClassification) -> dict[str, list[str]]:
    return _project_envs(classification, lambda r: [s.value for s in r.stages])


def _env_stage_files(classification: ChangeClassification) -> dict[str, list[str]]:
    return _project_envs(classification, lambda r: list(r.files))


def _provider_gate_required(classification: ChangeClassification) -> dict[str, bool]:
    return _project_envs(
        classification, lambda r: r.provider_gate.required, provider_only=True
    )


def _provider_gate_reasons(classification: ChangeClassification) -> dict[str, str]:
    return _project_envs(
        classification, lambda r: r.provider_gate.reason, provider_only=True
    )


def _provider_gate_files(classification: ChangeClassification) -> dict[str, list[str]]:
    return _project_envs(
        classification, lambda r: list(r.provider_gate.files), provider_only=True
    )


def normalize_path(path: str) -> str:
    return path.strip().replace("\\", "/")


def is_image_build_relevant(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized in IMAGE_BUILD_EXACT or normalized.startswith(
        IMAGE_BUILD_PREFIXES
    )


def _classify_components(files: tuple[str, ...]) -> dict[str, bool]:
    if not files or any(path in CI_DEFINITION_PATHS for path in files):
        return dict.fromkeys(COMPONENT_PREFIXES, True)
    return {
        name: any(path.startswith(prefixes) for path in files)
        for name, prefixes in COMPONENT_PREFIXES.items()
    }


def is_lightweight(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized in LIGHTWEIGHT_EXACT or normalized.startswith(
        LIGHTWEIGHT_PREFIXES
    )


def _is_app_test_or_doc_path(path: str) -> bool:
    if not path.startswith(("apps/backend/", "apps/frontend/")):
        return False
    file_name = path.rsplit("/", maxsplit=1)[-1]
    suffix = file_name.rsplit(".", maxsplit=1)[-1].lower()
    stem_parts = file_name.split(".")
    return (
        suffix in {"md", "mdx"}
        or "/tests/" in path
        or "/__tests__/" in path
        or (len(stem_parts) >= 3 and stem_parts[-2] in {"test", "spec"})
    )


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


def is_staging_ai_ocr_relevant(path: str) -> bool:
    normalized = normalize_path(path)
    return normalized in STAGING_AI_OCR_EXACT or normalized.startswith(
        STAGING_AI_OCR_PREFIXES
    )


def _empty_provider_gate() -> ProviderGateClassification:
    return ProviderGateClassification(
        files=(), required=False, reason="not-a-staging-provider-gate"
    )


def _classify_staging_provider_gate(
    files: tuple[str, ...],
) -> ProviderGateClassification:
    matched = tuple(path for path in files if is_staging_ai_ocr_relevant(path))
    reason = (
        "staging-ai-ocr-paths-changed"
        if matched
        else "no-changed-files-detected"
        if not files
        else "no-staging-ai-ocr-paths-changed"
    )
    return ProviderGateClassification(
        files=matched, required=bool(matched or not files), reason=reason
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
    matched = tuple(path for path in files if _matches_env_stage_rule(path, rule))
    required = bool(matched or (not files and rule.fail_closed_on_empty))
    reason = (
        rule.changed_reason
        if matched
        else "no-changed-files-detected"
        if not files and rule.fail_closed_on_empty
        else rule.unchanged_reason
    )
    return EnvStageClassification(
        files=matched,
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
    reason = (
        "runtime-or-ci-paths-changed"
        if heavy_files
        else "no-changed-files-detected"
        if not files
        else "lightweight-docs-or-docs-workflow-only"
    )
    pr_stage = EnvStageClassification(
        files=heavy_files,
        required=heavy_required,
        reason=reason,
        stages=ENV_STAGE_MATRIX[Environment.PR],
        provider_gate=_empty_provider_gate(),
    )
    return ChangeClassification(
        files=files,
        heavy_files=heavy_files,
        heavy_required=heavy_required,
        reason=reason,
        envs={
            Environment.LOCAL: _classify_static_stage(files, Environment.LOCAL),
            Environment.PR: pr_stage,
            Environment.STAGING: _classify_env_stage(files, Environment.STAGING),
            Environment.PRODUCTION: _classify_static_stage(
                files, Environment.PRODUCTION
            ),
        },
        image_build_files=image_build_files,
        image_build_required=bool(image_build_files or not files),
        component_changed=_classify_components(files),
        touched_e2e_tests=tuple(matrix.select_touched_e2e(files)),
    )


def write_github_outputs(
    classification: ChangeClassification, output_path: Path
) -> None:
    pairs = [
        ("heavy_required", str(classification.heavy_required).lower()),
        ("image_build_required", str(classification.image_build_required).lower()),
        ("reason", classification.reason),
        ("env_stage_required", _json_output(_env_stage_required(classification))),
        ("env_stage_reasons", _json_output(_env_stage_reasons(classification))),
        ("env_stage_stages", _json_output(_env_stage_stages(classification))),
        ("env_stage_files", _json_output(_env_stage_files(classification))),
        (
            "provider_gate_required",
            _json_output(_provider_gate_required(classification)),
        ),
        ("provider_gate_reasons", _json_output(_provider_gate_reasons(classification))),
        ("provider_gate_files", _json_output(_provider_gate_files(classification))),
        *(
            (f"{name}_changed", str(classification.component_changed[name]).lower())
            for name in COMPONENT_PREFIXES
        ),
        (
            "coverage_gate_components",
            ",".join(
                name
                for name in COMPONENT_PREFIXES
                if classification.component_changed[name]
            ),
        ),
        ("touched_e2e_tests", _json_output(list(classification.touched_e2e_tests))),
    ]
    with output_path.open("a", encoding="utf-8") as fh:
        fh.writelines(f"{k}={v}\n" for k, v in pairs)


def _write_file_section(fh: Any, title: str, paths: Sequence[str]) -> None:
    if paths:
        fh.write(f"\n{title}:\n\n")
        for path in paths[:50]:
            fh.write(f"- `{path}`\n")


def write_github_summary(
    classification: ChangeClassification, summary_path: Path
) -> None:
    with summary_path.open("a", encoding="utf-8") as fh:
        fh.write(
            "## Change Classification\n\n"
            f"- Heavy CI required: `{str(classification.heavy_required).lower()}`\n"
            f"- Reason: `{classification.reason}`\n"
        )
        for env, _pfx, req_label, reason_label, _files_label in LEGACY_ENV_OUTPUTS:
            env_result = classification.envs[env]
            fh.write(f"- {req_label} required: `{str(env_result.required).lower()}`\n")
            fh.write(f"- {reason_label} reason: `{env_result.reason}`\n")
        fh.write(
            f"- Staging AI/OCR required: `{str(classification.staging_ai_ocr_required).lower()}`\n"
            f"- Staging AI/OCR reason: `{classification.staging_ai_ocr_reason}`\n"
            f"- Changed files: `{len(classification.files)}`\n\n"
            "### Env x Stage Matrix\n\n"
            "| Environment | Required | Reason | Stages | Changed files |\n"
            "|---|---|---|---|---|\n"
        )
        for env, env_result in classification.envs.items():
            stages = ", ".join(s.value for s in env_result.stages)
            fh.write(
                f"| `{env.value}` | `{str(env_result.required).lower()}` | "
                f"`{env_result.reason}` | `{stages}` | `{len(env_result.files)}` |\n"
            )
        pg = classification.envs[Environment.STAGING].provider_gate
        fh.write(
            "\n### Provider Gate Matrix\n\n"
            "| Environment | Required | Reason | Changed files |\n"
            "|---|---|---|---|\n"
            f"| `{Environment.STAGING.value}` | `{str(pg.required).lower()}` | "
            f"`{pg.reason}` | `{len(pg.files)}` |\n"
        )
        _write_file_section(fh, "Heavy-triggering files", classification.heavy_files)
        for env, _pfx, _req_lbl, _rsn_lbl, files_label in LEGACY_ENV_OUTPUTS:
            _write_file_section(
                fh, f"{files_label}-triggering files", classification.envs[env].files
            )
        _write_file_section(
            fh, "Staging AI/OCR-triggering files", classification.staging_ai_ocr_files
        )
        fh.write(
            "\n### Component Changed (#1689 coverage-gate scoping)\n\n"
            "| Component | Changed |\n|---|---|\n"
        )
        for name in COMPONENT_PREFIXES:
            fh.write(
                f"| `{name}` | `{str(classification.component_changed[name]).lower()}` |\n"
            )
        if classification.touched_e2e_tests:
            fh.write("\n### Touched Non-LLM E2E Journeys (#2670)\n\n")
            for path in classification.touched_e2e_tests:
                fh.write(f"- `{path}`\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--github-summary", type=Path)
    args = parser.parse_args(argv)

    classification = classify_changed_paths(
        args.changed_files.read_text(encoding="utf-8").splitlines()
    )
    if args.github_output:
        write_github_outputs(classification, args.github_output)
    if args.github_summary:
        write_github_summary(classification, args.github_summary)

    for line in (
        f"heavy_required={str(classification.heavy_required).lower()}",
        f"reason={classification.reason}",
        f"env_stage_required={_json_output(_env_stage_required(classification))}",
        f"env_stage_reasons={_json_output(_env_stage_reasons(classification))}",
        f"env_stage_stages={_json_output(_env_stage_stages(classification))}",
        f"provider_gate_required={_json_output(_provider_gate_required(classification))}",
        f"component_changed={_json_output(dict(classification.component_changed))}",
        f"changed_files={len(classification.files)}",
    ):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
