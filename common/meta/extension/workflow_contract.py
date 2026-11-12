#!/usr/bin/env python3
"""Validate that CI/deploy SSOT prose and issue templates match workflows."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

ON_KEYS = ("on", True)

WORKFLOW_CONTRACT: dict[str, dict[str, tuple[str, ...]]] = {
    ".github/workflows/ci.yml": {
        "jobs": (
            "changes",
            "lint",
            "schema-migrations",
            "backend",
            "frontend-build",
            "frontend-vitest",
            "frontend-playwright",
            "frontend-telemetry-e2e",
            "finish",
        ),
        "triggers": ("push", "pull_request", "workflow_dispatch"),
    },
    ".github/workflows/docs.yml": {
        "jobs": ("build",),
        "triggers": ("push", "workflow_dispatch"),
    },
}

APP_WORKFLOW_FILES = (
    ".github/workflows/ci.yml",
    ".github/workflows/docs.yml",
)

WORKFLOW_FORBIDDEN_TRIGGERS: dict[str, tuple[str, ...]] = {}
WORKFLOW_FORBIDDEN_PUSH_BRANCHES: dict[str, tuple[str, ...]] = {}

MAIN_ONLY_JOBS: dict[str, dict[str, Any]] = {
    "verify-sha-image-published": {
        "pr_rehearsal": (
            "python",
            "tools/verify_release_images.py",
            "--registry",
            "ghcr.io",
            "--image-prefix",
            "wangzitian0/finance-report",
            "--version-ref",
            "0000000",
            "--dry-run",
        ),
        "failure_isolation": False,
        "isolation_reason": (
            "Commit image verification on main is a blocking release requirement"
        ),
    },
}

ACTION_RUNTIME_INVENTORY = "common/testing/data/github-action-runtime.yaml"
ACTION_RUNTIME_STATUSES = {"node24_native", "forced_node20_metadata"}
ACTION_RUNTIME_METADATA_GLOBS = (
    ".github/workflows/*.yml",
    ".github/workflows/*.yaml",
    ".github/actions/**/*.yml",
    ".github/actions/**/*.yaml",
)

_SHARD_MSG = (
    "the shard count is set only by the `backend` job matrix in ci.yml "
    "(#2688), not by a range/number in ci-cd.md"
)
_CLASSIFIER_MSG = "the CI classifier job id is `changes`, not `classify-changes`"

SSOT_FORBIDDEN_PROSE: dict[str, tuple[tuple[str, str], ...]] = {
    "common/testing/ci-cd.md": (
        ("classify-changes", _CLASSIFIER_MSG),
        ("Shards 1-8", _SHARD_MSG),
        ("4 seeded file-level shards", _SHARD_MSG),
        ("Shards 1-5", _SHARD_MSG),
    ),
    "common/runtime/deployment.md": (
        (
            "Push to main (apps/** changed)",
            "deploy.yml triggers on workflow_dispatch only, not push",
        ),
    ),
    "common/runtime/environments.md": (
        ("classify-changes", _CLASSIFIER_MSG),
        (
            "matches GitHub CI exactly",
            "local CI uses scripts/test_lifecycle.py + compose while GitHub CI "
            "uses services + sharded pytest; they share the same gate family, "
            "they are not byte-identical",
        ),
    ),
}

SSOT_REQUIRED_PROSE: dict[str, tuple[str, ...]] = {
    "common/testing/ci-cd.md": (
        "`.github/workflows/ci.yml`",
        "single CI metrics contract",
    ),
    "common/runtime/deployment.md": ("Manual dispatch only", "workflow_dispatch"),
    "common/runtime/environments.md": ("same gate family", "workflow_dispatch"),
}

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


def workflow_on_value(workflow: dict) -> object | None:
    for key in ON_KEYS:
        if key in workflow:
            return workflow[key]
    return None


def workflow_triggers(workflow: dict) -> set[str]:
    on_value = workflow_on_value(workflow)
    if isinstance(on_value, str):
        return {on_value}
    if isinstance(on_value, (list, dict)):
        return {str(item) for item in on_value}
    return set()


def workflow_push_branches(workflow: dict) -> set[str]:
    on_value = workflow_on_value(workflow)
    push = on_value.get("push") if isinstance(on_value, dict) else None
    branches = push.get("branches") if isinstance(push, dict) else None
    if isinstance(branches, str):
        return {branches}
    if isinstance(branches, list):
        return {str(branch) for branch in branches}
    return set()


def workflow_job_ids(workflow: dict) -> set[str]:
    jobs = workflow.get("jobs")
    return {str(job_id) for job_id in jobs} if isinstance(jobs, dict) else set()


def workflow_file_set(repo_root: Path, relative_dir: str) -> set[str]:
    workflow_dir = repo_root / relative_dir
    if not workflow_dir.exists():
        return set()
    return {
        f".github/workflows/{path.name}"
        for ext in ("*.yml", "*.yaml")
        for path in sorted(workflow_dir.glob(ext))
    }


def workflow_set_display(paths: set[str], *, prefix: str = "") -> list[str]:
    return sorted(f"{prefix}{path}" for path in paths)


def iter_action_uses(value: object) -> set[str]:
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
        errors.extend(
            f"{path}: documented job id {job!r} is missing from the workflow (found: {sorted(job_ids)})"
            for job in expected["jobs"]
            if job not in job_ids
        )

        triggers = workflow_triggers(workflow)
        errors.extend(
            f"{path}: documented trigger {trig!r} is missing from the workflow (found: {sorted(triggers)})"
            for trig in expected["triggers"]
            if trig not in triggers
        )
        errors.extend(
            f"{path}: trigger {trig!r} is forbidden by the documented standard (this workflow must stay manual-only)"
            for trig in WORKFLOW_FORBIDDEN_TRIGGERS.get(path, ())
            if trig in triggers
        )
        push_branches = workflow_push_branches(workflow)
        errors.extend(
            f"{path}: push branch {branch!r} is forbidden; deploy.yml may only use push for release tag promotion"
            for branch in WORKFLOW_FORBIDDEN_PUSH_BRANCHES.get(path, ())
            if branch in push_branches
        )


def find_main_only_jobs(workflow: dict[str, Any]) -> set[str]:
    jobs = workflow.get("jobs", {})
    if not isinstance(jobs, dict):
        return set()
    main_only: set[str] = set()
    for job_id, job in jobs.items():
        if_expr = job.get("if") if isinstance(job, dict) else None
        if not isinstance(if_expr, str) or "refs/heads/main" not in if_expr:
            continue
        if "||" in if_expr and any(
            t in if_expr
            for t in ("frontend_changed", "image_build_required", "pull_request")
        ):
            continue
        main_only.add(str(job_id))
    return main_only


def check_main_only_jobs(repo_root: Path, errors: list[str]) -> None:
    ci_path = ".github/workflows/ci.yml"
    try:
        workflow = load_yaml(repo_root, ci_path)
    except (FileNotFoundError, ValueError) as exc:
        errors.append(f"{ci_path}: {exc}")
        return

    jobs = workflow.get("jobs", {})
    detected = find_main_only_jobs(workflow)
    declared = set(MAIN_ONLY_JOBS.keys())

    missing = sorted(detected - declared)
    if missing:
        errors.append(
            f"{ci_path}: main-only job(s) {missing} must declare pr_rehearsal "
            "or failure_isolation in MAIN_ONLY_JOBS (#1811)."
        )
    stale = sorted(declared - set(jobs.keys()))
    if stale:
        errors.append(
            f"{ci_path}: declared main-only job(s) {stale} not found in ci.yml."
        )

    finish_needs = set(jobs.get("finish", {}).get("needs", []))
    for job_id, spec in MAIN_ONLY_JOBS.items():
        if job_id not in jobs:
            continue
        rehearsal, isolation = spec.get("pr_rehearsal"), spec.get("failure_isolation")
        if not rehearsal and not isolation:
            errors.append(
                f"{ci_path}: {job_id} must declare at least one of pr_rehearsal or failure_isolation."
            )
        if isolation:
            if job_id in finish_needs:
                errors.append(
                    f"{ci_path}: {job_id} declares failure_isolation=True but is a blocking "
                    "dependency of the 'finish' job."
                )
            if not any(
                isinstance(step, dict)
                and step.get("continue-on-error") is True
                and "run" in step
                for step in jobs[job_id].get("steps", [])
            ):
                errors.append(
                    f"{ci_path}: {job_id} declares failure_isolation=True but has no run step "
                    "with continue-on-error: true."
                )


def check_ssot_docs(repo_root: Path, errors: list[str]) -> None:
    all_paths = dict.fromkeys((*SSOT_FORBIDDEN_PROSE, *SSOT_REQUIRED_PROSE))
    contents: dict[str, str] = {}
    for path in all_paths:
        try:
            contents[path] = read_text(repo_root, path)
        except OSError as exc:
            errors.append(f"{path}: governed SSOT doc could not be read ({exc})")
    for path, forbidden in SSOT_FORBIDDEN_PROSE.items():
        if path in contents:
            errors.extend(
                f"{path}: stale prose {needle!r} must not appear ({explanation})"
                for needle, explanation in forbidden
                if needle in contents[path]
            )
    for path, required in SSOT_REQUIRED_PROSE.items():
        if path in contents:
            errors.extend(
                f"{path}: required reference {needle!r} is missing; the "
                "doc must positively reference the live workflow contract"
                for needle in required
                if needle not in contents[path]
            )


def required_string(mapping: dict, key: str, *, context: str, errors: list[str]) -> str:
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
        uses = required_string(entry, "uses", context="action entry", errors=errors)
        status = required_string(
            entry, "runtime_status", context=f"action {uses!r}", errors=errors
        )
        if not uses:
            continue
        if uses in inventoried:
            errors.append(f"{ACTION_RUNTIME_INVENTORY}: duplicate action {uses!r}")
        inventoried[uses] = {**entry, "runtime_status": status}
        if status not in ACTION_RUNTIME_STATUSES:
            errors.append(
                f"{ACTION_RUNTIME_INVENTORY}: {uses} has invalid runtime_status {status!r}"
            )
        required_string(entry, "owner", context=f"action {uses!r}", errors=errors)

    missing = sorted(used_actions - set(inventoried))
    if missing:
        errors.append(
            f"{ACTION_RUNTIME_INVENTORY}: workflow action(s) missing from runtime inventory: {missing}"
        )
    stale = sorted(set(inventoried) - used_actions)
    if stale:
        errors.append(
            f"{ACTION_RUNTIME_INVENTORY}: runtime inventory action(s) are not used by workflows/composite actions: {stale}"
        )

    exception_actions: dict[str, dict] = {}
    for exception in exceptions:
        if not isinstance(exception, dict):
            errors.append(f"{ACTION_RUNTIME_INVENTORY}: exception entries must be maps")
            continue
        uses = required_string(
            exception, "uses", context="exception entry", errors=errors
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
            f"{ACTION_RUNTIME_INVENTORY}: forced_node20_metadata_count_must_be must be an integer"
        )
    elif expected_forced_count != len(forced_actions):
        errors.append(
            f"{ACTION_RUNTIME_INVENTORY}: forced_node20_metadata_count_must_be must match runtime inventory "
            f"(expected={expected_forced_count}, actual={len(forced_actions)})"
        )

    if forced_actions != set(exception_actions):
        errors.append(
            f"{ACTION_RUNTIME_INVENTORY}: forced Node20 metadata actions must match exceptions exactly "
            f"(forced={sorted(forced_actions)}, exceptions={sorted(exception_actions)})"
        )

    workflow_paths = [
        p
        for ext in ("*.yml", "*.yaml")
        for p in sorted((repo_root / ".github" / "workflows").glob(ext))
    ]
    for workflow_path in workflow_paths:
        workflow_text = workflow_path.read_text(encoding="utf-8")
        rel = workflow_path.relative_to(repo_root)
        if (
            forced_actions
            and 'FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"' not in workflow_text
        ):
            errors.append(
                f"{rel}: forced Node20 metadata exceptions exist, so the "
                "workflow must keep FORCE_JAVASCRIPT_ACTIONS_TO_NODE24 enabled"
            )
        elif (
            not forced_actions and "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" in workflow_text
        ):
            errors.append(
                f"{rel}: no forced Node20 metadata exceptions remain, so "
                "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24 must be removed"
            )


def run_contract(repo_root: Path) -> int:
    errors: list[str] = []
    for check in (
        check_workflows,
        check_main_only_jobs,
        check_ssot_docs,
        check_action_runtime_inventory,
    ):
        check(repo_root, errors)
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
