#!/usr/bin/env python3
"""Validate that CI/deploy SSOT prose and issue templates match workflows.

This contract is the mechanical guard for issue #531: prose in
``docs/ssot/ci-cd.md``, ``docs/ssot/deployment.md``, and
``docs/ssot/environments.md`` must not drift from the actual
``.github/workflows/*.yml`` job ids and triggers, and issue templates must only
use labels that exist in the repository's label taxonomy.

The contract is intentionally *declarative*: the expected job ids and triggers
for each governed workflow are spelled out in :data:`WORKFLOW_CONTRACT`, then
checked against the parsed YAML. When a workflow's real job id or trigger
changes, this contract fails until both the workflow declaration and the
documented standard are reconciled — so the SSOT references the live contract
instead of stale prose.

It does NOT assert on mutable live-run status (run ids, timing, conclusions);
those belong in CI artifacts, not static docs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Declarative contract: the documented standard for each governed workflow.
# ---------------------------------------------------------------------------

# GitHub Actions normalizes a bare ``on:`` key to the YAML boolean True; read
# triggers from the parsed mapping defensively against both spellings.
ON_KEYS = ("on", True)

# Each governed workflow declares the job ids it MUST expose (so referenced /
# required check names stay stable) and the trigger events it MUST fire on. The
# tuples are required subsets: a workflow may add jobs/triggers, but removing or
# renaming a documented one fails the contract.
WORKFLOW_CONTRACT: dict[str, dict[str, tuple[str, ...]]] = {
    ".github/workflows/ci.yml": {
        # The classifier job id is `changes` (NOT `classify-changes`).
        "jobs": (
            "changes",
            "lint",
            "schema-migrations",
            "backend",
            "frontend",
            "unified-coverage",
            "ac-traceability",
            "finish",
        ),
        "triggers": ("push", "pull_request", "workflow_dispatch"),
    },
    ".github/workflows/staging-deploy.yml": {
        # Staging is manual-only: workflow_dispatch, no `push`.
        "jobs": ("build-and-deploy",),
        "triggers": ("workflow_dispatch",),
    },
    ".github/workflows/production-release.yml": {
        "jobs": ("build",),
        "triggers": ("push", "workflow_dispatch"),
    },
    ".github/workflows/docs.yml": {
        "jobs": ("build",),
        "triggers": ("push", "workflow_dispatch"),
    },
}

# Triggers a workflow must NOT declare. Staging auto-following `main` is the
# specific drift #531 fixes: the staging workflow must stay manual-only.
WORKFLOW_FORBIDDEN_TRIGGERS: dict[str, tuple[str, ...]] = {
    ".github/workflows/staging-deploy.yml": ("push", "pull_request"),
}

# Stale prose that must never reappear in the CI/deploy SSOT, keyed by file.
# Each entry is (forbidden substring, explanation of the correct fact).
SSOT_FORBIDDEN_PROSE: dict[str, tuple[tuple[str, str], ...]] = {
    "docs/ssot/ci-cd.md": (
        (
            "classify-changes",
            "the CI classifier job id is `changes`, not `classify-changes`",
        ),
    ),
    "docs/ssot/deployment.md": (
        (
            "Push to main (apps/** changed)",
            "staging-deploy.yml triggers on workflow_dispatch only, not push",
        ),
    ),
    "docs/ssot/environments.md": (
        (
            "classify-changes",
            "the CI classifier job id is `changes`, not `classify-changes`",
        ),
        (
            "matches GitHub CI exactly",
            "local CI uses scripts/test_lifecycle.py + compose while GitHub CI "
            "uses services + sharded pytest; they share the same gate family, "
            "they are not byte-identical",
        ),
    ),
}

# Prose the CI/deploy SSOT MUST contain so the docs positively reference the
# live job ids / triggers (not just avoid the stale strings).
SSOT_REQUIRED_PROSE: dict[str, tuple[str, ...]] = {
    "docs/ssot/ci-cd.md": (
        "`.github/workflows/ci.yml`",
        "single CI metrics contract",
    ),
    "docs/ssot/deployment.md": (
        "Manual dispatch only",
        "workflow_dispatch",
    ),
    "docs/ssot/environments.md": (
        "same gate family",
        "workflow_dispatch",
    ),
}

# ---------------------------------------------------------------------------
# Issue-template label taxonomy.
# ---------------------------------------------------------------------------

ISSUE_TEMPLATE_DIR = ".github/ISSUE_TEMPLATE"
NON_TEMPLATE_FILES = {"config.yml"}

# Current repository labels (mirror of `gh label list`). The stale `infra` /
# `feature` labels are intentionally absent: templates must use `infrastructure`
# / `enhancement`.
KNOWN_LABELS = frozenset(
    {
        "bug",
        "documentation",
        "duplicate",
        "enhancement",
        "good first issue",
        "help wanted",
        "idea",
        "incident",
        "infrastructure",
        "invalid",
        "investment-performance",
        "meta",
        "ongoing",
        "preview",
        "priority: critical",
        "priority: high",
        "priority: low",
        "priority: medium",
        "question",
        "surface: accounting",
        "surface: ai-ocr",
        "surface: backend",
        "surface: ci",
        "surface: docs",
        "surface: extraction",
        "surface: frontend",
        "surface: infra",
        "surface: portfolio",
        "surface: reconciliation",
        "surface: reporting",
        "surface: testing",
        "surface: tooling",
        "wontfix",
    }
)

# Labels removed from the taxonomy that must never reappear in a template.
STALE_LABELS = frozenset({"infra", "feature"})


def read_text(repo_root: Path, relative_path: str) -> str:
    return (repo_root / relative_path).read_text(encoding="utf-8")


def load_yaml(repo_root: Path, relative_path: str) -> dict:
    with (repo_root / relative_path).open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{relative_path}: expected a YAML mapping")
    return loaded


def workflow_triggers(workflow: dict) -> set[str]:
    """Return the set of trigger event names declared by a workflow `on:`."""
    on_value = None
    for key in ON_KEYS:
        if key in workflow:
            on_value = workflow[key]
            break
    if on_value is None:
        return set()
    if isinstance(on_value, str):
        return {on_value}
    if isinstance(on_value, (list, dict)):
        return {str(item) for item in on_value}
    return set()


def workflow_job_ids(workflow: dict) -> set[str]:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return set()
    return {str(job_id) for job_id in jobs}


def check_workflows(repo_root: Path, errors: list[str]) -> None:
    for path, expected in WORKFLOW_CONTRACT.items():
        try:
            workflow = load_yaml(repo_root, path)
        except (FileNotFoundError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
            continue

        job_ids = workflow_job_ids(workflow)
        for expected_job in expected["jobs"]:
            if expected_job not in job_ids:
                errors.append(
                    f"{path}: documented job id {expected_job!r} is missing "
                    f"from the workflow (found: {sorted(job_ids)})"
                )

        triggers = workflow_triggers(workflow)
        for expected_trigger in expected["triggers"]:
            if expected_trigger not in triggers:
                errors.append(
                    f"{path}: documented trigger {expected_trigger!r} is "
                    f"missing from the workflow (found: {sorted(triggers)})"
                )

        for forbidden_trigger in WORKFLOW_FORBIDDEN_TRIGGERS.get(path, ()):
            if forbidden_trigger in triggers:
                errors.append(
                    f"{path}: trigger {forbidden_trigger!r} is forbidden by "
                    "the documented standard (this workflow must stay "
                    "manual-only)"
                )


def check_ssot_docs(repo_root: Path, errors: list[str]) -> None:
    for path, forbidden in SSOT_FORBIDDEN_PROSE.items():
        content = read_text(repo_root, path)
        for needle, explanation in forbidden:
            if needle in content:
                errors.append(
                    f"{path}: stale prose {needle!r} must not appear ({explanation})"
                )

    for path, required in SSOT_REQUIRED_PROSE.items():
        content = read_text(repo_root, path)
        for needle in required:
            if needle not in content:
                errors.append(
                    f"{path}: required reference {needle!r} is missing; the "
                    "doc must positively reference the live workflow contract"
                )


def check_issue_templates(repo_root: Path, errors: list[str]) -> None:
    template_dir = repo_root / ISSUE_TEMPLATE_DIR
    template_paths = sorted(
        path
        for path in template_dir.glob("*.yml")
        if path.name not in NON_TEMPLATE_FILES
    )
    if not template_paths:
        errors.append(f"{ISSUE_TEMPLATE_DIR}: no issue templates found")
        return

    for template_path in template_paths:
        rel = template_path.relative_to(repo_root)
        with template_path.open(encoding="utf-8") as handle:
            template = yaml.safe_load(handle)
        if not isinstance(template, dict):
            errors.append(f"{rel}: expected a YAML mapping")
            continue
        labels = template.get("labels", [])
        if not isinstance(labels, list):
            errors.append(f"{rel}: `labels` must be a list")
            continue
        label_set = {str(label) for label in labels}

        stale = sorted(label_set & STALE_LABELS)
        if stale:
            errors.append(
                f"{rel}: uses removed/stale labels {stale} — use "
                "`infrastructure`/`enhancement`, not `infra`/`feature`"
            )

        unknown = sorted(label_set - KNOWN_LABELS)
        if unknown:
            errors.append(
                f"{rel}: uses labels not in the repository taxonomy: {unknown}"
            )


def run_contract(repo_root: Path) -> int:
    errors: list[str] = []
    check_workflows(repo_root, errors)
    check_ssot_docs(repo_root, errors)
    check_issue_templates(repo_root, errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Workflow contract OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    args = parser.parse_args(argv)
    return run_contract(args.repo_root)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
