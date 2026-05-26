import importlib.util
import json
import subprocess
import sys
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "github_workflow_diagnostics_summary.py"
)
SPEC = importlib.util.spec_from_file_location(
    "github_workflow_diagnostics_summary", MODULE_PATH
)
assert SPEC is not None
diag_summary = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["github_workflow_diagnostics_summary"] = diag_summary
SPEC.loader.exec_module(diag_summary)


def _completed_json(payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["gh"], returncode=0, stdout=json.dumps(payload), stderr=""
    )


def test_AC8_13_39_ci_diagnostics_separate_failure_classes(monkeypatch) -> None:
    jobs_payload = {
        "jobs": [
            {"id": 1, "name": "Backend Tests (Shard 1/6)", "conclusion": "failure"},
            {"id": 2, "name": "Build Staging Images", "conclusion": "failure"},
            {"id": 3, "name": "Calculate Unified Coverage", "conclusion": "failure"},
        ]
    }
    build_log = """ERROR: failed to build: failed to solve: error writing layer blob: failed to parse error response 502: <!DOCTYPE html>"""
    coveralls_log = """Waiting for GitHub status 'Coveralls - unified' on abc: not found"""

    def fake_run(args, **kwargs):  # type: ignore[no-untyped-def]
        if args[:3] == ["gh", "api", "repos/owner/repo/actions/runs/55/jobs?per_page=100"]:
            return _completed_json(jobs_payload)
        if args[:4] == ["gh", "run", "view", "55"] and "--job" in args:
            job_id = args[args.index("--job") + 1]
            if job_id == "2":
                return subprocess.CompletedProcess(args=args, returncode=0, stdout=build_log, stderr="")
            if job_id == "3":
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout=coveralls_log, stderr=""
                )
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

    monkeypatch.setattr(diag_summary.subprocess, "run", fake_run)

    summary = diag_summary.format_ci_failure_diagnostics("owner/repo", "55")

    assert "## CI Failure Diagnostics" in summary
    assert "Backend Tests (Shard 1/6)" in summary
    assert "Image build/push failures" in summary
    assert "likely external registry/buildx infrastructure failure" in summary
    assert "External status-gate failures" in summary
    assert "issues/471" in summary


def test_AC8_13_39_staging_diagnostics_report_healthy_but_stale(monkeypatch) -> None:
    monkeypatch.setattr(
        diag_summary,
        "_branch_head_sha",
        lambda repo, branch: "2cdc23526b9e380d9ee0c5a1e130125b580cbc01",
    )
    monkeypatch.setattr(
        diag_summary,
        "_health_snapshot",
        lambda url: diag_summary.HealthSnapshot(
            url=url,
            http_status=200,
            healthy=True,
            git_sha="0191d05aaaaaaa",
        ),
    )
    monkeypatch.setattr(
        diag_summary,
        "_load_run_jobs",
        lambda repo, run_id: [
            diag_summary.JobState(
                job_id=1,
                name="Build and Deploy",
                conclusion="failure",
                steps=(
                    diag_summary.JobStep(
                        name="Wait for matching CI success", conclusion="failure"
                    ),
                    diag_summary.JobStep(name="Deploy to Staging", conclusion="skipped"),
                ),
            )
        ],
    )

    summary = diag_summary.format_staging_staleness_diagnostics(
        repo="owner/repo",
        run_id="77",
        staging_health_url="https://report-staging.zitian.party/api/health",
        production_health_url="https://report.zitian.party/api/health",
        main_branch="main",
    )

    assert "## Staging Staleness Diagnostics" in summary
    assert "Latest `main` SHA: `2cdc23526b9e380d9ee0c5a1e130125b580cbc01`" in summary
    assert "Staging deployed SHA (`/api/health`): `0191d05aaaaaaa`" in summary
    assert "healthy-but-stale: `True`" in summary
    assert "blocked at `Wait for matching CI success`" in summary
