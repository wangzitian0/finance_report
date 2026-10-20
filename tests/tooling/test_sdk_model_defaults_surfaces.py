"""The infra2 SDK owns the default models; CI, preview and staging pin none (#2566).

Owner rules (2026-10-20): the SDK defines the default models; CI, preview and
staging carry no model configuration; only production may customize. These
guards read every surface that configures, documents or calls a model:

* app source names no model id of its own,
* workflows, actions, compose files and Dockerfiles assign no model variable,
* generated env files show exactly the SDK defaults, and
* docs name only the SDK default models.
"""

from __future__ import annotations

import re
from pathlib import Path

from infra2_sdk.runtime.llm import LlmSettings

ROOT = Path(__file__).resolve().parents[2]
# "glm-5", "glm-5.3-flashx", "GLM-5.1" and "glm4.6v" all match.
GLM_ID = re.compile(r"\bglm-?[0-9](?:[a-z0-9.\-]*[a-z0-9])?", re.IGNORECASE)
# Longest names first, so VISION_FALLBACK_MODELS never reads as FALLBACK_MODELS.
MODEL_VARS = (
    "VISION_FALLBACK_MODELS",
    "FALLBACK_MODELS",
    "PRIMARY_MODEL",
    "VISION_MODEL",
    "OCR_MODEL",
)
_VARS = "|".join(MODEL_VARS)
# `KEY=value` (.env) and `KEY: value` (YAML). A prefix such as `STAGING_E2E_` is part
# of the same slot, so the name may follow an underscore-joined prefix.
ASSIGNMENT = re.compile(
    rf"(?<![A-Za-z0-9])(?:[A-Z0-9]+_)*?({_VARS})\b\s*[:=]\s*(\$\{{\{{[^}}]*\}}\}}|[\"']?[^\"'\s#]*)"
)
# `| `KEY` | default | example | …` (env reference table): both value cells count.
REFERENCE_ROW = re.compile(rf"^\|\s*`(?:[A-Z0-9]+_)*?({_VARS})`\s*\|([^|]*)\|([^|]*)\|")
# Dockerfile `ENV KEY value` (space form).
DOCKER_ENV = re.compile(rf"^\s*ENV\s+(?:[A-Z0-9]+_)*?({_VARS})\s+([^\s=]+)\s*$")
QUOTED = re.compile(r"'([^']*)'|\"([^\"]*)\"")
# Python or JSON mapping form: "PRIMARY_MODEL": "value".
MAPPING = re.compile(rf"[\"'](?:[A-Z0-9]+_)*?({_VARS})[\"']\s*:\s*[\"']([^\"']+)[\"']")
# The GLM 5.3 wire adapter matches these family names to enable thinking; it
# chooses no model, so its three lines are exempt by exact content.
EXEMPT_LINES = {
    ("apps/backend/src/llm/extension/client.py", '"glm-5.3",'),
    ("apps/backend/src/llm/extension/client.py", '"glm-5.3-flash",'),
    ("apps/backend/src/llm/extension/client.py", '"glm-5.3-flashx",'),
}
# The manual cassette recorder calls the z.ai coding plan with thinking disabled,
# which the glm-5.3 models reject; it records fixtures offline and is no app model
# slot. Its migration needs a live check with the provider key (#2569).
EXCLUDED_PARTS = (
    "node_modules",
    "__tests__",
    ".test.",
    "/tests/",
    ".venv",
    ".claude/",
    "llm_cassettes",
    "common/extraction/record_hf_cassettes.py",
)
APP_SOURCE = (
    "apps/backend/src/**/*.py",
    "apps/frontend/src/**/*.ts",
    "apps/frontend/src/**/*.tsx",
)
NON_PRODUCTION_CONFIG = (
    ".github/workflows/*.yml",
    ".github/actions/**/*.yml",
    "**/*compose*.yml",
    "**/*compose*.yaml",
    "**/Dockerfile*",
    "tools/**/*.py",
    "common/runtime/dev/**/*",
    "**/*.sh",
    "Makefile",
)
GENERATED_ENV = (".env.example", "common/runtime/env-reference.generated.md")
DOCS = (
    "common/extraction/readme.md",
    "common/runtime/ci-cd.md",
    "common/llm/readme.md",
    "common/observability/observability-logging.md",
)


def _sdk_default_model_ids() -> frozenset[str]:
    sdk = LlmSettings()
    ids = (
        sdk.primary_model,
        sdk.ocr_model,
        sdk.vision_model,
        *sdk.fallback_models,
        *sdk.vision_fallback_models,
    )
    return frozenset(model_id for model_id in ids if model_id)


def _included(path: Path) -> bool:
    return path.is_file() and not any(
        part in str(path.relative_to(ROOT)) for part in EXCLUDED_PARTS
    )


def _glob(patterns: tuple[str, ...]) -> list[Path]:
    return sorted(
        {path for pattern in patterns for path in ROOT.glob(pattern) if _included(path)}
    )


def _glm_ids(path: Path) -> list[tuple[int, str]]:
    rel = str(path.relative_to(ROOT))
    found: list[tuple[int, str]] = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        if (rel, line.strip()) in EXEMPT_LINES:
            continue
        found.extend((line_no, match.group(0)) for match in GLM_ID.finditer(line))
    return found


def _slot_values(line: str) -> list[tuple[str, str]]:
    """Return (variable, model id) pairs that one line assigns to a model variable."""
    pairs: list[tuple[str, str]] = []
    row = REFERENCE_ROW.match(line)
    if row is not None:
        for cell in (row.group(2), row.group(3)):
            for value in re.findall(r"`([^`]*)`", cell):
                pairs.extend(
                    (row.group(1), item.strip())
                    for item in value.split(",")
                    if item.strip()
                )
        return pairs
    mapped = [(m.group(1), m.group(2).strip()) for m in MAPPING.finditer(line)]
    if mapped:
        return mapped
    docker = DOCKER_ENV.match(line)
    if docker is not None:
        return [
            (docker.group(1), item.strip())
            for item in docker.group(2).split(",")
            if item.strip()
        ]
    for match in ASSIGNMENT.finditer(line):
        value = match.group(2)
        if value == "${{":
            # An expression the parser cannot read fails closed: it is reported as a value.
            literals = [line.split(match.group(1), 1)[1].lstrip(" :=").strip()]
        elif value.startswith("${{"):
            # A workflow expression: check every literal default inside it.
            literals = [a or b for a, b in QUOTED.findall(value)]
        else:
            literals = [value.strip("\"'")]
        for literal in literals:
            pairs.extend(
                (match.group(1), item.strip())
                for item in literal.split(",")
                if item.strip()
            )
    return pairs


def test_AC_llm_sdk_model_defaults_2_slot_parser_reads_every_assignment_form() -> None:
    """AC-llm.sdk-model-defaults.2: the parser reads prefixed, YAML, .env, expression and table forms."""
    cases = {
        "STAGING_E2E_PRIMARY_MODEL: gpt-4o": [("PRIMARY_MODEL", "gpt-4o")],
        "  OCR_MODEL: 'glm-5.2'": [("OCR_MODEL", "glm-5.2")],
        "FALLBACK_MODELS=glm-5.2,glm-5-turbo": [
            ("FALLBACK_MODELS", "glm-5.2"),
            ("FALLBACK_MODELS", "glm-5-turbo"),
        ],
        "VISION_MODEL: ${{ vars.VISION_MODEL || 'gpt-4o' }}": [
            ("VISION_MODEL", "gpt-4o")
        ],
        "PRIMARY_MODEL=glm-5.3-flash OCR_MODEL=glm-5": [
            ("PRIMARY_MODEL", "glm-5.3-flash"),
            ("OCR_MODEL", "glm-5"),
        ],
        "| `PRIMARY_MODEL` | `glm-5.2` |  |  | AI Provider |": [
            ("PRIMARY_MODEL", "glm-5.2")
        ],
        "| `FALLBACK_MODELS` |  | `glm-4.6v` |  | AI Provider |": [
            ("FALLBACK_MODELS", "glm-4.6v")
        ],
        "ENV VISION_FALLBACK_MODELS=glm-4.5v": [("VISION_FALLBACK_MODELS", "glm-4.5v")],
        "echo primary=${STAGING_E2E_PRIMARY_MODEL}": [],
        "ENV PRIMARY_MODEL gpt-4o": [("PRIMARY_MODEL", "gpt-4o")],
        '{"PRIMARY_MODEL": "glm-5.2"}': [("PRIMARY_MODEL", "glm-5.2")],
        "| `STAGING_E2E_OCR_MODEL` | `glm-5.2` |  |": [("OCR_MODEL", "glm-5.2")],
    }
    for line, expected in cases.items():
        assert _slot_values(line) == expected, (
            f"{line!r} parsed as {_slot_values(line)}"
        )
    unreadable = _slot_values("PRIMARY_MODEL: ${{ format('{0}', 'gpt-4o') }}")
    assert unreadable and unreadable[0][1] not in _sdk_default_model_ids(), (
        f"an unreadable expression must fail closed, parsed as {unreadable}"
    )


def test_AC_llm_sdk_model_defaults_2_app_source_names_no_model_id() -> None:
    """AC-llm.sdk-model-defaults.2: backend and frontend source name no model id; the SDK owns them."""
    files = _glob(APP_SOURCE)
    assert len(files) > 100, f"the app source scan read only {len(files)} files"
    violations = [
        f"{p.relative_to(ROOT)}:{n}: {i}" for p in files for n, i in _glm_ids(p)
    ]
    assert violations == [], "app source names model ids:\n" + "\n".join(violations)


def test_AC_llm_sdk_model_defaults_2_ci_preview_staging_assign_no_model() -> None:
    """AC-llm.sdk-model-defaults.2: workflows, actions, compose files and Dockerfiles assign no model variable."""
    files = _glob(NON_PRODUCTION_CONFIG)
    assert len(files) >= 10, f"the config scan read only {len(files)} files"
    violations = []
    for path in files:
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            violations.extend(
                f"{path.relative_to(ROOT)}:{line_no}: {var}={value}"
                for var, value in _slot_values(line)
            )
    assert violations == [], "non-production config pins models:\n" + "\n".join(
        violations
    )


def test_AC_llm_sdk_model_defaults_2_generated_env_shows_the_sdk_defaults() -> None:
    """AC-llm.sdk-model-defaults.2: .env.example and the env reference show exactly the SDK default models."""
    sdk = _sdk_default_model_ids()
    for rel in GENERATED_ENV:
        values = [
            model_id
            for line in (ROOT / rel).read_text(encoding="utf-8").splitlines()
            for _var, model_id in _slot_values(line)
        ]
        assert set(values) == sdk, (
            f"{rel} shows {sorted(set(values))}, the SDK defaults are {sorted(sdk)}"
        )


def test_AC_llm_sdk_model_defaults_2_docs_name_only_sdk_default_models() -> None:
    """AC-llm.sdk-model-defaults.2: model docs and common Python name only the SDK default models."""
    sdk = _sdk_default_model_ids()
    files = [ROOT / rel for rel in DOCS] + _glob(("common/**/*.py",))
    seen = 0
    violations: list[str] = []
    for path in files:
        for line_no, model_id in _glm_ids(path):
            seen += 1
            if model_id.lower() not in sdk:
                violations.append(f"{path.relative_to(ROOT)}:{line_no}: {model_id}")
    assert seen >= 5, (
        f"the doc scan found only {seen} model ids; the file list is wrong"
    )
    assert violations == [], "docs name models outside the SDK defaults:\n" + "\n".join(
        violations
    )


def test_AC_llm_sdk_model_defaults_3_staging_gate_blocks_on_the_catalog_check() -> None:
    """AC-llm.sdk-model-defaults.3: the staging catalog check installs the SDK, runs once, can fail the job, and the canary waits for it."""
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    node = "tests/e2e/test_ai_provider_connectivity.py::test_staging_catalog_serves_the_sdk_default_models"
    provider_job = workflow.split("\n  provider-gate:", 1)[1].split(
        "\n  ai-ocr-gate:", 1
    )[0]
    assert node in provider_job, (
        "the catalog check must run in the staging provider-gate job"
    )
    install = 'uv pip install --python "$(command -v python)" "$sdk_wheel"'
    assert install in provider_job, "the SDK must go into the uv venv that runs pytest"
    assert 'python -c "import infra2_sdk.runtime.llm"' in provider_job
    assert provider_job.index(install) < provider_job.index(node), (
        "the provider gate must install the SDK before the catalog check"
    )
    steps = provider_job.split("\n      - name: ")
    catalog_steps = [step for step in steps if node in step]
    assert len(catalog_steps) == 1, (
        f"expected one provider-gate step that runs {node}, found {len(catalog_steps)}"
    )
    step = catalog_steps[0]
    assert "for n in" not in step, (
        "the catalog check must not run inside the provider retry loop"
    )
    assert "continue-on-error" not in step, (
        "the catalog check must be able to fail the job"
    )
    assert "\n        if:" not in step, (
        "the catalog step must not carry a condition that can skip it"
    )
    assert "|| true" not in step, "the catalog step must not swallow a failure"
    assert "set -euo pipefail" in step, (
        "the catalog step must stop on the first failure"
    )
    assert "id: model_catalog_policy" in step, (
        "the delivery result reads the catalog step outcome"
    )
    assert (
        "model_catalog_outcome: ${{ steps.model_catalog_policy.outcome }}"
        in provider_job
    )
    ai_ocr_job = workflow.split("\n  ai-ocr-gate:", 1)[1].split(
        "\n  financial-benchmark:", 1
    )[0]
    assert "needs.provider-gate.result == 'success'" in ai_ocr_job
    delivery_job = workflow.split("\n  post-merge-delivery:", 1)[1]
    catalog_branch = '[ "$model_catalog_outcome" = "failure" ]'
    provider_branch = '[ "$provider_result" != "success" ]'
    for text in (
        'model_catalog_outcome="${{ needs.provider-gate.outputs.model_catalog_outcome }}"',
        catalog_branch,
        'failure_reason="deployed model catalog does not equal the SDK default models"',
        provider_branch,
    ):
        assert text in delivery_job, f"post-merge delivery is missing: {text}"
    assert delivery_job.index(catalog_branch) < delivery_job.index(provider_branch)


def test_AC_llm_sdk_model_defaults_4_production_release_only_reports_the_catalog() -> (
    None
):
    """AC-llm.sdk-model-defaults.4: production may customize, so the release reports its catalog and never fails on it."""
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    step = release.split("\n      - name: Report production model catalog", 1)[1].split(
        "\n      - name: ", 1
    )[0]
    assert "continue-on-error: true" in step, (
        "the production catalog report must never fail the release"
    )
    assert "/api/llm/catalog" in step and "GITHUB_STEP_SUMMARY" in step
    assert "exit 1" not in step and "assert" not in step
