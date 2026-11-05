"""Guard that .pre-commit-config.yaml ruff-format scope matches CI and preflight (#2718, #2671)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from common.testing import preflight

REPO_ROOT = Path(__file__).resolve().parents[2]
PRECOMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), path
    return data


def _find_precommit_hook(config: dict[str, Any], hook_id: str) -> dict[str, Any]:
    for repo in config.get("repos", []):
        if not isinstance(repo, dict):
            continue
        for hook in repo.get("hooks", []):
            if isinstance(hook, dict) and hook.get("id") == hook_id:
                return hook
    raise AssertionError(f"pre-commit hook {hook_id!r} not found")


def _ci_ruff_format_targets(workflow: dict[str, Any]) -> tuple[str, list[str]]:
    lint_steps = workflow["jobs"]["lint"]["steps"]
    for step in lint_steps:
        run_cmd = str(step.get("run", ""))
        if "ruff format" not in run_cmd:
            continue
        cwd = "apps/backend" if "cd apps/backend" in run_cmd else "."
        for line in run_cmd.splitlines():
            tokens = line.strip().split()
            if "ruff" in tokens and "format" in tokens:
                fmt_idx = tokens.index("format")
                targets = [
                    tok for tok in tokens[fmt_idx + 1 :] if not tok.startswith("-")
                ]
                return cwd, targets
    raise AssertionError("CI lint step with 'ruff format' not found")


def test_precommit_ruff_format_files_regex_matches_ci_scope() -> None:
    """AC-testing.toolchain.3: #2718: pre-commit ruff-format files regex matches CI and preflight backend-format scope."""
    precommit = _load_yaml(PRECOMMIT_CONFIG)
    workflow = _load_yaml(CI_WORKFLOW)

    hook = _find_precommit_hook(precommit, "ruff-format")
    files_pattern = hook.get("files")
    assert isinstance(files_pattern, str) and files_pattern, (
        "ruff-format hook must declare a non-empty files: regex"
    )

    ci_cwd, ci_targets = _ci_ruff_format_targets(workflow)
    assert ci_cwd == "apps/backend"
    assert ci_targets == ["src", "tests"]

    expected_pattern = f"^{ci_cwd}/({'|'.join(ci_targets)})/"
    assert files_pattern == expected_pattern

    backend_format = next(c for c in preflight.CHECKS if c.name == "backend-format")
    assert backend_format.cwd == ci_cwd
    assert (
        preflight.PY,
        "-m",
        "ruff",
        "format",
        "--check",
        *ci_targets,
    ) in backend_format.commands

    compiled = re.compile(files_pattern)
    for in_scope in (
        "apps/backend/src/main.py",
        "apps/backend/src/ledger/models.py",
        "apps/backend/tests/unit/test_main.py",
    ):
        assert compiled.search(in_scope), f"expected {in_scope} to match {files_pattern}"

    for out_of_scope in (
        "tools/preflight.py",
        "common/testing/preflight.py",
        "tests/tooling/test_preflight.py",
        "apps/backend/scripts/seed.py",
    ):
        assert not compiled.search(out_of_scope), (
            f"expected {out_of_scope} not to match {files_pattern}"
        )


def test_pdf_fixture_templates_have_no_trailing_whitespace() -> None:
    """AC-testing.5.2: #2718: mari and moomoo PDF templates contain no trailing whitespace."""
    templates_dir = REPO_ROOT / "common" / "testing" / "fixtures" / "pdf" / "templates"
    for name in ("mari_template.yaml", "moomoo_template.yaml"):
        path = templates_dir / name
        assert path.is_file(), f"missing template {path}"
        offending = [
            line_no
            for line_no, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            )
            if line != line.rstrip(" \t")
        ]
        assert offending == [], f"{name} has trailing whitespace on lines {offending}"


def test_ci_frontend_prod_audit_is_scoped_to_dependency_changes_on_prs() -> None:
    """AC-testing.ci-structure.1: #2671: PR lint runs npm run audit:prod only when lockfiles or frontend package.json change."""
    workflow = _load_yaml(CI_WORKFLOW)
    lint_steps = workflow["jobs"]["lint"]["steps"]
    audit_steps = [
        step
        for step in lint_steps
        if isinstance(step, dict) and "npm run audit:prod" in str(step.get("run", ""))
    ]
    assert len(audit_steps) == 1
    run_script = str(audit_steps[0]["run"])
    assert "pull_request" in run_script
    assert "^(apps/frontend/package(-lock)?\\.json|package-lock\\.json)$" in run_script
