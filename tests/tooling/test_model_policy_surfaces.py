"""Runtime config surfaces name only approved model ids (#2566).

A refactor once moved the fallback defaults back to old models and pinned them
in a test. These guards read every surface that configures, documents or calls
a deployed model:

* a shape scan fails on any GLM model id outside the approved set, and
* a slot-value parse fails on any value of a model variable outside the set,
  including ids of other vendors.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "apps" / "backend" / "src" / "llm" / "model_policy.py"
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
# A wire-adapter matcher that recognises GLM 5.3 names; it is never a call target.
EXEMPT_LINES = {("apps/backend/src/llm/extension/client.py", '"glm-5.3",')}
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
# Each slot surface must yield at least this many model variable values. The env
# files carry five variables; VISION_FALLBACK_MODELS is empty by design, so four.
MIN_SLOT_VALUES = {
    ".env.example": 4,
    "common/runtime/env-reference.generated.md": 4,
    ".github/workflows/deploy.yml": 3,
    ".github/workflows/staging-ai-ocr-gate.yml": 3,
}


def _approved_model_ids() -> frozenset[str]:
    spec = importlib.util.spec_from_file_location("model_policy", POLICY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.APPROVED_MODEL_IDS


def _included(path: Path) -> bool:
    return path.is_file() and not any(
        part in str(path.relative_to(ROOT)) for part in EXCLUDED_PARTS
    )


def _shape_surfaces() -> list[Path]:
    patterns = (
        "apps/backend/src/**/*.py",
        "apps/frontend/src/**/*.ts",
        "apps/frontend/src/**/*.tsx",
        ".github/workflows/*.yml",
        ".github/actions/**/*.yml",
        "**/Dockerfile*",
        "**/*compose*.yml",
        "**/*compose*.yaml",
        "common/**/*.py",
    )
    paths = {
        path for pattern in patterns for path in ROOT.glob(pattern) if _included(path)
    }
    paths.update(
        ROOT / name
        for name in (
            ".env.example",
            "common/runtime/env-reference.generated.md",
            "common/extraction/readme.md",
            "common/runtime/ci-cd.md",
        )
    )
    return sorted(paths)


def _slot_surfaces() -> list[Path]:
    return [
        ROOT / ".env.example",
        ROOT / "common" / "runtime" / "env-reference.generated.md",
        *sorted((ROOT / ".github" / "workflows").glob("*.yml")),
        *sorted(p for p in ROOT.glob("**/*compose*.y*ml") if _included(p)),
        *sorted(p for p in ROOT.glob("**/Dockerfile*") if _included(p)),
    ]


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


def test_AC_llm_approved_models_2_slot_parser_reads_every_assignment_form() -> None:
    """AC-llm.approved-models.2: the parser reads prefixed, YAML, .env, expression and table forms."""
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
        "| `STAGING_E2E_OCR_MODEL` | `glm-5.2` |  |": [("OCR_MODEL", "glm-5.2")],
    }
    for line, expected in cases.items():
        assert _slot_values(line) == expected, (
            f"{line!r} parsed as {_slot_values(line)}"
        )
    unreadable = _slot_values("PRIMARY_MODEL: ${{ format('{0}', 'gpt-4o') }}")
    assert unreadable and unreadable[0][1] not in _approved_model_ids(), (
        f"an unreadable expression must fail closed, parsed as {unreadable}"
    )


def test_AC_llm_approved_models_2_config_surfaces_name_only_approved_models() -> None:
    """AC-llm.approved-models.2: code, config, env example, env reference, model docs and workflows name only approved ids."""
    approved = _approved_model_ids()
    seen = 0
    violations: list[str] = []
    for path in _shape_surfaces():
        assert path.is_file(), f"guarded surface is missing: {path.relative_to(ROOT)}"
        rel = str(path.relative_to(ROOT))
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if (rel, line.strip()) in EXEMPT_LINES:
                continue
            for match in GLM_ID.finditer(line):
                seen += 1
                if match.group(0).lower() not in approved:
                    violations.append(f"{rel}:{line_no}: {match.group(0)}")
    # The scan must read real model ids, so an empty scan cannot pass.
    assert seen >= 10, (
        f"the scan found only {seen} model ids; the surface list is wrong"
    )
    assert violations == [], "model ids outside the approved set:\n" + "\n".join(
        violations
    )


def test_AC_llm_approved_models_2_model_variables_hold_only_approved_values() -> None:
    """AC-llm.approved-models.2: every value of a model variable is an approved id, whatever its vendor."""
    approved = _approved_model_ids()
    counts: dict[str, int] = {}
    violations: list[str] = []
    for path in _slot_surfaces():
        rel = str(path.relative_to(ROOT))
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for variable, model_id in _slot_values(line):
                counts[rel] = counts.get(rel, 0) + 1
                if model_id.lower() not in approved:
                    violations.append(f"{rel}:{line_no}: {variable}={model_id}")
    for rel, minimum in MIN_SLOT_VALUES.items():
        assert counts.get(rel, 0) >= minimum, (
            f"{rel}: the parser read {counts.get(rel, 0)} model values, expected at least {minimum}"
        )
    assert violations == [], (
        "model variables with values outside the approved set:\n"
        + "\n".join(violations)
    )


def test_AC_llm_approved_models_3_staging_gate_blocks_on_the_catalog_check() -> None:
    """AC-llm.approved-models.3: deploy.yml runs the catalog check once, it can fail the job, and the canary waits for it."""
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    node = "tests/e2e/test_ai_provider_connectivity.py::test_deployed_catalog_lists_only_approved_models"
    provider_job = workflow.split("\n  provider-gate:", 1)[1].split(
        "\n  ai-ocr-gate:", 1
    )[0]
    assert node in provider_job, (
        "the catalog check must run in the staging provider-gate job"
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
    ai_ocr_job = workflow.split("\n  ai-ocr-gate:", 1)[1].split(
        "\n  financial-benchmark:", 1
    )[0]
    assert "needs.provider-gate.result == 'success'" in ai_ocr_job, (
        "the AI/OCR canary must not run when the provider-gate job, catalog check included, failed"
    )
    assert (
        "model_catalog_outcome: ${{ steps.model_catalog_policy.outcome }}"
        in provider_job
    ), "the provider gate must export the catalog step outcome"
    delivery_job = workflow.split("\n  post-merge-delivery:", 1)[1]
    read_line = 'model_catalog_outcome="${{ needs.provider-gate.outputs.model_catalog_outcome }}"'
    catalog_branch = '[ "$model_catalog_outcome" = "failure" ]'
    reason = (
        'failure_reason="deployed model catalog lists models outside the approved set"'
    )
    provider_branch = '[ "$provider_result" != "success" ]'
    for text in (read_line, catalog_branch, reason, provider_branch):
        assert text in delivery_job, f"post-merge delivery is missing: {text}"
    assert delivery_job.index(catalog_branch) < delivery_job.index(provider_branch), (
        "the catalog branch must come before the generic provider branch"
    )
