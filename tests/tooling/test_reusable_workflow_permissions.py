"""AC-runtime.reusable-permissions.1: a job that calls a reusable workflow grants the permissions that the called jobs request (#2516).

#2494 added the job `financial-benchmark` to `deploy.yml`. It calls `benchmark.yml`. The called job requests
`contents: write`, `pages: write` and `id-token: write`. The calling job had no `permissions:` block, so it held the
repository default (read). GitHub rejects such a workflow at startup, for every trigger. The tag push of `v0.2.7`
ended with `startup_failure` and no job. `actionlint` does not compare the permissions of a caller and a callee.
Pull request CI does not start `deploy.yml`. This test compares them for every local reusable workflow call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
LEVELS = {"none": 0, "read": 1, "write": 2}
# The token of a job without `permissions:` holds the repository default. Settings > Actions > General >
# Workflow permissions is "Read repository contents and packages permissions" (checked 2026-10-19 with
# `gh api repos/wangzitian0/finance_report/actions/permissions/workflow`).
REPOSITORY_DEFAULT = {"contents": "read", "packages": "read"}
ALL_SCOPES = "*"


def _permissions(raw: object) -> dict[str, int] | None:
    """The permissions of a `permissions:` key as scope -> level, or None when the key is absent."""
    if raw is None:
        return None
    if raw == "read-all":
        return {ALL_SCOPES: LEVELS["read"]}
    if raw == "write-all":
        return {ALL_SCOPES: LEVELS["write"]}
    assert isinstance(raw, dict), f"unsupported permissions value: {raw!r}"
    return {scope: LEVELS[str(level)] for scope, level in raw.items()}


def _level(granted: dict[str, int], scope: str) -> int:
    return granted.get(scope, granted.get(ALL_SCOPES, 0))


def _name(level: int) -> str:
    return next(name for name, value in LEVELS.items() if value == level)


def _local_calls(path: Path) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Each job of a workflow that calls a reusable workflow of this repository: (job id, job, workflow)."""
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        (job_id, job, workflow)
        for job_id, job in (workflow.get("jobs") or {}).items()
        if str(job.get("uses", "")).startswith("./.github/workflows/")
    ]


def _violations() -> list[str]:
    """Each called job that requests more than its calling job grants."""
    found: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for job_id, job, workflow in _local_calls(path):
            if "permissions" in job:
                granted = _permissions(job["permissions"]) or {}
            elif "permissions" in workflow:
                granted = _permissions(workflow["permissions"]) or {}
            else:
                granted = _permissions(REPOSITORY_DEFAULT) or {}
            callee_path = WORKFLOWS / Path(job["uses"]).name
            callee = yaml.safe_load(callee_path.read_text(encoding="utf-8"))
            for callee_job_id, callee_job in (callee.get("jobs") or {}).items():
                requested = _permissions(
                    callee_job["permissions"]
                    if "permissions" in callee_job
                    else callee.get("permissions")
                )
                for scope, level in (requested or {}).items():
                    if level > _level(granted, scope):
                        found.append(
                            f"{path.name}:{job_id} -> {callee_path.name}:{callee_job_id} requests "
                            f"{scope}: {_name(level)} and holds {scope}: {_name(_level(granted, scope))}"
                        )
    return found


def test_AC_runtime_reusable_permissions_1_the_scan_finds_the_reusable_calls() -> None:
    calls = {
        (path.name, job_id)
        for path in WORKFLOWS.glob("*.yml")
        for job_id, _, _ in _local_calls(path)
    }

    # A scan that finds no call would pass the next test without a check.
    assert {
        ("deploy.yml", "ai-ocr-gate"),
        ("deploy.yml", "financial-benchmark"),
        ("deploy.yml", "manual-ai-ocr-gate"),
        ("audit-replay.yml", "audit-replay"),
    } <= calls


def test_AC_runtime_reusable_permissions_1_every_call_grants_what_the_called_jobs_request() -> (
    None
):
    assert _violations() == []


def _write(directory: Path, name: str, workflow: dict[str, Any]) -> None:
    (directory / name).write_text(yaml.safe_dump(workflow), encoding="utf-8")


CALLEE_WRITE = {
    "on": {"workflow_call": {}},
    "jobs": {
        "run": {
            "runs-on": "ubuntu-latest",
            "permissions": {"contents": "write", "pages": "write"},
            "steps": [{"run": "true"}],
        }
    },
}
CALLEE_WORKFLOW_LEVEL = {
    "on": {"workflow_call": {}},
    "permissions": {"issues": "write"},
    "jobs": {"run": {"runs-on": "ubuntu-latest", "steps": [{"run": "true"}]}},
}
CALLEE_NONE = {
    "on": {"workflow_call": {}},
    "jobs": {"run": {"runs-on": "ubuntu-latest", "steps": [{"run": "true"}]}},
}
CALLEE_TWO_JOBS = {
    "on": {"workflow_call": {}},
    "jobs": {
        "first": {"runs-on": "ubuntu-latest", "steps": [{"run": "true"}]},
        "second": {
            "runs-on": "ubuntu-latest",
            "permissions": {"contents": "write"},
            "steps": [{"run": "true"}],
        },
    },
}
CALLEE_READ_CONTENTS = {
    "on": {"workflow_call": {}},
    "jobs": {
        "run": {
            "runs-on": "ubuntu-latest",
            "permissions": {"contents": "read"},
            "steps": [{"run": "true"}],
        }
    },
}
CALLEE_READ_ALL = {
    "on": {"workflow_call": {}},
    "jobs": {
        "run": {
            "runs-on": "ubuntu-latest",
            "permissions": "read-all",
            "steps": [{"run": "true"}],
        }
    },
}


@pytest.mark.parametrize(
    ("callee", "caller_job", "caller_workflow", "expected"),
    [
        # The job has no `permissions:` and holds the repository default: the call fails.
        (CALLEE_WRITE, {}, {}, 2),
        # The job grants every scope that the called job requests.
        (CALLEE_WRITE, {"permissions": {"contents": "write", "pages": "write"}}, {}, 0),
        # The job misses one scope.
        (CALLEE_WRITE, {"permissions": {"contents": "write"}}, {}, 1),
        # The job grants read where the called job asks for write.
        (
            CALLEE_WRITE,
            {"permissions": {"contents": "read", "pages": "write"}},
            {},
            1,
        ),
        # An empty `permissions: {}` grants nothing. The repository default does not apply to this job.
        (CALLEE_NONE, {"permissions": {}}, {}, 0),
        (CALLEE_READ_CONTENTS, {}, {}, 0),
        (CALLEE_READ_CONTENTS, {"permissions": {}}, {}, 1),
        (CALLEE_WORKFLOW_LEVEL, {"permissions": {}}, {}, 1),
        # The job inherits the permissions of its workflow.
        (CALLEE_WRITE, {}, {"permissions": {"contents": "write", "pages": "write"}}, 0),
        # The permissions of the job replace the permissions of the workflow.
        (
            CALLEE_WRITE,
            {"permissions": {"contents": "write"}},
            {"permissions": {"contents": "write", "pages": "write"}},
            1,
        ),
        # Every job of the called workflow counts, not only the first.
        (CALLEE_TWO_JOBS, {}, {}, 1),
        # The called workflow asks at workflow level.
        (CALLEE_WORKFLOW_LEVEL, {}, {}, 1),
        (CALLEE_WORKFLOW_LEVEL, {"permissions": {"issues": "write"}}, {}, 0),
        # The called workflow asks for nothing.
        (CALLEE_NONE, {}, {}, 0),
        # `write-all` grants every scope. `read-all` asks for read on every scope.
        (CALLEE_WRITE, {"permissions": "write-all"}, {}, 0),
        (CALLEE_READ_ALL, {}, {}, 1),
        (CALLEE_READ_ALL, {"permissions": "write-all"}, {}, 0),
    ],
    ids=[
        "default-vs-write",
        "grant-all",
        "scope-missing",
        "read-vs-write",
        "empty-vs-none",
        "default-grants-read",
        "empty-grants-nothing",
        "empty-vs-workflow-level",
        "inherit-workflow",
        "job-replaces-workflow",
        "second-callee-job",
        "callee-workflow-level",
        "callee-workflow-level-granted",
        "callee-asks-nothing",
        "write-all",
        "read-all-vs-default",
        "read-all-vs-write-all",
    ],
)
def test_AC_runtime_reusable_permissions_1_the_scan_compares_the_caller_with_the_callee(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    callee: dict[str, Any],
    caller_job: dict[str, Any],
    caller_workflow: dict[str, Any],
    expected: int,
) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    _write(workflows, "callee.yml", callee)
    _write(
        workflows,
        "caller.yml",
        {
            "on": {"push": {}},
            **caller_workflow,
            "jobs": {"call": {"uses": "./.github/workflows/callee.yml", **caller_job}},
        },
    )
    monkeypatch.setattr(f"{__name__}.WORKFLOWS", workflows)

    assert len(_violations()) == expected
