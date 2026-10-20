"""Runtime config surfaces name only approved model ids (#2566).

A refactor once moved the fallback defaults back to old models and pinned them
in a test. This guard reads every surface that configures or documents a
deployed model and fails on any GLM model id outside the approved set.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "apps" / "backend" / "src" / "llm" / "model_policy.py"
MODEL_ID = re.compile(r"\bglm-[0-9][a-z0-9.\-]*[a-z0-9]", re.IGNORECASE)


def _approved_model_ids() -> frozenset[str]:
    spec = importlib.util.spec_from_file_location("model_policy", POLICY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.APPROVED_MODEL_IDS


def _surfaces() -> list[Path]:
    paths = [
        ROOT / "apps" / "backend" / "src" / "config.py",
        ROOT / ".env.example",
        ROOT / "common" / "runtime" / "env-reference.generated.md",
        ROOT / "common" / "extraction" / "readme.md",
        ROOT / "common" / "runtime" / "ci-cd.md",
    ]
    paths.extend(sorted((ROOT / ".github" / "workflows").glob("*.yml")))
    return paths


def test_AC_llm_approved_models_2_config_surfaces_name_only_approved_models() -> None:
    """AC-llm.approved-models.2: config, env example, env reference, model docs and workflows name only approved ids."""
    approved = _approved_model_ids()
    seen = 0
    violations: list[str] = []
    for path in _surfaces():
        assert path.is_file(), f"guarded surface is missing: {path.relative_to(ROOT)}"
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            for match in MODEL_ID.finditer(line):
                seen += 1
                if match.group(0).lower() not in approved:
                    violations.append(
                        f"{path.relative_to(ROOT)}:{line_no}: {match.group(0)}"
                    )
    # The scan must read real model ids, so an empty scan cannot pass.
    assert seen >= 10, (
        f"the scan found only {seen} model ids; the surface list is wrong"
    )
    assert violations == [], "model ids outside the approved set:\n" + "\n".join(
        violations
    )
