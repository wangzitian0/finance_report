import io
import json
import re
import subprocess
import sys
import urllib.error
from datetime import timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def build_critical_matrix() -> dict:
    """Build the critical-proof matrix payload in-memory from the AC graph.

    The matrix is a derived (not committed) view of the one AC-keyed graph, so
    tests read the freshly-built payload instead of a checked-in YAML file.
    """
    from common.ssot.ac_graph import build_ac_graph
    from common.ssot.generate_critical_proof_matrix import build_matrix_from_graph

    return build_matrix_from_graph(build_ac_graph(ROOT))


def critical_matrix_text() -> str:
    """Render the in-memory critical-proof matrix to its canonical YAML text."""
    from common.ssot.generate_critical_proof_matrix import render_matrix

    return render_matrix(build_critical_matrix())


def critical_post_merge_llm_proof_files() -> list[str]:
    matrix = build_critical_matrix()
    return sorted(
        {
            proof["file"]
            for proof in matrix["proofs"]
            if proof["ci_tier"] == "post_merge_environment"
            and "llm" in proof["required_markers"]
        }
    )


def staging_ai_ocr_contract_shell() -> str:
    return subprocess.check_output(
        [
            sys.executable,
            "tools/staging_ai_ocr_gate_contract.py",
            "--shell",
        ],
        cwd=ROOT,
        text=True,
    )


def test_AC8_13_13_post_merge_train_waits_only_for_older_active_runs() -> None:
    """AC8.13.13: FIFO train gate waits for older active staging runs only."""
    from common.ci.wait_post_merge_train_turn import (
        older_active_runs,
        workflow_run_from_payload,
    )

    def run_payload(run_id: int, status: str, created_at: str) -> dict[str, object]:
        return {
            "id": run_id,
            "status": status,
            "conclusion": None if status != "completed" else "success",
            "created_at": created_at,
            "html_url": f"https://github.test/runs/{run_id}",
            "display_title": f"run-{run_id}",
        }

    current = workflow_run_from_payload(
        run_payload(20, "in_progress", "2026-06-05T04:20:00Z")
    )
    runs = [
        workflow_run_from_payload(run_payload(10, "completed", "2026-06-05T04:10:00Z")),
        workflow_run_from_payload(
            run_payload(11, "in_progress", "2026-06-05T04:11:00Z")
        ),
        workflow_run_from_payload(run_payload(12, "queued", "2026-06-05T04:12:00Z")),
        workflow_run_from_payload(
            run_payload(30, "in_progress", "2026-06-05T04:30:00Z")
        ),
        current,
    ]

    blockers = older_active_runs(current, runs)

    assert [run.run_id for run in blockers] == [11, 12]
    assert current.created_at.tzinfo is timezone.utc


def test_AC8_13_13_post_merge_train_waits_until_blockers_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.13: FIFO gate polls until older active runs are gone."""
    from common.ci import wait_post_merge_train_turn as train

    current_payload = {
        "id": 20,
        "workflow_id": 100,
        "status": "in_progress",
        "conclusion": None,
        "created_at": "2026-06-05T04:20:00Z",
        "html_url": "https://github.test/runs/20",
        "display_title": "current",
    }
    blocking_payload = {
        "id": 10,
        "status": "queued",
        "conclusion": None,
        "created_at": "2026-06-05T04:10:00Z",
        "html_url": "https://github.test/runs/10",
        "display_title": "blocking",
    }

    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        def get_run_payload(self, run_id: int) -> dict[str, object]:
            assert run_id == 20
            return current_payload

        def list_workflow_runs(self, workflow_id: int) -> list[dict[str, object]]:
            assert workflow_id == 100
            self.calls += 1
            if self.calls == 1:
                return [current_payload, blocking_payload]
            return [current_payload]

    monotonic_values = iter([0.0, 1.0])
    sleeps: list[int] = []
    monkeypatch.setattr(train.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(train.time, "sleep", sleeps.append)

    output = io.StringIO()
    train.wait_for_train_turn(
        client=FakeClient(),
        run_id=20,
        timeout_seconds=30,
        poll_seconds=5,
        output=output,
    )

    assert sleeps == [5]
    assert "waiting for 1 older run(s): 10:queued" in output.getvalue()
    assert "front of the train" in output.getvalue()


def test_AC8_13_13_post_merge_train_timeout_lists_blockers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.13: FIFO timeout reports the blocking run URLs."""
    from common.ci import wait_post_merge_train_turn as train

    current_payload = {
        "id": 20,
        "workflow_id": 100,
        "status": "in_progress",
        "conclusion": None,
        "created_at": "2026-06-05T04:20:00Z",
        "html_url": "https://github.test/runs/20",
        "display_title": "current",
    }
    blocking_payload = {
        "id": 10,
        "status": "waiting",
        "conclusion": None,
        "created_at": "2026-06-05T04:10:00Z",
        "html_url": "https://github.test/runs/10",
        "display_title": "blocking",
    }

    class FakeClient:
        def get_run_payload(self, run_id: int) -> dict[str, object]:
            assert run_id == 20
            return current_payload

        def list_workflow_runs(self, workflow_id: int) -> list[dict[str, object]]:
            assert workflow_id == 100
            return [current_payload, blocking_payload]

    monkeypatch.setattr(train.time, "monotonic", lambda: 0.0)

    with pytest.raises(TimeoutError) as exc_info:
        train.wait_for_train_turn(
            client=FakeClient(),
            run_id=20,
            timeout_seconds=5,
            poll_seconds=6,
            output=io.StringIO(),
        )

    assert "Timed out waiting" in str(exc_info.value)
    assert "10 waiting https://github.test/runs/10" in str(exc_info.value)


def test_AC8_13_13_github_actions_client_pages_workflow_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.13: GitHub client follows workflow-run pagination."""
    from common.ci.wait_post_merge_train_turn import GitHubActionsClient

    requested_urls: list[str] = []

    class FakeResponse:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = payload

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        assert timeout == 20
        assert hasattr(request, "full_url")
        requested_urls.append(request.full_url)
        page = "page=2" in request.full_url
        batch_size = 2 if page else 100
        return FakeResponse(
            {
                "workflow_runs": [
                    {"id": index, "created_at": "2026-06-05T04:00:00Z"}
                    for index in range(batch_size)
                ]
            }
        )

    monkeypatch.setattr(
        "common.ci.wait_post_merge_train_turn.urllib.request.urlopen",
        fake_urlopen,
    )

    client = GitHubActionsClient(
        repository="owner/repo", token="token", api_url="https://api.github.test/"
    )
    runs = client.list_workflow_runs(123)

    assert len(runs) == 102
    assert requested_urls == [
        "https://api.github.test/repos/owner/repo/actions/workflows/123/runs?per_page=100&page=1",
        "https://api.github.test/repos/owner/repo/actions/workflows/123/runs?per_page=100&page=2",
    ]


def test_AC8_13_13_github_actions_client_reports_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.13: GitHub API failures stay readable in CI logs."""
    from common.ci.wait_post_merge_train_turn import GitHubActionsClient

    def fake_urlopen(_request: object, timeout: int) -> object:
        assert timeout == 20
        raise urllib.error.HTTPError(
            url="https://api.github.test/fail",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"denied"}'),
        )

    monkeypatch.setattr(
        "common.ci.wait_post_merge_train_turn.urllib.request.urlopen",
        fake_urlopen,
    )

    client = GitHubActionsClient(
        repository="owner/repo", token="token", api_url="https://api.github.test"
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.get_run_payload(20)

    assert "GitHub API HTTP 403" in str(exc_info.value)
    assert "denied" in str(exc_info.value)


def test_AC8_13_13_post_merge_train_cli_validates_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.13: CLI exits clearly when GitHub context is missing."""
    from common.ci.wait_post_merge_train_turn import main

    assert main(["--repository", "", "--run-id", "0", "--token", ""]) == 2

    captured = capsys.readouterr()
    assert "Missing required GitHub context: repository, run-id, token" in captured.err


def test_AC8_13_13_post_merge_train_cli_handles_runtime_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.13: CLI returns failure without a Python traceback."""
    from common.ci import wait_post_merge_train_turn as train

    class FakeClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

    def fail_wait(**_kwargs: object) -> None:
        raise RuntimeError("api unavailable")

    monkeypatch.setattr(train, "GitHubActionsClient", FakeClient)
    monkeypatch.setattr(train, "wait_for_train_turn", fail_wait)

    assert (
        train.main(
            [
                "--repository",
                "owner/repo",
                "--run-id",
                "20",
                "--token",
                "token",
            ]
        )
        == 1
    )

    captured = capsys.readouterr()
    assert captured.err.strip() == "api unavailable"


def row_covers_ac_id(row: str, ac_id: str) -> bool:
    if ac_id in row:
        return True

    ac_match = re.fullmatch(r"(AC\d+\.\d+\.)(\d+)", ac_id)
    if not ac_match:
        return False
    ac_prefix, ac_number = ac_match.group(1), int(ac_match.group(2))

    for range_match in re.finditer(r"(AC\d+\.\d+\.)(\d+)-AC\d+\.\d+\.(\d+)", row):
        prefix, start, end = range_match.groups()
        if prefix == ac_prefix and int(start) <= ac_number <= int(end):
            return True
    return False


def test_AC8_13_50_critical_proof_e2e_files_are_epic_owned() -> None:
    """AC8.13.50: Critical proof E2E files stay listed in EPIC-008 ownership."""
    proof_matrix = build_critical_matrix()
    epic = read("docs/project/EPIC-008.testing-strategy.md")

    proof_files = {
        proof["file"]: proof["ac_ids"]
        for proof in proof_matrix["proofs"]
        if proof["file"].startswith(("tests/e2e/", "apps/backend/tests/e2e/"))
    }

    assert proof_files
    epic_rows = {
        path: line
        for line in epic.splitlines()
        for path in proof_files
        if f"`{path}`" in line
    }
    assert [path for path in proof_files if path not in epic_rows] == []
    assert {
        path: [
            ac_id for ac_id in ac_ids if not row_covers_ac_id(epic_rows[path], ac_id)
        ]
        for path, ac_ids in proof_files.items()
        if any(not row_covers_ac_id(epic_rows[path], ac_id) for ac_id in ac_ids)
    } == {}


def test_AC8_13_50_product_e2e_files_are_epic_owned() -> None:
    """AC8.13.50: Product E2E test files stay owned by EPIC-008."""
    epic = read("docs/project/EPIC-008.testing-strategy.md")
    product_e2e_files = sorted(
        path.relative_to(ROOT).as_posix()
        for root in [
            ROOT / "tests" / "e2e",
            ROOT / "apps" / "backend" / "tests" / "e2e",
        ]
        for path in root.glob("test_*.py")
    )

    assert product_e2e_files
    assert [path for path in product_e2e_files if f"`{path}`" not in epic] == []


def test_AC8_13_1_to_5_full_statement_journey_contract() -> None:
    """AC8.13.1 AC8.13.2 AC8.13.3 AC8.13.4 AC8.13.5: Full DBS journey is wired."""
    journey = read("tests/e2e/test_statement_full_journey.py")
    test_body = journey.split("async def test_dbs_statement_full_journey", 1)[1]

    assert "DBS PDF upload" in journey
    assert "# === AC8.13.1: Upload PDF ===" in test_body
    assert "Upload & Parse Statement" in test_body
    assert "# === AC8.13.2: Poll until" in test_body
    assert 'a[href="/statements/{statement_id}"]' in test_body
    assert "filter(has_text=INSTITUTION_LABEL).first" not in test_body
    assert '"parsed"' in test_body
    assert "# === AC8.13.3: Detail page shows transactions ===" in test_body
    assert "Transactions" in test_body
    assert "# === AC8.13.4: Start Review" in test_body
    assert "approved" in test_body
    assert "# === AC8.13.5: Balance sheet report loads ===" in test_body
    assert "/reports/balance-sheet" in test_body


def test_AC8_10_8_registration_flow_accepts_current_landing_route() -> None:
    """AC8.10.8 AC16.12.6 AC1.7.1: registration E2E follows current auth landing route."""
    flow = read("tests/e2e/test_e2e_flows.py")
    test_body = flow.split("async def test_registration_flow", 1)[1]

    assert 'page.expect_response("**/api/auth/register")' in test_body
    assert "await expect(page).to_have_url(AUTH_LANDING_URL_PATTERN" in test_body
    assert 'page.wait_for_url("**/dashboard"' not in test_body
    assert '"/dashboard" in page.url' not in test_body


def test_AC8_13_6_critical_e2e_skips_become_failures() -> None:
    """AC8.13.6: Critical staging E2E skips fail the deploy gate."""
    conftest = read("tests/e2e/conftest.py")

    assert "pytest_runtest_makereport" in conftest
    assert "fail_or_skip_ai_ocr_gate" in conftest
    assert "critical" in conftest
    assert 'report.outcome = "failed"' in conftest
    assert "Critical E2E gate skipped" in conftest


def test_AC8_13_7_full_statement_journey_is_a_hard_ai_ocr_gate() -> None:
    """AC8.13.7: Full statement journey fails on rejected AI/OCR parsing."""
    journey = read("tests/e2e/test_statement_full_journey.py")
    test_body = journey.split("async def test_dbs_statement_full_journey", 1)[1]

    assert "@pytest.mark.critical" in journey
    assert "fail_or_skip_ai_ocr_gate(" in test_body
    assert "status=rejected" in test_body
    assert "/api/statements/{statement_id}" in test_body
    assert "validation_error" in read("tests/e2e/conftest.py")
    assert "Last statement payload" in test_body
    assert "pytest.skip(" not in test_body


def test_AC8_13_8_upload_readiness_gate_rejects_rejected_status() -> None:
    """AC8.13.8: Upload readiness E2E does not accept rejected statements."""
    upload = read("tests/e2e/test_statement_upload_e2e.py")
    test_body = upload.split("async def test_statement_upload_full_flow", 1)[1].split(
        "@pytest.mark.e2e", 1
    )[0]

    assert "AI/OCR readiness gate" in test_body
    assert "fail_or_skip_ai_ocr_gate(" in test_body
    assert "statement=statement" in test_body
    assert '"rejected"' not in test_body.split("assert status in", 1)[1]


def test_AC8_13_11_health_check_diagnoses_staging_api_route_404() -> None:
    """AC8.13.11: Staging health 404 reports API route diagnostics."""
    health_check = read("tools/_lib/shell/health_check.sh")

    assert "print_health_route_probe" in health_check
    assert "route_probe attempt=" in health_check
    assert "platform_failure_domain=traefik-public-route" in health_check
    assert "api_status=$api_status" in health_check
    assert "frontend_status=$frontend_status" in health_check
    assert "print_404_route_diagnostics" in health_check
    assert "Traefik API route is missing or shadowed" in health_check
    assert 'probe_route "API ping" "$APP_BASE_URL/api/ping"' in health_check
    assert 'probe_route "Frontend shell" "$APP_BASE_URL/"' in health_check
    assert '[[ "$http_code" == "404" ]]' in health_check


def test_AC8_13_11_deploy_preflights_vault_token_before_redeploy() -> None:
    """AC8.13.11: Staging deploy fails before redeploy when Vault token is invalid."""
    common = read("common/shell/common.sh")
    deploy_script = read("tools/_lib/shell/dokploy_deploy.sh")

    assert "verify_vault_app_token()" in common
    assert "auth/token/lookup-self" in common
    assert "VAULT_APP_TOKEN is invalid or expired" in common
    assert "VAULT_APP_TOKEN is not renewable" in common
    assert "ttl ${ttl}s is below required" in common
    assert (
        "DEPLOY_ENV=${repair_env} invoke vault.setup-tokens --project=finance_report --service=app"
        in common
    )
    assert "Do not add VAULT_ROOT_TOKEN to GitHub Actions" in common
    assert (
        'verify_vault_app_token "$current_env" "Dokploy VAULT_APP_TOKEN preflight" 172800 "$vault_repair_env"'
        in deploy_script
    )
    assert 'vault_repair_env="staging"' in deploy_script
    assert deploy_script.index("verify_vault_app_token") < deploy_script.index(
        'dokploy_api_call "POST" "compose.update"'
    )


def test_AC8_13_12_ai_ocr_gate_failure_includes_statement_context() -> None:
    """AC8.13.12: AI/OCR gate failures include statement validation context."""
    conftest = read("tests/e2e/conftest.py")
    journey = read("tests/e2e/test_statement_full_journey.py")
    upload = read("tests/e2e/test_statement_upload_e2e.py")
    brokerage = read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")
    four_asset = read("tests/e2e/test_four_asset_net_worth_golden_path.py")

    assert "format_ai_ocr_gate_failure" in conftest
    for token in (
        "validation_error",
        "confidence_score",
        "parsing_progress",
        "balance_validated",
    ):
        assert token in conftest
    assert "model=default_model" in journey
    assert "statement=last_statement" in journey
    assert "statement=statement" in upload
    assert "statement=last_payload" in brokerage
    assert "fail_or_skip_ai_ocr_gate(" in four_asset


def test_AC8_13_13_staging_deploy_fast_fail_guardrails() -> None:
    """AC8.13.13 AC8.13.105: Staging deploy is a singleton post-merge train."""
    workflow = read(".github/workflows/staging-deploy.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "concurrency:" in workflow
    assert "group: staging-deploy" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "post-merge-train-turn:" not in workflow
    assert "classify-staging:" not in workflow
    # Manual-only staging is serialized by the workflow-level concurrency group;
    # the in-job FIFO post-merge train wait (which only applied to the retired
    # workflow_run auto-deploy) is removed.
    assert "name: Wait for FIFO post-merge train turn" not in workflow
    assert "wait_post_merge_train_turn.py" not in workflow
    assert "name: Classify staging and AI/OCR relevance" in workflow
    assert "staging_required: ${{ steps.gates.outputs.staging_required }}" in workflow
    assert "provider_gate_required" in workflow
    assert (
        "staging-post-merge-${{ github.event.workflow_run.head_branch || github.ref_name }}"
        not in workflow
    )
    assert "timeout-minutes: 75" in workflow
    assert "timeout-minutes: 22" in workflow
    assert "run_timed_phase()" in workflow
    assert "[phase:start]" in workflow
    assert "[phase:end]" in workflow
    assert "duration=%ss" in workflow
    assert 'run_timed_phase "Phase 1: Smoke Check (Shell)"' in workflow
    assert 'run_timed_phase "Phase 2: Core Flow Validation (Python)"' in workflow
    assert "in-job FIFO" not in ci_cd
    assert "workflow-level singleton concurrency" in ci_cd
    assert "No two `Deploy Staging` workflow runs mutate staging concurrently" not in ci_cd
    assert "only one `Deploy Staging` run mutates staging at a time" in ci_cd
    assert "75-minute deploy-health job timeout" in ci_cd
    assert "22-minute E2E step timeout" in ci_cd


def test_AC8_13_13_main_ci_keeps_each_merge_commit_run() -> None:
    """AC8.13.13: Main push CI uses SHA-scoped concurrency."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert (
        "group: ${{ github.workflow }}-${{ github.event_name == 'pull_request' && github.ref || github.event_name == 'push' && github.sha || github.run_id }}"
        in workflow
    )
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in workflow
    assert "Pushes to `main` use a SHA-scoped concurrency" in ci_cd
    assert "do not cancel or replace a pending main CI" in ci_cd


def test_AC8_13_14_staging_ai_ocr_gate_is_separate_deploy_job() -> None:
    """AC8.13.14: Provider-backed AI/OCR gate runs outside deploy health."""
    deploy_workflow = read(".github/workflows/staging-deploy.yml")
    ai_workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "ai-ocr-gate:" in deploy_workflow
    assert "needs: [build-and-deploy, provider-gate]" in deploy_workflow
    assert (
        "if: ${{ always() && needs.build-and-deploy.outputs.staging_required == 'true' && needs.build-and-deploy.outputs.ai_ocr_required == 'true' && needs.provider-gate.outputs.provider_status == 'pass' }}"
        in deploy_workflow
    )
    assert "name: Staging AI/OCR Gate" in deploy_workflow
    assert "commit_full_sha: ${{ steps.get_sha.outputs.full_sha }}" in deploy_workflow
    assert (
        "ref: ${{ needs.build-and-deploy.outputs.commit_full_sha }}" in deploy_workflow
    )
    assert "PARSING_TIMEOUT_MS: 480000" in deploy_workflow
    assert (
        "EXPECTED_SHA: ${{ needs.build-and-deploy.outputs.commit_sha }}"
        in deploy_workflow
    )
    assert 'run_timed_phase "Staging AI/OCR Gate' in deploy_workflow
    assert "tools/staging_ai_ocr_gate_contract.py --shell" in deploy_workflow
    assert 'pytest "${STAGING_AI_OCR_TESTS[@]}"' in deploy_workflow
    assert '-v -m "llm"' in deploy_workflow
    deploy_e2e_block = deploy_workflow.split("name: End-to-End Tests", 1)[1].split(
        "name: AI Provider Connectivity Smoke", 1
    )[0]
    assert '-v -m "llm"' not in deploy_e2e_block
    assert "name: Staging AI/OCR Gate" in ai_workflow
    assert 'workflows: ["Deploy Staging"]' not in ai_workflow
    assert "workflow_dispatch:" in ai_workflow
    assert "group: staging-manual-ai-ocr-${{ github.ref }}" in ai_workflow
    assert "cancel-in-progress: false" in ai_workflow
    assert "timeout-minutes: 22" in ai_workflow
    assert "STRICT_E2E_GATES: true" in ai_workflow
    assert "PARSING_TIMEOUT_MS: 480000" in ai_workflow
    assert "EXPECTED_SHA: ${{ steps.expected_sha.outputs.short_sha }}" in ai_workflow
    assert "test_version_check.py" in ai_workflow
    assert "tools/staging_ai_ocr_gate_contract.py --shell" in ai_workflow
    assert 'pytest "${STAGING_AI_OCR_TESTS[@]}"' in ai_workflow
    assert '-v -m "llm"' in ai_workflow
    assert "same serialized post-merge workflow unit" in ci_cd
    assert "manual recovery entry point" in ci_cd


def test_AC8_13_49_staging_ai_ocr_gate_publishes_audit_inventory_and_summary() -> None:
    """AC8.13.49: Staging AI/OCR gates publish replay inputs and summary fields."""
    deploy_workflow = read(".github/workflows/staging-deploy.yml")
    ai_workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    observability = read("docs/ssot/observability-logging.md")

    for workflow in (deploy_workflow, ai_workflow):
        assert "write_staging_audit_inventory()" in workflow
        assert "write_staging_audit_result()" in workflow
        assert "## Staging Audit Replay Inputs" in workflow
        assert "## Staging Audit Replay Summary" in workflow
        assert "- Environment: staging" in workflow
        assert "- GitHub run ID: ${{ github.run_id }}" in workflow
        assert "- Expected SHA: ${EXPECTED_SHA}" in workflow
        assert "- Backend image tag:" in workflow
        assert "- Frontend image tag:" in workflow
        assert (
            "- Models: primary=${STAGING_E2E_PRIMARY_MODEL}, ocr=${STAGING_E2E_OCR_MODEL}, vision=${STAGING_E2E_VISION_MODEL}"
            in workflow
        )
        assert "- Expected uploads: ${STAGING_AI_OCR_EXPECTED_UPLOADS}" in workflow
        assert (
            "- Expected parse completions: ${STAGING_AI_OCR_EXPECTED_PARSE_COMPLETIONS}"
            in workflow
        )
        assert (
            "- Expected brokerage imports: ${STAGING_AI_OCR_EXPECTED_BROKERAGE_IMPORTS}"
            in workflow
        )
        assert (
            "- Expected report verifications: ${STAGING_AI_OCR_EXPECTED_REPORT_VERIFICATIONS}"
            in workflow
        )
        assert "- Expected failures: 0" in workflow
        assert "- Uploads verified: ${verified_uploads}" in workflow
        assert "- Parse completions verified: ${verified_parse_completions}" in workflow
        assert "- Brokerage imports verified: ${verified_brokerage_imports}" in workflow
        assert (
            "- Report verifications verified: ${verified_report_verifications}"
            in workflow
        )
        assert "- Failures observed: ${verified_failures}" in workflow
        assert "for fixture_test in" in workflow
        assert "${STAGING_AI_OCR_TESTS[@]}" in workflow
        assert "GITHUB_STEP_SUMMARY" in workflow
        assert "- Expected uploads: 7" not in workflow
        assert "- Expected parse completions: 7" not in workflow
        assert "- Expected brokerage imports: 3" not in workflow
        assert "- Expected report verifications: 1" not in workflow

    assert deploy_workflow.index(
        "write_staging_audit_inventory"
    ) < deploy_workflow.index('run_timed_phase "Staging AI/OCR Version Check"')
    assert ai_workflow.index("write_staging_audit_inventory") < ai_workflow.index(
        'run_timed_phase "Staging AI/OCR Version Check"'
    )
    assert "Staging Audit Replay Contract" in observability
    assert "deployment-level inputs" in observability


def test_AC8_13_49_staging_ai_ocr_contract_outputs_files_and_counts() -> None:
    """AC8.13.49: Staging AI/OCR replay contract has one file/count source."""
    shell = staging_ai_ocr_contract_shell()
    match = re.search(r"^STAGING_AI_OCR_TESTS=\((?P<files>.+)\)$", shell, re.M)
    assert match is not None
    files = match.group("files").split()

    for token in (
        "tests/e2e/test_statement_full_journey.py",
        "tests/e2e/test_brokerage_upload_to_portfolio_value.py",
        "tests/e2e/test_four_asset_net_worth_golden_path.py",
        "tests/e2e/test_personal_financial_report_package.py",
        "tests/e2e/test_statement_upload_e2e.py",
        "STAGING_AI_OCR_EXPECTED_UPLOADS=9",
        "STAGING_AI_OCR_EXPECTED_PARSE_COMPLETIONS=9",
        "STAGING_AI_OCR_EXPECTED_BROKERAGE_IMPORTS=4",
        "STAGING_AI_OCR_EXPECTED_REPORT_VERIFICATIONS=2",
    ):
        assert token in shell
    assert len(files) == len(set(files))
    assert files == sorted(files)


def test_AC8_13_50_critical_llm_post_merge_proofs_are_in_ai_ocr_gates() -> None:
    """AC8.13.50: Critical LLM post-merge proofs are executed by AI/OCR gates."""
    proof_files = critical_post_merge_llm_proof_files()
    shell = staging_ai_ocr_contract_shell()
    assert proof_files == [
        "tests/e2e/test_brokerage_upload_to_portfolio_value.py",
        "tests/e2e/test_four_asset_net_worth_golden_path.py",
        "tests/e2e/test_personal_financial_report_package.py",
        "tests/e2e/test_statement_full_journey.py",
    ]

    for workflow_path in (
        ".github/workflows/staging-deploy.yml",
        ".github/workflows/staging-ai-ocr-gate.yml",
    ):
        workflow = read(workflow_path)
        assert "tools/staging_ai_ocr_gate_contract.py --shell" in workflow
        assert 'pytest "${STAGING_AI_OCR_TESTS[@]}"' in workflow

    missing = [proof_file for proof_file in proof_files if proof_file not in shell]
    assert missing == []


def test_AC8_13_76_ci_environment_gates_publish_failure_path_context() -> None:
    """AC8.13.76: CI and deploy gates upload replayable status context."""
    ci = read(".github/workflows/ci.yml")
    pr_preview = read(".github/workflows/pr-test.yml")
    staging = read(".github/workflows/staging-deploy.yml")
    manual_ai = read(".github/workflows/staging-ai-ocr-gate.yml")
    production = read(".github/workflows/production-release.yml")
    cleanup = read(".github/workflows/pr-preview-cleanup.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    for token in (
        "backend-shard-${{ matrix.shard }}-test-context",
        "backend-integration-test-context",
        "backend-tier1-e2e-test-context",
        "frontend-test-context",
        "AC-TRACEABILITY-CONTEXT.md",
    ):
        assert token in ci
    assert "--junit-xml=test-results/backend-shard-${{ matrix.shard }}.xml" in ci
    assert "--junit-xml=test-results/backend-integration.xml" in ci
    assert "--junit-xml=test-results/backend-tier1-e2e.xml" in ci
    assert "test-results/vitest-junit.xml" in ci
    assert "apps/frontend/playwright-report/" in ci
    assert "if: ${{ always() }}" in ci.split("Upload backend shard test context", 1)[0]

    assert "pr-preview-test-context" in pr_preview
    # Full runtime/API/UI E2E now runs image-free in the in-runner `e2e` job
    # (issue #839) after successful PR CI. Its junit lives here.
    assert "test-results/in-runner-e2e.xml" in pr_preview
    assert "ci-context/pr-preview-context.txt" in pr_preview
    assert "preview_runtime=github-runner-compose" in pr_preview
    assert (
        "persistent_preview_url=${{ needs.setup.outputs.preview_app_url }}"
        in pr_preview
    )
    assert "registry_image_push=false" in pr_preview
    assert "dokploy_deploy=after-e2e-non-blocking-build-from-source" in pr_preview
    assert "e2e_outcome=${{ steps.e2e_tests.outcome }}" in pr_preview

    assert "staging-deploy-test-context" in staging
    assert "test-results/staging-core-e2e.xml" in staging
    assert "ci-context/staging-deploy-context.txt" in staging
    assert (
        "failure_domain=${{ steps.deploy_failure_context.outputs.failure_domain }}"
        in staging
    )
    assert (
        "failed_step=${{ steps.deploy_failure_context.outputs.failed_step }}" in staging
    )
    assert (
        "failure_summary=${{ steps.deploy_failure_context.outputs.failure_summary }}"
        in staging
    )
    assert "staging-ai-ocr-test-context" in staging
    assert "test-results/staging-ai-ocr-version.xml" in staging
    assert "test-results/staging-ai-ocr-gate.xml" in staging
    assert "primary_model=${STAGING_E2E_PRIMARY_MODEL}" in staging

    assert "staging-ai-ocr-test-context" in manual_ai
    assert "ci-context/staging-ai-ocr-context.txt" in manual_ai
    assert "test-results/staging-ai-ocr-gate.xml" in manual_ai

    assert "production-release-build-context" in production
    assert "production-dry-run-context" in production
    assert "production-deploy-test-context" in production
    assert "test-results/production-readonly-e2e.xml" in production

    assert "pr-preview-scheduled-cleanup-context" in cleanup
    assert "cleanup_action=reconcile" in cleanup

    assert "CI observability artifacts" in ci_cd
    assert "Step summaries remain human-readable status pages" in ci_cd


def test_AC8_13_51_staging_deploy_is_manual_dispatch_only() -> None:
    """AC8.13.51: Staging deploy is manual (`workflow_dispatch`) only; it does not auto-follow main CI."""
    workflow = read(".github/workflows/staging-deploy.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    parsed = yaml.safe_load(workflow)
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = parsed.get("on", parsed.get(True))
    assert isinstance(triggers, dict), "staging-deploy.yml must declare an `on:` map"
    assert "workflow_dispatch" in triggers, (
        "staging deploy must be manually dispatchable"
    )
    assert "workflow_run" not in triggers, (
        "staging deploy must NOT auto-follow CI (manual-only)"
    )
    assert "ref" in (triggers["workflow_dispatch"].get("inputs") or {}), (
        "manual dispatch must accept a `ref` input to deploy any commit"
    )
    # The deploy job still must not poll/wait for CI inside the job.
    assert "wait_for_github_ci.py" not in workflow
    # SSOT reflects the manual staging deploy policy.
    assert "Staging deploy is manual" in ci_cd


def test_AC8_13_103_post_merge_delivery_summary_check_aggregates_staging_gates() -> (
    None
):
    """AC8.13.103/AC8.13.108: Delivery aggregates gates and failure context."""
    workflow = read(".github/workflows/staging-deploy.yml")
    ci_cd = read("docs/ssot/ci-cd.md")
    epic = read("docs/project/EPIC-008.testing-strategy.md")

    assert "post-merge-delivery:" in workflow
    assert "name: Post-merge Delivery" in workflow
    assert ("needs: [build-and-deploy, provider-gate, ai-ocr-gate]") in workflow
    assert "Aggregate post-merge delivery result" in workflow
    assert (
        'staging_required="${{ needs.build-and-deploy.outputs.staging_required }}"'
        in workflow
    )
    assert (
        'ai_ocr_required="${{ needs.build-and-deploy.outputs.ai_ocr_required }}"'
        in workflow
    )
    assert 'build_result="${{ needs.build-and-deploy.result }}"' in workflow
    assert 'provider_result="${{ needs.provider-gate.result }}"' in workflow
    assert (
        'provider_status="${{ needs.provider-gate.outputs.provider_status }}"'
        in workflow
    )
    assert 'ai_ocr_result="${{ needs.ai-ocr-gate.result }}"' in workflow
    # The retired post-merge auto-deploy alert job is no longer a delivery input.
    assert "staging-deploy-alert" not in workflow
    assert "alert_result" not in workflow
    assert (
        'failure_domain="${{ needs.build-and-deploy.outputs.failure_domain }}"'
        in workflow
    )
    assert 'failed_step="${{ needs.build-and-deploy.outputs.failed_step }}"' in workflow
    assert (
        'failure_summary="${{ needs.build-and-deploy.outputs.failure_summary }}"'
        in workflow
    )
    assert 'delivery_status="skipped-no-staging-required"' in workflow
    assert (
        '[ "$ai_ocr_required" = "true" ] && [ "$ai_ocr_result" != "success" ]'
        in workflow
    )
    assert 'failure_reason="build/deploy gate failed"' in workflow
    assert 'failure_reason="provider connectivity gate failed"' in workflow
    assert 'failure_reason="staging AI/OCR gate failed"' in workflow
    assert 'delivery_status="degraded-provider"' in workflow
    assert "## Post-merge Delivery" in workflow
    assert "Build/deploy failure domain: ${failure_domain:-unknown}" in workflow
    assert "Build/deploy failed step: ${failed_step:-unknown}" in workflow
    assert "Build/deploy failure summary: ${failure_summary:-unknown}" in workflow
    assert "Post-merge delivery failed" in workflow
    assert (
        "exit 1"
        in workflow.split("post-merge-delivery:", 1)[1].split("post-merge-summary:", 1)[
            0
        ]
    )
    assert (
        "needs: [build-and-deploy, provider-gate, ai-ocr-gate, post-merge-delivery]"
    ) in workflow
    assert "dedicated `Post-merge Delivery` check" in ci_cd
    assert "A green `CI` workflow alone is not sufficient evidence" in ci_cd
    assert "AC8.13.103" in epic


def test_AC8_13_55_post_merge_staging_is_scoped_to_deploy_relevant_paths() -> None:
    """AC8.13.55: Post-merge staging only runs for deploy-relevant changes."""
    workflow = read(".github/workflows/staging-deploy.yml")
    classifier = read("common/ci/change_classifier.py")
    classifier_tests = read("tests/tooling/test_ci_change_classifier.py")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "classify-staging:" not in workflow
    assert "name: Classify staging and AI/OCR relevance" in workflow
    assert "fetch-depth: 0" in workflow
    # Manual-only staging no longer scopes by changed paths inside the deploy
    # workflow: a manual dispatch always classifies staging (and the AI/OCR gate)
    # as required. The diff-based change classifier remains for CI/PR scoping only.
    assert "git diff --name-only" not in workflow
    assert "tools/ci_change_classifier.py" not in workflow
    assert "staging_required: ${{ steps.gates.outputs.staging_required }}" in workflow
    assert "staging_reason: ${{ steps.gates.outputs.staging_reason }}" in workflow
    assert "if: steps.gates.outputs.staging_required == 'true'" in workflow
    assert (
        "ENV_STAGE_REQUIRED: ${{ steps.classify.outputs.env_stage_required }}"
        in workflow
    )
    assert "manual-dispatch" in workflow

    assert "STAGING_EXACT" in classifier
    assert "STAGING_PREFIXES" in classifier
    assert "def is_staging_relevant" in classifier
    assert "staging-paths-changed" in classifier
    assert "no-staging-paths-changed" in classifier
    assert (
        "test_AC8_13_55_staging_only_runs_for_runtime_deploy_or_e2e_changes"
        in classifier_tests
    )
    assert "docs/project/archive/AC-TEST-TRACEABILITY-AUDIT.md" in classifier_tests
    assert "common/ssot/check_ssot_ownership.py" in classifier_tests
    assert "Staging deploy is manual (`workflow_dispatch`) only" in ci_cd
    assert (
        "The diff-based change classifier no longer scopes the staging deploy by changed paths"
        in ci_cd
    )


def test_AC8_13_60_deploy_workflows_have_no_nonblocking_noop_gates() -> None:
    """AC8.13.60: Deploy gates do not keep no-op or warning-only checks."""
    workflows = [
        read(".github/workflows/staging-deploy.yml"),
        read(".github/workflows/production-release.yml"),
        read(".github/workflows/pr-test.yml"),
    ]
    ci_cd = read("docs/ssot/ci-cd.md")

    for workflow in workflows:
        assert "Check Deployment Dependencies" not in workflow
        assert "Deployment deps check skipped" not in workflow

    staging = workflows[0]
    assert "Performance Benchmark" not in staging
    assert "Don't block deploy, but report issues" not in staging
    assert "Deploy dependency preflight lives in `tools/dokploy_deploy.sh`" in ci_cd


def test_AC8_13_52_production_release_dry_run_does_not_mutate_production() -> None:
    """AC8.13.52 AC8.13.65: Production dry-run validates without deploying."""
    workflow = read(".github/workflows/production-release.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "dry_run:" in workflow
    assert "Validate release prerequisites without deploying production" in workflow
    assert "dry-run:" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.dry_run" in workflow
    assert "moon run :lint" in workflow
    assert "moon run :test" not in workflow
    assert "Verify source CI passed" in workflow
    assert "--workflow ci.yml" in workflow
    assert '--commit "$GITHUB_SHA"' in workflow
    assert '.headBranch == "main"' in workflow
    assert "Verify SHA Images Dry Run" in workflow
    assert "Production mutation skipped" in workflow
    dry_run_section = workflow.split("dry-run:", 1)[1].split("\n  deploy:", 1)[0]
    assert "environment:" not in dry_run_section
    assert "dokploy_deploy.sh" not in dry_run_section
    assert "inputs.dry_run" in workflow.split("deploy:", 1)[1].split("steps:", 1)[0]
    assert "Production release dry-run" in ci_cd
    assert "Verify SHA Images Dry Run" in workflow
    assert "docker buildx imagetools create" not in dry_run_section


def test_AC8_13_16_ci_change_classification_and_frontend_cache() -> None:
    """AC8.13.16: CI skips heavy jobs for lightweight changes and caches npm."""
    workflow = read(".github/workflows/ci.yml")
    pr_workflow = read(".github/workflows/pr-test.yml")
    classifier = read("common/ci/change_classifier.py")
    ci_cd = read("docs/ssot/ci-cd.md")
    environments = read("docs/ssot/environments.md")

    assert "name: Classify Changes" in workflow
    assert "pr_required: ${{ steps.gates.outputs.pr_required }}" in workflow
    assert (
        "ENV_STAGE_REQUIRED: ${{ steps.classify.outputs.env_stage_required }}"
        in workflow
    )
    assert "tools/ci_change_classifier.py" in workflow
    assert "--changed-files changed-files.txt" in workflow
    assert '"docs/"' in classifier
    assert '".github/ISSUE_TEMPLATE/"' in classifier
    assert '".github/workflows/docs.yml"' in classifier
    assert "path.endswith" not in workflow
    assert "path.endswith" not in classifier
    assert "runtime-or-ci-paths-changed" in classifier
    assert "lightweight-docs-or-docs-workflow-only" in classifier
    assert "pr-preview-paths-changed" in classifier
    assert "no-pr-preview-paths-changed" in classifier
    assert "needs: [changes]" in workflow
    assert "if: needs.changes.outputs.pr_required == 'true'" in workflow
    assert (
        "pr_preview_required: ${{ steps.preview_gate.outputs.pr_preview_required }}"
        in pr_workflow
    )
    assert "name: Classify PR preview relevance" in pr_workflow
    assert "name: Normalize PR preview gate" in pr_workflow
    assert "needs.setup.outputs.pr_preview_required == 'true'" in pr_workflow
    assert "name: AC Traceability Check" in workflow
    assert (
        "needs: [changes, schema-migrations, backend, backend-integration, backend-e2e-tier1, frontend, container-images, lint, tooling-coverage, unified-coverage, ac-traceability, ac-behavioral-ratchet]"
        in workflow
    )
    assert "finish remains the authoritative aggregate gate" in ci_cd
    assert (
        "Heavy backend/frontend/coverage jobs skipped for lightweight changes."
        in workflow
    )
    assert "uses: actions/setup-node@v4" in workflow
    assert "cache: npm" in workflow
    assert "cache-dependency-path: apps/frontend/package-lock.json" in workflow
    assert "run: npm ci" in workflow
    assert "run: npm install" not in workflow
    assert "PR vs Main CI Responsibilities" in ci_cd
    assert "Lightweight changes do not repeat the heavy path" in ci_cd
    assert (
        "PR preview environments deploy only for runtime app, compose, root E2E, dependency, Dockerfile/config, or preview-action changes"
        in ci_cd
    )
    assert "Frontend dependency installation uses `actions/setup-node@v4`" in ci_cd
    assert (
        "Markdown outside the documented lightweight trees is treated as heavy" in ci_cd
    )
    assert "lightweight documentation" in environments.lower()


def test_AC8_13_16_workflows_opt_into_node24_actions_runtime() -> None:
    """AC8.13.16: JavaScript actions are validated against the Node 24 runtime before migration."""
    workflow_paths = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflow_paths
    for workflow_path in workflow_paths:
        workflow = workflow_path.read_text(encoding="utf-8")
        assert 'FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"' in workflow, (
            workflow_path.name
        )

    ci_cd = read("docs/ssot/ci-cd.md")
    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" in ci_cd
    assert (
        "GitHub JavaScript action runtime is explicitly validated on Node 24" in ci_cd
    )


def test_AC8_13_17_ac_traceability_runs_registry_generation_check() -> None:
    """AC8.13.17: AC traceability checks registry generation before audit output."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert (
        "uv run --with pyyaml python tools/generate_ac_registry.py --check" in workflow
    )
    assert "uv run --with pyyaml python tools/check_ac_traceability.py" in workflow
    assert (
        "uv run --with pyyaml python tools/build_ac_traceability.py --output"
        in workflow
    )
    assert workflow.index("tools/generate_ac_registry.py --check") < workflow.index(
        "tools/check_ac_traceability.py"
    )
    assert workflow.index("tools/check_ac_traceability.py") < workflow.index(
        "tools/build_ac_traceability.py --output"
    )
    assert "generated registry indexes can be materialized" in ci_cd
    assert (
        "CI fails on mandatory AC coverage that is missing, placeholder-only, or stub-only"
        in ci_cd
    )


def test_AC8_13_53_generated_api_reference_is_ci_checked() -> None:
    """AC8.13.53: API reference docs are generated contract output in CI."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "Generated API Reference Check" in workflow
    assert "uv run python ../../tools/generate_api_reference.py --check" in workflow
    assert workflow.index("Install dependencies") < workflow.index(
        "tools/generate_api_reference.py --check"
    )
    assert "Generated API reference" in ci_cd
    assert "FastAPI OpenAPI" in ci_cd


def test_AC14_1_17_generated_db_schema_reference_is_ci_checked() -> None:
    """AC14.1.17: DB schema reference docs are generated contract output in CI."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "Generated DB Schema Reference Check" in workflow
    assert (
        "uv run python ../../tools/generate_db_schema_reference.py --check" in workflow
    )
    generate_line = "uv run python ../../tools/generate_db_schema_reference.py\n"
    assert generate_line in workflow
    assert workflow.index(generate_line) < workflow.index(
        "uv run python ../../tools/generate_db_schema_reference.py --check"
    )
    assert workflow.index("tools/generate_api_reference.py --check") < workflow.index(
        "tools/generate_db_schema_reference.py --check"
    )
    assert "Generated DB schema reference" in ci_cd
    assert "SQLAlchemy model metadata" in ci_cd
    assert "docs/hooks.py" in ci_cd


def test_AC8_13_53_pr_ci_avoids_moon_bootstrap_for_direct_gates() -> None:
    """AC8.13.53: PR CI avoids Moon bootstrap when direct commands suffice."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "moonrepo/setup-toolchain@v0" not in workflow
    assert "moon run :build" not in workflow
    assert "Build Frontend (via Moon)" not in workflow

    backend_block = workflow.split("  backend:", 1)[1].split(
        "  backend-integration:",
        1,
    )[0]
    integration_block = workflow.split("  backend-integration:", 1)[1].split(
        "  backend-e2e-tier1:",
        1,
    )[0]
    tier1_block = workflow.split("  backend-e2e-tier1:", 1)[1].split(
        "  frontend:",
        1,
    )[0]
    frontend_block = workflow.split("  frontend:", 1)[1].split(
        "  container-images:",
        1,
    )[0]

    assert "moonrepo/setup-toolchain@v0" not in backend_block
    assert "moonrepo/setup-toolchain@v0" not in integration_block
    assert "moonrepo/setup-toolchain@v0" not in tier1_block
    assert "moonrepo/setup-toolchain@v0" not in frontend_block
    assert "name: Build Frontend" in frontend_block
    assert "run: npm run build" in frontend_block
    assert "working-directory: apps/frontend" in frontend_block
    assert "PR CI avoids Moon bootstrap" in ci_cd
    assert "direct `pytest` and `npm` commands" in ci_cd
    assert (
        "Moon CLI availability and project graph coverage are static contracts" in ci_cd
    )


def test_AC8_13_68_ci_runs_e2e_epic_traceability_gate() -> None:
    """AC8.13.68: CI gates product E2E tests and project EPIC ownership."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("docs/ssot/ci-cd.md")
    tdd = read("docs/ssot/tdd.md")

    assert (
        "uv run --with pyyaml python tools/check_e2e_epic_traceability.py --output"
        in workflow
    )
    assert "$RUNNER_TEMP/E2E-EPIC-TRACEABILITY.md" in workflow
    assert workflow.index("tools/check_ac_traceability.py") < workflow.index(
        "tools/check_e2e_epic_traceability.py"
    )
    assert workflow.index("tools/check_e2e_epic_traceability.py") < workflow.index(
        "tools/check_critical_proof_matrix.py"
    )
    assert workflow.index("tools/check_e2e_epic_traceability.py") < workflow.index(
        "tools/build_ac_traceability.py --output"
    )
    assert "function-level EPIC IDs" in ci_cd
    assert "tools/check_e2e_epic_traceability.py" in tdd


def test_AC8_13_70_ci_documents_closed_e2e_traceability_system() -> None:
    """AC8.13.70: E2E traceability documents README and asset closure."""
    ci_cd = read("docs/ssot/ci-cd.md")
    tdd = read("docs/ssot/tdd.md")
    readme = read("README.md")
    checker = read("common/ssot/check_e2e_epic_traceability.py")

    assert "the README EPIC map matches project EPIC files" in ci_cd
    assert "unclassified E2E-like assets outside declared roots" in ci_cd
    assert "root README EPIC map" in tdd
    assert "fails unclassified" in tdd
    assert "tools/check_e2e_epic_traceability.py" in readme
    assert "DECLARED_NON_PRODUCT_E2E_ROOTS" in checker
    assert "DECLARED_NON_PRODUCT_E2E_FILES" in checker


def test_AC8_13_9_production_release_runs_prod_safe_e2e_smoke() -> None:
    """AC8.13.9: Production release runs prod-safe read-only E2E smoke."""
    workflow = read(".github/workflows/production-release.yml")
    prod_smoke = read("tests/e2e/test_production_readonly_smoke.py")

    assert 'NODE_VERSION: "20.19.0"' in workflow
    assert "Set up Node" in workflow
    assert "Install frontend dependencies" in workflow
    assert "cache-dependency-path: apps/frontend/package-lock.json" in workflow
    assert "working-directory: apps/frontend" in workflow
    assert "Verify source CI passed" in workflow
    assert workflow.index("Install frontend dependencies") < workflow.index(
        "moon run :lint"
    )
    assert "Setup E2E Tests" in workflow
    assert "Production Infrastructure Smoke" in workflow
    assert "tools/production_infra_smoke.py" in workflow
    assert "--signoz-url" in workflow
    assert "test_production_readonly_smoke.py" in workflow
    assert "TEST_ENV: production" in workflow
    assert "@pytest.mark.prod_safe" in prod_smoke
    for mutating_token in (
        "/api/auth/register",
        ".post(",
        ".patch(",
        ".put(",
        ".delete(",
    ):
        assert mutating_token not in prod_smoke


def test_AC8_13_67_production_release_preserves_version_metadata() -> None:
    """AC8.13.67: Production release preserves deployed version metadata."""
    workflow = read(".github/workflows/production-release.yml")
    deploy_script = read("tools/_lib/shell/dokploy_deploy.sh")
    app_compose = read("repo/finance_report/finance_report/10.app/compose.yaml")

    # In the promote-not-rebuild pattern, we promote staging-validated images instead of rebuilding.
    # We verify that promotion uses docker buildx imagetools create.
    promote_blocks = re.findall(r"docker buildx imagetools create --tag", workflow)
    assert len(promote_blocks) == 2

    assert "Verify staging passed" in workflow
    assert "Verify SHA Images Dry Run" in workflow

    config_hash_update = 'new_env=$(update_env_var "$new_env" "IAC_CONFIG_HASH" "deploy-${IMAGE_TAG}-$(date +%s)")'
    assert config_hash_update in deploy_script
    assert deploy_script.count('update_env_var "$new_env" "IAC_CONFIG_HASH"') == 1
    assert deploy_script.index(config_hash_update) < deploy_script.index(
        'dokploy_api_call "POST" "compose.update"'
    )
    assert "models-${IMAGE_TAG}" not in deploy_script

    assert "GIT_COMMIT_SHA: ${GIT_COMMIT_SHA:-unknown}" in app_compose
    assert app_compose.index("backend:") < app_compose.index(
        "GIT_COMMIT_SHA: ${GIT_COMMIT_SHA:-unknown}"
    )


def test_AC7_10_production_release_promotes_not_rebuilds() -> None:
    """AC7.10.1 - AC7.10.5: Production release promotes staging-validated SHA image and fails closed on drift."""
    workflow = read(".github/workflows/production-release.yml")
    ci_cd = read("docs/ssot/ci-cd.md")
    deployment = read("docs/ssot/deployment.md")

    # AC7.10.1: promotes staging-validated image instead of rebuilding
    assert "docker buildx imagetools create --tag" in workflow
    assert "docker/build-push-action" not in workflow

    # AC7.10.2: fails closed if no staging-validated SHA image exists or digests differ
    assert "Verify staging passed" in workflow
    assert "docker buildx imagetools inspect" in workflow
    assert 'backend_sha_digest" != "$backend_promoted_digest' in workflow
    assert 'frontend_sha_digest" != "$frontend_promoted_digest' in workflow

    # AC7.10.3: summary records released commit, source CI run, digest, and no rebuild
    assert "Released commit: ${{ github.sha }}" in workflow
    assert "Source CI run: ${{ env.staging_run_id }}" in workflow
    assert "Promoted backend image digest" in workflow
    assert "No rebuild occurred" in workflow

    # AC7.10.4: SSOTs document promote-not-rebuild consistency ladder
    assert "promote-not-rebuild consistency ladder" in deployment
    assert "promote-not-rebuild consistency ladder" in ci_cd

    # AC7.10.5: workflow_dispatch dry-run proves promote path without mutating
    assert "Verify SHA Images Dry Run" in workflow
    assert "dry_run:" in workflow


def test_AC8_13_7_staging_runs_llm_e2e_serially_with_glm_5_1() -> None:
    """AC8.13.7: Post-merge AI/OCR E2E is a single-provider-access gate."""
    workflow = read(".github/workflows/staging-deploy.yml")
    ai_workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    pr_workflow = read(".github/workflows/pr-test.yml")
    journey = read("tests/e2e/test_statement_full_journey.py")
    brokerage = read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")
    four_asset = read("tests/e2e/test_four_asset_net_worth_golden_path.py")
    upload = read("tests/e2e/test_statement_upload_e2e.py")
    deploy_script = read("tools/_lib/shell/dokploy_deploy.sh")
    preview_lifecycle = read("tools/_lib/dev/pr_preview_lifecycle.py")

    assert "post-merge-train-turn:" not in workflow
    assert "wait_post_merge_train_turn.py" not in workflow
    assert "workflow_dispatch:" in workflow
    assert "STAGING_E2E_PRIMARY_MODEL: glm-5.1" in workflow
    assert "STAGING_E2E_OCR_MODEL: glm-4.6v" in workflow
    assert "STAGING_E2E_VISION_MODEL: glm-4.6v" in workflow
    assert (
        "DEPLOY_PRIMARY_MODEL_OVERRIDE: ${{ env.STAGING_E2E_PRIMARY_MODEL }}"
        in workflow
    )
    assert "DEPLOY_OCR_MODEL_OVERRIDE: ${{ env.STAGING_E2E_OCR_MODEL }}" in workflow
    assert (
        "DEPLOY_VISION_MODEL_OVERRIDE: ${{ env.STAGING_E2E_VISION_MODEL }}" in workflow
    )
    assert (
        'update_env_var "$new_env" "PRIMARY_MODEL" "$DEPLOY_PRIMARY_MODEL_OVERRIDE"'
        in deploy_script
    )
    assert (
        'update_env_var "$new_env" "OCR_MODEL" "$DEPLOY_OCR_MODEL_OVERRIDE"'
        in deploy_script
    )
    assert (
        'update_env_var "$new_env" "VISION_MODEL" "$DEPLOY_VISION_MODEL_OVERRIDE"'
        in deploy_script
    )
    assert 'update_env_var "$new_env" "IAC_CONFIG_HASH"' in deploy_script
    assert '-m "(smoke or e2e) and not llm" -n 4' in workflow
    assert "PARSING_TIMEOUT_MS: 480000" in workflow
    # Staging is manual-only; no workflow_run auto-trigger remains.
    assert "workflow_run" not in workflow
    contract = staging_ai_ocr_contract_shell()
    assert "test_brokerage_upload_to_portfolio_value.py" in contract
    assert "test_four_asset_net_worth_golden_path.py" in contract
    assert "tools/staging_ai_ocr_gate_contract.py --shell" in workflow
    assert '-v -m "llm"' in workflow
    assert "PARSING_TIMEOUT_MS: 480000" in ai_workflow
    assert "@pytest.mark.llm" in journey
    assert "@pytest.mark.llm" in brokerage
    assert "@pytest.mark.llm" in four_asset
    assert upload.count("@pytest.mark.llm") >= 2
    assert '"ZAI_API_KEY": ""' in preview_lifecycle
    assert '"AI_BASE_URL": "https://api.z.ai/api/coding/paas/v4"' in preview_lifecycle
    assert '"OCR_MODEL": "glm-4.6v"' in preview_lifecycle
    assert '"AI_JSON_TIMEOUT_SECONDS": "360"' in preview_lifecycle
    assert '"AI_JSON_MAX_TOKENS": "8192"' in preview_lifecycle
    assert '"AI_JSON_DISABLE_THINKING": "true"' in preview_lifecycle
    assert "https://api.z.ai/api/coding/paas/v4" in read("docs/ssot/ci-cd.md")
    assert '-m "(smoke or e2e) and not llm"' in pr_workflow
    assert '-m "smoke or e2e"' not in pr_workflow


def test_AC8_13_21_staging_ai_ocr_gate_runs_under_manual_dispatch() -> None:
    """AC8.13.21: Provider-backed staging AI/OCR runs inside a manual dispatch, not auto-after-CI."""
    workflow = read(".github/workflows/staging-deploy.yml")
    on_demand_gate = read(".github/workflows/staging-ai-ocr-gate.yml")

    parsed = yaml.safe_load(workflow)
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = parsed.get("on", parsed.get(True))
    assert isinstance(triggers, dict), "staging-deploy.yml must declare an `on:` map"
    assert "workflow_dispatch" in triggers, (
        "staging deploy must be manually dispatchable"
    )
    assert "workflow_run" not in triggers, "staging deploy must NOT auto-follow CI"

    # The AI/OCR gate still exists in the staging deploy workflow and inherits its
    # `workflow_dispatch` trigger rather than auto-following a CI `workflow_run`.
    assert "ai-ocr-gate:" in workflow
    assert "name: Staging AI/OCR Gate" in workflow
    assert "Run Staging AI/OCR Gate" in workflow
    # workflow_dispatch is the sole trigger, so every job (build-and-deploy and the
    # gate it gates on) runs only on a manual dispatch; a redundant job-level
    # `if: github.event_name == 'workflow_dispatch'` would always be true.
    assert list(triggers.keys()) == ["workflow_dispatch"]

    # An on-demand recovery entry point also runs the gate via workflow_dispatch.
    on_demand_parsed = yaml.safe_load(on_demand_gate)
    on_demand_triggers = on_demand_parsed.get("on", on_demand_parsed.get(True))
    assert isinstance(on_demand_triggers, dict)
    assert "workflow_dispatch" in on_demand_triggers


def test_AC8_13_120_staging_runs_lightweight_provider_connectivity_smoke() -> None:
    """AC8.13.120: provider-risk staging changes prove a provider round trip."""
    workflow = read(".github/workflows/staging-deploy.yml")
    ci_cd = read("docs/ssot/ci-cd.md")
    provider_test = read("tests/e2e/test_ai_provider_connectivity.py")

    assert "provider-gate:" in workflow
    assert "name: Staging Provider Gate" in workflow
    assert "needs: [build-and-deploy]" in workflow
    assert (
        "if: ${{ needs.build-and-deploy.outputs.staging_required == 'true' && needs.build-and-deploy.outputs.provider_gate_required == 'true' }}"
        in workflow
    )
    assert (
        "provider_gate_required: ${{ steps.gates.outputs.provider_gate_required }}"
        in workflow
    )
    assert (
        "provider_gate_reason: ${{ steps.gates.outputs.provider_gate_reason }}"
        in workflow
    )
    assert (
        "provider_status: ${{ steps.ai_provider_connectivity.outputs.provider_status }}"
        in workflow
    )
    assert "name: AI Provider Connectivity Smoke" in workflow
    assert "id: ai_provider_connectivity" in workflow
    assert "timeout-minutes: 10" in workflow
    assert "pytest tests/e2e/test_ai_provider_connectivity.py" in workflow
    assert '-v -m "llm"' in workflow
    assert "test-results/staging-provider-connectivity.xml" in workflow
    assert "provider-connectivity" in workflow
    assert "provider_connectivity_outcome=" in workflow
    build_job = workflow.split("  build-and-deploy:", 1)[1].split(
        "\n  provider-gate:", 1
    )[0]
    provider_job = workflow.split("  provider-gate:", 1)[1].split("\n  ai-ocr-gate:", 1)
    assert "id: ai_provider_connectivity" not in build_job
    assert "id: ai_provider_connectivity" in provider_job[0]
    assert (
        "ref: ${{ needs.build-and-deploy.outputs.commit_full_sha }}" in provider_job[0]
    )
    # The smoke is resilient to transient provider failure: it retries with
    # backoff, hard-fails only on a client/config 4xx
    # (config-failure), and reports a transient 5xx/timeout as a non-blocking
    # degraded status so a provider blip cannot red main.
    assert "PROVIDER_CONNECTIVITY_RETRIES" in workflow
    assert "provider_status=config-failure" in workflow
    assert "provider_status=degraded" in workflow
    assert "degraded-provider" in workflow
    provider_smoke = (
        provider_job[0]
        .split("name: AI Provider Connectivity Smoke", 1)[1]
        .split("name: Write provider gate context", 1)[0]
    )
    config_branch = provider_smoke.split("provider_status=config-failure", 1)[1].split(
        "provider_status=degraded", 1
    )[0]
    degraded_branch = provider_smoke.split("provider_status=degraded", 1)[1]
    assert "connectivity failed: [0-9]{3}" in provider_smoke
    assert '[ "$status_code" -ge 400 ]' in provider_smoke
    assert '[ "$status_code" -lt 500 ]' in provider_smoke
    assert "exit 1" in config_branch
    assert "exit 0" in degraded_branch
    assert "provider connectivity smoke" in ci_cd
    assert "runs only when `provider_gate_required.staging` is true" in ci_cd
    assert "full OCR/LLM replay remains gated" in ci_cd
    assert "degraded-provider" in ci_cd
    assert "transient provider blips do not" in ci_cd
    assert "@pytest.mark.llm" in provider_test
    assert "authenticated_page_unique" in provider_test
    assert "authenticated_page_unique.request.post" in provider_test
    assert '"/chat"' in provider_test
    assert "Wait for matching CI success" not in workflow
    assert "wait_for_github_ci.py" not in workflow
    assert "inherits the deploy workflow's `workflow_dispatch` trigger" in ci_cd


def test_AC8_13_22_staging_deploy_builds_from_dispatched_ref() -> None:
    """AC8.13.22: Staging deploy builds and deploys the manually dispatched `ref`."""
    workflow = read(".github/workflows/staging-deploy.yml")

    parsed = yaml.safe_load(workflow)
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = parsed.get("on", parsed.get(True))
    assert isinstance(triggers, dict)
    assert "workflow_dispatch" in triggers
    assert "workflow_run" not in triggers

    assert "actions: read" in workflow
    assert "contents: read" in workflow
    assert "packages: write" in workflow
    # workflow_dispatch is the sole trigger, so the build-and-deploy job runs only
    # on a manual dispatch without a redundant (always-true) job-level `if`.
    assert list(triggers.keys()) == ["workflow_dispatch"]
    assert "Wait for matching CI success" not in workflow
    # Checkout uses the dispatched ref (falling back to the triggering SHA), and
    # that checkout happens before any build or deploy.
    assert "ref: ${{ inputs.ref || github.sha }}" in workflow
    assert workflow.index("ref: ${{ inputs.ref || github.sha }}") < workflow.index(
        "Build and push Backend"
    )
    assert workflow.index("ref: ${{ inputs.ref || github.sha }}") < workflow.index(
        "Deploy to Staging"
    )


def test_AC8_13_36_post_merge_reuses_sha_tagged_staging_images() -> None:
    """AC8.13.36: Main CI builds SHA images and staging reuses them on manual dispatch."""
    ci_workflow = read(".github/workflows/ci.yml")
    deploy_workflow = read(".github/workflows/staging-deploy.yml")
    check_script = read("tools/_lib/shell/check_ghcr_image_tag.sh")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "container-images:" in ci_workflow
    assert "name: Build Staging Images" in ci_workflow
    container_block = ci_workflow.split("  container-images:", 1)[1].split(
        "  tooling-coverage:", 1
    )[0]
    assert "needs: [changes]" in container_block
    assert "lint" not in container_block.split("steps:", 1)[0]
    assert "ac-traceability" not in container_block.split("steps:", 1)[0]
    assert "needs.changes.outputs.pr_required == 'true'" in ci_workflow
    assert (
        "if: github.event_name == 'push' && github.ref == 'refs/heads/main'"
        in ci_workflow
    )
    assert "packages: write" in ci_workflow
    assert "Build Backend SHA image" in ci_workflow
    assert "Build Frontend SHA image" in ci_workflow
    assert (
        "push: ${{ (github.event_name == 'push' && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/release/'))) || github.event_name == 'workflow_dispatch' }}"
        in ci_workflow
    )
    assert (
        "${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}-backend:${{ steps.get_sha.outputs.short_sha }}"
        in ci_workflow
    )
    assert (
        "${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}-frontend:${{ steps.get_sha.outputs.short_sha }}"
        in ci_workflow
    )
    assert "backend:staging" not in ci_workflow
    assert "frontend:staging" not in ci_workflow

    assert "Resolve Backend Image" in deploy_workflow
    assert "Resolve Frontend Image" in deploy_workflow
    assert "tools/check_ghcr_image_tag.sh" in deploy_workflow
    assert "steps.backend_image.outputs.build_required == 'true'" in deploy_workflow
    assert "steps.frontend_image.outputs.build_required == 'true'" in deploy_workflow
    assert "Promote Backend Image to Staging Tag" in deploy_workflow
    assert "Promote Frontend Image to Staging Tag" in deploy_workflow
    assert "ref: ${{ inputs.ref || github.sha }}" in deploy_workflow
    assert deploy_workflow.index(
        "ref: ${{ inputs.ref || github.sha }}"
    ) < deploy_workflow.index("Resolve Backend Image")
    assert deploy_workflow.index("Resolve Backend Image") < deploy_workflow.index(
        "Build and push Backend"
    )
    assert deploy_workflow.index("Resolve Frontend Image") < deploy_workflow.index(
        "Build and push Frontend"
    )
    assert deploy_workflow.index("Build and push Frontend") < deploy_workflow.index(
        "Promote Backend Image to Staging Tag"
    )
    assert deploy_workflow.index(
        "Promote Backend Image to Staging Tag"
    ) < deploy_workflow.index("Deploy to Staging")

    assert "docker buildx imagetools inspect" in check_script
    assert "docker buildx imagetools create" not in check_script
    assert 'write_output "build_required" "false"' in check_script
    assert 'write_output "build_required" "true"' in check_script
    assert "SHA-tagged staging images" in ci_cd
    assert "falls back to building only the missing image" in ci_cd
    assert (
        "promotes existing SHA images to the moving `staging` tag on a manual "
        "dispatch" in ci_cd
    )
    assert "when the `:<sha>` image already exists from CI" in ci_cd


def test_AC8_13_40_pr_ci_dry_runs_staging_image_builds_before_merge() -> None:
    """AC8.13.40: PR CI dry-runs staging image builds before merge."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    container_block = workflow.split("  container-images:", 1)[1].split(
        "  tooling-coverage:", 1
    )[0]
    finish_block = workflow.split("- name: Check job status", 1)[1]
    login_block = container_block.split("- name: Log in to Container registry", 1)[
        1
    ].split("- name: Set up Docker Buildx", 1)[0]

    assert "if: needs.changes.outputs.pr_required == 'true'" in container_block
    assert (
        "if: (github.event_name == 'push' && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/release/'))) || github.event_name == 'workflow_dispatch'"
        in login_block
    )
    assert container_block.count("uses: docker/build-push-action@v5") == 2
    assert (
        container_block.count(
            "push: ${{ (github.event_name == 'push' && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/release/'))) || github.event_name == 'workflow_dispatch' }}"
        )
        == 2
    )
    assert "Build Backend SHA image" in container_block
    assert "Build Frontend SHA image" in container_block
    assert "Container image validation failed" in finish_block
    assert "PR CI dry-runs staging image builds before merge" in ci_cd
    assert "Main and release-branch push CI, plus on-demand" in ci_cd


def test_AC8_13_89_pr_preview_follows_ci_without_pr_image_builds() -> None:
    """AC8.13.89: the in-runner e2e gate runs synchronously on pull_request (independent
    of CI) and does not build/push PR images."""
    workflow = read(".github/workflows/pr-test.yml")
    ci_cd = read("docs/ssot/ci-cd.md")
    compose = read("docker-compose.yml")
    frontend_dockerfile = read("apps/frontend/Dockerfile")
    frontend_version_route = read(
        "apps/frontend/src/app/frontend-version.json/route.ts"
    )

    e2e_block = workflow.split("  e2e:", 1)[1].split("  cleanup:", 1)[0]
    cleanup_block = workflow.split("  cleanup:", 1)[1]
    deploy_block = workflow.split("  deploy-preview:", 1)[1].split("  e2e:", 1)[0]
    pr_preview_compose = read("docker-compose.pr-preview.yml")
    frontend_compose_block = compose.split("  frontend:", 1)[1].split("networks:", 1)[0]

    # The in-runner e2e gate runs SYNCHRONOUSLY on pull_request (not async via
    # workflow_run, which a fast/auto merge could outrun) so it is a real required
    # check before merge. Preview stays on-demand (deploy-preview = workflow_dispatch).
    assert "workflow_run:" not in workflow
    assert "types: [opened, synchronize, reopened, closed]" in workflow
    assert 'action = "deploy"' in workflow
    assert 'action_reason = "pull-request-sync"' in workflow
    assert 'action = "cleanup"' in workflow
    assert "github.event.pull_request.number" in workflow
    assert "gate-cheap-ci:" not in workflow
    assert "tools/wait_for_cheap_ci.py" not in workflow
    # No PR preview IMAGES are built/pushed/preflighted in CI: the persistent
    # preview is built from source on the Dokploy host instead.
    assert "build-preview-backend-image:" not in workflow
    assert "build-preview-frontend-image:" not in workflow
    assert "Preflight PR preview image tags" not in workflow
    assert "docker/build-push-action@v5" not in workflow
    assert "push: true" not in workflow
    assert "packages: write" not in workflow
    # Persistent preview: non-blocking deploy job, after the in-runner E2E gate,
    # building from the PR source on the Dokploy host (no image pull/push).
    assert "deploy-preview:" in workflow
    assert "needs: [setup, e2e]" in deploy_block
    assert "needs.e2e.result == 'success'" in workflow
    assert "continue-on-error: true" in deploy_block
    assert "--action deploy" in deploy_block
    assert "--github-integration-id" in deploy_block
    assert "build from source on Dokploy host" in deploy_block
    # The preview compose builds backend/frontend from source (no image pull).
    assert "context: ./apps/backend" in pr_preview_compose
    assert "context: ./apps/frontend" in pr_preview_compose
    assert "pull_policy: always" not in pr_preview_compose
    assert "GIT_COMMIT_SHA: ${{ needs.setup.outputs.head_sha }}" in e2e_block
    assert "EXPECTED_SHA: ${{ needs.setup.outputs.head_sha }}" in e2e_block
    assert "APP_URL: http://localhost:8080" in e2e_block
    assert "docker compose up --build" in e2e_block
    assert "docker compose down --volumes --remove-orphans" in e2e_block
    assert "ARG GIT_COMMIT_SHA=unknown" in frontend_dockerfile
    assert "ENV GIT_COMMIT_SHA=${GIT_COMMIT_SHA}" in frontend_dockerfile
    assert "process.env.GIT_COMMIT_SHA" in frontend_version_route
    assert "GIT_COMMIT_SHA: ${GIT_COMMIT_SHA:-}" in frontend_compose_block
    assert (
        sum(
            1
            for line in frontend_compose_block.splitlines()
            if line.strip().startswith("GIT_COMMIT_SHA:")
        )
        == 2
    )
    assert "Wait for stack readiness" in e2e_block
    assert "End-to-End Tests" in e2e_block
    assert e2e_block.index("Wait for stack readiness") < e2e_block.index(
        "End-to-End Tests"
    )
    assert 'curl -fsS "$APP_URL/api/health"' in e2e_block
    assert "bash tools/smoke_test.sh" in e2e_block
    assert "no PR preview image is pushed" in e2e_block
    assert "Delete GHCR images" not in cleanup_block
    assert "pr_preview_images=not-created" in cleanup_block
    assert "synchronously on `pull_request`" in ci_cd
    assert "does not push, preflight, pull, or delete PR preview images" in ci_cd
    assert "built from the PR source on the Dokploy host" in ci_cd
    assert "The runner stack waits for `/api/health` before smoke/E2E" in ci_cd


def test_AC8_13_23_post_merge_deploy_and_ai_ocr_are_one_serial_unit() -> None:
    """AC8.13.23: Deploy health and provider gate share one serialized workflow unit."""
    deploy_workflow = read(".github/workflows/staging-deploy.yml")
    ai_workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "post-merge-train-turn:" not in deploy_workflow
    assert "name: Classify staging and AI/OCR relevance" in deploy_workflow
    assert "ai-ocr-gate:" in deploy_workflow
    assert "needs: [build-and-deploy]" in deploy_workflow
    assert (
        "ai_ocr_required: ${{ steps.gates.outputs.ai_ocr_required }}" in deploy_workflow
    )
    assert (
        "PROVIDER_GATE_REQUIRED: ${{ steps.classify.outputs.provider_gate_required }}"
        in deploy_workflow
    )
    assert (
        "STAGING_AI_OCR_REQUIRED: ${{ steps.classify.outputs.staging_ai_ocr_required }}"
        in deploy_workflow
    )
    assert (
        "STAGING_AI_OCR_REASON: ${{ steps.classify.outputs.staging_ai_ocr_reason }}"
        in deploy_workflow
    )
    assert "commit_full_sha: ${{ steps.get_sha.outputs.full_sha }}" in deploy_workflow
    assert (
        "ref: ${{ needs.build-and-deploy.outputs.commit_full_sha }}" in deploy_workflow
    )
    assert (
        "EXPECTED_SHA: ${{ needs.build-and-deploy.outputs.commit_sha }}"
        in deploy_workflow
    )
    assert 'workflows: ["Deploy Staging"]' not in ai_workflow
    assert "serialized deploy workflow unit" in ci_cd
    assert "in-job FIFO" not in ci_cd
    assert (
        "test code, audit context, and deployed image under validation aligned" in ci_cd
    )
    assert "only one `Deploy Staging` run mutates staging at a time" in ci_cd


def test_AC8_13_24_ac_traceability_uploads_audit_artifact_without_stale_doc_gate() -> (
    None
):
    """AC8.13.24: CI uploads traceability audit instead of gating stale snapshots."""
    workflow = read(".github/workflows/ci.yml")
    audit_builder = read("common/ssot/build_ac_traceability.py")
    ci_cd = read("docs/ssot/ci-cd.md")
    project_readme = read("docs/project/README.md")

    assert (
        "uv run --with pyyaml python tools/generate_ac_registry.py --check" in workflow
    )
    assert (
        'tools/build_ac_traceability.py --output "$RUNNER_TEMP/AC-TEST-TRACEABILITY-AUDIT.md"'
        in workflow
    )
    assert "uses: actions/upload-artifact@v4" in workflow
    assert "name: ac-test-traceability-audit" in workflow
    assert "tools/build_ac_traceability.py --check" not in workflow
    assert "CI uploads the generated audit as an artifact" in audit_builder
    assert "uploaded as a CI artifact" in ci_cd
    assert "Do not commit generated audit snapshots in routine" in project_readme
    assert "issue #548" in project_readme


def test_AC8_13_25_full_ci_aggregates_static_traceability_and_test_gates() -> None:
    """AC8.13.25: Full CI starts tests early while finish aggregates every gate."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    backend_block = workflow.split("  backend:", 1)[1].split("  frontend:", 1)[0]
    frontend_block = workflow.split("  frontend:", 1)[1].split(
        "  container-images:", 1
    )[0]
    image_block = workflow.split("  container-images:", 1)[1].split(
        "  tooling-coverage:", 1
    )[0]
    tooling_block = workflow.split("  tooling-coverage:", 1)[1].split(
        "  unified-coverage:", 1
    )[0]
    traceability_block = workflow.split("  ac-traceability:", 1)[1].split(
        "  finish:", 1
    )[0]
    finish_block = workflow.split("  finish:", 1)[1]

    for block in (backend_block, frontend_block, image_block, tooling_block):
        assert "needs: [changes]" in block
        assert "lint" not in block.split("steps:", 1)[0]
        assert "ac-traceability" not in block.split("steps:", 1)[0]

    assert "needs: [lint]" not in traceability_block
    assert "needs:" not in traceability_block.split("steps:", 1)[0]
    assert (
        "needs: [changes, schema-migrations, backend, backend-integration, backend-e2e-tier1, frontend, "
        "container-images, lint, tooling-coverage, unified-coverage, ac-traceability, ac-behavioral-ratchet]"
        in finish_block
    )
    assert "Standalone lint and AC traceability start immediately" in ci_cd
    assert (
        "Deterministic test and image jobs start after change classification" in ci_cd
    )
    assert "finish remains the authoritative aggregate gate" in ci_cd


def test_AC8_13_86_fast_feedback_jobs_do_not_wait_for_behavior_gates() -> None:
    """AC8.13.86: CI fast feedback jobs preserve actual workflow dependency semantics."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    lint_block = workflow.split("  lint:", 1)[1].split("  backend:", 1)[0]
    backend_block = workflow.split("  backend:", 1)[1].split(
        "  backend-integration:", 1
    )[0]
    frontend_block = workflow.split("  frontend:", 1)[1].split(
        "  container-images:", 1
    )[0]
    image_block = workflow.split("  container-images:", 1)[1].split(
        "  tooling-coverage:", 1
    )[0]
    traceability_block = workflow.split("  ac-traceability:", 1)[1].split(
        "  finish:", 1
    )[0]

    for block in (backend_block, frontend_block, image_block):
        assert "needs: [changes]" in block
        assert "backend-integration" not in block.split("steps:", 1)[0]
        assert "backend-e2e-tier1" not in block.split("steps:", 1)[0]
        assert "lint" not in block.split("steps:", 1)[0]
        assert "ac-traceability" not in block.split("steps:", 1)[0]

    assert "needs:" not in lint_block.split("steps:", 1)[0]
    assert "needs:" not in traceability_block.split("steps:", 1)[0]
    assert "Standalone gates start immediately" in ci_cd
    assert (
        "Deterministic test and image jobs start after change classification" in ci_cd
    )
    assert "Behavior-only backend gates run in parallel" in ci_cd


def test_AC8_13_94_env_and_pipeline_stage_contract_is_documented() -> None:
    """AC8.13.94: environments and pipeline stages are separate matrix axes."""
    ci_cd = read("docs/ssot/ci-cd.md")
    environments = read("docs/ssot/environments.md")
    readme = read("README.md")

    for token in (
        "Environment Axis",
        "Pipeline Stage Axis",
        "Env x Stage Execution Matrix",
        "local",
        "pr",
        "pr-preview",
        "staging",
        "prd",
        "Changed/Affected UT",
        "Lint/Static",
        "Full UT",
        "Regression/E2E",
        "Local runs are fast advisory gates",
        "PR CI is the deterministic merge authority",
        "deployed-environment proof gates",
    ):
        assert token in ci_cd

    assert "not every environment runs every pipeline stage" in ci_cd
    assert "environment taxonomy, pipeline stages, and GitHub Actions jobs" in ci_cd
    assert (
        "Environment taxonomy is not the delivery pipeline stage count" in environments
    )
    assert "Local fast feedback" in readme
    assert "PR CI is the authoritative merge gate" in readme


def test_AC8_13_95_local_fast_gate_and_escalation_policy_are_documented() -> None:
    """AC8.13.95: local defaults stay fast but escalate for high-risk paths."""
    ci_cd = read("docs/ssot/ci-cd.md")
    development = read("docs/ssot/development.md")
    readme = read("README.md")

    for token in (
        "Path Risk to Local Gate Matrix",
        "accounting, posting, reconciliation, money, balance",
        "schema, migrations",
        "API contract, OpenAPI",
        "shared common/tooling",
        "Docker, workflow, environment, deploy",
        "docs-only",
    ):
        assert token in ci_cd

    assert "Default local verification starts with affected fast tests" in development
    assert "moon run :test -- --smart" in development
    assert "Risk-triggered local escalation" in development
    assert "Default local loop" in readme
    assert "risk-triggered escalation" in readme


def test_AC8_13_67_backend_tier1_api_e2e_scope_excludes_browser_e2e() -> None:
    """AC8.13.67: Tier-1 backend API E2E does not collect Playwright browser E2E."""
    workflow = read(".github/workflows/ci.yml")
    pyproject = read("apps/backend/pyproject.toml")
    ci_cd = read("docs/ssot/ci-cd.md")

    tier1_block = workflow.split("  backend-e2e-tier1:", 1)[1].split("  frontend:", 1)[
        0
    ]

    assert "tests/e2e/test_core_journeys.py" in tier1_block
    assert "tests/e2e/test_auth_flows.py" not in tier1_block
    assert "tests/e2e/test_e2e_flows.py" not in tier1_block
    assert "playwright install" not in tier1_block
    assert (
        "e2e: End-to-end tests, including backend API scenarios and browser UI flows"
        in pyproject
    )
    assert "apps/backend/tests/e2e/test_core_journeys.py" in ci_cd


def test_AC8_13_27_coveralls_uploads_are_reporting_only() -> None:
    """AC8.13.27: PR CI has no external Coveralls status surface."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("docs/ssot/ci-cd.md")
    coverage = read("docs/ssot/coverage.md")
    readme = read("README.md")

    unified_block = workflow.split(
        "- name: Upload main unified coverage to Coveralls", 1
    )[1].split("  ac-traceability:", 1)[0]

    assert (
        "if: github.event_name == 'push' && github.ref == 'refs/heads/main'"
        in unified_block
    )
    assert "Upload backend to Coveralls (per-flag)" not in workflow
    assert "Upload frontend to Coveralls (per-flag)" not in workflow
    global_permissions = workflow.split("env:", 1)[0]
    unified_coverage_block = workflow.split("  unified-coverage:", 1)[1].split(
        "  ac-traceability:", 1
    )[0]
    assert "statuses: write" not in global_permissions
    assert "statuses: write" not in unified_coverage_block
    assert "Mark Coveralls statuses reporting-only" not in workflow
    assert "tools/mark_coveralls_reporting_status.py" not in workflow
    assert "publish_coveralls_reporting_statuses" not in workflow
    assert "Wait for Coveralls unified status" not in workflow
    assert "mark_coveralls_reporting_status.py" not in workflow
    assert "wait_for_github_status.py" not in workflow
    assert "Write coverage gate summary" in workflow
    assert "Authoritative coverage gate" in workflow
    assert "Pull requests do not publish Coveralls status contexts" in workflow
    assert "Pull requests do not call Coveralls" in ci_cd
    assert "coverage gate summary" in ci_cd
    assert "Coveralls badge is reporting-only" in coverage
    assert "authoritative coverage gate" in coverage
    assert "PR CI does not call Coveralls" in coverage
    assert "Pull requests do not publish" in readme
    assert "merge readiness follows the `finish` check" in readme


def test_AC8_13_75_coverage_gate_summary_is_nonblocking() -> None:
    """AC8.13.75: Coverage summary display cannot fail final CI aggregation."""
    workflow = read(".github/workflows/ci.yml")

    summary_block = workflow.split("- name: Write coverage gate summary", 1)[1].split(
        "- name: Check job status", 1
    )[0]

    assert "if: ${{ always() }}" in summary_block
    assert "continue-on-error: true" in summary_block
    assert "Authoritative coverage gate" in summary_block
    assert "badge/trend reporting only" in summary_block
    assert "Merge readiness follows" in summary_block


def test_AC8_13_75_unified_coverage_uploads_debug_context() -> None:
    """AC8.13.75: Unified coverage preserves line-level debug inputs."""
    workflow = read(".github/workflows/ci.yml")
    coverage = read("docs/ssot/coverage.md")
    ci_cd = read("docs/ssot/ci-cd.md")

    tooling_coverage_block = workflow.split("  tooling-coverage:", 1)[1].split(
        "  unified-coverage:", 1
    )[0]
    unified_coverage_block = workflow.split("  unified-coverage:", 1)[1].split(
        "  ac-traceability:", 1
    )[0]
    upload_block = unified_coverage_block.split(
        "- name: Upload unified coverage context", 1
    )[1].split("# Note: baseline auto-push removed", 1)[0]

    assert "Tooling/Common Coverage" in tooling_coverage_block
    assert "Run tooling tests with coverage" in tooling_coverage_block
    assert "Upload tooling coverage context" in tooling_coverage_block
    assert "name: coverage-tooling" in tooling_coverage_block
    assert "--cov=common" in tooling_coverage_block
    assert "--cov=tools" in tooling_coverage_block
    assert "Run tooling tests with coverage" not in unified_coverage_block
    assert "Download tooling coverage" in unified_coverage_block
    assert "Write coverage debug context" in unified_coverage_block
    assert "if: ${{ always() }}" in upload_block
    assert "name: unified-coverage-context" in upload_block
    assert "coverage/backend.lcov" in upload_block
    assert "coverage/frontend.lcov" in upload_block
    assert "coverage/common.lcov" in upload_block
    assert "coverage/tools.lcov" in upload_block
    assert "coverage/coverage-context.txt" in upload_block
    assert "unified-coverage.json" in upload_block
    assert "coverage context artifact" in coverage
    assert "unified-coverage-context" in coverage
    assert "raw line-count inputs" in ci_cd


def test_AC8_13_66_coveralls_uploads_use_line_only_lcov() -> None:
    """AC8.13.66: Main Coveralls reporting uses the unified line-only metric."""
    workflow = read(".github/workflows/ci.yml")
    coverage = read("docs/ssot/coverage.md")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert (
        "tools/build_unified_lcov.py coverage/coveralls-unified.lcov --strip-branches"
        in workflow
    )
    assert "file: coverage/coveralls-unified.lcov" in workflow
    assert "file: coverage/coveralls-backend.lcov" not in workflow
    assert "file: coverage/coveralls-frontend.lcov" not in workflow
    assert (
        "if: github.event_name == 'push' && github.ref == 'refs/heads/main'" in workflow
    )
    assert "Coveralls upload LCOV files are line-only" in coverage
    assert "Coveralls is a main-branch external reporting baseline only" in coverage
    assert "Coverage scope is deny-list based within each governed source root" in ci_cd
    assert "strip branch records before upload" in ci_cd


def test_AC8_13_93_staging_promotion_requires_manual_dispatch() -> None:
    """AC8.13.93: Staging is mutated only by an explicit manual dispatch; no auto path."""
    workflow = read(".github/workflows/staging-deploy.yml")
    ci_cd = read("docs/ssot/ci-cd.md")
    deployment = read("docs/ssot/deployment.md")

    parsed = yaml.safe_load(workflow)
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = parsed.get("on", parsed.get(True))
    assert isinstance(triggers, dict), "staging-deploy.yml must declare an `on:` map"
    # The ONLY trigger is a manual dispatch: no workflow_run / push / schedule path
    # can mutate staging.
    assert list(triggers.keys()) == ["workflow_dispatch"]
    assert "ref" in (triggers["workflow_dispatch"].get("inputs") or {})

    # The retired auto-deploy machinery (the dedicated "CI Workflow Run Ignored"
    # skip-summary job that fired on a non-success CI workflow_run) is gone.
    assert "ci-not-success-summary:" not in workflow
    assert "name: CI Workflow Run Ignored" not in workflow

    # The build-and-deploy job, image promotion, and Dokploy mutation only run on
    # a manual dispatch. Because workflow_dispatch is the sole `on:` trigger, a
    # job-level `if: github.event_name == 'workflow_dispatch'` would be redundant
    # (always true) and is intentionally absent.
    assert "if: ${{ github.event_name == 'workflow_dispatch' }}" not in workflow

    # The structured deploy failure-context classification is preserved.
    failure_context = workflow.split("Classify staging deploy failure context", 1)[
        1
    ].split("Write staging deploy context", 1)[0]
    for expected_line in [
        "id: deploy_failure_context",
        '"runner/docker-buildx-bootstrap"',
        '"registry/backend-image-resolution"',
        '"image-build/backend"',
        '"registry/frontend-image-resolution"',
        '"image-build/frontend"',
        '"dokploy-rollout-or-health"',
        '"application-smoke-e2e"',
        "Failure domain: ${failure_domain}",
        "Failed step: ${failed_step}",
        "Failure summary: ${failure_summary}",
    ]:
        assert expected_line in failure_context

    assert "Staging deploy is manual" in ci_cd
    assert "does not poll or wait for CI" in ci_cd
    assert "failure domain, failed step, and failure summary" in ci_cd
    assert "manual" in deployment.lower()


def test_AC8_13_45_make_test_routes_through_root_moon_test() -> None:
    """AC8.13.45: make test uses the root Moon verification entry point."""
    makefile = read("Makefile")
    development = read("docs/ssot/development.md")
    environments = read("docs/ssot/environments.md")

    assert "\n\tmoon run :test\n" in makefile
    assert "moon run backend:test" not in makefile
    assert "same gate family as GitHub CI" in development
    assert "same gate family as GitHub CI" in environments


def test_AC8_13_45_root_moon_tasks_do_not_hash_repo_submodule() -> None:
    """AC8.13.45: Root Moon gates avoid hashing the infra submodule gitlink."""
    moon = yaml.safe_load(read("moon.yml"))

    workspace_inputs = moon["fileGroups"]["workspace"]
    assert "repo" not in workspace_inputs
    assert "**/*" not in workspace_inputs
    assert "common/**/*" in workspace_inputs
    assert "tools/**/*" in workspace_inputs
    assert "uncached wrappers with explicit workspace inputs" in read(
        "docs/ssot/development.md"
    )

    for task_name in ("setup", "dev", "test", "lint", "build", "clean"):
        task = moon["tasks"][task_name]
        task_inputs = task["inputs"]
        assert task_inputs == ["@group(workspace)"]
        assert task["options"]["cache"] is False


def test_AC8_13_46_pr_preview_non_llm_gate_matches_staging_strict_parallelism() -> None:
    """AC8.13.46: PR preview keeps strictness while narrowing to preview scope."""
    preview = read(".github/workflows/pr-test.yml")
    staging = read(".github/workflows/staging-deploy.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    preview_block = preview.split("- name: End-to-End Tests", 1)[1].split(
        "- name: Rollback on E2E Failure", 1
    )[0]
    staging_block = staging.split("- name: End-to-End Tests", 1)[1].split(
        "\n  ai-ocr-gate:", 1
    )[0]

    for block in (preview_block, staging_block):
        assert "STRICT_E2E_GATES: true" in block
        assert '-m "(smoke or e2e) and not llm" -n 4' in block

    assert "PR_PREVIEW_E2E_TESTS=(" in preview_block
    assert "tests/e2e/test_core_journeys.py" in preview_block
    assert "tests/e2e/test_e2e_flows.py::test_full_navigation" in preview_block
    assert 'pytest "${PR_PREVIEW_E2E_TESTS[@]}"' in preview_block
    assert "pytest tests/e2e -v" not in preview_block

    assert 'pytest tests/e2e -v -m "(smoke or e2e) and not llm" -n 4' in staging_block

    assert "PR preview non-LLM E2E is a strict preview-relevant subset" in ci_cd


def test_AC8_13_38_pr_preview_dokploy_responses_are_not_logged() -> None:
    """AC8.13.38: PR preview cleanup parses Dokploy responses without raw logs."""
    preview = read(".github/workflows/pr-test.yml")
    ci_cd = read("docs/ssot/ci-cd.md")
    lifecycle = read("tools/_lib/dev/pr_preview_lifecycle.py")

    assert (
        "PR preview Dokploy API responses are parsed for required fields only" in ci_cd
    )
    assert "Cleanup preview lifecycle" in preview
    # Deploy + cleanup both go through pr_preview_lifecycle.py (no hand-rolled
    # Dokploy curl), so neither logs raw responses.
    assert "Deploy preview lifecycle" in preview
    assert "--action deploy" in preview
    assert "--action cleanup" in preview
    assert "Response body" not in lifecycle
    assert "raw_body_printed: false" in lifecycle
    assert "safe_message" in lifecycle

    unsafe_patterns = (
        r"response=\$\(curl[^)]*/compose\.create",
        r"curl -sf -X POST [^\n]*/compose\.update[\s\S]*?\n\s*-d \"\$PAYLOAD\"\n(?![\s\S]*?-o )",
        r"curl -sf -X POST [^\n]*/compose\.deploy[\s\S]*?\n\s*-d \"\{\\\"composeId",
        r"curl -sf -X POST [^\n]*/compose\.delete[\s\S]*?\n\s*-d \"\{\\\"composeId",
        r"echo \"Response: \$response\"",
    )
    for pattern in unsafe_patterns:
        assert re.search(pattern, preview) is None


def test_AC8_13_72_staging_deploy_proves_health_sha_after_dokploy_trigger() -> None:
    """AC8.13.72 AC8.13.106: staging proof checks health git_sha, not just Dokploy trigger."""
    workflow = read(".github/workflows/staging-deploy.yml")
    deploy_script = read("tools/_lib/shell/dokploy_deploy.sh")
    health_check = read("tools/_lib/shell/health_check.sh")

    deploy_block = workflow.split("- name: Deploy to Staging", 1)[1].split(
        "- name: Setup E2E Tests", 1
    )[0]

    assert "IMAGE_TAG: ${{ steps.get_sha.outputs.short_sha }}" in deploy_block
    assert "bash tools/dokploy_deploy.sh" in deploy_block
    assert "bash tools/health_check.sh" in deploy_block
    assert deploy_block.index("bash tools/dokploy_deploy.sh") < deploy_block.index(
        "bash tools/health_check.sh"
    )
    assert "wait_for_dokploy_deployment_rollout" in deploy_script
    assert "previous_deployment_ids" in deploy_script
    assert "render_dokploy_rollout_summary" in deploy_script
    assert "latest_deployment_logPath:" in deploy_script
    assert "raw_deployment_printed: false" in deploy_script
    assert "Dokploy deployment observed" in deploy_script
    assert "DOKPLOY_ROLLOUT_TIMEOUT_SECONDS:-600" in deploy_script
    assert "DOKPLOY_NEW_DEPLOYMENT_TIMEOUT_SECONDS:-120" in deploy_script
    assert "did not create a new deployment before readiness polling" in deploy_script
    assert "retrying with compose.redeploy" in deploy_script
    assert 'deploy_compose "compose.redeploy" "Redeployment trigger"' in deploy_script
    assert "Dokploy redeploy did not expose a new deployment record" in deploy_script
    assert "proceeding to target SHA health check" not in deploy_script
    assert "entered error before creating a new deployment record" in deploy_script
    assert "return 3" in deploy_script
    assert 'rollout_status" -eq 2 || "$rollout_status" -eq 3' in deploy_script
    assert (
        "Dokploy redeploy left compose in error without a new deployment record"
        in deploy_script
    )
    assert "render_dokploy_rollout_summary" in deploy_script
    assert "raw_deployment_printed: false" in deploy_script
    assert 'latest_status" == "done"' in deploy_script
    assert (
        'latest_status" == "running" || "$latest_status" == "done"' not in deploy_script
    )
    assert deploy_script.index('deploy_compose "compose.deploy"') < deploy_script.index(
        'wait_for_dokploy_deployment_rollout "$COMPOSE_ID" "$previous_deployment_ids"'
    )
    assert '"https://report-staging.zitian.party/api/health"' in deploy_block
    assert '"$IMAGE_TAG"' in deploy_block
    assert (
        'actual_sha=$(echo "$health_response" | jq -r \'.git_sha // .version // ""\')'
        in health_check
    )
    assert 'HEALTH_CHECK_MAX_SHA_MISMATCH_ATTEMPTS: "18"' in deploy_block
    assert "MAX_SHA_MISMATCH_ATTEMPTS" in health_check
    assert "Stable mismatch attempts" in health_check
    assert "Git SHA Mismatch" in health_check
    assert "exit 1" in health_check


def test_AC8_13_72_staging_dokploy_rollout_parsing_is_typed_and_fail_fast() -> None:
    """AC8.13.72: staging rollout parsing handles Dokploy shape drift clearly."""
    deploy_script = read("tools/_lib/shell/dokploy_deploy.sh")
    function_block = (
        "deployment_ids_from_response()"
        + deploy_script.split("deployment_ids_from_response()", 1)[1].split(
            "wait_for_dokploy_deployment_rollout()", 1
        )[0]
    )

    response = json.dumps(
        {
            "deployments": [
                {
                    "deploymentId": 123,
                    "status": "running",
                    "createdAt": "2026-01-01T00:00:00Z",
                },
                "not-a-deployment-object",
                {
                    "deploymentId": "dep-456",
                    "status": "done",
                    "finishedAt": "2026-01-01T00:01:00Z",
                },
            ]
        }
    )
    non_array_response = json.dumps({"deployments": {"deploymentId": "ignored"}})
    probe = subprocess.run(
        [
            "bash",
            "-e",
            "-u",
            "-o",
            "pipefail",
            "-c",
            function_block
            + """
response="$DOKPLOY_RESPONSE"
non_array_response="$DOKPLOY_NON_ARRAY_RESPONSE"
printf 'ids=%s\\n' "$(deployment_ids_from_response "$response")"
printf 'new=%s\\n' "$(new_deployment_ids_from_response "$response" "123")"
printf 'latest=%s\\n' "$(latest_new_deployment_status_from_response "$response" "dep-456")"
printf 'count=%s\\n' "$(deployment_count_from_response "$response")"
printf 'non_array=%s\\n' "$(deployment_ids_from_response "$non_array_response")"
printf 'non_array_count=%s\\n' "$(deployment_count_from_response "$non_array_response")"
""",
        ],
        cwd=ROOT,
        env={
            "DOKPLOY_RESPONSE": response,
            "DOKPLOY_NON_ARRAY_RESPONSE": non_array_response,
        },
        check=True,
        capture_output=True,
        text=True,
    )

    assert probe.stdout.splitlines() == [
        "ids=123,dep-456",
        "new=dep-456",
        "latest=done",
        "count=2",
        "non_array=",
        "non_array_count=0",
    ]
    assert 'select(type == "object")' in deploy_script
    assert "local deploy_payload" in deploy_script
    assert (
        'new_deployment_ids=$(new_deployment_ids_from_response "$rollout_response" "$previous_deployment_ids") || exit 1'
        in deploy_script
    )
    assert (
        'latest_status=$(latest_new_deployment_status_from_response "$rollout_response" "$new_deployment_ids") || exit 1'
        in deploy_script
    )
    assert (
        'previous_deployment_ids=$(deployment_ids_from_response "$effective_response") || exit 1'
        in deploy_script
    )
    assert (
        'deployment_count=$(deployment_count_from_response "$rollout_response") || exit 1'
        in deploy_script
    )


def test_AC8_13_72_staging_dokploy_noop_after_redeploy_fails_before_health() -> None:
    """AC8.13.72: staging fails when Dokploy accepts deploys without rollout records."""
    deploy_script = read("tools/_lib/shell/dokploy_deploy.sh")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "Dokploy redeploy did not expose a new deployment record" in deploy_script
    assert (
        "target SHA health check"
        not in deploy_script.split('if [[ "$rollout_status" -eq 2 ]]; then', 1)[
            1
        ].split('elif [[ "$rollout_status" -eq 3 ]]; then', 1)[0]
    )
    assert (
        'exit "$rollout_status"'
        in deploy_script.split('if [[ "$rollout_status" -eq 2 ]]; then', 1)[1].split(
            'elif [[ "$rollout_status" -eq 3 ]]; then', 1
        )[0]
    )
    assert (
        "fails before application readiness when no deployment record materializes"
        in ci_cd
    )


def test_AC8_13_108_staging_failure_context_fails_closed_on_classifier_and_unknown_failures() -> (
    None
):
    """AC8.13.108: staging failure context does not hide real failures as skips."""
    workflow = read(".github/workflows/staging-deploy.yml")
    failure_context = workflow.split("Classify staging deploy failure context", 1)[
        1
    ].split("Write staging deploy context", 1)[0]

    for step_id in [
        "checkout",
        "get_sha",
        "classify",
        "install_moon",
        "install_uv",
        "setup_python",
        "registry_login",
        "setup_buildx",
    ]:
        assert f"id: {step_id}" in workflow

    assert '"classification"' in failure_context
    assert '"change-classification"' in failure_context
    assert (
        "Change classification failed before staging relevance could be trusted."
        in failure_context
    )
    assert '"toolchain/moon-install"' in failure_context
    assert '"toolchain/uv-install"' in failure_context
    assert '"toolchain/python-setup"' in failure_context
    assert '"registry/login"' in failure_context
    assert '"unclassified-build-deploy-failure"' in failure_context
    assert (
        "A build/deploy job step failed outside the known failure map."
        in failure_context
    )
    assert "STEPS_CONTEXT: ${{ toJSON(steps) }}" in failure_context
    assert 'grep -q \'"outcome":"failure"\'' in failure_context
    assert failure_context.index('"change-classification"') < failure_context.index(
        'staging_required" != "true"'
    )


def test_AC8_13_47_delivery_engine_recommendations_are_tracked() -> None:
    """AC8.13.47: remaining delivery-engine work is captured outside mutable SSOT."""
    recommendation = read("docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md")
    project_readme = read("docs/project/README.md")
    ci_cd = read("docs/ssot/ci-cd.md")

    for token in (
        "Coveralls reporting split",
        "workflow_run staging trigger",
        "parallel image build jobs",
        "Current baseline",
        "Out of scope for this PR",
    ):
        assert token in recommendation

    assert "DELIVERY_ENGINE_RECOMMENDATIONS.md" in project_readme
    assert "delivery-engine recommendation note" in ci_cd


def test_AC8_13_112_sparse_matrix_recommendation_tracks_simplification_path() -> None:
    """AC8.13.112: sparse-matrix audit keeps the simplification path explicit."""
    recommendation = read("docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md")
    ci_cd = read("docs/ssot/ci-cd.md")
    classifier = read("common/ci/change_classifier.py")

    for token in (
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
    ):
        assert token in recommendation

    assert "Env x Stage Contract" in ci_cd
    assert "Legacy scalar outputs" in ci_cd
    assert (
        "GitHub Actions consumers normalize gates from the structured matrix" in ci_cd
    )
    assert "ENV_STAGE_MATRIX" in classifier
    assert "LEGACY_ENV_OUTPUTS" in classifier


def test_AC8_13_112_workflows_consume_structured_env_stage_gates() -> None:
    """AC8.13.112: workflows consume structured gates, not legacy scalar gates."""
    ci_workflow = read(".github/workflows/ci.yml")
    pr_workflow = read(".github/workflows/pr-test.yml")
    staging_workflow = read(".github/workflows/staging-deploy.yml")

    assert "pr_required: ${{ steps.gates.outputs.pr_required }}" in ci_workflow
    assert (
        "ENV_STAGE_REQUIRED: ${{ steps.classify.outputs.env_stage_required }}"
        in ci_workflow
    )
    assert (
        "ENV_STAGE_REASONS: ${{ steps.classify.outputs.env_stage_reasons }}"
        in ci_workflow
    )
    assert "if: needs.changes.outputs.pr_required == 'true'" in ci_workflow
    assert "needs.changes.outputs.heavy_required" not in ci_workflow
    assert (
        "heavy_required: ${{ steps.classify.outputs.heavy_required }}"
        not in ci_workflow
    )

    assert (
        "pr_preview_required: ${{ steps.preview_gate.outputs.pr_preview_required }}"
        in pr_workflow
    )
    assert (
        "ENV_STAGE_REQUIRED: ${{ steps.preview.outputs.env_stage_required }}"
        in pr_workflow
    )
    assert (
        "ENV_STAGE_REASONS: ${{ steps.preview.outputs.env_stage_reasons }}"
        in pr_workflow
    )
    assert "required['pr-preview']" in pr_workflow
    assert "steps.preview.outputs.pr_preview_required" not in pr_workflow

    assert (
        "staging_required: ${{ steps.gates.outputs.staging_required }}"
        in staging_workflow
    )
    assert (
        "ai_ocr_required: ${{ steps.gates.outputs.ai_ocr_required }}"
        in staging_workflow
    )
    assert (
        "ENV_STAGE_REQUIRED: ${{ steps.classify.outputs.env_stage_required }}"
        in staging_workflow
    )
    assert (
        "PROVIDER_GATE_REQUIRED: ${{ steps.classify.outputs.provider_gate_required }}"
        in staging_workflow
    )
    assert (
        "STAGING_AI_OCR_REQUIRED: ${{ steps.classify.outputs.staging_ai_ocr_required }}"
        in staging_workflow
    )
    assert (
        "STAGING_AI_OCR_REASON: ${{ steps.classify.outputs.staging_ai_ocr_reason }}"
        in staging_workflow
    )
    assert "staging_ai_ocr_required_raw" in staging_workflow
    assert "staging_ai_ocr_reason = os.environ.get" in staging_workflow
    assert "env_required['staging']" in staging_workflow
    assert "provider_required['staging']" in staging_workflow
    assert "steps.classify.outputs.staging_required" not in staging_workflow


def test_AC8_13_113_sparse_matrix_evidence_and_resource_leak_audit_are_recorded() -> (
    None
):
    """AC8.13.113: sparse-matrix review records log evidence and leak risks."""
    epic = read("docs/project/EPIC-008.testing-strategy.md")
    recommendation = read("docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md")

    for token in (
        "AC8.13.113",
        "three newest successful and three newest failed",
        "delivery-speed balance",
        "end-to-end consistency",
        "quality fallback",
        "resource leak candidates",
    ):
        assert token in epic

    for token in (
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
        "PR preview Dokploy compose",
        "GHCR PR images",
        "Docker build cache",
        "stale staging or production routes",
        "safe simplification boundary",
    ):
        assert token in recommendation


def test_AC8_13_119_delivery_resource_leak_hardening_is_contracted() -> None:
    """AC8.13.119: delivery cleanup covers the five known leak paths."""
    epic = read("docs/project/EPIC-008.testing-strategy.md")
    recommendation = read("docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md")
    preview_cleanup = read(".github/workflows/pr-preview-cleanup.yml")
    pr_preview = read(".github/workflows/pr-test.yml")
    staging = read(".github/workflows/staging-deploy.yml")
    production = read(".github/workflows/production-release.yml")
    hygiene = read("tools/_lib/dev/vps_host_hygiene.py")

    for token in (
        "AC8.13.119",
        "PR preview leftovers",
        "GHCR PR tag accumulation",
        "stale staging or production routes",
        "provider-backed external-state residue",
        "Docker build cache and stopped containers",
    ):
        assert token in epic

    for token in (
        "Resource leak hardening bundle",
        "one PR",
        "closed-PR Dokploy reconciliation",
        "closed-PR PR preview GHCR tags",
        "production_before_version",
        "isolated-users-provider-gate-only",
        "finance-report-vps-host-hygiene",
    ):
        assert token in recommendation

    assert "packages: write" in preview_cleanup
    assert "Prune stale PR preview GHCR tags" in preview_cleanup
    assert "retention_days=14" in preview_cleanup
    assert "gh pr list --state open" in preview_cleanup
    assert 'owner_type="$(gh api' in preview_cleanup
    assert (
        'package_scope_path="/orgs/${{ github.repository_owner }}"' in preview_cleanup
    )
    assert (
        'package_scope_path="/users/${{ github.repository_owner }}"' in preview_cleanup
    )
    assert (
        '"${package_scope_path}/packages/container/${image_name}/versions"'
        in preview_cleanup
    )
    assert "if ! gh api \\" in preview_cleanup
    assert "list-failed package_scope=${package_scope_path}" in preview_cleanup
    assert "continue" in preview_cleanup
    assert (
        'f"{package_scope_path}/packages/container/{image_name}/versions/{version_id}"'
        in preview_cleanup
    )
    assert (
        '"/orgs/${{ github.repository_owner }}/packages/container'
        not in preview_cleanup
    )
    assert 'f"/orgs/{owner}/packages/container' not in preview_cleanup
    assert r"^pr-([1-9][0-9]*)-[0-9a-f]{40}$" in preview_cleanup
    assert "ghcr_cleanup=closed-pr-pr-tags-older-than-14-days" in preview_cleanup
    assert "host_hygiene_schedule=finance-report-vps-host-hygiene" in preview_cleanup
    assert "VPS_SSH_KEY" not in preview_cleanup
    assert "ssh-keyscan" not in preview_cleanup

    assert "Delete GHCR images" not in pr_preview
    assert "pr_preview_images=not-created" in pr_preview
    assert "registry_image_push=false" in pr_preview

    assert "provider_resource_boundary=isolated-users-provider-gate-only" in staging
    assert "shared mutable user fixtures" in staging

    assert "Probe current production version" in production
    assert "production_before_version" in production
    assert "deploy_health_outcome" in production
    assert "failure_domain=${failure_domain}" in production
    assert "production-deploy-health-or-version" in production

    assert "finance-report-vps-host-hygiene" in hygiene
    assert "docker builder prune" in hygiene
    assert "docker image prune" in hygiene
    assert "docker network prune" in hygiene
    assert "journalctl --vacuum" in hygiene


def test_AC8_13_10_multi_brokerage_upload_to_portfolio_value_gate() -> None:
    """AC8.13.10: Staging proves multi-brokerage upload through latest value."""
    workflow = read(".github/workflows/staging-deploy.yml")
    brokerage = read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")
    statements_router = read("apps/backend/src/routers/statements.py")
    generator = read("tools/_lib/pdf_fixtures/generate_pdf_fixtures.py")

    assert "tools/staging_ai_ocr_gate_contract.py --shell" in workflow
    assert (
        "test_brokerage_upload_to_portfolio_value.py" in staging_ai_ocr_contract_shell()
    )
    assert '-m "llm"' in workflow
    assert "pytest.mark.critical" in brokerage
    assert "pytest.mark.llm" in brokerage
    assert '("moomoo", "Moomoo E2E Portfolio")' in brokerage
    assert '("futu", "Futu E2E Portfolio")' in brokerage
    assert "/statements/upload" in brokerage
    assert "/brokerage/import" in brokerage
    assert "/portfolio/holdings" in brokerage
    assert "/reports/balance-sheet" in brokerage
    assert "fail_or_skip_ai_ocr_gate(" in brokerage
    assert "parsed_positions" in brokerage
    assert "_assert_portfolio_market_valuation_covered" in brokerage
    assert "_market_valuation_lines" in brokerage
    assert "market_valuation_adjustment_total" in brokerage
    assert "non_portfolio_asset_total" in brokerage
    assert "BrokeragePositionImportService" in statements_router
    assert (
        "Statement must be parsed before importing brokerage positions"
        in statements_router
    )
    assert '"futu"' in generator


def test_AC8_13_19_brokerage_gate_reports_portfolio_diagnostics() -> None:
    """AC8.13.19: Brokerage gate failures include portfolio valuation diagnostics."""
    brokerage = read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")

    for token in (
        "imported_positions=",
        "holdings_total_market_value=",
        "market_valuation_adjustment_total=",
        "non_portfolio_asset_total=",
        "net_worth_adjustment_gain_loss=",
        "relevant_asset_lines=",
    ):
        assert token in brokerage


def test_AC8_13_28_vision_hard_gate_uses_deterministic_fixture_with_fresh_user() -> (
    None
):
    """AC8.13.28/29/30/31: deterministic upload-to-dashboard gate covers the full fresh-user flow."""
    gate = read("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py")
    epic = read("docs/project/EPIC-008.testing-strategy.md")

    assert "@pytest.mark.e2e" in gate
    assert "@pytest.mark.tier3" in gate
    assert "@pytest.mark.critical" in gate
    assert "@pytest.mark.llm" not in gate
    assert "authenticated_page_unique" in gate
    assert "vision_hard_gate_statement.csv" in gate
    assert "pytest.skip(" in gate
    assert "AC8.13.28" in epic
    assert "AC8.13.29" in epic
    assert "AC8.13.30" in epic
    assert "AC8.13.31" in epic
    assert "test_statement_upload_to_dashboard_vision_hard_gate" in epic


def test_AC8_13_28_vision_hard_gate_uses_statement_id_link_locator() -> None:
    """AC8.13.28: statement upload E2E locates the detail link by statement id."""
    gate = read("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py")
    test_body = gate.split(
        "async def test_statement_upload_to_dashboard_vision_hard_gate", 1
    )[1]

    assert "f'a[href=\"/statements/{statement_id}\"]'" in test_body
    assert "statement_card" in test_body
    assert "fixture_path.name" in test_body
    assert "filter(has_text=INSTITUTION_LABEL).first" not in test_body
    assert 'page.locator("a").filter(has_text=INSTITUTION_LABEL)' not in test_body


def test_AC8_13_28_vision_hard_gate_waits_for_review_payload_before_approval() -> None:
    """AC8.13.28: staging hard gate waits for Stage 1 review data before approving."""
    gate = read("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py")
    test_body = gate.split(
        "async def test_statement_upload_to_dashboard_vision_hard_gate", 1
    )[1]

    assert 'review_path = f"/statements/{statement_id}/review"' in test_body
    assert "f\"a[href='{review_path}']\"" in test_body
    assert "page.expect_response(" in test_body
    assert 'r.request.method == "GET"' in test_body
    assert 'f"/api/statements/{statement_id}/review"' in test_body
    assert "review_resp.status == 200" in test_body
    assert "(await review_resp.text())[:1_000]" in test_body
    assert 'get_by_role("button", name="Approve", exact=True)' in test_body
    assert 'get_by_role("link", name=re.compile("Start Review"))' not in test_body


def test_AC8_13_30_vision_hard_gate_waits_for_stage2_queue_page_payload() -> None:
    """AC8.13.30: staging hard gate waits for Stage 2 queue data before UI assertions."""
    gate = read("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py")
    test_body = gate.split(
        "async def test_statement_upload_to_dashboard_vision_hard_gate", 1
    )[1]

    assert 'stage2_queue_path = "/api/statements/stage2/queue"' in test_body
    assert 'r.request.method == "GET"' in test_body
    assert "stage2_page_resp.status == 200" in test_body
    assert "stage2_page_info" in test_body
    assert "(await stage2_page_resp.text())[:1_000]" in test_body


def test_AC8_13_32_vision_hard_gate_proves_trusted_reporting_totals() -> None:
    """AC8.13.32: deterministic vision gate asserts exact trusted accounting/report totals."""
    gate = read("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py")
    ci_cd = read("docs/ssot/ci-cd.md")

    for token in (
        "journal_entries_created",
        "/api/reconciliation/run",
        "/api/statements/stage2/queue",
        "/api/accounts/processing/summary",
        "/dashboard",
        "/reports/balance-sheet",
        "/reports/income-statement",
        "/api/reports/cash-flow",
        '"total_income": Decimal("5600.00")',
        '"total_expenses": Decimal("5600.00")',
        '"net_income": Decimal("0.00")',
        '"No pending matches"',
        '"No pending transfers found."',
    ):
        assert token in gate
    assert 'f"/reports/cash-flow' not in gate
    assert '"Cash Flow Statement"' not in gate
    assert "upload-to-dashboard vision hard gate" in ci_cd


def test_AC8_13_42_four_asset_net_worth_golden_path_is_post_merge_critical() -> None:
    """AC8.13.42: four-asset as-of net worth proof is wired into the post-merge hard gate."""
    gate = read("tests/e2e/test_four_asset_net_worth_golden_path.py")
    deploy_workflow = read(".github/workflows/staging-deploy.yml")
    ai_workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    matrix = critical_matrix_text()
    epic = read("docs/project/EPIC-008.testing-strategy.md")
    ci_cd = read("docs/ssot/ci-cd.md")

    for token in (
        "@pytest.mark.e2e",
        "@pytest.mark.tier3",
        "@pytest.mark.critical",
        "@pytest.mark.llm",
        "authenticated_page_unique",
        "/statements/upload",
        "/review/approve",
        "/reconciliation/run",
        "/brokerage/import",
        "/assets/valuation-snapshots",
        "/assets/valuation-components",
        "/reports/balance-sheet",
        "include_restricted=true",
        "/dashboard",
        'BANK_CASH = Decimal("2500.00")',
        'PROPERTY_VALUE = Decimal("1200000.00")',
        'MORTGAGE_BALANCE = Decimal("650000.00")',
        'ESOP_VALUE = Decimal("42000.00")',
        "expected_net_worth",
        "net_worth_adjustment_gain_loss",
        "market valuation adjustment",
    ):
        assert token in gate

    for workflow in (deploy_workflow, ai_workflow):
        assert "tools/staging_ai_ocr_gate_contract.py --shell" in workflow
        assert '-v -m "llm"' in workflow
    assert "test_four_asset_net_worth_golden_path.py" in staging_ai_ocr_contract_shell()

    assert "four-asset-as-of-net-worth" in matrix
    assert "test_four_asset_as_of_net_worth_golden_path" in matrix
    assert "AC8.13.42" in matrix
    assert "AC8.13.42" in epic
    assert "test_four_asset_as_of_net_worth_golden_path" in epic
    assert "four-asset gate" in ci_cd


def test_AC8_13_33_e2e_setup_caches_virtualenv_and_playwright_browsers() -> None:
    """AC8.13.33: shared E2E setup caches Python and Playwright install work."""
    action = read(".github/actions/setup-e2e-tests/action.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "Cache E2E virtualenv" in action
    assert "path: .venv" in action
    assert (
        "e2e-venv-${{ runner.os }}-${{ hashFiles('tests/e2e/requirements.txt') }}"
        in action
    )
    assert "Cache Playwright browsers" in action
    assert "path: ~/.cache/ms-playwright" in action
    assert (
        "playwright-${{ runner.os }}-${{ hashFiles('tests/e2e/requirements.txt') }}"
        in action
    )
    assert "if [ ! -x .venv/bin/python ]; then" in action
    assert (
        'echo "PYTHONPATH=${GITHUB_WORKSPACE:-$PWD}${PYTHONPATH:+:$PYTHONPATH}"'
        ' >> "$GITHUB_ENV"'
    ) in action
    assert "uv pip install -r tests/e2e/requirements.txt" in action
    assert "shared E2E setup action caches `.venv` and Playwright browsers" in ci_cd


def test_AC8_13_34_ci_and_post_merge_write_timing_summaries() -> None:
    """AC8.13.34: CI and post-merge workflows report queue and critical-path timing."""
    ci_workflow = read(".github/workflows/ci.yml")
    deploy_workflow = read(".github/workflows/staging-deploy.yml")
    timing_script = read("common/ci/github_workflow_timing_summary.py")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "Write CI timing summary" in ci_workflow
    assert "tools/github_workflow_timing_summary.py" in ci_workflow
    assert '--title "CI Timing Summary"' in ci_workflow
    assert '--run-id "${{ github.run_id }}"' in ci_workflow
    assert '--summary-path "$GITHUB_STEP_SUMMARY"' in ci_workflow
    assert "post-merge-summary:" in deploy_workflow
    assert (
        "needs: [build-and-deploy, provider-gate, ai-ocr-gate, post-merge-delivery]"
        in deploy_workflow
    )
    assert "Write post-merge timing summary" in deploy_workflow
    assert '--title "Post-merge Timing Summary"' in deploy_workflow
    assert "Queue delay" in timing_script
    assert "Longest completed job" in timing_script
    assert "GitHub Step Summary" in ci_cd


def test_AC8_13_114_pr_preview_follows_successful_ci_workflow_run() -> None:
    """AC8.13.114: the in-runner e2e gate runs synchronously on pull_request, so it is a
    real required check a fast/auto merge cannot bypass. It no longer follows CI async
    via workflow_run — that fired after CI and a quick merge could land before it ran as
    a gate (skipped required checks count as passed). It is image-free, so it needs no
    CI artifact and runs independently."""
    workflow = read(".github/workflows/pr-test.yml")
    assert "workflow_run:" not in workflow
    assert "types: [opened, synchronize, reopened, closed]" in workflow
    assert 'action_reason = "pull-request-sync"' in workflow
    assert 'action = "deploy"' in workflow
    assert 'action = "cleanup"' in workflow  # pull_request closed -> cleanup
    assert "pr_preview_required == 'true'" in workflow
    assert "tools/wait_for_cheap_ci.py" not in workflow
    assert "gate-cheap-ci:" not in workflow
    assert "build-preview-backend-image:" not in workflow
    assert "build-preview-frontend-image:" not in workflow


def test_AC8_13_115_readiness_fail_fast() -> None:
    """AC8.13.115: Runner preview readiness is bounded before smoke/E2E starts."""
    workflow = read(".github/workflows/pr-test.yml")
    e2e_block = workflow.split("  e2e:", 1)[1].split("  cleanup:", 1)[0]
    assert "timeout-minutes: 25" in e2e_block
    assert "Wait for stack readiness" in e2e_block
    assert "for i in $(seq 1 60)" in e2e_block
    assert "stack did not become healthy within 300s" in e2e_block
    assert "consecutive_dokploy_failures" not in workflow
    assert "consecutive_404_failures" not in workflow


def test_AC8_13_116_skip_heavy_ci_on_main_push() -> None:
    """AC8.13.116: Post-merge -> staging start latency is reduced by removing redundant heavy re-run on push to main."""
    workflow = read(".github/workflows/ci.yml")

    # Check that heavy jobs skip on push to main by checking pr_required gate
    for job in [
        "schema-migrations:",
        "backend:",
        "backend-integration:",
        "backend-e2e-tier1:",
        "frontend:",
        "tooling-coverage:",
        "unified-coverage:",
    ]:
        job_block = workflow.split(job, 1)[1].split("\n\n", 1)[0]
        assert "if: needs.changes.outputs.pr_required == 'true'" in job_block

    # Check container-images has pr_required gate
    container_images_block = workflow.split("  container-images:", 1)[1].split(
        "\n\n", 1
    )[0]
    assert "if: needs.changes.outputs.pr_required == 'true'" in container_images_block

    # Check finish job handles skipped tests on push via pr_required output
    finish_block = workflow.split("  finish:", 1)[1]
    assert (
        'if [[ "${{ needs.changes.outputs.pr_required }}" == "true" ]]; then'
        in finish_block
    )


def test_AC8_13_118_timeouts_and_retries_documented() -> None:
    """AC8.13.118: Critical-path timeouts and retries are documented in docs/ssot/ci-cd.md."""
    ci_cd = read("docs/ssot/ci-cd.md")
    # The staging FIFO train wait is retired with the manual-only model; staging is
    # serialized by the workflow concurrency group, so no FIFO timeout is documented.
    assert "STAGING_FIFO_TIMEOUT_SECONDS" not in ci_cd
    assert "The runner stack waits for `/api/health` before smoke/E2E" in ci_cd
    assert "caps readiness at 300 seconds" in ci_cd
    assert "docker compose down --volumes" in ci_cd
    assert "parallel staging" in ci_cd


def test_wait_for_cheap_ci_full_flow(monkeypatch) -> None:
    """Test wait_for_cheap_ci with mock urlopen to get full test coverage."""
    import importlib

    importlib.import_module("tools.wait_for_cheap_ci")
    from common.ci.wait_for_cheap_ci import GitHubActionsClient, main
    import urllib.request
    import urllib.error
    from io import BytesIO
    import json

    class MockResponse:
        def __init__(self, data: bytes, code: int = 200):
            self.data = data
            self.code = code

        def read(self) -> bytes:
            return self.data

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    def mock_urlopen(request, timeout=None):
        url = request.full_url
        if "jobs" in url:
            res_data = {
                "jobs": [
                    {"name": "Lint", "status": "completed", "conclusion": "success"},
                    {
                        "name": "AC Traceability Check",
                        "status": "completed",
                        "conclusion": "success",
                    },
                ]
            }
            return MockResponse(json.dumps(res_data).encode("utf-8"))
        elif "runs" in url:
            res_data = {
                "workflow_runs": [
                    {
                        "id": 3,
                        "status": "completed",
                        "conclusion": "success",
                        "created_at": "2026-06-08T10:00:00Z",
                    },
                    {
                        "id": 4,
                        "status": "queued",
                        "conclusion": None,
                        "created_at": "2026-06-08T10:01:00Z",
                    },
                ]
            }
            return MockResponse(json.dumps(res_data).encode("utf-8"))
        return MockResponse(b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    # Test error handling path
    client = GitHubActionsClient(repository="owner/repo", token="tok")

    def mock_urlopen_error(request, timeout=None):
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=BytesIO(b"Forbidden error body"),
        )

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_error)
    try:
        client.get_workflow_runs("abc")
    except RuntimeError as e:
        assert "GitHub API HTTP 403" in str(e)

    # Restore normal mock_urlopen
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    argv = [
        "--repository",
        "owner/repo",
        "--token",
        "tok",
        "--commit-sha",
        "abc123",
        "--poll-seconds",
        "1",
        "--timeout-seconds",
        "5",
    ]
    res = main(argv)
    assert res == 0
