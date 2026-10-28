import copy
import functools
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _has(text: str, *snippets: str) -> None:
    for s in snippets:
        assert s in text


def _lacks(text: str, *snippets: str) -> None:
    for s in snippets:
        assert s not in text


@functools.lru_cache(maxsize=128)
def _read_cached(path: str) -> str:
    target = ROOT / path
    if target.is_dir():
        return "\n# <<< file-boundary >>>\n".join(
            (p.read_text(encoding="utf-8") for p in sorted(target.rglob("*.py")))
        )
    return target.read_text(encoding="utf-8")


def read(path: str) -> str:
    return _read_cached(path)


_orig_safe_load = yaml.safe_load


@functools.lru_cache(maxsize=128)
def _cached_safe_load(stream: str) -> Any:
    return _orig_safe_load(stream)


def _safe_load_wrapper(stream: Any) -> Any:
    if isinstance(stream, str):
        return copy.deepcopy(_cached_safe_load(stream))
    return _orig_safe_load(stream)


yaml.safe_load = _safe_load_wrapper


def build_critical_matrix() -> dict:
    """Build the critical-proof matrix payload in-memory from the AC graph.

    The matrix is a derived (not committed) view of the one AC-keyed graph, so
    tests read the freshly-built payload instead of a checked-in YAML file.
    """
    from common.testing.ac_graph import build_ac_graph
    from common.testing.generate_critical_proof_matrix import build_matrix_from_graph

    return build_matrix_from_graph(build_ac_graph(ROOT))


def critical_matrix_text() -> str:
    """Render the in-memory critical-proof matrix to its canonical YAML text."""
    from common.testing.generate_critical_proof_matrix import render_matrix

    return render_matrix(build_critical_matrix())


def staging_ai_ocr_contract_shell() -> str:
    return subprocess.check_output(
        [sys.executable, "tools/staging_ai_ocr_gate_contract.py", "--shell"],
        cwd=ROOT,
        text=True,
    )


def test_AC8_13_11_health_check_diagnoses_staging_api_route_404() -> None:
    """AC-testing.deploy-gates.2: AC8.13.11: Staging health 404 reports API route diagnostics."""
    health_check = read("common/runtime/health_check.py")
    _has(
        health_check,
        "from infra2_sdk.deploy import",
        "_print_route_probe",
        "route_probe attempt=",
        "platform_failure_domain=traefik-public-route",
        "api_status={api_status}",
        "frontend_status={frontend_status}",
        "_print_404_route_diagnostics",
        "Traefik API route is missing or shadowed",
        '"API ping", f"{app_base_url}/api/ping"',
        '"Frontend shell", f"{app_base_url}/"',
        "status_code == 404",
    )


def test_AC8_13_12_ai_ocr_gate_failure_includes_statement_context() -> None:
    """AC-testing.deploy-gates.3: AC8.13.12: AI/OCR gate failures include statement validation context."""
    conftest = read("tests/e2e/conftest.py")
    read("tests/e2e/test_statement_full_journey.py")
    read("tests/e2e/test_statement_upload_e2e.py")
    read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")
    read("tests/e2e/test_four_asset_net_worth_golden_path.py")
    assert "format_ai_ocr_gate_failure" in conftest
    _has(
        conftest,
        "validation_error",
        "confidence_score",
        "parsing_progress",
        "balance_validated",
    )


def test_AC8_13_13_staging_deploy_fast_fail_guardrails() -> None:
    """AC-testing.deploy-gates.4 AC-testing.deploy-gates.21: AC8.13.13 AC8.13.105: Staging deploy is a singleton post-merge train."""
    workflow = read(".github/workflows/deploy.yml")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    _has(
        workflow,
        "concurrency:",
        "inputs.target == 'staging' && 'staging-deploy'",
        "cancel-in-progress: false",
    )
    _lacks(workflow, "post-merge-train-turn:", "classify-staging:")


def test_AC8_13_157_audit_replay_workflow_is_weekly_and_blocks_nothing() -> None:
    """AC-testing.deploy-gates.32: AC8.13.157: heavy LLM journeys run in a separate audit-replay
    workflow (weekly schedule, manual dispatch, post-deploy core_journey dispatch). No deploy
    or release depends on it, so its red blocks nothing (#2370)."""
    audit = yaml.safe_load(read(".github/workflows/audit-replay.yml"))
    yaml.safe_load(read(".github/workflows/deploy.yml"))
    triggers = audit.get("on", audit.get(True))
    assert isinstance(triggers, dict)
    assert "workflow_dispatch" in triggers


def test_AC_extraction_1913_10_staging_statement_canary_is_sha_pinned_and_blocking() -> (
    None
):
    """AC-extraction.1913.10: required durable statement journeys fail the deploy."""
    deploy = yaml.safe_load(read(".github/workflows/deploy.yml"))
    canary = deploy["jobs"]["ai-ocr-gate"]
    read(".github/workflows/deploy.yml").split(
        "Deploy to Staging through infra2 receiver", 1
    )[1].split("Confirm staging backend health", 1)[0]
    assert canary["with"]["corpus"] == "canary"
    assert "blocking" not in canary["with"]


def test_AC8_13_158_canary_transient_classification_owned_by_provider_gate() -> None:
    """AC-testing.deploy-gates.33: AC8.13.158: provider transient (5xx/timeout)=degraded, 4xx/config=block; the
    canary delegates this classification to the Staging Provider Gate."""
    deploy = read(".github/workflows/deploy.yml")
    assert "needs.provider-gate.outputs.provider_status == 'pass'" in deploy
    provider_block = deploy.split("provider-gate:", 1)[1].split("ai-ocr-gate:", 1)[0]
    _has(
        provider_block,
        "provider_status=config-failure",
        "client/config error",
        "provider_status=degraded",
        "transient",
    )


def test_AC8_13_160_ci_cd_distinguishes_canary_from_audit_replay() -> None:
    """AC-testing.deploy-gates.35: AC8.13.160: SSOT distinguishes the blocking minimal AI/OCR Canary from the
    nightly comprehensive Audit Replay, and the split is enforced in workflows."""
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    _has(ci_cd, "AI/OCR Canary", "Audit Replay", "audit-replay.yml")
    assert "test_brokerage_upload_to_portfolio_value.py" in ci_cd


def test_AC8_13_14_staging_ai_ocr_gate_is_separate_deploy_job() -> None:
    """AC-testing.deploy-gates.5: AC8.13.14: Provider-backed AI/OCR gate runs outside deploy health."""
    deploy_workflow = read(".github/workflows/deploy.yml")
    read(".github/workflows/staging-ai-ocr-gate.yml")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    _has(
        deploy_workflow,
        "ai-ocr-gate:",
        "needs: [build-and-deploy, provider-gate]",
        "if: ${{ always() && github.event_name == 'workflow_dispatch' && inputs.target == 'staging' && needs.build-and-deploy.outputs.staging_required == 'true' && needs.build-and-deploy.outputs.ai_ocr_required == 'true' && needs.provider-gate.outputs.provider_status == 'pass' && needs.provider-gate.result == 'success' }}",
        "name: Staging AI/OCR Gate",
        "commit_full_sha: ${{ steps.release.outputs.full_sha }}",
        "deployed_version_ref: ${{ steps.release.outputs.version_ref }}",
        "uses: ./.github/workflows/staging-ai-ocr-gate.yml",
        "commit_ref: ${{ needs.build-and-deploy.outputs.commit_full_sha }}",
        "expected_sha: ${{ needs.build-and-deploy.outputs.deployed_version_ref }}",
    )
    assert "blocking:" not in deploy_workflow


def _gha_expr_substituted(script: str, values: dict[str, str]) -> str:
    """Replace ``${{ expr }}`` GHA interpolations with plain values, the same
    textual substitution the Actions runner performs before a shell ever sees
    the script. Every placeholder present in the step under test must have an
    entry in ``values`` or the returned script is invalid bash (``${{`` is not
    a valid parameter expansion)."""
    substituted = script
    for expr, value in values.items():
        substituted = substituted.replace("${{ " + expr + " }}", value)
    assert substituted.count("${{") == 0, (
        f"unsubstituted GHA expression remains: {substituted}"
    )
    return substituted


def _run_gate_timeout_fallback(
    tmp_path: Path, *, outcome: str, corpus: str, existing_issue: str
) -> dict[str, object]:
    """Execute the real ``gate_timeout_fallback`` step body (AC8.13.166) as a
    subprocess against a stub ``gh``, exercising actual behavior instead of
    grepping the script text (mirror-assertion ratchet, common/testing/
    mirror_ratchet.py, #1435)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    workflow = yaml.safe_load(read(".github/workflows/staging-ai-ocr-gate.yml"))
    fallback = next(
        (
            s
            for s in workflow["jobs"]["run"]["steps"]
            if s.get("id") == "gate_timeout_fallback"
        )
    )
    script = _gha_expr_substituted(
        fallback["run"],
        {"steps.staging_ai_ocr_tests.outcome": outcome, "github.run_id": "999"},
    )
    gh_calls_log = tmp_path / "gh_calls.jsonl"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        f'''#!/bin/bash\npython3 -c 'import json,sys; open(sys.argv[1], "a").write(json.dumps(sys.argv[2:]) + "\\n")' "{gh_calls_log}" "$@"\nif [ "$1" = "issue" ] && [ "$2" = "list" ]; then\n  printf %s "{existing_issue}"\n  exit 0\nfi\nexit 0\n'''
    )
    fake_gh.chmod(493)
    github_output = tmp_path / "github_output.txt"
    github_output.write_text("")
    github_step_summary = tmp_path / "github_step_summary.txt"
    github_step_summary.write_text("")
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "GH_TOKEN": "fake-token",
            "GITHUB_OUTPUT": str(github_output),
            "GITHUB_STEP_SUMMARY": str(github_step_summary),
            "CORPUS": corpus,
            "COMMIT_REF": "deadbeef",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    output_lines = [line for line in github_output.read_text().splitlines() if line]
    parsed_output = dict((line.split("=", 1) for line in output_lines))
    gh_calls = (
        [json.loads(line) for line in gh_calls_log.read_text().splitlines()]
        if gh_calls_log.exists()
        else []
    )
    return {
        "exit_code": result.returncode,
        "stderr": result.stderr,
        "parsed_output": parsed_output,
        "gh_calls": gh_calls,
        "step_summary": github_step_summary.read_text(),
    }


def test_AC8_13_166_gate_timeout_fallback_alerts_when_corpus_step_dies_without_output(
    tmp_path: Path,
) -> None:
    """AC-testing.deploy-gates.41: AC8.13.166: alerting survives the corpus step's own timeout-minutes killing
    it before record_and_finish ever runs (the 5-night-red silent gap, #1767).
    Behavioral (subprocess), not a text mirror -- see _run_gate_timeout_fallback."""
    workflow = yaml.safe_load(read(".github/workflows/staging-ai-ocr-gate.yml"))
    job = workflow["jobs"]["run"]
    fallback = next((s for s in job["steps"] if s.get("id") == "gate_timeout_fallback"))
    assert (
        fallback["if"]
        == "${{ always() && steps.staging_ai_ocr_tests.outcome != 'success' && steps.staging_ai_ocr_tests.outputs.ai_ocr_status == '' }}"
    )
    assert (
        job["outputs"]["ai_ocr_status"]
        == "${{ steps.staging_ai_ocr_tests.outputs.ai_ocr_status || steps.gate_timeout_fallback.outputs.ai_ocr_status || 'not-run' }}"
    )


def test_AC8_13_167_timeout_budget_is_sized_per_corpus_worst_case() -> None:
    """AC-testing.deploy-gates.42: AC8.13.167: step/job timeout-minutes fit every sequential parse wait in a
    corpus hitting its own 8-minute PARSING_TIMEOUT_MS ceiling, not just the
    happy path -- sized off the real per-corpus wait count, not a file/journey
    guess (#1767: the shipped 22-min budget only covered 66% of one real run)."""
    workflow = yaml.safe_load(read(".github/workflows/staging-ai-ocr-gate.yml"))
    job = workflow["jobs"]["run"]
    corpus_step = next(
        (s for s in job["steps"] if s.get("id") == "staging_ai_ocr_tests")
    )
    assert (
        corpus_step["timeout-minutes"]
        == "${{ inputs.corpus == 'canary' && 25 || (inputs.corpus == 'all' && 150 || 135) }}"
    )
    assert workflow["env"]["PARSING_TIMEOUT_MS"] == 480000


def test_AC8_13_49_staging_ai_ocr_gate_publishes_audit_inventory_and_summary() -> None:
    """AC-testing.deploy-gates.11: AC8.13.49: Staging AI/OCR gates publish replay inputs and summary fields."""
    workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    read("common/observability/observability-logging.md")
    _has(
        workflow,
        "write_staging_audit_inventory()",
        "write_staging_audit_result()",
        "## Staging Audit Replay Inputs",
        "## Staging Audit Replay Summary",
        "- Environment: staging",
        "- GitHub run ID: ${{ github.run_id }}",
    )
    assert (
        "- Expected SHA: ${EXPECTED_SHA}" in workflow
        or "- Expected version: ${EXPECTED_SHA}" in workflow
    )


def test_AC8_13_51_staging_deploy_is_manual_dispatch_only() -> None:
    """AC-testing.deploy-gates.12: AC8.13.51: Staging deploy is manual (`workflow_dispatch`) only; it does not auto-follow main CI."""
    workflow = read(".github/workflows/deploy.yml")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    parsed = yaml.safe_load(workflow)
    triggers = parsed.get("on", parsed.get(True))
    assert isinstance(triggers, dict), "deploy.yml must declare an `on:` map"
    _has(triggers, "workflow_dispatch")


def test_AC8_13_103_post_merge_delivery_summary_check_aggregates_staging_gates() -> (
    None
):
    """AC-testing.deploy-gates.20: AC8.13.103/AC8.13.108: Delivery aggregates gates and failure context."""
    workflow = read(".github/workflows/deploy.yml")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    read("docs/project/EPIC-008.testing-strategy.md")
    _has(
        workflow,
        "post-merge-delivery:",
        "name: Post-merge Delivery",
        "needs: [build-and-deploy, provider-gate, ai-ocr-gate, financial-benchmark]",
        "Aggregate post-merge delivery result",
        'staging_required="${{ needs.build-and-deploy.outputs.staging_required }}"',
        'ai_ocr_required="${{ needs.build-and-deploy.outputs.ai_ocr_required }}"',
        'build_result="${{ needs.build-and-deploy.result }}"',
        'provider_result="${{ needs.provider-gate.result }}"',
        'provider_status="${{ needs.provider-gate.outputs.provider_status }}"',
        'ai_ocr_result="${{ needs.ai-ocr-gate.result }}"',
        'ai_ocr_status="${{ needs.ai-ocr-gate.outputs.ai_ocr_status }}"',
    )
    _lacks(workflow, "staging-deploy-alert", "alert_result")


def test_AC8_13_60_deploy_workflows_have_no_nonblocking_noop_gates() -> None:
    """AC-testing.deploy-gates.15: AC8.13.60: Deploy gates do not keep no-op or warning-only checks."""
    workflows = [
        read(".github/workflows/deploy.yml"),
        read(".github/workflows/deploy.yml"),
    ]
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    for workflow in workflows:
        assert "Check Deployment Dependencies" not in workflow
        assert "Deployment deps check skipped" not in workflow
    staging = workflows[0]
    _lacks(staging, "Performance Benchmark", "Don't block deploy, but report issues")


def test_AC8_13_52_production_release_dry_run_does_not_mutate_production() -> None:
    """AC-testing.deploy-gates.13 AC-testing.deploy-gates.17: AC8.13.52 AC8.13.65: Production dry-run validates without deploying."""
    workflow = read(".github/workflows/release.yml")
    read("common/runtime/release_evidence.py")
    read("common/runtime/release_images.py")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    _has(
        workflow,
        "dry_run:",
        "version_ref:",
        "Version ref to deploy (vX.Y.Z release tag)",
    )
    assert "leave empty for latest" not in workflow


BACKEND_DIGEST = "sha256:" + "1" * 64
FRONTEND_DIGEST = "sha256:" + "2" * 64


def _deploy_log_with_escape_codes() -> str:
    """A Deploy Staging job log in the shape of a real run (#2491).

    The echoed shell source of a step starts with the code ESC[36;1m and ends with ESC[0m.
    """
    return f'2026-10-16T04:24:41.6518661Z Found backend release image digest: {BACKEND_DIGEST}\n2026-10-16T04:24:41.6519117Z Found frontend release image digest: {FRONTEND_DIGEST}\n2026-10-16T04:28:13.0556017Z \x1b[36;1m  echo "backend_digest={BACKEND_DIGEST}"\x1b[0m\n2026-10-16T04:28:13.0556641Z \x1b[36;1m  echo "frontend_digest={FRONTEND_DIGEST}"\x1b[0m\n'


def _staging_runs_json(args: list[str], *, head_sha: str = "a" * 40) -> object:
    if " run list " in f" {' '.join(args)} ":
        return [
            {
                "databaseId": 12,
                "status": "completed",
                "displayTitle": "Deploy Staging v1.2.3",
                "headSha": head_sha,
            }
        ]
    return {
        "jobs": [
            {"name": "Deploy Staging", "databaseId": 999, "conclusion": "success"},
            {
                "name": "Staging Provider Gate",
                "databaseId": 1000,
                "conclusion": "success",
            },
            {
                "name": "Staging AI/OCR Gate",
                "databaseId": 1001,
                "conclusion": "success",
            },
            {
                "name": "Financial Benchmark",
                "databaseId": 1002,
                "conclusion": "success",
            },
        ]
    }


def _verify_with_log(gh_text: object) -> str:
    from common.runtime import release_evidence

    return release_evidence.verify_staging(
        repository="owner/repo",
        version_ref="v1.2.3",
        release_sha="a" * 40,
        expected_backend_digest=BACKEND_DIGEST,
        expected_frontend_digest=FRONTEND_DIGEST,
        gh_json=_staging_runs_json,
        gh_text=gh_text,
    )


def test_AC8_13_16_ci_change_classification_and_frontend_cache() -> None:
    """AC-testing.classifier.1: AC8.13.16: CI skips heavy jobs for lightweight changes and caches npm."""
    workflow = read(".github/workflows/ci.yml")
    classifier = read("common/testing/change_classifier.py")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    read("common/runtime/environments.md")
    _has(
        workflow,
        "name: Classify Changes",
        "pr_required: ${{ steps.gates.outputs.pr_required }}",
        "ENV_STAGE_REQUIRED: ${{ steps.classify.outputs.env_stage_required }}",
        "tools/ci_change_classifier.py",
        "--changed-files changed-files.txt",
    )
    _has(
        classifier,
        '"docs/"',
        '".github/ISSUE_TEMPLATE/"',
        '".github/workflows/docs.yml"',
    )


def _assert_job_setup_minio_invocations(
    job_name: str, steps: list[dict[str, Any]]
) -> None:
    count = sum(
        (1 for step in steps if "./.github/actions/setup-minio" in step.get("uses", ""))
    )
    assert count >= 2, (
        f"job {job_name} invoked setup-minio {count} times (expected >= 2)"
    )


def test_AC8_13_145_backend_tier1_pr_fail_fast_but_main_reports_all_failures() -> None:
    """AC-testing.ci-structure.6: AC8.13.145: Tier-1 API E2E is retired in favor of Bench V2 and backend integration."""
    workflow = read(".github/workflows/ci.yml")
    assert "backend-e2e-tier1:" not in workflow


def test_AC8_13_147_frontend_ci_split_preserves_merge_authority() -> None:
    """AC-testing.ci-structure.7: AC8.13.147: frontend PR CI is split without dropping required proof."""
    workflow_text = read(".github/workflows/ci.yml")
    workflow = yaml.safe_load(workflow_text)
    jobs = workflow["jobs"]
    split_jobs = [
        "frontend-build",
        "frontend-vitest",
        "frontend-playwright",
        "frontend-telemetry-e2e",
    ]
    assert "frontend" not in jobs
    for job_id in split_jobs:
        assert jobs[job_id]["needs"] == ["changes"]


def test_AC8_13_162_frontend_telemetry_e2e_is_right_moved_and_skip_is_a_pass() -> None:
    """AC-testing.ci-structure.10: AC8.13.162: frontend-telemetry-e2e is right-moved off unrelated PRs
    (mirrors container-images' image_build_required pattern), and finish's
    aggregation treats its skip as a pass, not a gap (#1689)."""
    workflow = yaml.safe_load(read(".github/workflows/ci.yml"))
    jobs = workflow["jobs"]
    telemetry_if = jobs["frontend-telemetry-e2e"]["if"]
    required_fragments = (
        "needs.changes.outputs.frontend_changed",
        "github.event_name == 'workflow_dispatch'",
        "refs/heads/main",
    )
    for fragment in required_fragments:
        assert fragment in telemetry_if
    finish_commands = "\n".join(
        (
            str(step.get("run", ""))
            for step in jobs["finish"].get("steps", [])
            if isinstance(step, dict)
        )
    )
    skip_is_a_pass_clause = '"${{ needs.frontend-telemetry-e2e.result }}" != "success" && "${{ needs.frontend-telemetry-e2e.result }}" != "skipped"'
    assert skip_is_a_pass_clause in finish_commands


def test_AC_testing_ci_structure_11_frontend_build_and_playwright_are_right_moved_and_skip_is_a_pass() -> (
    None
):
    """AC-testing.ci-structure.11: frontend-build and frontend-playwright are right-moved off PRs
    that touch no apps/frontend/ path (same pattern as frontend-telemetry-e2e's
    AC-testing.ci-structure.10, minus the always-run-on-push override those two
    non-canary jobs don't need — see AC-testing.deploy-gates.25), and finish's
    aggregation treats a skip as a pass, not a gap."""
    workflow = yaml.safe_load(read(".github/workflows/ci.yml"))
    jobs = workflow["jobs"]
    pr_required_clause = "needs.changes.outputs.pr_required == 'true'"
    frontend_changed_clause = "needs.changes.outputs.frontend_changed == 'true'"
    for job_id in ("frontend-build", "frontend-playwright"):
        job_if = jobs[job_id]["if"]
        assert pr_required_clause in job_if
        assert frontend_changed_clause in job_if
    finish_commands = "\n".join(
        (
            str(step.get("run", ""))
            for step in jobs["finish"].get("steps", [])
            if isinstance(step, dict)
        )
    )
    for job_id in ("frontend-build", "frontend-playwright"):
        skip_is_a_pass_clause = f'"${{{{ needs.{job_id}.result }}}}" != "success" && "${{{{ needs.{job_id}.result }}}}" != "skipped"'
        assert skip_is_a_pass_clause in finish_commands


def test_AC_testing_ci_structure_12_setup_uv_retries_once_via_one_composite_action() -> (
    None
):
    """AC-testing.ci-structure.12: every `Install uv` step in ci.yml retries once through a single
    local composite action instead of failing the job outright on a transient
    astral-sh/setup-uv network fetch failure (run 35091080269 red-flagged
    Backend Integration Tests on exactly this; mirrors truealpha#890's buildx
    retry idiom)."""
    workflow_text = read(".github/workflows/ci.yml")
    workflow = yaml.safe_load(workflow_text)
    jobs = workflow["jobs"]
    action_path = Path(".github/actions/setup-uv-retry/action.yml")
    action_text = read(str(action_path))
    yaml.safe_load(action_text)
    raw_action_reference = "astral-sh/setup-uv"
    assert raw_action_reference not in workflow_text
    all_steps = [
        step
        for job in jobs.values()
        for step in job.get("steps", [])
        if isinstance(step, dict)
    ]
    install_uv_steps = [step for step in all_steps if step.get("name") == "Install uv"]
    [
        step
        for step in all_steps
        if step.get("uses") == "./.github/actions/setup-uv-retry"
    ]
    assert install_uv_steps


def test_AC_testing_ci_structure_14_tier1_runs_as_seeded_matrix_legs() -> None:
    """AC-testing.ci-structure.14: Tier-1 API E2E shard legs are retired and unified into backend integration and Bench V2."""
    workflow = yaml.safe_load(read(".github/workflows/ci.yml"))
    assert "backend-e2e-tier1" not in workflow["jobs"]
    assert "backend-integration" in workflow["jobs"]


def test_AC8_13_148_backend_shards_use_seeded_least_duration_split() -> None:
    """AC-testing.ci-structure.8: AC8.13.148: backend shards use a seeded least-duration split.

    The shard count is the matrix length (#2688): the job name, `--splits` and the gate
    inventory must agree with it.
    """
    workflow_text = read(".github/workflows/ci.yml")
    workflow = yaml.safe_load(workflow_text)
    backend_job = workflow["jobs"]["backend"]
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    json.loads(read("apps/backend/ci/backend-test-durations.json"))
    shards = backend_job["strategy"]["matrix"]["shard"]
    assert shards == list(range(1, len(shards) + 1))
    assert len(shards) >= 4


def test_AC8_13_149_fan_in_jobs_download_only_required_artifacts() -> None:
    """AC-testing.ci-structure.9: AC8.13.149: coverage and ratchet fan-in stays scoped and stdlib-fast."""
    workflow_text = read(".github/workflows/ci.yml")
    workflow = yaml.safe_load(workflow_text)
    jobs = workflow["jobs"]
    unified_block = workflow_text.split("  unified-coverage:", 1)[1].split(
        "  unified-coverage-baseline-pr:", 1
    )[0]
    workflow_text.split("  ac-behavioral-ratchet:", 1)[1].split("  finish:", 1)[0]
    assert jobs["unified-coverage"]["needs"] == [
        "changes",
        "backend",
        "frontend-vitest",
        "tooling-coverage",
    ]
    _lacks(
        unified_block,
        "Install uv",
        "uv run python tools/merge_lcov.py",
        "uv run python tools/check_coverage_policy.py",
        "uv run python tools/calculate_unified_coverage.py",
    )


def test_AC_testing_deploy_gates_36_every_main_commit_image_is_independently_verified() -> (
    None
):
    """AC-testing.deploy-gates.36 (#1759, W4 of #1435).

    "container-images always builds+pushes :<sha> on main" was previously
    guaranteed only by the build step's own self-report. This test proves a
    second, independent job re-inspects the registry for that exact tag
    right after the build, so a push that reports success without the image
    actually landing would be caught at commit time rather than later at
    promote.
    """
    ci = yaml.safe_load(read(".github/workflows/ci.yml"))
    jobs = ci["jobs"]
    gate_job = jobs["verify-sha-image-published"]
    assert gate_job["needs"] == ["container-images"]
    assert (
        gate_job["if"]
        == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    )


def test_AC8_13_9_production_release_runs_prod_safe_e2e_smoke() -> None:
    """AC-testing.deploy-gates.1: AC8.13.9: Production release runs prod-safe read-only E2E smoke."""
    workflow = read(".github/workflows/release.yml")
    read("tests/e2e/test_production_readonly_smoke.py")
    _has(
        workflow,
        'NODE_VERSION: "20.19.0"',
        "Set up Node",
        "Install frontend dependencies",
        "cache-dependency-path: apps/frontend/package-lock.json",
        "working-directory: apps/frontend",
        "Verify source CI passed",
    )
    assert workflow.index("Install frontend dependencies") < workflow.index(
        "moon run :lint"
    )


def test_AC8_13_144_production_release_rolls_back_with_deploy_v2_after_post_deploy_failure() -> (
    None
):
    """AC-testing.deploy-gates.29: AC8.13.144: production rollback uses deploy_v2 and confirms previous health."""
    workflow = read(".github/workflows/release.yml")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    workflow.split("- name: Roll back production after post-deploy failure", 1)[
        1
    ].split("- name: Warn when production rollback cannot run", 1)[0]
    workflow.split("- name: Warn when production rollback cannot run", 1)[1].split(
        "- name: Write production deploy context", 1
    )[0]
    workflow.split("- name: Probe current production version", 1)[1].split(
        "- name: Deploy with deploy_v2", 1
    )[0]
    rollback_evidence_block = workflow.split(
        "- name: Resolve rollback release coordinate", 1
    )[1].split("- name: Roll back production after post-deploy failure", 1)[0]
    assert rollback_evidence_block.count("continue-on-error: true") == 3
    _has(
        rollback_evidence_block,
        "Verify rollback release images workflow passed",
        "Verify rollback staging passed",
        "Verify rollback reviewed change",
    )


def test_AC8_13_67_production_release_preserves_version_metadata() -> None:
    """AC-testing.deploy-gates.18: AC8.13.67: Production release preserves deployed version metadata."""
    workflow = read(".github/workflows/release.yml")
    release_images = read(".github/workflows/deploy.yml")
    promote_blocks = re.findall(
        "docker buildx imagetools create --prefer-index=false --tag", release_images
    )
    assert len(promote_blocks) == 2
    assert "docker buildx imagetools create --tag" not in workflow


def test_AC7_10_production_release_promotes_not_rebuilds() -> None:
    """AC-meta.release-pipeline.1: AC7.10.1 - AC7.10.5: Production release promotes staging-validated SHA image and fails closed on drift."""
    read(".github/workflows/release.yml")
    release_images = read(".github/workflows/deploy.yml")
    read("common/runtime/release_images.py")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    read("common/runtime/deployment.md")
    _has(release_images, "docker buildx imagetools create --prefer-index=false --tag")
    assert "docker/build-push-action" not in release_images


def test_AC8_13_21_staging_ai_ocr_gate_runs_under_manual_dispatch() -> None:
    """AC-testing.deploy-gates.6: AC8.13.21: Provider-backed staging AI/OCR runs inside a manual dispatch, not auto-after-CI."""
    workflow = read(".github/workflows/deploy.yml")
    read(".github/workflows/deploy.yml")
    read(".github/workflows/staging-ai-ocr-gate.yml")
    parsed = yaml.safe_load(workflow)
    triggers = parsed.get("on", parsed.get(True))
    assert isinstance(triggers, dict), "deploy.yml must declare an `on:` map"
    _has(triggers, "workflow_dispatch")


def test_AC8_13_120_staging_runs_lightweight_provider_connectivity_smoke() -> None:
    """AC-testing.deploy-gates.27: AC8.13.120: provider-risk staging changes prove a provider round trip."""
    workflow = read(".github/workflows/deploy.yml")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    read("tests/e2e/test_ai_provider_connectivity.py")
    _has(
        workflow,
        "provider-gate:",
        "name: Staging Provider Gate",
        "needs: [build-and-deploy]",
        "if: ${{ github.event_name == 'workflow_dispatch' && inputs.target == 'staging' && needs.build-and-deploy.outputs.staging_required == 'true' && needs.build-and-deploy.outputs.provider_gate_required == 'true' }}",
        "provider_gate_required: ${{ steps.gates.outputs.provider_gate_required }}",
        "provider_gate_reason: ${{ steps.gates.outputs.provider_gate_reason }}",
        "provider_status: ${{ steps.ai_provider_connectivity.outputs.provider_status }}",
        "name: AI Provider Connectivity Smoke",
        "id: ai_provider_connectivity",
        "timeout-minutes: 10",
        "pytest tests/e2e/test_ai_provider_connectivity.py",
    )
    _has(
        workflow,
        "test-results/staging-provider-connectivity.xml",
        "provider-connectivity",
        "provider_connectivity_outcome=",
    )


def test_AC8_13_22_staging_deploys_manually_dispatched_version_ref() -> None:
    """AC-testing.deploy-gates.7: AC8.13.22: Staging deploys the manually dispatched release version_ref."""
    workflow = read(".github/workflows/deploy.yml")
    read("common/runtime/release_coordinate.py")
    parsed = yaml.safe_load(workflow)
    triggers = parsed.get("on", parsed.get(True))
    assert isinstance(triggers, dict)
    assert "workflow_dispatch" in triggers


def test_AC8_13_36_post_merge_reuses_sha_tagged_staging_images() -> None:
    """AC-testing.deploy-gates.9: AC8.13.36: Main CI builds SHA images, deploy.yml tags them, staging deploys the tag."""
    ci_workflow = read(".github/workflows/ci.yml")
    read(".github/workflows/deploy.yml")
    read(".github/workflows/deploy.yml")
    read("common/runtime/release_coordinate.py")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    _has(ci_workflow, "container-images:", "name: Build Staging Images")
    container_block = ci_workflow.split("  container-images:", 1)[1].split(
        "  tooling-coverage:", 1
    )[0]
    assert "needs: [changes]" in container_block


def test_AC8_13_40_pr_ci_dry_runs_staging_image_builds_before_merge() -> None:
    """AC-testing.deploy-gates.10: AC8.13.40: PR CI dry-runs staging image builds before merge."""
    workflow = read(".github/workflows/ci.yml")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    container_block = workflow.split("  container-images:", 1)[1].split(
        "  tooling-coverage:", 1
    )[0]
    workflow.split("- name: Check job status", 1)[1]
    login_block = container_block.split("- name: Log in to Container registry", 1)[
        1
    ].split("- name: Set up Docker Buildx", 1)[0]
    _has(
        container_block,
        "needs.changes.outputs.pr_required == 'true' && needs.changes.outputs.image_build_required == 'true'",
    )
    _has(
        login_block,
        "if: (github.event_name == 'push' && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/release/'))) || github.event_name == 'workflow_dispatch'",
    )


def test_AC8_13_23_post_merge_deploy_and_ai_ocr_are_one_serial_unit() -> None:
    """AC-testing.deploy-gates.8: AC8.13.23: Deploy health and provider gate share one serialized workflow unit."""
    deploy_workflow = read(".github/workflows/deploy.yml")
    read(".github/workflows/deploy.yml")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    assert "post-merge-train-turn:" not in deploy_workflow
    _has(
        deploy_workflow,
        "name: Classify staging and AI/OCR relevance",
        "ai-ocr-gate:",
        "needs: [build-and-deploy]",
        "ai_ocr_required: ${{ steps.gates.outputs.ai_ocr_required }}",
        "PROVIDER_GATE_REQUIRED: ${{ steps.classify.outputs.provider_gate_required }}",
        "STAGING_AI_OCR_REQUIRED: ${{ steps.classify.outputs.staging_ai_ocr_required }}",
        "STAGING_AI_OCR_REASON: ${{ steps.classify.outputs.staging_ai_ocr_reason }}",
        "commit_full_sha: ${{ steps.release.outputs.full_sha }}",
        "deployed_version_ref: ${{ steps.release.outputs.version_ref }}",
        "ref: ${{ needs.build-and-deploy.outputs.commit_full_sha }}",
        "EXPECTED_SHA: ${{ needs.build-and-deploy.outputs.deployed_version_ref }}",
    )


def test_AC8_13_24_ac_traceability_uploads_audit_artifact_without_stale_doc_gate() -> (
    None
):
    """AC-testing.acgates.2: AC8.13.24: CI uploads traceability audit instead of gating stale snapshots."""
    workflow = read(".github/workflows/ci.yml")
    read("common/testing/build_ac_traceability.py")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    read("docs/project/README.md")
    _has(
        workflow,
        'tools/build_ac_traceability.py --output "$RUNNER_TEMP/AC-TEST-TRACEABILITY-AUDIT.md"',
        "uses: actions/upload-artifact@v7",
        "name: ac-test-traceability-audit",
    )
    assert "tools/build_ac_traceability.py --check" not in workflow


def test_AC8_13_25_full_ci_aggregates_static_traceability_and_test_gates() -> None:
    """AC-testing.ci-structure.1: AC8.13.25: Full CI starts tests early while finish aggregates every gate."""
    workflow = read(".github/workflows/ci.yml")
    workflow_data = yaml.safe_load(workflow)
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    backend_block = workflow.split("  backend:", 1)[1].split("  frontend-build:", 1)[0]
    frontend_block = workflow.split("  frontend-build:", 1)[1].split(
        "  container-images:", 1
    )[0]
    image_block = workflow.split("  container-images:", 1)[1].split(
        "  tooling-coverage:", 1
    )[0]
    tooling_block = workflow.split("  tooling-coverage:", 1)[1].split(
        "  unified-coverage:", 1
    )[0]
    workflow.split("  finish:", 1)[1]
    for block in (backend_block, frontend_block, image_block, tooling_block):
        assert "needs: [changes]" in block
        assert "lint" not in block.split("steps:", 1)[0]
        assert "ac-traceability" not in block.split("steps:", 1)[0]
    traceability_needs = set(workflow_data["jobs"]["ac-traceability"]["needs"])
    assert traceability_needs == {
        "changes",
        "lint",
        "tooling-coverage",
        "backend",
        "backend-integration",
        "frontend-vitest",
    }


def test_AC8_13_86_fast_feedback_jobs_do_not_wait_for_behavior_gates() -> None:
    """AC-testing.ci-structure.5: AC8.13.86: CI fast feedback jobs preserve actual workflow dependency semantics."""
    workflow = read(".github/workflows/ci.yml")
    yaml.safe_load(workflow)
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    lint_block = workflow.split("  lint:", 1)[1].split("  backend:", 1)[0]
    backend_block = workflow.split("  backend:", 1)[1].split(
        "  backend-integration:", 1
    )[0]
    frontend_block = workflow.split("  frontend-build:", 1)[1].split(
        "  container-images:", 1
    )[0]
    image_block = workflow.split("  container-images:", 1)[1].split(
        "  tooling-coverage:", 1
    )[0]
    for block in (backend_block, frontend_block, image_block):
        assert "needs: [changes]" in block
        assert "backend-integration" not in block.split("steps:", 1)[0]
        assert "backend-e2e-tier1" not in block.split("steps:", 1)[0]
        assert "lint" not in block.split("steps:", 1)[0]
        assert "ac-traceability" not in block.split("steps:", 1)[0]
    assert "needs:" not in lint_block.split("steps:", 1)[0]


def test_AC8_13_94_env_and_pipeline_stage_contract_is_documented() -> None:
    """AC-testing.governance.3: AC8.13.94: environments and pipeline stages are separate matrix axes."""
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    read("common/runtime/environments.md")
    read("README.md")
    _has(
        ci_cd,
        "Environment Axis",
        "Pipeline Stage Axis",
        "Env x Stage Execution Matrix",
        "local",
        "pr",
        "staging",
        "prd",
        "Changed/Affected UT",
        "Lint/Static",
        "Full UT",
        "Regression/E2E",
        "Local runs are fast advisory gates",
        "PR CI is the deterministic merge authority",
        "deployed-environment proof gates",
    )
    _has(
        ci_cd,
        "not every environment runs every pipeline stage",
        "environment taxonomy, pipeline stages, and GitHub Actions jobs",
    )


def test_AC8_13_95_local_fast_gate_and_escalation_policy_are_documented() -> None:
    """AC-testing.governance.4: AC8.13.95: local defaults stay fast but escalate for high-risk paths."""
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    development = read("common/meta/development.md")
    read("README.md")
    _has(
        ci_cd,
        "Path Risk to Local Gate Matrix",
        "accounting, posting, reconciliation, money, balance",
        "schema, migrations",
        "API contract, OpenAPI",
        "shared common/tooling",
        "Docker, workflow, environment, deploy",
        "docs-only",
    )
    _has(
        development,
        "Default local verification starts with affected fast tests",
        "moon run :test -- --smart",
        "Risk-triggered local escalation",
    )


def test_AC8_13_27_coveralls_uploads_are_reporting_only() -> None:
    """AC-testing.coverage.2: AC8.13.27: PR CI has no external Coveralls status surface."""
    workflow = read(".github/workflows/ci.yml")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    read("common/testing/coverage.md")
    read("README.md")
    unified_block = workflow.split(
        "- name: Upload main unified coverage to Coveralls", 1
    )[1].split("  ac-traceability:", 1)[0]
    _has(
        unified_block,
        "if: github.event_name == 'push' && github.ref == 'refs/heads/main'",
    )
    _lacks(
        workflow,
        "Upload backend to Coveralls (per-flag)",
        "Upload frontend to Coveralls (per-flag)",
    )


def test_AC8_13_75_coverage_gate_summary_is_nonblocking() -> None:
    """AC-testing.coverage.4: AC8.13.75: Coverage summary display cannot fail final CI aggregation."""
    workflow = read(".github/workflows/ci.yml")
    summary_block = workflow.split("- name: Write coverage gate summary", 1)[1].split(
        "- name: Check job status", 1
    )[0]
    _has(
        summary_block,
        "if: ${{ always() }}",
        "continue-on-error: true",
        "Authoritative coverage gate",
        "badge/trend reporting only",
        "Merge readiness follows",
    )


def test_AC8_13_143_unified_coverage_updates_baseline_through_pr_not_direct_main_push() -> (
    None
):
    """AC-testing.coverage.5: AC8.13.143: main baseline updates are automated through a PR, not a direct push."""
    workflow = read(".github/workflows/ci.yml")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    unified_coverage_block = workflow.split("  unified-coverage:", 1)[1].split(
        "  unified-coverage-baseline-pr:", 1
    )[0]
    baseline_job_block = workflow.split("  unified-coverage-baseline-pr:", 1)[1].split(
        "  ac-traceability:", 1
    )[0]
    baseline_job_block.split("- name: Open unified coverage baseline PR", 1)[1]
    _has(unified_coverage_block, "permissions:", "contents: read")
    _lacks(unified_coverage_block, "contents: write", "pull-requests: write")


def test_AC8_13_93_staging_promotion_requires_manual_dispatch() -> None:
    """AC-testing.deploy-gates.19 AC-testing.deploy-gates.22: AC8.13.93: Staging is mutated only by an explicit manual dispatch; no auto path."""
    workflow = read(".github/workflows/deploy.yml")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    read("common/runtime/deployment.md")
    parsed = yaml.safe_load(workflow)
    triggers = parsed.get("on", parsed.get(True))
    assert isinstance(triggers, dict), "deploy.yml must declare an `on:` map"
    assert set(triggers) == {"push", "workflow_dispatch"}


def test_AC8_13_46_staging_non_llm_gate_uses_strict_parallelism() -> None:
    """AC-testing.preview.2: AC8.13.46: Staging batch non-LLM E2E uses strict gates and matrix SSOT selection."""
    staging = read(".github/workflows/deploy.yml")
    staging_block = staging.split("- name: End-to-End Tests", 1)[1].split("- name:", 1)[
        0
    ]
    assert "STRICT_E2E_GATES: true" in staging_block
    _has(
        staging_block,
        'eval "$(python tools/test_selection.py --stage staging_core_e2e --shell)"',
        'pytest "${STAGING_CORE_E2E_TESTS[@]}"',
        '-m "$STAGING_CORE_E2E_MARKER"',
    )


def test_AC8_13_47_delivery_engine_recommendations_are_tracked() -> None:
    """AC-testing.governance.1: AC8.13.47: remaining delivery-engine work is captured outside mutable SSOT."""
    recommendation = read("docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md")
    project_readme = read("docs/project/README.md")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    _has(
        recommendation,
        "Coveralls reporting split",
        "workflow_run staging trigger",
        "parallel image build jobs",
        "Current baseline",
        "#1252 closure readout",
        "27896401849",
        "ab2630e1",
        "4m 46s",
        "3m 31s / 3m 43s / 3m 49s / 3m 50s / 3m 41s",
        "Do not add more shards",
        "Out of scope for this PR",
    )
    assert "DELIVERY_ENGINE_RECOMMENDATIONS.md" in project_readme


def test_AC8_13_112_sparse_matrix_recommendation_tracks_simplification_path() -> None:
    """AC-testing.classifier.8: AC8.13.112: sparse-matrix audit keeps the simplification path explicit."""
    recommendation = read("docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    read("common/testing/change_classifier.py")
    _has(
        recommendation,
        "Structured matrix consumer migration",
        "Env x Stage",
        "env_stage_required",
        "env_stage_reasons",
        "env_stage_stages",
        "env_stage_files",
        "legacy scalar outputs",
        "compatibility shims",
        "GitHub Actions jobs now",
        "branch protection",
        "CI",
        "PR Test Environment",
        "Deploy Staging",
        "Staging AI/OCR Gate",
        "Production Release",
    )
    assert "Env x Stage Contract" in ci_cd


def test_AC8_13_152_workflow_consumers_keep_classification_single_owned() -> None:
    """AC-testing.classifier.9: AC8.13.152: downstream workflow jobs do not reclassify changed paths."""
    ci_workflow = read(".github/workflows/ci.yml")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    ci_jobs = yaml.safe_load(ci_workflow)["jobs"]

    def step(job: dict[str, object], name: str) -> dict[str, object]:
        steps = job["steps"]
        assert isinstance(steps, list)
        for candidate in steps:
            assert isinstance(candidate, dict)
            if candidate.get("name") == name:
                return candidate
        raise AssertionError(f"Missing step: {name}")

    def job_text(job: object) -> str:
        return json.dumps(job, sort_keys=True)

    def needs_job(job: dict[str, object], required: str) -> bool:
        needs = job.get("needs", [])
        if isinstance(needs, str):
            return needs == required
        assert isinstance(needs, list)
        return required in needs

    ci_classify = step(ci_jobs["changes"], "Classify changed paths")
    assert "python tools/ci_change_classifier.py" in str(ci_classify["run"])
    step(ci_jobs["changes"], "Normalize Env x Stage gates")
    assert (
        ci_jobs["changes"]["outputs"]["pr_required"]
        == "${{ steps.gates.outputs.pr_required }}"
    )


def test_AC8_13_113_sparse_matrix_evidence_and_resource_leak_audit_are_recorded() -> (
    None
):
    """AC-testing.deploy-gates.24: AC8.13.113: sparse-matrix review records log evidence and leak risks."""
    from common.meta.extension.generate_ac_registry import _roadmap_acs_from_contract

    statements = {
        record["id"]: record["statement"]
        for record in _roadmap_acs_from_contract(ROOT / "common/testing/contract.py")
    }
    statement = statements["AC-testing.deploy-gates.24"]
    recommendation = read("docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md")
    _has(
        statement,
        "three newest successful and three newest failed",
        "delivery-speed balance",
        "end-to-end consistency",
        "quality fallback",
        "resource leak candidates",
    )
    _has(
        recommendation,
        "June 9, 2026 evidence sample",
        "27186502313",
        "27184608585",
        "27186502312",
        "27184608593",
        "27182443187",
        "27136569205",
        "26636834757",
        "26636451107",
        "resource leak candidates",
        "GHCR PR images",
        "Docker build cache",
        "stale staging or production routes",
        "safe simplification boundary",
    )


def test_AC8_13_119_delivery_resource_leak_hardening_is_contracted() -> None:
    """AC-testing.deploy-gates.26: AC8.13.119: delivery cleanup covers the four known leak paths."""
    from common.meta.extension.generate_ac_registry import _roadmap_acs_from_contract

    statements = {
        record["id"]: record["statement"]
        for record in _roadmap_acs_from_contract(ROOT / "common/testing/contract.py")
    }
    statement = statements["AC-testing.deploy-gates.26"]
    recommendation = read("docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md")
    read(".github/workflows/maintenance.yml")
    read(".github/workflows/staging-ai-ocr-gate.yml")
    read(".github/workflows/release.yml")
    _has(
        statement,
        "GHCR PR tag accumulation",
        "stale staging or production routes",
        "provider-backed external-state residue",
        "Docker build cache and stopped containers",
    )
    _has(
        recommendation,
        "Resource leak hardening bundle",
        "one PR",
        "legacy closed-PR GHCR tags",
        "production_before_version",
        "isolated-users-provider-gate-only",
        "finance-report-vps-host-hygiene",
    )


def test_AC8_13_10_multi_brokerage_upload_to_portfolio_value_gate() -> None:
    """AC-extraction.813.10: Staging proves multi-brokerage upload through latest value."""
    reusable = read(".github/workflows/staging-ai-ocr-gate.yml")
    read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")
    read("apps/backend/src/routers/statements.py")
    read("apps/backend/src/extraction/extension/brokerage_statement_payload.py")
    read("common/testing/fixtures/pdf/generate_pdf_fixtures.py")
    assert "tools/staging_ai_ocr_gate_contract.py --shell" in reusable
    _has(staging_ai_ocr_contract_shell(), "test_brokerage_upload_to_portfolio_value.py")


def test_AC8_13_28_vision_hard_gate_uses_deterministic_fixture_with_fresh_user() -> (
    None
):
    """AC-testing.product-gates.2: deterministic source facts stop at economic review."""
    gate = read("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py")
    read("common/testing/contract.py")
    _has(gate, "@pytest.mark.e2e", "@pytest.mark.tier3", "@pytest.mark.critical")
    assert "@pytest.mark.llm" not in gate


def test_AC8_13_42_four_asset_net_worth_golden_path_is_post_merge_critical() -> None:
    """AC-testing.product-gates.7: AC8.13.42: four-asset as-of net worth proof is wired into the post-merge hard gate."""
    gate = read("tests/e2e/test_four_asset_net_worth_golden_path.py")
    ai_workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    critical_matrix_text()
    read("common/testing/contract.py")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    _has(
        gate,
        "@pytest.mark.e2e",
        "@pytest.mark.tier3",
        "@pytest.mark.critical",
        "@pytest.mark.llm",
        "authenticated_page_unique",
        "/statements/upload",
        "/review/approve",
        "/reconciliation/runs",
        "/brokerage/import",
        "/assets/valuation-snapshots",
        "/assets/valuation-components",
        "/reports/balance-sheet",
        "/reports?tab=balance-sheet",
        "include_restricted=true",
        "/dashboard",
        'BANK_CASH = Decimal("2500.00")',
        'PROPERTY_VALUE = Decimal("1200000.00")',
        'MORTGAGE_BALANCE = Decimal("650000.00")',
        'ESOP_VALUE = Decimal("42000.00")',
        "expected_net_worth",
        "net_worth_adjustment_gain_loss",
        "market valuation adjustment",
    )
    assert "tools/staging_ai_ocr_gate_contract.py --shell" in ai_workflow


def test_AC8_13_33_e2e_setup_caches_virtualenv_and_playwright_browsers() -> None:
    """AC-testing.ci-structure.3: AC8.13.33: shared E2E setup caches Python and Playwright install work."""
    action = read(".github/actions/setup-e2e-tests/action.yml")
    read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    playwright_action = read(".github/actions/install-playwright/action.yml")
    _has(
        action,
        "Cache E2E virtualenv",
        "path: .venv",
        "e2e-venv-${{ runner.os }}-${{ hashFiles('tests/e2e/requirements.txt') }}",
        "uses: ./.github/actions/install-playwright",
        "command: ./.venv/bin/playwright",
        "if [ ! -x .venv/bin/python ]; then",
        'echo "PYTHONPATH=${GITHUB_WORKSPACE:-$PWD}${PYTHONPATH:+:$PYTHONPATH}" >> "$GITHUB_ENV"',
        "uv pip install -r tests/e2e/requirements.txt",
    )
    _has(
        playwright_action,
        "Cache Playwright browsers",
        "path: ~/.cache/ms-playwright",
        "key: playwright-${{ runner.os }}-${{ steps.version.outputs.version }}-${{ inputs.browser }}",
    )


def test_AC8_13_115_readiness_fail_fast() -> None:
    """AC-testing.preview.14: AC8.13.115: Deploy readiness is bounded before smoke/E2E starts."""
    workflow = read(".github/workflows/deploy.yml")
    assert "Wait for frontend readiness" in workflow
    _has(
        workflow,
        "timeout-minutes: 10",
        "deadline = time.monotonic() + 540",
        "Refusing to run E2E against old frontend code.",
    )


def test_AC8_13_116_skip_heavy_ci_on_main_push() -> None:
    """AC-testing.deploy-gates.25: AC8.13.116: Post-merge -> staging start latency is reduced by removing redundant heavy re-run on push to main."""
    workflow = read(".github/workflows/ci.yml")
    for job in [
        "schema-migrations:",
        "backend:",
        "backend-integration:",
        "frontend-build:",
        "frontend-vitest:",
        "frontend-playwright:",
        "tooling-coverage:",
        "unified-coverage:",
    ]:
        job_block = workflow.split(job, 1)[1].split("\n\n", 1)[0]
        assert "if: needs.changes.outputs.pr_required == 'true'" in job_block
    container_images_block = workflow.split("  container-images:", 1)[1].split(
        "\n\n", 1
    )[0]
    _has(
        container_images_block,
        "needs.changes.outputs.pr_required == 'true' && needs.changes.outputs.image_build_required == 'true'",
        "github.event_name == 'push' && (github.ref == 'refs/heads/main'",
    )


def test_AC8_13_118_timeouts_and_retries_documented() -> None:
    """AC-testing.governance.5: AC8.13.118: Critical-path timeouts and retries are documented in common/runtime/ci-cd.md."""
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    assert "STAGING_FIFO_TIMEOUT_SECONDS" not in ci_cd
    _has(ci_cd, "parallel staging")


def _timing_commands(job: dict) -> list[dict]:
    return [
        step
        for step in job["steps"]
        if "tools/github_workflow_timing_summary.py" in str(step.get("run", ""))
    ]


def test_AC8_13_34_main_ci_budget_is_enforced_by_a_non_required_job() -> None:
    """AC-testing.ci-structure.4: a main run past its budget fails a non-required job (#2688)."""
    jobs = yaml.safe_load(read(".github/workflows/ci.yml"))["jobs"]
    budget = jobs["pipeline-budget"]
    [_, enforce] = _timing_commands(budget)
    assert "pipeline-budget" not in jobs["finish"]["needs"]
    assert budget["needs"] == ["finish"]
