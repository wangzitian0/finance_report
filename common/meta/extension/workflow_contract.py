#!/usr/bin/env python3
"""Validate that CI/deploy SSOT prose and issue templates match workflows.

This contract is the mechanical guard for issue #531: prose in
``common/testing/ci-cd.md``, ``common/runtime/deployment.md``, and
``common/runtime/environments.md`` must not drift from the actual
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
from collections.abc import Sequence
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
    ".github/workflows/audit-replay.yml": {
        # Heavy provider-backed LLM audit journeys, decoupled from the blocking
        # deploy path: nightly schedule + manual dispatch, record-only
        # (issue #1232 / AC8.13.157).
        "jobs": ("resolve-target", "audit-replay"),
        "triggers": ("schedule", "workflow_dispatch"),
    },
    ".github/workflows/ci.yml": {
        # The classifier job id is `changes` (NOT `classify-changes`).
        "jobs": (
            "changes",
            "lint",
            "schema-migrations",
            "backend",
            "frontend-build",
            "frontend-vitest",
            "frontend-playwright",
            "frontend-telemetry-e2e",
            "unified-coverage",
            "ac-traceability",
            "finish",
        ),
        "triggers": ("push", "pull_request", "workflow_dispatch"),
    },
    ".github/workflows/deploy.yml": {
        # Staging is a manual-only job; tag-push image promotion shares the
        # deploy workflow but is gated to release tags. Production release moved
        # to release.yml (#1354 / AC8.13.154).
        "jobs": ("build-and-deploy", "promote"),
        "triggers": ("push", "workflow_dispatch"),
    },
    ".github/workflows/release.yml": {
        # Production release line, split out of deploy.yml: manual-dispatch only,
        # dry-run + deploy gated on the `dry_run` input.
        "jobs": ("dry-run", "deploy"),
        "triggers": ("workflow_dispatch",),
    },
    ".github/workflows/staging-ai-ocr-gate.yml": {
        # Reusable workflow that owns the staging AI/OCR corpus gate; both the
        # inline and manual deploy.yml entrances call it (AC8.13.153).
        "jobs": ("run",),
        "triggers": ("workflow_call",),
    },
    ".github/workflows/docs.yml": {
        "jobs": ("build",),
        "triggers": ("push", "workflow_dispatch"),
    },
}

APP_WORKFLOW_FILES = (
    ".github/workflows/audit-replay.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/deploy.yml",
    ".github/workflows/docs.yml",
    ".github/workflows/maintenance.yml",
    ".github/workflows/notify-infra2.yml",
    ".github/workflows/preview.yml",
    ".github/workflows/release.yml",
    ".github/workflows/staging-ai-ocr-gate.yml",
)

# Triggers a workflow must NOT declare. Staging auto-following `main` is the
# specific drift #531 fixes: the staging workflow must stay manual-only.
WORKFLOW_FORBIDDEN_TRIGGERS: dict[str, tuple[str, ...]] = {}
WORKFLOW_FORBIDDEN_PUSH_BRANCHES: dict[str, tuple[str, ...]] = {
    ".github/workflows/deploy.yml": ("main",),
    # release.yml is manual-dispatch only; a branch push must never deploy prod.
    ".github/workflows/release.yml": ("main",),
}

ACTION_RUNTIME_INVENTORY = "common/testing/data/github-action-runtime.yaml"
ACTION_RUNTIME_STATUSES = {"node24_native", "forced_node20_metadata"}
ACTION_RUNTIME_METADATA_GLOBS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".github/actions/**/*.yml",
    ".github/actions/**/*.yaml",
)

# Stale prose that must never reappear in the CI/deploy SSOT, keyed by file.
# Each entry is (forbidden substring, explanation of the correct fact).
SSOT_FORBIDDEN_PROSE: dict[str, tuple[tuple[str, str], ...]] = {
    "common/testing/ci-cd.md": (
        (
            "classify-changes",
            "the CI classifier job id is `changes`, not `classify-changes`",
        ),
        (
            "Shards 1-8",
            "the backend fast path uses 5 seeded shards, not 8 shards",
        ),
    ),
    "common/runtime/deployment.md": (
        (
            "Push to main (apps/** changed)",
            "deploy.yml triggers on workflow_dispatch only, not push",
        ),
    ),
    "common/runtime/environments.md": (
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
    "common/testing/ci-cd.md": (
        "`.github/workflows/ci.yml`",
        "single CI metrics contract",
    ),
    "common/runtime/deployment.md": (
        "Manual dispatch only",
        "workflow_dispatch",
    ),
    "common/runtime/environments.md": (
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
    try:
        with (repo_root / relative_path).open(encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ValueError(f"{relative_path}: invalid YAML ({exc})") from exc
    if not isinstance(loaded, dict):
        raise ValueError(f"{relative_path}: expected a YAML mapping")
    return loaded


def workflow_triggers(workflow: dict) -> set[str]:
    """Return the set of trigger event names declared by a workflow `on:`."""
    on_value = workflow_on_value(workflow)
    if on_value is None:
        return set()
    if isinstance(on_value, str):
        return {on_value}
    if isinstance(on_value, (list, dict)):
        return {str(item) for item in on_value}
    return set()


def workflow_on_value(workflow: dict) -> object | None:
    """Return the raw workflow `on:` value, handling PyYAML's boolean key."""
    on_value = None
    for key in ON_KEYS:
        if key in workflow:
            on_value = workflow[key]
            break
    return on_value


def workflow_push_branches(workflow: dict) -> set[str]:
    on_value = workflow_on_value(workflow)
    if not isinstance(on_value, dict):
        return set()
    push = on_value.get("push")
    if not isinstance(push, dict):
        return set()
    branches = push.get("branches")
    if isinstance(branches, str):
        return {branches}
    if isinstance(branches, list):
        return {str(branch) for branch in branches}
    return set()


def workflow_job_ids(workflow: dict) -> set[str]:
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return set()
    return {str(job_id) for job_id in jobs}


def workflow_file_set(repo_root: Path, relative_dir: str) -> set[str]:
    workflow_dir = repo_root / relative_dir
    if not workflow_dir.exists():
        return set()
    return {
        f".github/workflows/{path.name}" for path in sorted(workflow_dir.glob("*.yml"))
    } | {
        f".github/workflows/{path.name}" for path in sorted(workflow_dir.glob("*.yaml"))
    }


def workflow_set_display(paths: set[str], *, prefix: str = "") -> list[str]:
    return sorted(f"{prefix}{path}" for path in paths)


def iter_action_uses(value: object) -> set[str]:
    """Collect external `uses:` action references from workflow-like YAML."""
    found: set[str] = set()
    if isinstance(value, dict):
        uses = value.get("uses")
        if isinstance(uses, str) and not uses.startswith(("./", "docker://")):
            found.add(uses)
        for nested in value.values():
            found.update(iter_action_uses(nested))
    elif isinstance(value, list):
        for nested in value:
            found.update(iter_action_uses(nested))
    return found


def workflow_action_uses(repo_root: Path) -> set[str]:
    uses: set[str] = set()
    for pattern in ACTION_RUNTIME_METADATA_GLOBS:
        for path in sorted(repo_root.glob(pattern)):
            try:
                data = load_yaml(repo_root, str(path.relative_to(repo_root)))
            except ValueError:
                # YAML validity is checked elsewhere in the same contract path;
                # avoid duplicate parse noise here.
                continue
            uses.update(iter_action_uses(data))
    return uses


def check_workflows(repo_root: Path, errors: list[str]) -> None:
    app_workflows = workflow_file_set(repo_root, ".github/workflows")
    expected_app_workflows = set(APP_WORKFLOW_FILES)
    if app_workflows != expected_app_workflows:
        errors.append(
            ".github/workflows: consolidated app workflow set drifted "
            f"(expected: {workflow_set_display(expected_app_workflows)}, "
            f"found: {workflow_set_display(app_workflows)})"
        )

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

        push_branches = workflow_push_branches(workflow)
        for forbidden_branch in WORKFLOW_FORBIDDEN_PUSH_BRANCHES.get(path, ()):
            if forbidden_branch in push_branches:
                errors.append(
                    f"{path}: push branch {forbidden_branch!r} is forbidden; "
                    "deploy.yml may only use push for release tag promotion"
                )


def check_ssot_docs(repo_root: Path, errors: list[str]) -> None:
    for path, forbidden in SSOT_FORBIDDEN_PROSE.items():
        try:
            content = read_text(repo_root, path)
        except OSError as exc:
            errors.append(f"{path}: governed SSOT doc could not be read ({exc})")
            continue
        for needle, explanation in forbidden:
            if needle in content:
                errors.append(
                    f"{path}: stale prose {needle!r} must not appear ({explanation})"
                )

    for path, required in SSOT_REQUIRED_PROSE.items():
        try:
            content = read_text(repo_root, path)
        except OSError as exc:
            errors.append(f"{path}: governed SSOT doc could not be read ({exc})")
            continue
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
        try:
            with template_path.open(encoding="utf-8") as handle:
                template = yaml.safe_load(handle)
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{rel}: issue template could not be parsed ({exc})")
            continue
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


def required_string(
    mapping: dict,
    key: str,
    *,
    context: str,
    errors: list[str],
) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{ACTION_RUNTIME_INVENTORY}: {context} missing `{key}`")
        return ""
    return value.strip()


def check_action_runtime_inventory(repo_root: Path, errors: list[str]) -> None:
    try:
        inventory = load_yaml(repo_root, ACTION_RUNTIME_INVENTORY)
    except ValueError as exc:
        errors.append(str(exc))
        return

    actions = inventory.get("actions")
    exceptions = inventory.get("exceptions", [])
    if not isinstance(actions, list) or not actions:
        errors.append(f"{ACTION_RUNTIME_INVENTORY}: `actions` must be a non-empty list")
        return
    if not isinstance(exceptions, list):
        errors.append(f"{ACTION_RUNTIME_INVENTORY}: `exceptions` must be a list")
        return

    used_actions = workflow_action_uses(repo_root)
    inventoried: dict[str, dict] = {}
    for entry in actions:
        if not isinstance(entry, dict):
            errors.append(f"{ACTION_RUNTIME_INVENTORY}: action entries must be maps")
            continue
        uses = required_string(
            entry,
            "uses",
            context="action entry",
            errors=errors,
        )
        status = required_string(
            entry,
            "runtime_status",
            context=f"action {uses!r}",
            errors=errors,
        )
        if not uses:
            continue
        if uses in inventoried:
            errors.append(f"{ACTION_RUNTIME_INVENTORY}: duplicate action {uses!r}")
        inventoried[uses] = {**entry, "runtime_status": status}
        if status not in ACTION_RUNTIME_STATUSES:
            errors.append(
                f"{ACTION_RUNTIME_INVENTORY}: {uses} has invalid "
                f"runtime_status {status!r}"
            )
        required_string(entry, "owner", context=f"action {uses!r}", errors=errors)

    missing = sorted(used_actions - set(inventoried))
    if missing:
        errors.append(
            f"{ACTION_RUNTIME_INVENTORY}: workflow action(s) missing from "
            f"runtime inventory: {missing}"
        )
    stale = sorted(set(inventoried) - used_actions)
    if stale:
        errors.append(
            f"{ACTION_RUNTIME_INVENTORY}: runtime inventory action(s) are not "
            f"used by workflows/composite actions: {stale}"
        )

    exception_actions: dict[str, dict] = {}
    for exception in exceptions:
        if not isinstance(exception, dict):
            errors.append(f"{ACTION_RUNTIME_INVENTORY}: exception entries must be maps")
            continue
        uses = required_string(
            exception,
            "uses",
            context="exception entry",
            errors=errors,
        )
        if not uses:
            continue
        if uses in exception_actions:
            errors.append(f"{ACTION_RUNTIME_INVENTORY}: duplicate exception {uses!r}")
        exception_actions[uses] = exception
        for key in ("owner", "reason", "review_after"):
            required_string(
                exception, key, context=f"exception {uses!r}", errors=errors
            )

    forced_actions = {
        uses
        for uses, entry in inventoried.items()
        if entry.get("runtime_status") == "forced_node20_metadata"
    }
    expected_forced_count = inventory.get("forced_node20_metadata_count_must_be")
    if not isinstance(expected_forced_count, int):
        errors.append(
            f"{ACTION_RUNTIME_INVENTORY}: "
            "forced_node20_metadata_count_must_be must be an integer"
        )
    elif expected_forced_count != len(forced_actions):
        errors.append(
            f"{ACTION_RUNTIME_INVENTORY}: "
            "forced_node20_metadata_count_must_be must match runtime inventory "
            f"(expected={expected_forced_count}, actual={len(forced_actions)})"
        )

    if forced_actions != set(exception_actions):
        errors.append(
            f"{ACTION_RUNTIME_INVENTORY}: forced Node20 metadata actions must "
            "match exceptions exactly "
            f"(forced={sorted(forced_actions)}, exceptions={sorted(exception_actions)})"
        )

    workflow_paths = sorted(
        (repo_root / ".github" / "workflows").glob("*.yml")
    ) + sorted((repo_root / ".github" / "workflows").glob("*.yaml"))
    if forced_actions:
        for workflow_path in workflow_paths:
            workflow_text = workflow_path.read_text(encoding="utf-8")
            if 'FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"' not in workflow_text:
                rel = workflow_path.relative_to(repo_root)
                errors.append(
                    f"{rel}: forced Node20 metadata exceptions exist, so the "
                    "workflow must keep FORCE_JAVASCRIPT_ACTIONS_TO_NODE24 enabled"
                )
    else:
        for workflow_path in workflow_paths:
            workflow_text = workflow_path.read_text(encoding="utf-8")
            if "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" in workflow_text:
                rel = workflow_path.relative_to(repo_root)
                errors.append(
                    f"{rel}: no forced Node20 metadata exceptions remain, so "
                    "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24 must be removed"
                )


def run_contract(repo_root: Path) -> int:
    errors: list[str] = []
    check_workflows(repo_root, errors)
    check_ssot_docs(repo_root, errors)
    check_issue_templates(repo_root, errors)
    check_action_runtime_inventory(repo_root, errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Workflow contract OK")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=Path(__file__).resolve().parents[3]
    )
    args = parser.parse_args(argv)
    return run_contract(args.repo_root)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
