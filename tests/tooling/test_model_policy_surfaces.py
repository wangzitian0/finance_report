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
MODEL_VARS = (
    "PRIMARY_MODEL",
    "VISION_MODEL",
    "OCR_MODEL",
    "FALLBACK_MODELS",
    "VISION_FALLBACK_MODELS",
)
_VARS = "|".join(MODEL_VARS)
# `KEY=value` (.env), `KEY: value` (YAML) and `| `KEY` | … | `value` |` (env reference table).
ASSIGNMENT = re.compile(rf"\b({_VARS})\b\s*[:=]\s*[\"']?([^\"'\s#]*)")
REFERENCE_ROW = re.compile(rf"^\|\s*`({_VARS})`\s*\|[^|]*\|\s*`([^`]*)`")
# A wire-adapter matcher that recognises GLM 5.3 names; it is never a call target.
EXEMPT_LINES = {("apps/backend/src/llm/extension/client.py", '"glm-5.3",')}
# The manual cassette recorder calls the z.ai coding plan with thinking disabled,
# which the glm-5.3 models reject; it records fixtures offline and is no app model
# slot. Its migration needs a live check with the provider key (#2566 follow-up).
EXCLUDED_PARTS = (
    "node_modules",
    "__tests__",
    ".test.",
    "/tests/",
    "llm_cassettes",
    "common/extraction/record_hf_cassettes.py",
)


def _approved_model_ids() -> frozenset[str]:
    spec = importlib.util.spec_from_file_location("model_policy", POLICY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.APPROVED_MODEL_IDS


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
        path
        for pattern in patterns
        for path in ROOT.glob(pattern)
        if path.is_file()
        and not any(part in str(path.relative_to(ROOT)) for part in EXCLUDED_PARTS)
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
        *sorted(
            p for p in ROOT.glob("**/*compose*.y*ml") if "node_modules" not in str(p)
        ),
    ]


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
    assignments = 0
    violations: list[str] = []
    for path in _slot_surfaces():
        rel = str(path.relative_to(ROOT))
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for pattern in (REFERENCE_ROW, ASSIGNMENT):
                match = pattern.search(line)
                if match is None:
                    continue
                assignments += 1
                value = match.group(2)
                if value.startswith("$"):  # a workflow expression, resolved at run time
                    break
                for model_id in filter(
                    None, (item.strip() for item in value.split(","))
                ):
                    if model_id.lower() not in approved:
                        violations.append(
                            f"{rel}:{line_no}: {match.group(1)}={model_id}"
                        )
                break
    assert assignments >= 5, (
        f"only {assignments} model variable assignments found; the parser is wrong"
    )
    assert violations == [], (
        "model variables with values outside the approved set:\n"
        + "\n".join(violations)
    )


def test_AC_llm_approved_models_3_staging_gate_blocks_on_the_catalog_check() -> None:
    """AC-llm.approved-models.3: deploy.yml runs the catalog check once, outside the retry loop, and it can fail the job."""
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
        f"expected one deploy.yml step that runs {node}, found {len(catalog_steps)}"
    )
    step = catalog_steps[0]
    assert "for n in" not in step, (
        "the catalog check must not run inside the provider retry loop"
    )
    assert "continue-on-error" not in step, (
        "the catalog check must be able to fail the job"
    )
    assert "set -euo pipefail" in step, (
        "the catalog step must stop on the first failure"
    )
