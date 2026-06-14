"""Contract test for the content-level secret-scan gate (AC8.13.132).

Filename-based `.gitignore` only stops *tracked* credential files; it does not
stop a `git add -f .env` or a pasted key. This gate adds a content-level scan
(gitleaks) and pins it to BOTH the pre-commit hooks and the CI `lint` job so the
same check runs locally and in CI (local==CI parity).
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_AC8_13_132_gitleaks_runs_in_precommit_and_ci() -> None:
    """gitleaks is wired into both pre-commit and the CI lint job."""
    # 1. pre-commit: a gitleaks repo with the gitleaks hook id.
    precommit = yaml.safe_load(_read(".pre-commit-config.yaml"))
    repos = precommit.get("repos", [])
    gitleaks_repos = [
        r for r in repos if "gitleaks" in str(r.get("repo", "")).lower()
    ]
    assert gitleaks_repos, "no gitleaks repo in .pre-commit-config.yaml"
    hook_ids = {
        h.get("id") for repo in gitleaks_repos for h in repo.get("hooks", [])
    }
    assert "gitleaks" in hook_ids, "gitleaks hook id missing from pre-commit"

    # 2. CI: the lint job runs a gitleaks-backed secret scan step.
    workflow = yaml.safe_load(_read(".github/workflows/ci.yml"))
    lint_steps = workflow["jobs"]["lint"]["steps"]
    scan_steps = [
        s
        for s in lint_steps
        if "gitleaks" in str(s.get("run", "")).lower()
        or "gitleaks" in str(s.get("name", "")).lower()
    ]
    assert scan_steps, "no gitleaks secret-scan step in CI lint job"
    # The CI step must actually fail the build on a finding, not just warn.
    run_text = " ".join(str(s.get("run", "")) for s in scan_steps)
    assert "--exit-code 1" in run_text, "CI gitleaks step does not fail on findings"
