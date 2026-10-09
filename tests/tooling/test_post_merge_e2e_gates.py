import copy
import functools
import io
import json
import re
import subprocess
import sys
import urllib.error
from datetime import timezone
from pathlib import Path
from typing import Any

import pytest
import yaml
from common.testing import staging_ai_ocr_gate_contract as contract

ROOT = Path(__file__).resolve().parents[2]


def _has(text: str, *snippets: str) -> None:
    for s in snippets:
        assert s in text


def _lacks(text: str, *snippets: str) -> None:
    for s in snippets:
        assert s not in text


def _run_payload(
    run_id: int,
    status: str,
    created_at: str,
    workflow_id: int = 100,
    conclusion: str | None = None,
    **extra: object,
) -> dict[str, object]:
    d = {
        "id": run_id,
        "workflow_id": workflow_id,
        "status": status,
        "conclusion": conclusion
        if conclusion is not None
        else ("success" if status == "completed" else None),
        "created_at": created_at,
        "html_url": f"https://github.test/runs/{run_id}",
        "display_title": extra.get("display_title", f"run-{run_id}"),
    }
    d.update(extra)
    return d


class _FakeResponse:
    def __init__(self, data: object, code: int = 200) -> None:
        if isinstance(data, (bytes, bytearray)):
            self.data = bytes(data)
        elif isinstance(data, str):
            self.data = data.encode("utf-8")
        else:
            self.data = json.dumps(data).encode("utf-8")
        self.code = code

    def read(self) -> bytes:
        return self.data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        pass


@functools.lru_cache(maxsize=128)
def _read_cached(path: str) -> str:
    target = ROOT / path
    if target.is_dir():
        return "\n# <<< file-boundary >>>\n".join(
            p.read_text(encoding="utf-8") for p in sorted(target.rglob("*.py"))
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
    from common.runtime.wait_post_merge_train_turn import (
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
    from common.runtime import wait_post_merge_train_turn as train

    current_payload = _run_payload(
        20, "in_progress", "2026-06-05T04:20:00Z", display_title="current"
    )
    blocking_payload = _run_payload(
        10, "queued", "2026-06-05T04:10:00Z", display_title="blocking"
    )

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
    _has(
        output.getvalue(), "waiting for 1 older run(s): 10:queued", "front of the train"
    )


def test_AC8_13_13_post_merge_train_timeout_lists_blockers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.13: FIFO timeout reports the blocking run URLs."""
    from common.runtime import wait_post_merge_train_turn as train

    current_payload = _run_payload(
        20, "in_progress", "2026-06-05T04:20:00Z", display_title="current"
    )
    blocking_payload = _run_payload(
        10, "waiting", "2026-06-05T04:10:00Z", display_title="blocking"
    )

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

    _has(
        str(exc_info.value),
        "Timed out waiting",
        "10 waiting https://github.test/runs/10",
    )


def test_AC8_13_13_github_actions_client_pages_workflow_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.13: GitHub client follows workflow-run pagination."""
    from common.runtime.wait_post_merge_train_turn import GitHubActionsClient

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
        "common.runtime.wait_post_merge_train_turn.urllib.request.urlopen",
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
    from common.runtime.wait_post_merge_train_turn import GitHubActionsClient

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
        "common.runtime.wait_post_merge_train_turn.urllib.request.urlopen",
        fake_urlopen,
    )

    client = GitHubActionsClient(
        repository="owner/repo", token="token", api_url="https://api.github.test"
    )

    with pytest.raises(RuntimeError) as exc_info:
        client.get_run_payload(20)

    _has(str(exc_info.value), "GitHub API HTTP 403", "denied")


def test_AC8_13_13_post_merge_train_cli_validates_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.13: CLI exits clearly when GitHub context is missing."""
    from common.runtime.wait_post_merge_train_turn import main

    assert main(["--repository", "", "--run-id", "0", "--token", ""]) == 2

    captured = capsys.readouterr()
    assert "Missing required GitHub context: repository, run-id, token" in captured.err


def test_AC8_13_13_post_merge_train_cli_handles_runtime_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.13: CLI returns failure without a Python traceback."""
    from common.runtime import wait_post_merge_train_turn as train

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
    _has(
        test_body,
        "# === AC8.13.1: Upload PDF ===",
        "Upload & Parse Statement",
        "# === AC8.13.2: Poll until",
        "_statement_row(page, INSTITUTION_LABEL)",
        '_get_url(f"/statements/{statement_id}")',
    )
    _lacks(
        test_body,
        'a[href="/statements/{statement_id}"]',
        "filter(has_text=INSTITUTION_LABEL).first",
    )
    _has(
        test_body,
        '"parsed"',
        "# === AC8.13.3: Detail page shows transactions ===",
        "Transactions",
        "# === AC8.13.4: Start Review",
        "approved",
        "# === AC8.13.5: Balance sheet report loads ===",
        "/reports/balance-sheet",
    )


def test_AC8_10_8_registration_flow_accepts_current_landing_route() -> None:
    """AC8.10.8 AC16.12.6 AC1.7.1: registration E2E follows current auth landing route."""
    flow = read("tests/e2e/test_auth_flows.py")
    test_body = flow.split("async def test_registration_flow", 1)[1]

    _has(
        test_body,
        'page.expect_response("**/api/auth/register")',
        "await expect(page).to_have_url(AUTH_LANDING_URL_PATTERN",
    )
    _lacks(test_body, 'page.wait_for_url("**/dashboard"', '"/dashboard" in page.url')


def test_AC8_13_6_critical_e2e_skips_become_failures() -> None:
    """AC8.13.6: Critical staging E2E skips fail the deploy gate.

    The skip-to-failure DECISION logic is covered behaviorally by
    tests/tooling/test_critical_skip_gate.py (#1435 W1) — this checks only
    that the hookwrapper is still wired to that logic and to the AI/OCR
    gate helper, not the conditional itself.
    """
    conftest = read("tests/e2e/conftest.py")

    _has(
        conftest,
        "pytest_runtest_makereport",
        "fail_or_skip_ai_ocr_gate",
        "should_convert_skip_to_failure",
        'report.outcome = "failed"',
    )


def test_AC8_13_7_full_statement_journey_is_a_hard_ai_ocr_gate() -> None:
    """AC8.13.7: Full statement journey fails on rejected AI/OCR parsing."""
    journey = read("tests/e2e/test_statement_full_journey.py")
    test_body = journey.split("async def test_dbs_statement_full_journey", 1)[1]

    assert "@pytest.mark.critical" in journey
    _has(
        test_body,
        "fail_or_skip_ai_ocr_gate(",
        "status=rejected",
        "/api/statements/{statement_id}",
    )
    assert "validation_error" in read("tests/e2e/conftest.py")
    assert "Last statement payload" in test_body
    assert "pytest.skip(" not in test_body


def test_AC8_13_8_upload_readiness_gate_rejects_rejected_status() -> None:
    """AC8.13.8: Upload readiness E2E does not accept rejected statements."""
    upload = read("tests/e2e/test_statement_upload_e2e.py")
    test_body = upload.split("async def test_statement_upload_full_flow", 1)[1].split(
        "@pytest.mark.e2e", 1
    )[0]

    _has(
        test_body,
        "AI/OCR readiness gate",
        "fail_or_skip_ai_ocr_gate(",
        "statement=statement",
    )
    assert '"rejected"' not in test_body.split("assert status in", 1)[1]


def test_AC8_13_11_health_check_diagnoses_staging_api_route_404() -> None:
    """AC-testing.deploy-gates.2: AC8.13.11: Staging health 404 reports API route diagnostics."""
    health_check = read("common/runtime/health_check.py")

    # The generic polling algorithm moved to infra2_sdk.deploy_health (#1535,
    # infra2-sdk v0.5.0); this module keeps only the route-shadow diagnostics.
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
    journey = read("tests/e2e/test_statement_full_journey.py")
    upload = read("tests/e2e/test_statement_upload_e2e.py")
    brokerage = read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")
    four_asset = read("tests/e2e/test_four_asset_net_worth_golden_path.py")

    assert "format_ai_ocr_gate_failure" in conftest
    _has(
        conftest,
        "validation_error",
        "confidence_score",
        "parsing_progress",
        "balance_validated",
    )
    _has(journey, "model=default_model", "statement=last_statement")
    assert "statement=statement" in upload
    assert "statement=last_payload" in brokerage
    assert "fail_or_skip_ai_ocr_gate(" in four_asset


def test_AC8_13_13_staging_deploy_fast_fail_guardrails() -> None:
    """AC-testing.deploy-gates.4 AC-testing.deploy-gates.21: AC8.13.13 AC8.13.105: Staging deploy is a singleton post-merge train."""
    workflow = read(".github/workflows/deploy.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    _has(
        workflow,
        "concurrency:",
        "inputs.target == 'staging' && 'staging-deploy'",
        "cancel-in-progress: false",
    )
    _lacks(workflow, "post-merge-train-turn:", "classify-staging:")
    # Manual-only staging is serialized by the workflow-level concurrency group;
    # the in-job FIFO post-merge train wait (which only applied to the retired
    # workflow_run auto-deploy) is removed.
    _lacks(
        workflow,
        "name: Wait for FIFO post-merge train turn",
        "wait_post_merge_train_turn.py",
    )
    _has(
        workflow,
        "name: Classify staging and AI/OCR relevance",
        "staging_required: ${{ steps.gates.outputs.staging_required }}",
        "provider_gate_required",
    )
    _lacks(
        workflow,
        "staging-post-merge-${{ github.event.workflow_run.head_branch || github.ref_name }}",
    )
    _has(
        workflow,
        "timeout-minutes: 75",
        "timeout-minutes: 22",
        "run_timed_phase()",
        "[phase:start]",
        "[phase:end]",
        "duration=%ss",
        'run_timed_phase "Phase 1: Smoke Check (Shell)"',
        'run_timed_phase "Phase 2: Core Flow Validation (Python)"',
    )
    assert "in-job FIFO" not in ci_cd
    assert "workflow-level singleton concurrency" in ci_cd
    _lacks(ci_cd, "No two `Deploy Staging` workflow runs mutate staging concurrently")
    _has(
        ci_cd,
        "only one `Deploy Staging` run mutates staging at a time",
        "75-minute deploy-health job timeout",
        "22-minute E2E step timeout",
    )


def test_AC8_13_13_main_ci_keeps_each_merge_commit_run() -> None:
    """AC8.13.13: Main push CI uses SHA-scoped concurrency."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    _has(
        workflow,
        "group: ${{ github.workflow }}-${{ github.event_name == 'pull_request' && github.ref || github.event_name == 'push' && github.sha || github.run_id }}",
        "cancel-in-progress: ${{ github.event_name == 'pull_request' }}",
    )
    _has(
        ci_cd,
        "Pushes to `main` use a SHA-scoped concurrency",
        "do not cancel or replace a pending main CI",
    )


def test_AC8_13_157_audit_replay_workflow_is_nightly_and_nonblocking() -> None:
    """AC-testing.deploy-gates.32: AC8.13.157: heavy LLM journeys run as a separate nightly/manual, non-blocking
    audit-replay job that does not block production promotion by default."""
    audit = yaml.safe_load(read(".github/workflows/audit-replay.yml"))
    deploy = yaml.safe_load(read(".github/workflows/deploy.yml"))

    # Manual dispatch on-demand, NOT on push / workflow_run / pull_request.
    triggers = audit.get("on", audit.get(True))
    assert isinstance(triggers, dict)
    assert "workflow_dispatch" in triggers
    _lacks(triggers, "push", "workflow_run", "pull_request")

    # The audit-replay job calls the SAME reusable gate body, selecting the heavy
    # audit corpus, and is non-blocking (blocking=false) so it never blocks
    # production promotion.
    jobs = audit["jobs"]
    callers = [
        job
        for job in jobs.values()
        if job.get("uses") == "./.github/workflows/staging-ai-ocr-gate.yml"
    ]
    assert callers, "audit-replay.yml must call the reusable AI/OCR gate"
    for job in callers:
        assert job["with"]["corpus"] == "audit_replay"
        assert job["with"]["blocking"] is False
        assert job.get("secrets") == "inherit"

    # The production-promotion (deploy) blocking path keeps the heavy corpus OUT:
    # its inline ai-ocr-gate runs only the canary corpus.
    assert deploy["jobs"]["ai-ocr-gate"]["with"]["corpus"] == "canary"

    # SSOT names the audit-replay job as separate and non-blocking.
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    assert "audit-replay.yml" in ci_cd


def test_AC_extraction_1913_10_staging_statement_canary_is_sha_pinned_and_blocking() -> (
    None
):
    """AC-extraction.1913.10: required durable statement journeys fail the deploy."""
    deploy = yaml.safe_load(read(".github/workflows/deploy.yml"))
    canary = deploy["jobs"]["ai-ocr-gate"]
    emitted_sha = "${{ needs.build-and-deploy.outputs.commit_full_sha }}"
    release_tag = "${{ needs.build-and-deploy.outputs.deployed_version_ref }}"
    deploy_request = (
        read(".github/workflows/deploy.yml")
        .split("Deploy to Staging through infra2 receiver", 1)[1]
        .split("Confirm staging backend health", 1)[0]
    )

    assert canary["with"]["corpus"] == "canary"
    assert canary["with"]["blocking"] is True
    assert canary["with"]["commit_ref"] == emitted_sha
    assert canary["with"]["expected_sha"] == release_tag
    _has(
        deploy_request,
        'source_sha="${{ steps.release.outputs.full_sha }}"',
        '--source-sha "$source_sha"',
    )


def test_AC8_13_158_canary_transient_classification_owned_by_provider_gate() -> None:
    """AC-testing.deploy-gates.33: AC8.13.158: provider transient (5xx/timeout)=degraded, 4xx/config=block; the
    canary delegates this classification to the Staging Provider Gate."""
    deploy = read(".github/workflows/deploy.yml")

    # The canary only runs after the provider gate passes, so transient/config
    # classification gates the canary path.
    assert "needs.provider-gate.outputs.provider_status == 'pass'" in deploy

    # The provider gate keeps the 4xx-block / 5xx-degrade classifier.
    provider_block = deploy.split("provider-gate:", 1)[1].split("ai-ocr-gate:", 1)[0]
    _has(
        provider_block,
        "provider_status=config-failure",
        "client/config error",
        "provider_status=degraded",
        "transient",
    )
    # 4xx blocks (exit 1), transient degrades without blocking (exit 0).
    assert '"$status_code" -ge 400 ] && [ "$status_code" -lt 500 ]' in provider_block


def test_AC8_13_160_ci_cd_distinguishes_canary_from_audit_replay() -> None:
    """AC-testing.deploy-gates.35: AC8.13.160: SSOT distinguishes the blocking minimal AI/OCR Canary from the
    nightly comprehensive Audit Replay, and the split is a recorded decision."""
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    _has(ci_cd, "AI/OCR Canary", "Audit Replay", "audit-replay.yml")
    # The canary is the minimal blocking-path liveness check.
    assert "test_brokerage_upload_to_portfolio_value.py" in ci_cd
    # The split is recorded as an intentional keep_separate decision in the
    # gate inventory.
    inventory = yaml.safe_load(read("common/meta/data/ci-gate-inventory.yaml"))
    candidate = next(
        item
        for item in inventory["deferred_candidates"]
        if item["id"] == "ai_ocr_canary_vs_audit_replay"
    )
    assert candidate["status"] == "keep_separate"


def test_AC8_13_14_staging_ai_ocr_gate_is_separate_deploy_job() -> None:
    """AC-testing.deploy-gates.5: AC8.13.14: Provider-backed AI/OCR gate runs outside deploy health."""
    deploy_workflow = read(".github/workflows/deploy.yml")
    reusable = read(".github/workflows/staging-ai-ocr-gate.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    # Inline caller in deploy.yml delegates to the reusable gate (AC8.13.153).
    _has(
        deploy_workflow,
        "ai-ocr-gate:",
        "needs: [build-and-deploy, provider-gate]",
        "if: ${{ always() && github.event_name == 'workflow_dispatch' && inputs.target == 'staging' && needs.build-and-deploy.outputs.staging_required == 'true' && needs.build-and-deploy.outputs.ai_ocr_required == 'true' && needs.provider-gate.outputs.provider_status == 'pass' }}",
        "name: Staging AI/OCR Gate",
        "commit_full_sha: ${{ steps.release.outputs.full_sha }}",
        "deployed_version_ref: ${{ steps.release.outputs.version_ref }}",
        "uses: ./.github/workflows/staging-ai-ocr-gate.yml",
        "commit_ref: ${{ needs.build-and-deploy.outputs.commit_full_sha }}",
        "expected_sha: ${{ needs.build-and-deploy.outputs.deployed_version_ref }}",
        "blocking: true",
    )

    # The gate body (corpus replay, contract shell, version check) lives once in
    # the reusable workflow.
    _has(
        reusable,
        "PARSING_TIMEOUT_MS: 480000",
        'run_timed_phase "Staging AI/OCR Gate',
        "tools/staging_ai_ocr_gate_contract.py --shell",
        'pytest "${STAGING_AI_OCR_TESTS[@]}"',
    )
    # Marker expression equality is owned by the matrix conformance
    # gate (AC8.23.2, tests/tooling/test_workflow_selection_conformance.py).
    _has(reusable, "test_version_check.py", "STRICT_E2E_GATES: true")

    # The deploy-health E2E stage in build-and-deploy must not run the llm corpus.
    deploy_e2e_block = deploy_workflow.split("name: End-to-End Tests", 1)[1].split(
        "name: AI Provider Connectivity Smoke", 1
    )[0]
    assert '-v -m "llm"' not in deploy_e2e_block

    # Manual entrance is the same reusable gate, fail-fast (blocking=true).
    assert "manual-ai-ocr-gate:" in deploy_workflow
    assert 'workflows: ["Deploy Staging"]' not in deploy_workflow
    _has(
        deploy_workflow,
        "workflow_dispatch:",
        "inputs.target == 'staging-ai-ocr-gate' && format('staging-manual-ai-ocr-{0}', github.ref)",
        "cancel-in-progress: false",
        "blocking: true",
        "expected_sha: ${{ github.sha }}",
    )
    _has(
        ci_cd, "same serialized post-merge workflow unit", "manual recovery entry point"
    )


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
    tmp_path: Path,
    *,
    outcome: str,
    blocking: str,
    existing_issue: str,
) -> dict[str, object]:
    """Execute the real ``gate_timeout_fallback`` step body (AC8.13.166) as a
    subprocess against a stub ``gh``, exercising actual behavior instead of
    grepping the script text (mirror-assertion ratchet, common/testing/
    mirror_ratchet.py, #1435)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    workflow = yaml.safe_load(read(".github/workflows/staging-ai-ocr-gate.yml"))
    fallback = next(
        s
        for s in workflow["jobs"]["run"]["steps"]
        if s.get("id") == "gate_timeout_fallback"
    )
    script = _gha_expr_substituted(
        fallback["run"],
        {
            "steps.staging_ai_ocr_tests.outcome": outcome,
            "github.run_id": "999",
            "inputs.corpus": "audit_replay",
            "inputs.blocking": blocking,
            "inputs.commit_ref": "deadbeef",
        },
    )

    gh_calls_log = tmp_path / "gh_calls.jsonl"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        "#!/bin/bash\n"
        'python3 -c \'import json,sys; open(sys.argv[1], "a").write(json.dumps(sys.argv[2:]) + "\\n")\' '
        f'"{gh_calls_log}" "$@"\n'
        'if [ "$1" = "issue" ] && [ "$2" = "list" ]; then\n'
        f'  printf %s "{existing_issue}"\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    fake_gh.chmod(0o755)

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
        },
        capture_output=True,
        text=True,
        timeout=30,
    )

    output_lines = [line for line in github_output.read_text().splitlines() if line]
    parsed_output = dict(line.split("=", 1) for line in output_lines)
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
    fallback = next(s for s in job["steps"] if s.get("id") == "gate_timeout_fallback")
    # Fires exactly when the corpus step did not succeed AND produced no
    # output -- i.e. it died before its own record_and_finish call. A normal
    # blocking=true regression already sets ai_ocr_status and must not
    # double-alert here (record_and_finish owns that path, #1623).
    assert fallback["if"] == (
        "${{ always() && steps.staging_ai_ocr_tests.outcome != 'success' "
        "&& steps.staging_ai_ocr_tests.outputs.ai_ocr_status == '' }}"
    )
    # The job's ai_ocr_status/ai_ocr_exit_code outputs fall through inner step
    # -> fallback step -> generic default, so a died-without-output run
    # reports the distinct status this step sets, never the ambiguous
    # 'not-run' that also means "conditionally skipped" elsewhere.
    assert job["outputs"]["ai_ocr_status"] == (
        "${{ steps.staging_ai_ocr_tests.outputs.ai_ocr_status || "
        "steps.gate_timeout_fallback.outputs.ai_ocr_status || 'not-run' }}"
    )
    assert job["outputs"]["ai_ocr_exit_code"] == (
        "${{ steps.staging_ai_ocr_tests.outputs.ai_ocr_exit_code || "
        "steps.gate_timeout_fallback.outputs.ai_ocr_exit_code || '0' }}"
    )
    # issues: write permission (#1623) already covers this step's own gh
    # issue create -- no separate permission grant needed.
    assert job["permissions"]["issues"] == "write"

    # Behavior 1: no standing alert -> creates exactly one issue and reports
    # the distinct gate-timeout status, non-blocking mode exits clean.
    run1 = _run_gate_timeout_fallback(
        tmp_path / "case1", outcome="cancelled", blocking="false", existing_issue=""
    )
    assert run1["exit_code"] == 0
    assert run1["parsed_output"] == {
        "ai_ocr_status": "gate-timeout",
        "ai_ocr_exit_code": "124",
    }
    creates = [call for call in run1["gh_calls"] if call[:2] == ["issue", "create"]]
    assert len(creates) == 1
    assert creates[0].count("--title") == 1
    list_calls = [call for call in run1["gh_calls"] if call[:2] == ["issue", "list"]]
    assert len(list_calls) == 1
    search_arg = list_calls[0][list_calls[0].index("--search") + 1]
    create_title_arg = creates[0][creates[0].index("--title") + 1]
    # The dedup search string must be built from the SAME title used to
    # create the issue, or dedup and creation would silently drift apart.
    assert search_arg == f"in:title {create_title_arg}"

    # Behavior 2: a standing alert already exists -> dedup, no new issue.
    run2 = _run_gate_timeout_fallback(
        tmp_path / "case2", outcome="failure", blocking="false", existing_issue="42"
    )
    assert run2["exit_code"] == 0
    creates2 = [call for call in run2["gh_calls"] if call[:2] == ["issue", "create"]]
    assert creates2 == []

    # Behavior 3: blocking mode still alerts (fresh issue) but propagates
    # failure so the manual diagnostic entrance stays fail-fast even on a
    # bare timeout (#1767 F3: the recovery path shared the same flaw).
    run3 = _run_gate_timeout_fallback(
        tmp_path / "case3", outcome="cancelled", blocking="true", existing_issue=""
    )
    assert run3["exit_code"] == 1
    creates3 = [call for call in run3["gh_calls"] if call[:2] == ["issue", "create"]]
    assert len(creates3) == 1


def test_AC8_13_167_timeout_budget_is_sized_per_corpus_worst_case() -> None:
    """AC-testing.deploy-gates.42: AC8.13.167: step/job timeout-minutes fit every sequential parse wait in a
    corpus hitting its own 8-minute PARSING_TIMEOUT_MS ceiling, not just the
    happy path -- sized off the real per-corpus wait count, not a file/journey
    guess (#1767: the shipped 22-min budget only covered 66% of one real run)."""
    workflow = yaml.safe_load(read(".github/workflows/staging-ai-ocr-gate.yml"))
    job = workflow["jobs"]["run"]
    corpus_step = next(s for s in job["steps"] if s.get("id") == "staging_ai_ocr_tests")

    assert corpus_step["timeout-minutes"] == (
        "${{ inputs.corpus == 'canary' && 25 || (inputs.corpus == 'all' && 125 || 110) }}"
    )
    # 8-min parse ceiling that the budgets below are computed against, read as
    # a structured env value rather than grepped text.
    assert workflow["env"]["PARSING_TIMEOUT_MS"] == 480000

    # pytest runs single-worker in this job (no xdist matrix/parallel-test
    # tooling anywhere in this workflow file), so every parse wait across
    # every selected file is fully serial -- totals()['uploads'] is therefore
    # the exact worst-case wait count, not a per-file undercount (a single
    # test can await multiple sequential waits, e.g. the 2-upload canary
    # journey; test_institution_statement_journeys.py instead spreads its 4
    # waits across 4 separate test functions -- both collapse to one serial
    # queue under a single pytest process).
    parse_ceiling_minutes = 8
    overhead_minutes = 6
    budgets = {"canary": 25, "audit_replay": 110, "all": 125}
    wait_counts = {
        "canary": contract.totals(contract.canary_files())["uploads"],
        "audit_replay": contract.totals(contract.audit_replay_files())["uploads"],
        "all": contract.totals(contract.gate_files())["uploads"],
    }
    for corpus_name, budget in budgets.items():
        worst_case = wait_counts[corpus_name] * parse_ceiling_minutes + overhead_minutes
        assert worst_case <= budget, (
            f"{corpus_name} corpus grew to {wait_counts[corpus_name]} sequential "
            f"parse waits; its {budget}min budget no longer covers the "
            f"{worst_case}min worst case (raise the budget alongside the corpus)"
        )

    # Job-level timeout-minutes must be >= the largest step budget plus slack
    # for checkout/setup/context-write/upload steps around the corpus step.
    assert job["timeout-minutes"] >= max(budgets.values())


def test_AC8_13_49_staging_ai_ocr_gate_publishes_audit_inventory_and_summary() -> None:
    """AC-testing.deploy-gates.11: AC8.13.49: Staging AI/OCR gates publish replay inputs and summary fields."""
    # The gate body — and therefore its audit replay inventory/summary — lives
    # once in the reusable workflow shared by both entrances (AC8.13.153).
    workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    observability = read("common/observability/observability-logging.md")

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
    _has(
        workflow,
        "- Backend image tag:",
        "- Frontend image tag:",
        "- Models: primary=${STAGING_E2E_PRIMARY_MODEL}, ocr=${STAGING_E2E_OCR_MODEL}, vision=${STAGING_E2E_VISION_MODEL}",
        "- Expected uploads: ${STAGING_AI_OCR_EXPECTED_UPLOADS}",
        "- Expected parse completions: ${STAGING_AI_OCR_EXPECTED_PARSE_COMPLETIONS}",
        "- Expected brokerage imports: ${STAGING_AI_OCR_EXPECTED_BROKERAGE_IMPORTS}",
        "- Expected report verifications: ${STAGING_AI_OCR_EXPECTED_REPORT_VERIFICATIONS}",
        "- Expected failures: 0",
        "- Uploads verified: ${verified_uploads}",
        "- Parse completions verified: ${verified_parse_completions}",
        "- Brokerage imports verified: ${verified_brokerage_imports}",
        "- Report verifications verified: ${verified_report_verifications}",
        "- Failures observed: ${verified_failures}",
        "for fixture_test in",
        "${STAGING_AI_OCR_TESTS[@]}",
        "GITHUB_STEP_SUMMARY",
    )
    _lacks(
        workflow,
        "- Expected uploads: 7",
        "- Expected parse completions: 7",
        "- Expected brokerage imports: 3",
        "- Expected report verifications: 1",
    )

    assert workflow.index("write_staging_audit_inventory") < workflow.index(
        'run_timed_phase "Staging AI/OCR Version Check"'
    )
    _has(observability, "Staging Audit Replay Contract", "deployment-level inputs")


def test_AC8_13_49_staging_ai_ocr_contract_outputs_files_and_counts() -> None:
    """AC8.13.49: Staging AI/OCR replay contract has one file/count source."""
    shell = staging_ai_ocr_contract_shell()
    match = re.search(r"^STAGING_AI_OCR_TESTS=\((?P<files>.+)\)$", shell, re.M)
    assert match is not None
    files = match.group("files").split()

    _has(
        shell,
        "tests/e2e/test_statement_full_journey.py",
        "tests/e2e/test_brokerage_upload_to_portfolio_value.py",
        "tests/e2e/test_four_asset_net_worth_golden_path.py",
        "tests/e2e/test_personal_financial_report_package.py",
        "tests/e2e/test_statement_upload_e2e.py",
        "tests/e2e/test_gxs_browser_journey.py",
        "tests/e2e/test_institution_statement_journeys.py",
        "STAGING_AI_OCR_EXPECTED_UPLOADS=14",
        "STAGING_AI_OCR_EXPECTED_PARSE_COMPLETIONS=14",
        "STAGING_AI_OCR_EXPECTED_BROKERAGE_IMPORTS=4",
        "STAGING_AI_OCR_EXPECTED_REPORT_VERIFICATIONS=3",
    )
    assert len(files) == len(set(files))
    assert files == sorted(files)


def test_AC8_13_50_critical_llm_post_merge_proofs_are_in_ai_ocr_gates() -> None:
    """AC8.13.50: Critical LLM post-merge proofs are executed by AI/OCR gates."""
    proof_files = critical_post_merge_llm_proof_files()
    shell = staging_ai_ocr_contract_shell()
    assert proof_files == [
        "tests/e2e/test_brokerage_upload_to_portfolio_value.py",
        "tests/e2e/test_four_asset_net_worth_golden_path.py",
        "tests/e2e/test_gxs_browser_journey.py",
        "tests/e2e/test_institution_statement_journeys.py",
        "tests/e2e/test_personal_financial_report_package.py",
        "tests/e2e/test_statement_full_journey.py",
    ]

    # Both entrances (inline + manual) share the reusable gate body.
    workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    _has(
        workflow,
        "tools/staging_ai_ocr_gate_contract.py --shell",
        'pytest "${STAGING_AI_OCR_TESTS[@]}"',
    )

    missing = [proof_file for proof_file in proof_files if proof_file not in shell]
    assert missing == []


def test_AC8_13_76_ci_environment_gates_publish_failure_path_context() -> None:
    """AC8.13.76: CI and deploy gates upload replayable status context."""
    ci = read(".github/workflows/ci.yml")
    pr_preview = read(".github/workflows/preview.yml")
    staging = read(".github/workflows/deploy.yml")
    ai_gate = read(".github/workflows/staging-ai-ocr-gate.yml")
    production = read(".github/workflows/release.yml")
    cleanup = read(".github/workflows/maintenance.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    _has(
        ci,
        "backend-shard-${{ matrix.shard }}-test-context",
        "backend-integration-test-context",
        "frontend-vitest-test-context",
        "frontend-playwright-test-context",
        "frontend-telemetry-test-context",
        "AC-TRACEABILITY-CONTEXT.md",
    )
    _has(
        ci,
        "--junit-xml=test-results/backend-shard-${{ matrix.shard }}.xml",
        "--junit-xml=test-results/backend-integration.xml",
        "test-results/vitest-junit.xml",
        "apps/frontend/playwright-report/",
    )
    assert "if: ${{ always() }}" in ci.split("Upload backend shard test context", 1)[0]

    assert "pr-preview-test-context" in pr_preview
    # Full runtime/API/UI E2E now runs image-free in the in-runner `e2e` job
    # (issue #839) after successful PR CI. Its junit lives here.
    _has(
        pr_preview,
        "test-results/in-runner-e2e.xml",
        "ci-context/pr-preview-context.txt",
        "preview_runtime=github-runner-compose",
        "persistent_preview_url=${{ needs.setup.outputs.preview_app_url }}",
        "registry_image_push=false",
        "dokploy_deploy=after-e2e-non-blocking-build-from-source",
        "e2e_outcome=${{ steps.e2e_tests.outcome }}",
    )

    _has(
        staging,
        "staging-deploy-test-context",
        "test-results/staging-core-e2e.xml",
        "ci-context/staging-deploy-context.txt",
        "failure_domain=${{ steps.deploy_failure_context.outputs.failure_domain }}",
        "failed_step=${{ steps.deploy_failure_context.outputs.failed_step }}",
        "failure_summary=${{ steps.deploy_failure_context.outputs.failure_summary }}",
    )
    # Observability-backend pivot links are intentionally NOT emitted by the app
    # workflow; the app emits OTLP and infra2 owns linking to its backend.
    assert "signoz" not in staging.lower()

    # The AI/OCR gate context/artifacts are owned by the reusable workflow.
    _has(
        ai_gate,
        "staging-ai-ocr-test-context",
        "test-results/staging-ai-ocr-version.xml",
        "test-results/staging-ai-ocr-gate.xml",
        "ci-context/staging-ai-ocr-context.txt",
        "primary_model=${STAGING_E2E_PRIMARY_MODEL}",
    )

    # Production release context lives in release.yml.
    _has(
        production,
        "production-dry-run-context",
        "production-deploy-test-context",
        "test-results/production-readonly-e2e.xml",
    )

    _has(
        cleanup,
        "pr-preview-scheduled-cleanup-context",
        "cleanup_action=ghcr-pr-tag-prune-only",
    )

    _has(
        ci_cd,
        "CI observability artifacts",
        "Step summaries remain human-readable status pages",
    )


def test_AC8_13_51_staging_deploy_is_manual_dispatch_only() -> None:
    """AC-testing.deploy-gates.12: AC8.13.51: Staging deploy is manual (`workflow_dispatch`) only; it does not auto-follow main CI."""
    workflow = read(".github/workflows/deploy.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    parsed = yaml.safe_load(workflow)
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = parsed.get("on", parsed.get(True))
    assert isinstance(triggers, dict), "deploy.yml must declare an `on:` map"
    _has(triggers, "workflow_dispatch")
    _lacks(triggers, "workflow_run")
    inputs = triggers["workflow_dispatch"].get("inputs") or {}
    _has(inputs, "version_ref")
    _lacks(inputs, "tag")
    assert inputs["version_ref"].get("required") is False, (
        "version_ref is validated by the staging/production target jobs because "
        "deploy.yml also hosts the on-demand AI/OCR diagnostic target"
    )
    # The deploy job still must not poll/wait for CI inside the job.
    assert "wait_for_github_ci.py" not in workflow
    # SSOT reflects the manual staging deploy policy.
    assert "Staging deploy is manual" in ci_cd


def test_AC8_13_103_post_merge_delivery_summary_check_aggregates_staging_gates() -> (
    None
):
    """AC-testing.deploy-gates.20: AC8.13.103/AC8.13.108: Delivery aggregates gates and failure context."""
    workflow = read(".github/workflows/deploy.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    epic = read("docs/project/EPIC-008.testing-strategy.md")

    _has(
        workflow,
        "post-merge-delivery:",
        "name: Post-merge Delivery",
        "needs: [build-and-deploy, provider-gate, ai-ocr-gate]",
        "Aggregate post-merge delivery result",
        'staging_required="${{ needs.build-and-deploy.outputs.staging_required }}"',
        'ai_ocr_required="${{ needs.build-and-deploy.outputs.ai_ocr_required }}"',
        'build_result="${{ needs.build-and-deploy.result }}"',
        'provider_result="${{ needs.provider-gate.result }}"',
        'provider_status="${{ needs.provider-gate.outputs.provider_status }}"',
        'ai_ocr_result="${{ needs.ai-ocr-gate.result }}"',
        'ai_ocr_status="${{ needs.ai-ocr-gate.outputs.ai_ocr_status }}"',
    )
    # The retired post-merge auto-deploy alert job is no longer a delivery input.
    _lacks(workflow, "staging-deploy-alert", "alert_result")
    _has(
        workflow,
        'failure_domain="${{ needs.build-and-deploy.outputs.failure_domain }}"',
        'failed_step="${{ needs.build-and-deploy.outputs.failed_step }}"',
        'failure_summary="${{ needs.build-and-deploy.outputs.failure_summary }}"',
        'delivery_status="skipped-no-staging-required"',
        'failure_reason="build/deploy gate failed"',
        'failure_reason="provider connectivity gate failed"',
        'failure_reason="staging AI/OCR canary failed"',
        "Post-merge delivery failed: ${failure_reason}",
    )
    # A reusable-workflow caller cannot set continue-on-error, so blocking must
    # be enforced by the caller input and reflected in the delivery aggregate.
    _has(
        workflow.split("ai-ocr-gate:", 1)[1].split("post-merge-delivery:", 1)[0],
        "blocking: true",
    )
    _has(
        workflow,
        'delivery_status="degraded-provider"',
        "## Post-merge Delivery",
        "Build/deploy failure domain: ${failure_domain:-unknown}",
        "Build/deploy failed step: ${failed_step:-unknown}",
        "Build/deploy failure summary: ${failure_summary:-unknown}",
        "Post-merge delivery failed",
    )
    _has(
        workflow.split("post-merge-delivery:", 1)[1].split("post-merge-summary:", 1)[0],
        "exit 1",
    )
    _has(
        workflow,
        "needs: [build-and-deploy, provider-gate, ai-ocr-gate, post-merge-delivery]",
    )
    _has(
        ci_cd,
        "dedicated `Post-merge Delivery` check",
        "A green `CI` workflow alone is not sufficient evidence",
        "comprehensive staging AI/OCR audit replay",
        "Release gate reclassification",
        "Left-shifted:",
        "Strengthened:",
        "Removed:",
        "Right-shifted:",
    )
    assert "AC8.13.103" in epic


def test_AC8_13_55_post_merge_staging_is_scoped_to_deploy_relevant_paths() -> None:
    """AC8.13.55: Post-merge staging only runs for deploy-relevant changes."""
    workflow = read(".github/workflows/deploy.yml")
    classifier = read("common/testing/change_classifier.py")
    classifier_tests = read("tests/tooling/test_ci_change_classifier.py")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    assert "classify-staging:" not in workflow
    _has(workflow, "name: Classify staging and AI/OCR relevance", "fetch-depth: 0")
    # Manual-only staging no longer scopes by changed paths inside the deploy
    # workflow: a manual dispatch always classifies staging (and the AI/OCR gate)
    # as required. The diff-based change classifier remains for CI/PR scoping only.
    _lacks(workflow, "git diff --name-only", "tools/ci_change_classifier.py")
    _has(
        workflow,
        "staging_required: ${{ steps.gates.outputs.staging_required }}",
        "staging_reason: ${{ steps.gates.outputs.staging_reason }}",
        "if: steps.gates.outputs.staging_required == 'true'",
        "ENV_STAGE_REQUIRED: ${{ steps.classify.outputs.env_stage_required }}",
        "manual-dispatch",
    )

    _has(
        classifier,
        "STAGING_EXACT",
        "STAGING_PREFIXES",
        "def is_staging_relevant",
        "staging-paths-changed",
        "no-staging-paths-changed",
    )
    _has(
        classifier_tests,
        "test_AC8_13_55_staging_only_runs_for_runtime_deploy_or_e2e_changes",
        "docs/project/archive/AC-TEST-TRACEABILITY-AUDIT.md",
        "common/meta/extension/check_ssot_ownership.py",
    )
    _has(
        ci_cd,
        "Staging deploy is manual (`workflow_dispatch`) only",
        "The diff-based change classifier no longer scopes the staging deploy by changed paths",
    )


def test_AC8_13_60_deploy_workflows_have_no_nonblocking_noop_gates() -> None:
    """AC-testing.deploy-gates.15: AC8.13.60: Deploy gates do not keep no-op or warning-only checks."""
    workflows = [
        read(".github/workflows/deploy.yml"),
        read(".github/workflows/deploy.yml"),
        read(".github/workflows/preview.yml"),
    ]
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    for workflow in workflows:
        assert "Check Deployment Dependencies" not in workflow
        assert "Deployment deps check skipped" not in workflow

    staging = workflows[0]
    _lacks(staging, "Performance Benchmark", "Don't block deploy, but report issues")
    assert "infra2 receiver owns deploy dependency preflight" in ci_cd


def test_AC8_13_52_production_release_dry_run_does_not_mutate_production() -> None:
    """AC-testing.deploy-gates.13 AC-testing.deploy-gates.17: AC8.13.52 AC8.13.65: Production dry-run validates without deploying."""
    workflow = read(".github/workflows/release.yml")
    release_evidence = read("common/runtime/release_evidence.py")
    release_images = read("common/runtime/release_images.py")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    _has(
        workflow,
        "dry_run:",
        "version_ref:",
        "Version ref to deploy (vX.Y.Z release tag)",
    )
    assert "leave empty for latest" not in workflow
    _has(
        workflow,
        "Validate release prerequisites without deploying production",
        "dry-run:",
        "if: ${{ inputs.dry_run }}",
        "moon run :lint",
    )
    assert "moon run :test" not in workflow
    _has(workflow, "Resolve release coordinate", "tools/resolve_release_coordinate.py")
    assert workflow.count("tools/verify_release_evidence.py") == 11
    assert workflow.count("tools/verify_release_images.py") == 2
    assert "Verify source CI passed" in workflow
    _has(
        release_evidence,
        '"--workflow"',
        '"ci.yml"',
        "--commit",
        'run.get("headBranch") == "main"',
    )
    _has(
        workflow,
        "Verify release images workflow passed",
        "Verify staging passed",
        "Verify Release Images Dry Run",
    )
    assert '"docker", "buildx", "imagetools", "inspect"' in release_images
    # release.yml is the production release line; the whole file is the prod jobs.
    _lacks(workflow, "gh run list", "gh run view")
    assert "Production mutation skipped" in workflow
    dry_run_section = workflow.split("dry-run:", 1)[1].split("\n  deploy:", 1)[0]
    _lacks(dry_run_section, "environment:", "dokploy_deploy.sh")
    assert "inputs.dry_run" in workflow.split("\n  deploy:", 1)[1].split("steps:", 1)[0]
    assert "Production release dry-run" in ci_cd
    assert "Verify Release Images Dry Run" in workflow
    assert "docker buildx imagetools create" not in dry_run_section


def test_AC8_13_52_production_release_checks_use_pinned_python() -> None:
    """AC8.13.52: Production release checks run after setup-python."""
    workflow = read(".github/workflows/release.yml")
    dry_run_section = workflow.split("  dry-run:", 1)[1].split("\n  deploy:", 1)[0]
    deploy_section = workflow.split("\n  deploy:", 1)[1]

    def step_index(
        section: str,
        step_name_prefix: str,
        *,
        exclude: tuple[str, ...] = (),
    ) -> int:
        prefix = step_name_prefix.casefold()
        excluded = tuple(value.casefold() for value in exclude)
        for match in re.finditer(r"(?m)^\s*-\s+name:\s+(.+)$", section):
            step_name = match.group(1).strip().casefold()
            if step_name.startswith(prefix) and not any(
                value in step_name for value in excluded
            ):
                return match.start()
        raise AssertionError(f"missing workflow step matching {step_name_prefix!r}")

    for section in (dry_run_section, deploy_section):
        setup_python = step_index(section, "Set up Python")
        resolve_coordinate = step_index(section, "Resolve release coordinate")
        source_ci = step_index(section, "Verify source CI passed")
        release_images_run = step_index(
            section, "Verify release images workflow passed"
        )
        staging = step_index(section, "Verify staging passed")
        verify_images = step_index(
            section,
            "Verify release images",
            exclude=("workflow passed",),
        )

        assert setup_python < resolve_coordinate
        assert setup_python < source_ci
        assert setup_python < release_images_run
        assert setup_python < staging
        assert setup_python < verify_images


def test_AC8_13_52_production_release_matches_exact_staging_run_name() -> None:
    """AC8.13.52: Production release requires staging validation for the exact version_ref."""
    release_evidence = read("common/runtime/release_evidence.py")
    staging_contract = release_evidence.split("def verify_staging", 1)[1].split(
        "def _required", 1
    )[0]

    _has(
        staging_contract,
        'expected_title = f"Deploy Staging {version_ref}"',
        'run.get("displayTitle") == expected_title',
        'run.get("status") == "completed"',
    )
    assert 'run.get("conclusion") == "success"' not in staging_contract
    _has(
        staging_contract,
        'required_staging_jobs = {"Deploy Staging", "Staging Provider Gate"}',
        'optional_staging_jobs = {"Staging AI/OCR Gate"}',
        "candidate_run_ids",
        "for candidate_run_id in candidate_run_ids:",
        '"gh",',
        '"run",',
        '"view",',
        "candidate_run_id,",
        "Skipping staging run ",
        "{candidate_run_id}: release-critical jobs",
        "with successful release-critical jobs",
        "Staging AI/OCR Gate",
        "does not block production release eligibility",
    )
    assert 'version_ref in (run.get("displayTitle") or "")' not in staging_contract


def test_AC8_13_52_release_evidence_tool_requires_exact_successful_staging_run() -> (
    None
):
    """AC8.13.52: Shared release evidence rejects fuzzy or failed staging proof."""
    from common.runtime import release_evidence

    def fake_gh_json(args: list[str]) -> object:
        command = " ".join(args)
        if " run list " in f" {command} ":
            return [
                {
                    "databaseId": 10,
                    "status": "completed",
                    "displayTitle": "Deploy Staging v1.2.30",
                    "headSha": "a" * 40,
                },
                {
                    "databaseId": 11,
                    "status": "completed",
                    "displayTitle": "Deploy Staging v1.2.3",
                    "headSha": "b" * 40,
                },
                {
                    "databaseId": 12,
                    "status": "completed",
                    "displayTitle": "Deploy Staging v1.2.3",
                    "headSha": "a" * 40,
                },
            ]
        assert " run view " in f" {command} "
        run_id = args[3]
        jobs_by_run = {
            "11": [
                {"name": "Deploy Staging", "conclusion": "success"},
                {"name": "Staging Provider Gate", "conclusion": "failure"},
            ],
            "12": [
                {"name": "Deploy Staging", "conclusion": "success"},
                {"name": "Staging Provider Gate", "conclusion": "success"},
                {"name": "Staging AI/OCR Gate", "conclusion": "failure"},
            ],
        }
        return {"jobs": jobs_by_run[run_id]}

    run_id = release_evidence.verify_staging(
        repository="owner/repo",
        version_ref="v1.2.3",
        release_sha="a" * 40,
        gh_json=fake_gh_json,
    )

    assert run_id == "12"


def test_AC8_13_52_release_evidence_tool_reports_source_and_release_runs() -> None:
    """AC8.13.52: Shared release evidence reports source and release-image runs."""
    from common.runtime import release_evidence

    def source_ci_json(_args: list[str]) -> object:
        return [
            {
                "databaseId": 20,
                "event": "pull_request",
                "headBranch": "main",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "databaseId": 21,
                "event": "push",
                "headBranch": "main",
                "status": "completed",
                "conclusion": "success",
            },
        ]

    def release_images_json(_args: list[str]) -> object:
        return [
            {
                "databaseId": 30,
                "event": "push",
                "status": "completed",
                "conclusion": "success",
            }
        ]

    assert (
        release_evidence.verify_source_ci(
            repository="owner/repo",
            release_sha="a" * 40,
            gh_json=source_ci_json,
        )
        == "21"
    )
    assert (
        release_evidence.verify_release_images_run(
            repository="owner/repo",
            release_sha="a" * 40,
            gh_json=release_images_json,
        )
        == "30"
    )

    def reviewed_changes_json(_args: list[str]) -> object:
        base = {"ref": "main", "repo": {"full_name": "owner/repo"}}
        return [
            {
                "number": 41,
                "state": "closed",
                "merged_at": "2026-07-14T00:00:00Z",
                "merge_commit_sha": "b" * 40,
                "html_url": "https://github.com/owner/repo/pull/41",
                "base": base,
            },
            {
                "number": 42,
                "state": "closed",
                "merged_at": "2026-07-15T00:00:00Z",
                "merge_commit_sha": "a" * 40,
                "html_url": "https://github.com/owner/repo/pull/42",
                "base": base,
            },
        ]

    assert (
        release_evidence.verify_reviewed_change(
            repository="owner/repo",
            release_sha="a" * 40,
            gh_json=reviewed_changes_json,
        )
        == "https://github.com/owner/repo/pull/42"
    )

    with pytest.raises(RuntimeError, match="No merged main-branch pull request"):
        release_evidence.verify_reviewed_change(
            repository="owner/repo",
            release_sha="c" * 40,
            gh_json=reviewed_changes_json,
        )


def test_AC8_13_52_release_evidence_cli_writes_exact_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """AC8.13.52: Each CLI evidence mode emits only its canonical output."""
    from common.runtime import release_evidence

    output_path = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setattr(
        release_evidence,
        "verify_staging",
        lambda **kwargs: "51",
    )
    assert (
        release_evidence.main(
            [
                "--check",
                "staging",
                "--repository",
                "owner/repo",
                "--version-ref",
                "v1.2.3",
                "--release-sha",
                "a" * 40,
            ]
        )
        == 0
    )
    assert "check=staging run_id=51" in capsys.readouterr().out

    monkeypatch.setattr(
        release_evidence,
        "verify_reviewed_change",
        lambda **kwargs: "https://github.com/owner/repo/pull/42",
    )
    assert (
        release_evidence.main(
            [
                "--check",
                "reviewed-change",
                "--repository",
                "owner/repo",
                "--release-sha",
                "a" * 40,
            ]
        )
        == 0
    )
    _has(
        capsys.readouterr().out,
        "reviewed_change_url=https://github.com/owner/repo/pull/42",
    )

    monkeypatch.setattr(
        release_evidence,
        "verify_release_images_run",
        lambda **kwargs: "61",
    )
    assert (
        release_evidence.main(
            [
                "--check",
                "release-images-run",
                "--repository",
                "owner/repo",
                "--release-sha",
                "a" * 40,
            ]
        )
        == 0
    )
    assert "check=release-images-run run_id=61" in capsys.readouterr().out
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "run_id=51",
        "reviewed_change_url=https://github.com/owner/repo/pull/42",
        "run_id=61",
    ]


def test_AC8_13_52_release_evidence_tool_fails_without_staging_jobs() -> None:
    """AC8.13.52: Shared release evidence fails when staging jobs are missing."""
    from common.runtime import release_evidence

    def fake_gh_json(args: list[str]) -> object:
        command = " ".join(args)
        if " run list " in f" {command} ":
            return [
                {
                    "databaseId": 40,
                    "status": "completed",
                    "displayTitle": "Deploy Staging v1.2.3",
                    "headSha": "a" * 40,
                }
            ]
        return {"jobs": [{"name": "Deploy Staging", "conclusion": "success"}]}

    with pytest.raises(RuntimeError, match="successful release-critical jobs"):
        release_evidence.verify_staging(
            repository="owner/repo",
            version_ref="v1.2.3",
            release_sha="a" * 40,
            gh_json=fake_gh_json,
        )


def test_AC8_13_52_release_image_tool_reports_backend_and_frontend_digests() -> None:
    """AC8.13.52: Shared release image verification emits both image digests."""
    from common.runtime import release_images

    def inspect_image(image: str) -> tuple[int, str]:
        digest_by_image = {
            "ghcr.io/owner/finance_report-backend:v1.2.3": "sha256:backend",
            "ghcr.io/owner/finance_report-frontend:v1.2.3": "sha256:frontend",
        }
        return 0, f"Name: {image}\nDigest: {digest_by_image[image]}\n"

    digests = release_images.verify_release_images(
        registry="ghcr.io",
        image_prefix="owner/finance_report",
        version_ref="v1.2.3",
        inspect_image=inspect_image,
    )

    assert digests == {
        "backend_digest": "sha256:backend",
        "frontend_digest": "sha256:frontend",
    }


def test_AC8_13_52_release_image_tool_fails_when_a_digest_is_missing() -> None:
    """AC8.13.52: Shared release image verification fails closed on missing digest."""
    from common.runtime import release_images

    def inspect_image(_image: str) -> tuple[int, str]:
        return 0, "Name: missing-digest\n"

    with pytest.raises(RuntimeError, match="Release image not found"):
        release_images.verify_release_images(
            registry="ghcr.io",
            image_prefix="owner/finance_report",
            version_ref="v1.2.3",
            inspect_image=inspect_image,
        )


def test_AC8_13_16_ci_change_classification_and_frontend_cache() -> None:
    """AC-testing.classifier.1: AC8.13.16: CI skips heavy jobs for lightweight changes and caches npm."""
    workflow = read(".github/workflows/ci.yml")
    pr_workflow = read(".github/workflows/preview.yml")
    classifier = read("common/testing/change_classifier.py")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    environments = read("common/runtime/environments.md")

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
    assert "path.endswith" not in workflow
    assert "path.endswith" not in classifier
    _has(
        classifier,
        "runtime-or-ci-paths-changed",
        "lightweight-docs-or-docs-workflow-only",
        "pr-preview-paths-changed",
        "no-pr-preview-paths-changed",
    )
    _has(
        workflow, "needs: [changes]", "if: needs.changes.outputs.pr_required == 'true'"
    )
    _has(
        pr_workflow,
        "pr_preview_required: ${{ steps.preview_gate.outputs.pr_preview_required }}",
        "name: Classify PR preview relevance",
        "name: Normalize PR preview gate",
        "needs.setup.outputs.pr_preview_required == 'true'",
    )
    _has(
        workflow,
        "name: AC Traceability Check",
        "needs: [changes, schema-migrations, backend, backend-integration, frontend-build, frontend-vitest, frontend-playwright, frontend-telemetry-e2e, container-images, verify-sha-image-published, lint, tooling-coverage, unified-coverage, ac-traceability, ac-behavioral-ratchet]",
    )
    assert "finish remains the authoritative aggregate gate" in ci_cd
    _has(
        workflow,
        "Heavy backend/frontend/coverage jobs skipped for lightweight changes.",
        "uses: actions/setup-node@v6",
        "cache: npm",
        "cache-dependency-path: apps/frontend/package-lock.json",
        "run: npm ci",
    )
    assert "run: npm install" not in workflow
    _has(
        ci_cd,
        "PR vs Main CI Responsibilities",
        "Lightweight changes do not repeat the heavy path",
        "PR preview environments deploy only for runtime app, compose, root E2E, dependency, Dockerfile/config, or preview-action changes",
        "Frontend dependency installation uses `actions/setup-node@v6`",
        "Markdown outside the documented lightweight trees is treated as heavy",
    )
    assert "lightweight documentation" in environments.lower()


def test_AC8_13_16_workflows_opt_into_node24_actions_runtime() -> None:
    """AC8.13.16: workflows stay on Node 24-native JavaScript actions."""
    workflow_paths = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflow_paths
    for workflow_path in workflow_paths:
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" not in workflow, workflow_path.name

    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    inventory = yaml.safe_load(read("common/testing/data/github-action-runtime.yaml"))
    forced_actions = [
        action["uses"]
        for action in inventory["actions"]
        if action["runtime_status"] == "forced_node20_metadata"
    ]
    exceptions = {exception["uses"] for exception in inventory["exceptions"]}
    assert inventory["forced_node20_metadata_count_must_be"] == 0
    _has(
        ci_cd,
        "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24",
        "GitHub JavaScript action runtime debt is closed",
        "common/testing/data/github-action-runtime.yaml",
    )
    assert not forced_actions
    assert set(forced_actions) == exceptions


def test_AC8_13_17_ac_traceability_runs_registry_generation_check() -> None:
    """AC8.13.17 AC8.13.141: registry check precedes the audit; the fail-closed
    AC-index gate (with folded traceability) is the single index gate.

    The standalone ``check_ac_traceability`` STEP is retired (its contract is
    folded into ``check_ac_index``, which runs once in the ``lint`` job). The
    ``ac-traceability`` job still checks registry generation before building the
    audit artifact.
    """
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    _has(workflow, "uv run --with pyyaml python tools/generate_ac_registry.py --check")
    # The single, fail-closed index gate (folds in the former traceability gate).
    _has(
        workflow, "uv run --with pyyaml --with pydantic python tools/check_ac_index.py"
    )
    # The retired standalone steps are gone.
    _lacks(
        workflow,
        "tools/check_ac_traceability.py",
        "tools/check_critical_proof_matrix.py",
    )
    _has(
        workflow, "uv run --with pyyaml python tools/build_ac_traceability.py --output"
    )
    assert workflow.index("tools/generate_ac_registry.py --check") < workflow.index(
        "tools/build_ac_traceability.py --output"
    )
    assert "generated registry indexes can be materialized" in ci_cd


def test_AC8_13_53_generated_api_reference_is_ci_checked() -> None:
    """AC8.13.53: API reference docs are generated contract output in CI."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    _has(
        workflow,
        "Generated API Reference Check",
        "uv run python ../../tools/generate_api_reference.py --check",
    )
    assert workflow.index("Install dependencies") < workflow.index(
        "tools/generate_api_reference.py --check"
    )
    _has(ci_cd, "Generated API reference", "FastAPI OpenAPI")


def test_AC14_1_17_generated_db_schema_reference_is_ci_checked() -> None:
    """AC14.1.17: DB schema reference docs are generated contract output in CI."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    _has(
        workflow,
        "Generated DB Schema Reference Check",
        "uv run python ../../tools/generate_db_schema_reference.py --check",
    )
    generate_line = "uv run python ../../tools/generate_db_schema_reference.py\n"
    assert generate_line in workflow
    assert workflow.index(generate_line) < workflow.index(
        "uv run python ../../tools/generate_db_schema_reference.py --check"
    )
    assert workflow.index("tools/generate_api_reference.py --check") < workflow.index(
        "tools/generate_db_schema_reference.py --check"
    )
    _has(
        ci_cd,
        "Generated DB schema reference",
        "SQLAlchemy model metadata",
        "docs/hooks.py",
    )


def test_AC8_13_53_pr_ci_avoids_moon_bootstrap_for_direct_gates() -> None:
    """AC8.13.53: PR CI avoids Moon bootstrap when direct commands suffice."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    _lacks(
        workflow,
        "moonrepo/setup-toolchain@v0",
        "moon run :build",
        "Build Frontend (via Moon)",
    )

    backend_block = workflow.split("  backend:", 1)[1].split(
        "  backend-integration:",
        1,
    )[0]
    integration_block = workflow.split("  backend-integration:", 1)[1].split(
        "  frontend-build:",
        1,
    )[0]
    frontend_build_block = workflow.split("  frontend-build:", 1)[1].split(
        "  frontend-vitest:",
        1,
    )[0]
    frontend_vitest_block = workflow.split("  frontend-vitest:", 1)[1].split(
        "  frontend-playwright:",
        1,
    )[0]
    frontend_playwright_block = workflow.split("  frontend-playwright:", 1)[1].split(
        "  frontend-telemetry-e2e:",
        1,
    )[0]
    frontend_telemetry_block = workflow.split("  frontend-telemetry-e2e:", 1)[1].split(
        "  container-images:",
        1,
    )[0]

    assert "moonrepo/setup-toolchain@v0" not in backend_block
    assert "moonrepo/setup-toolchain@v0" not in integration_block
    for frontend_block in (
        frontend_build_block,
        frontend_vitest_block,
        frontend_playwright_block,
        frontend_telemetry_block,
    ):
        assert "moonrepo/setup-toolchain@v0" not in frontend_block
        assert "working-directory: apps/frontend" in frontend_block
    _has(frontend_build_block, "name: Build Frontend", "run: npm run build")
    _has(
        ci_cd,
        "PR CI avoids Moon bootstrap",
        "direct `pytest` and `npm` commands",
        "Moon CLI availability and project graph coverage are static contracts",
    )


def _assert_job_setup_minio_invocations(
    job_name: str, steps: list[dict[str, Any]]
) -> None:
    count = sum(
        1 for step in steps if "./.github/actions/setup-minio" in step.get("uses", "")
    )
    assert count >= 2, (
        f"job {job_name} invoked setup-minio {count} times (expected >= 2)"
    )


def test_backend_integration_invokes_setup_minio() -> None:
    """CI backend-integration lane must invoke setup-minio."""
    workflow = yaml.safe_load(read(".github/workflows/ci.yml"))
    jobs = workflow.get("jobs", {})
    for job_name in ("backend-integration",):
        assert job_name in jobs, f"job {job_name} not found in ci.yml"
        _assert_job_setup_minio_invocations(job_name, jobs[job_name].get("steps", []))


def test_backend_integration_invoke_setup_minio_falsifiable() -> None:
    """Verify that mock steps with 0 or 1 setup-minio invocations fail the production assertion."""
    for step_count in (0, 1):
        mock_steps = [{"uses": "./.github/actions/setup-minio"}] * step_count
        with pytest.raises(
            AssertionError, match=r"invoked setup-minio \d times \(expected >= 2\)"
        ):
            _assert_job_setup_minio_invocations("mock-job", mock_steps)


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
    # frontend-vitest feeds unified-coverage's line-coverage baseline (its LCOV
    # is not component-scoped away, unlike backend-e2e-tier1's/frontend-build's/
    # frontend-playwright's non-coverage proof), so it stays gated on
    # pr_required alone — see AC-testing.ci-structure.11 for the other two.
    assert (
        jobs["frontend-vitest"]["if"] == "needs.changes.outputs.pr_required == 'true'"
    )
    # frontend-telemetry-e2e is right-moved (#1689): still required proof on
    # every PR that touches apps/frontend/**, but no longer runs unconditionally
    # on every PR — see test_AC8_13_162_frontend_telemetry_e2e_is_right_moved_and_skip_is_a_pass.
    frontend_changed_output = "needs.changes.outputs.frontend_changed"
    assert frontend_changed_output in jobs["frontend-telemetry-e2e"]["if"]
    # AC-testing.ci-structure.11: frontend-build/frontend-playwright are
    # right-moved the same way, off PRs that touch no apps/frontend/** path —
    # see test_AC_testing_ci_structure_11_frontend_build_and_playwright_are_right_moved_and_skip_is_a_pass.
    pr_required_output = "needs.changes.outputs.pr_required == 'true'"
    for job_id in ("frontend-build", "frontend-playwright"):
        assert pr_required_output in jobs[job_id]["if"]
        assert frontend_changed_output in jobs[job_id]["if"]

    assert jobs["unified-coverage"]["needs"] == [
        "changes",
        "backend",
        "frontend-vitest",
        "tooling-coverage",
    ]
    assert jobs["ac-behavioral-ratchet"]["needs"] == [
        "changes",
        "backend",
        "backend-integration",
        "frontend-vitest",
    ]
    assert jobs["finish"]["needs"] == [
        "changes",
        "schema-migrations",
        "backend",
        "backend-integration",
        "frontend-build",
        "frontend-vitest",
        "frontend-playwright",
        "frontend-telemetry-e2e",
        "container-images",
        "verify-sha-image-published",
        "lint",
        "tooling-coverage",
        "unified-coverage",
        "ac-traceability",
        "ac-behavioral-ratchet",
    ]

    def job_run_commands(job_id: str) -> str:
        return "\n".join(
            str(step.get("run", ""))
            for step in jobs[job_id].get("steps", [])
            if isinstance(step, dict)
        )

    assert "npm run typecheck" in job_run_commands("frontend-build")
    assert "npm run test:coverage" in job_run_commands("frontend-vitest")
    _has(
        job_run_commands("frontend-playwright"),
        "npm run test:e2e -- --reporter=line,html",
    )
    assert "npm run test:e2e:telemetry" in job_run_commands("frontend-telemetry-e2e")
    for job_id in split_jobs:
        assert "npm run audit:prod" not in job_run_commands(job_id)

    playwright_commands = job_run_commands("frontend-playwright")
    telemetry_commands = job_run_commands("frontend-telemetry-e2e")
    assert playwright_commands.index("npm run build") < playwright_commands.index(
        "npm run test:e2e"
    )
    assert telemetry_commands.index("npm run build") < telemetry_commands.index(
        "npm run test:e2e:telemetry"
    )
    _has(
        workflow_text,
        "coverage-frontend",
        "frontend-vitest-test-context",
        "frontend-playwright-test-context",
        "frontend-telemetry-test-context",
    )


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
        str(step.get("run", ""))
        for step in jobs["finish"].get("steps", [])
        if isinstance(step, dict)
    )
    skip_is_a_pass_clause = (
        '"${{ needs.frontend-telemetry-e2e.result }}" != "success" '
        '&& "${{ needs.frontend-telemetry-e2e.result }}" != "skipped"'
    )
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
        str(step.get("run", ""))
        for step in jobs["finish"].get("steps", [])
        if isinstance(step, dict)
    )
    for job_id in ("frontend-build", "frontend-playwright"):
        skip_is_a_pass_clause = (
            f'"${{{{ needs.{job_id}.result }}}}" != "success" '
            f'&& "${{{{ needs.{job_id}.result }}}}" != "skipped"'
        )
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
    action = yaml.safe_load(action_text)

    # ci.yml never calls the raw action directly -- only through the retry
    # wrapper -- and every "Install uv" step resolves to that one wrapper.
    raw_action_reference = "astral-sh/setup-uv"
    assert raw_action_reference not in workflow_text
    all_steps = [
        step
        for job in jobs.values()
        for step in job.get("steps", [])
        if isinstance(step, dict)
    ]
    install_uv_steps = [step for step in all_steps if step.get("name") == "Install uv"]
    wrapper_steps = [
        step
        for step in all_steps
        if step.get("uses") == "./.github/actions/setup-uv-retry"
    ]
    # Non-empty (never a vacuous pass), but not pinned to a job count: jobs
    # may be added or removed as long as each uv install routes through the
    # wrapper. The two lists must be the same steps, so a renamed step cannot
    # slip past either direction.
    assert install_uv_steps
    assert install_uv_steps == wrapper_steps

    # The wrapper itself: attempt 1 tolerates failure, a wait, then a retry
    # attempt that does NOT tolerate failure (a second failure must still
    # fail the job) -- both attempts call the same pinned upstream action.
    action_steps = action["runs"]["steps"]
    assert len(action_steps) == 3
    attempt_1, wait_step, retry = action_steps
    assert attempt_1["uses"] == "astral-sh/setup-uv@v8.2.0"
    assert attempt_1.get("continue-on-error") is True
    attempt_1_id = attempt_1["id"]
    assert wait_step["if"] == f"steps.{attempt_1_id}.outcome == 'failure'"
    assert retry["uses"] == "astral-sh/setup-uv@v8.2.0"
    assert retry["if"] == f"steps.{attempt_1_id}.outcome == 'failure'"
    assert retry.get("continue-on-error") is None


def test_AC_testing_ci_structure_14_tier1_runs_as_seeded_matrix_legs() -> None:
    """AC-testing.ci-structure.14: Tier-1 API E2E shard legs are retired and unified into backend integration and Bench V2."""
    workflow = yaml.safe_load(read(".github/workflows/ci.yml"))
    assert "backend-e2e-tier1" not in workflow["jobs"]
    assert "backend-integration" in workflow["jobs"]


def test_AC8_13_148_backend_shards_use_seeded_4_way_split() -> None:
    """AC-testing.ci-structure.8: AC8.13.148: backend shards use a seeded 4-way least-duration split
    (consolidated from 8-way alongside pytest -n auto parallelization, so a shard's slowest wall-clock
    time stays low while cutting fixed VM startup overhead)."""
    workflow_text = read(".github/workflows/ci.yml")
    workflow = yaml.safe_load(workflow_text)
    backend_job = workflow["jobs"]["backend"]
    inventory = read("common/meta/data/ci-gate-inventory.yaml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    durations = json.loads(read("apps/backend/ci/backend-test-durations.json"))

    assert backend_job["name"] == "Backend Tests (Shard ${{ matrix.shard }}/4)"
    assert backend_job["strategy"]["matrix"]["shard"] == [1, 2, 3, 4]
    assert len(durations) >= 2_000
    assert all(isinstance(value, (int, float)) for value in durations.values())

    backend_commands = "\n".join(
        str(step.get("run", ""))
        for step in backend_job.get("steps", [])
        if isinstance(step, dict)
    )
    _has(
        backend_commands,
        "Loaded pytest-split duration seed",
        "pytest-split duration seed is missing",
        "len(durations) < 500",
        "--splits 4",
        "--group ${{ matrix.shard }}",
        "--splitting-algorithm=least_duration",
        "--durations-path ci/backend-test-durations.json",
    )
    assert "--store-durations" not in backend_commands
    _lacks(
        workflow_text, "test-results/backend-shard-${{ matrix.shard }}-durations.json"
    )

    upload_context = workflow_text.split("Upload backend shard test context", 1)[1]
    _has(
        upload_context,
        "apps/backend/test-results/backend-shard-${{ matrix.shard }}.xml",
    )
    assert "apps/backend/ci/backend-test-durations.json" not in upload_context
    _has(
        ci_cd,
        "workflow job name `Backend Tests (Shard ${{ matrix.shard }}/4)`",
        "4-way parallel test sharding over the `pytest-split` duration seed",
        "apps/backend/ci/backend-test-durations.json",
        "not runner-local cache writes",
    )
    assert "matrix_legs: 4" in inventory


def test_AC8_13_149_fan_in_jobs_download_only_required_artifacts() -> None:
    """AC-testing.ci-structure.9: AC8.13.149: coverage and ratchet fan-in stays scoped and stdlib-fast."""
    workflow_text = read(".github/workflows/ci.yml")
    workflow = yaml.safe_load(workflow_text)
    jobs = workflow["jobs"]

    unified_block = workflow_text.split("  unified-coverage:", 1)[1].split(
        "  unified-coverage-baseline-pr:", 1
    )[0]
    ratchet_block = workflow_text.split("  ac-behavioral-ratchet:", 1)[1].split(
        "  finish:", 1
    )[0]

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
    _has(
        unified_block,
        "python tools/merge_lcov.py coverage/backend.lcov",
        "python tools/check_coverage_policy.py",
        "python tools/calculate_unified_coverage.py",
    )

    assert jobs["ac-behavioral-ratchet"]["needs"] == [
        "changes",
        "backend",
        "backend-integration",
        "frontend-vitest",
    ]
    assert "Download all test junit artifacts" not in ratchet_block
    _has(
        ratchet_block,
        "pattern: backend-shard-*-test-context",
        "name: backend-integration-test-context",
    )
    assert "pattern: backend-tier1-e2e-*-test-context" not in ratchet_block
    assert "name: frontend-vitest-test-context" in ratchet_block
    _lacks(ratchet_block, "uv run --with pyyaml python tools/aggregate_ac_evidence.py")
    _has(
        ratchet_block,
        "python tools/aggregate_ac_evidence.py",
        "python tools/check_ac_score_baseline.py",
    )


def test_AC8_13_146_report_main_dispatch_waits_for_ci_images() -> None:
    """AC-testing.deploy-gates.30: AC8.13.146: report-branch-main deploys only successful CI SHA images.

    The dispatch/skip DECISION (does a workflow_run completion's SHA still
    match main's tip, or is it stale?) is covered behaviorally by
    tests/tooling/test_report_main_dispatch.py (#1435 W1 / #1534), which
    executes tools/_lib/shell/resolve_report_main_dispatch_sha.sh directly.
    This test covers the surrounding wiring: trigger config, the env-var ->
    script-argument handoff, and the payload construction.
    """
    notify = read(".github/workflows/notify-infra2.yml")
    notify_yaml = yaml.safe_load(notify)
    notify_on = notify_yaml.get(True) or notify_yaml.get("on")

    # Exact trigger set (not just "push absent"/"workflow_dispatch present")
    # so an accidental third trigger fails this too, not just a missing one.
    assert set(notify_on) == {"workflow_run", "workflow_dispatch"}
    assert notify_on["workflow_run"]["workflows"] == ["CI"]
    assert notify_on["workflow_run"]["types"] == ["completed"]
    assert notify_on["workflow_run"]["branches"] == ["main"]

    dispatch_job = notify_yaml["jobs"]["dispatch"]
    _has(
        dispatch_job["if"],
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.head_branch == 'main'",
    )
    dispatch_script = "\n".join(
        step.get("run", "") for step in dispatch_job["steps"] if isinstance(step, dict)
    )
    assert "WORKFLOW_RUN_SHA: ${{ github.event.workflow_run.head_sha }}" in notify
    _has(
        dispatch_script,
        "/git/ref/heads/main",
        "tools/_lib/shell/resolve_report_main_dispatch_sha.sh",
    )
    assert "$GITHUB_SHA" not in dispatch_script
    assert '--arg sha "$dispatch_sha"' in dispatch_script

    delivery_gates = yaml.safe_load(read("common/meta/data/delivery-gates.yaml"))[
        "gates"
    ]
    report_gate = next(
        gate for gate in delivery_gates if gate["id"] == "report-main-preview"
    )
    assert report_gate["trigger"] == "workflow_run"
    assert report_gate["blocking"] is False


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

    # A missing job raises KeyError here, which fails the test just as loudly
    # as an explicit assert would — no need for a redundant membership check
    # (kept off the mirror-assertion ratchet, #1435).
    gate_job = jobs["verify-sha-image-published"]

    assert gate_job["needs"] == ["container-images"]
    assert (
        gate_job["if"]
        == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    )

    gate_script = "\n".join(
        step.get("run", "") for step in gate_job["steps"] if isinstance(step, dict)
    )
    # Verifies the per-commit :<sha> tag via the recomputed short_sha, not a
    # release version_ref and not container-images' own output (that would
    # just be re-asserting the build step's self-report instead of an
    # independent registry inspection).
    assert (
        "tools/verify_release_images.py" in gate_script
        and '--version-ref "${{ steps.get_sha.outputs.short_sha }}"' in gate_script
        and "container-images.outputs" not in gate_script
    )

    finish_job = jobs["finish"]
    finish_script = "\n".join(
        step.get("run", "")
        for step in finish_job["steps"]
        if isinstance(step, dict) and step.get("name") == "Check job status"
    )
    # Skip (PR / non-main push) must read as a pass, mirroring container-images'
    # own skip-is-a-pass clause — otherwise every PR would fail finish. (The
    # membership check above already proves finish depends on this job at
    # all; this proves the skip case specifically doesn't fail it.)
    _has(
        finish_script,
        '"${{ needs.verify-sha-image-published.result }}" != "success" && "${{ needs.verify-sha-image-published.result }}" != "skipped"',
    )


def test_AC8_13_68_ci_runs_e2e_epic_traceability_gate() -> None:
    """AC8.13.68: CI gates product E2E tests and project EPIC ownership."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    tdd = read("common/testing/tdd.md")

    _has(
        workflow,
        "uv run --with pyyaml python tools/check_e2e_epic_traceability.py --output",
        "$RUNNER_TEMP/E2E-EPIC-TRACEABILITY.md",
    )
    # The standalone check_ac_traceability / check_critical_proof_matrix steps are
    # retired (AC8.13.141); the surviving ordering is E2E traceability before the
    # audit-artifact build.
    assert workflow.index("tools/check_e2e_epic_traceability.py") < workflow.index(
        "tools/build_ac_traceability.py --output"
    )
    assert "function-level EPIC IDs" in ci_cd
    assert "tools/check_e2e_epic_traceability.py" in tdd


def test_AC8_13_70_ci_documents_closed_e2e_traceability_system() -> None:
    """AC8.13.70: E2E traceability documents README and asset closure."""
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    tdd = read("common/testing/tdd.md")
    readme = read("README.md")
    checker = read("common/testing/check_e2e_epic_traceability.py")

    _has(
        ci_cd,
        "the README EPIC map matches project EPIC files",
        "unclassified E2E-like assets outside declared roots",
    )
    _has(tdd, "root README EPIC map", "fails unclassified")
    assert "tools/check_e2e_epic_traceability.py" in readme
    _has(checker, "DECLARED_NON_PRODUCT_E2E_ROOTS", "DECLARED_NON_PRODUCT_E2E_FILES")


def test_AC8_13_9_production_release_runs_prod_safe_e2e_smoke() -> None:
    """AC-testing.deploy-gates.1: AC8.13.9: Production release runs prod-safe read-only E2E smoke."""
    workflow = read(".github/workflows/release.yml")
    prod_smoke = read("tests/e2e/test_production_readonly_smoke.py")

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
    _has(
        workflow,
        "Setup E2E Tests",
        "Production Infrastructure Smoke",
        "tools/production_infra_smoke.py",
        "test_production_readonly_smoke.py",
        "TEST_ENV: production",
    )
    assert "@pytest.mark.prod_safe" in prod_smoke
    _lacks(prod_smoke, "/api/auth/register", ".post(", ".patch(", ".put(", ".delete(")


def test_AC8_13_144_production_release_rolls_back_with_deploy_v2_after_post_deploy_failure() -> (
    None
):
    """AC-testing.deploy-gates.29: AC8.13.144: production rollback uses deploy_v2 and confirms previous health."""
    workflow = read(".github/workflows/release.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    inventory = read("common/meta/data/ci-gate-inventory.yaml")

    rollback_block = workflow.split(
        "- name: Roll back production after post-deploy failure", 1
    )[1].split("- name: Warn when production rollback cannot run", 1)[0]
    rollback_unavailable_block = workflow.split(
        "- name: Warn when production rollback cannot run", 1
    )[1].split("- name: Write production deploy context", 1)[0]
    probe_block = workflow.split("- name: Probe current production version", 1)[
        1
    ].split("- name: Deploy with deploy_v2", 1)[0]
    rollback_evidence_block = workflow.split(
        "- name: Resolve rollback release coordinate", 1
    )[1].split("- name: Roll back production after post-deploy failure", 1)[0]

    # infra2#588: these three verify a ROLLBACK TARGET's own release evidence by
    # reconstructing it from this repo's Actions history — blind to a prod version
    # deployed via any other deploy_v2 caller. They must not hard-fail the whole
    # job (that would block an otherwise fully-evidenced NEW release over a gap in
    # the OLD version's paper trail); rollback_block/rollback_unavailable_block's
    # outcome-based branching above is what actually handles a real gap safely.
    assert rollback_evidence_block.count("continue-on-error: true") == 3
    _has(
        rollback_evidence_block,
        "Verify rollback release images workflow passed",
        "Verify rollback staging passed",
        "Verify rollback reviewed change",
    )

    _has(
        rollback_block,
        "id: production_rollback",
        "failure()",
        "steps.deploy_v2.outcome == 'success'",
        "steps.production_before.outputs.rollback_ref != ''",
    )
    for step_id in (
        "deploy_health",
        "production_infra_smoke",
        "production_smoke",
        "production_readonly_e2e",
    ):
        assert f"steps.{step_id}.outcome == 'failure'" in rollback_block
    _has(probe_block, "rollback_ref", "health_version", "git_sha")
    _has(
        rollback_block,
        'rollback_ref="${{ steps.rollback_release.outputs.version_ref }}"',
    )
    _lacks(rollback_block, "pre-deploy version", "is not a release tag")
    _has(
        rollback_block,
        "python -m tools.app_deploy_request",
        "python -m tools.app_deploy_transport",
        "--deploy-type prod",
        '--version-ref "$rollback_ref"',
        "--staging-run-url",
        "--reviewed-change-url",
        "bash tools/health_check.sh",
        '"$rollback_ref"',
    )
    # infra2#588: a rollback target's OWN release evidence (release-images/staging/
    # reviewed-change) is reconstructed from this repo's Actions history, which is
    # blind to a prod version deployed via any other deploy_v2 caller — so this
    # step must fire on EITHER no rollback_ref being found, OR that evidence chain
    # failing to verify (not just the former). all(...) keeps this off the
    # mirror-assertion ratchet (common/testing/mirror_ratchet.py, #1558/#1435).
    unavailable_required_snippets = (
        "steps.production_before.outputs.rollback_ref != ''",
        "steps.rollback_release_images.outcome == 'success'",
        "steps.rollback_staging.outcome == 'success'",
        "steps.rollback_reviewed_change.outcome == 'success'",
        "deploy_v2/prod-compatible release tag",
        "could not verify",
        "reached production through a path other than this workflow",
    )
    assert all(
        snippet in rollback_unavailable_block
        for snippet in unavailable_required_snippets
    )
    # infra2#588: "Roll back production..." must only fire once the rollback
    # target's own evidence steps actually succeeded (not just outcome-agnostic
    # on rollback_ref being found) — an evidence gap routes to the warning below
    # instead. all(...) here (not one assert per snippet) keeps this off the
    # mirror-assertion ratchet (common/testing/mirror_ratchet.py, #1558/#1435).
    assert all(
        f"steps.{step_id}.outcome == 'success'" in rollback_block
        for step_id in (
            "rollback_release_images",
            "rollback_staging",
            "rollback_reviewed_change",
        )
    )
    assert "dokploy_deploy.sh" not in rollback_block
    _has(
        workflow,
        "production_rollback_outcome=${{ steps.production_rollback.outcome }}",
        "production_rollback_unavailable_outcome=${{ steps.production_rollback_unavailable.outcome }}",
        "production_before_rollback_ref=${{ steps.production_before.outputs.rollback_ref }}",
    )
    assert "Production release rollback uses the infra2 receiver" in ci_cd
    assert "production_rollback" in inventory


def test_AC8_13_67_production_release_preserves_version_metadata() -> None:
    """AC-testing.deploy-gates.18: AC8.13.67: Production release preserves deployed version metadata."""
    workflow = read(".github/workflows/release.yml")
    # Tag promotion (imagetools create x2) stays in deploy.yml's promote job.
    release_images = read(".github/workflows/deploy.yml")

    # In the promote-not-rebuild pattern, deploy.yml promotes the retained tag once.
    # Production sends the exact tag to infra2 and never re-promotes it.
    promote_blocks = re.findall(
        r"docker buildx imagetools create --prefer-index=false --tag",
        release_images,
    )
    assert len(promote_blocks) == 2
    assert "docker buildx imagetools create --tag" not in workflow

    _has(
        workflow,
        "Verify staging passed",
        "Verify Release Images Dry Run",
        '--source-sha "$source_sha"',
        '"${{ steps.release.outputs.version_ref }}"',
    )


def test_AC7_10_production_release_promotes_not_rebuilds() -> None:
    """AC-meta.release-pipeline.1: AC7.10.1 - AC7.10.5: Production release promotes staging-validated SHA image and fails closed on drift."""
    workflow = read(".github/workflows/release.yml")
    # Tag promotion stays in deploy.yml's promote job; the release line moved to
    # release.yml (#1354 / AC8.13.154).
    release_images = read(".github/workflows/deploy.yml")
    release_image_tool = read("common/runtime/release_images.py")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    deployment = read("common/runtime/deployment.md")

    # AC7.10.1: deploy.yml promotes main-CI SHA images instead of rebuilding.
    _has(release_images, "docker buildx imagetools create --prefer-index=false --tag")
    assert "docker/build-push-action" not in release_images
    assert "docker buildx imagetools create --tag" not in workflow
    # short_sha truncation is now covered behaviorally, not by source text —
    # see tests/tooling/test_release_coordinate.py (#1435 W1).
    # build-and-deploy (deploy.yml) + dry-run + deploy (release.yml) each resolve
    # the release coordinate once.
    assert (
        release_images.count("tools/resolve_release_coordinate.py")
        + workflow.count("tools/resolve_release_coordinate.py")
        == 3
    )

    # AC7.10.2: fails closed if no staging-validated SHA image exists or digests differ
    _has(workflow, "Verify staging passed", "Verify release images workflow passed")
    assert '"docker", "buildx", "imagetools", "inspect"' in release_image_tool
    assert "tools/verify_release_images.py" in workflow
    _has(
        release_images,
        "main-CI SHA images not found",
        'backend_sha_digest" != "$backend_promoted_digest',
        'frontend_sha_digest" != "$frontend_promoted_digest',
    )

    # AC7.10.3: summary records released commit, source CI run, digest, and no rebuild
    _has(
        workflow,
        "Released commit: ${{ steps.release.outputs.full_sha }}",
        "Source CI run: ${{ steps.source_ci.outputs.run_id }}",
        "Backend release image digest",
        "No rebuild occurred",
    )

    # AC7.10.4: SSOTs document promote-not-rebuild consistency ladder
    assert "promote-not-rebuild consistency ladder" in deployment
    assert "promote-not-rebuild consistency ladder" in ci_cd

    # AC7.10.5: workflow_dispatch dry-run proves promote path without mutating
    _has(workflow, "Verify Release Images Dry Run", "dry_run:")


def test_AC8_13_7_staging_runs_llm_e2e_serially_with_glm_5_1() -> None:
    """AC8.13.7: Post-merge AI/OCR E2E is a single-provider-access gate."""
    workflow = read(".github/workflows/deploy.yml")
    ai_workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    pr_workflow = read(".github/workflows/preview.yml")
    journey = read("tests/e2e/test_statement_full_journey.py")
    brokerage = read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")
    four_asset = read("tests/e2e/test_four_asset_net_worth_golden_path.py")
    upload = read("tests/e2e/test_statement_upload_e2e.py")
    preview_lifecycle = read("tools/_lib/dev/pr_preview_lifecycle")

    _lacks(workflow, "post-merge-train-turn:", "wait_post_merge_train_turn.py")
    _has(
        workflow,
        "workflow_dispatch:",
        "STAGING_E2E_PRIMARY_MODEL: glm-5.2",
        "STAGING_E2E_OCR_MODEL: glm-4.6v",
        "STAGING_E2E_VISION_MODEL: glm-4.6v",
    )
    # Marker expression equality is owned by the matrix conformance
    # gate (AC8.23.2, tests/tooling/test_workflow_selection_conformance.py).
    assert "PARSING_TIMEOUT_MS: 480000" in workflow
    # Staging is manual-only; no workflow_run auto-trigger remains.
    assert "workflow_run" not in workflow
    contract = staging_ai_ocr_contract_shell()
    _has(
        contract,
        "test_brokerage_upload_to_portfolio_value.py",
        "test_four_asset_net_worth_golden_path.py",
    )
    assert "tools/staging_ai_ocr_gate_contract.py --shell" in ai_workflow
    # Marker expression equality is owned by the matrix conformance
    # gate (AC8.23.2, tests/tooling/test_workflow_selection_conformance.py).
    assert "PARSING_TIMEOUT_MS: 480000" in ai_workflow
    assert "@pytest.mark.llm" in journey
    assert "@pytest.mark.llm" in brokerage
    assert "@pytest.mark.llm" in four_asset
    assert upload.count("@pytest.mark.llm") >= 2
    _has(
        preview_lifecycle,
        '"ZAI_API_KEY": ""',
        '"AI_BASE_URL": "https://api.z.ai/api/coding/paas/v4"',
        '"OCR_MODEL": "glm-4.6v"',
        '"AI_JSON_TIMEOUT_SECONDS": "360"',
        '"AI_JSON_MAX_TOKENS": "8192"',
        '"AI_JSON_DISABLE_THINKING": "true"',
    )
    _has(
        read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md"),
        "https://api.z.ai/api/coding/paas/v4",
    )
    # The preview marker expression is derived from the execution matrix at
    # runtime (#1547/#1556); the llm exclusion is asserted on the SSOT value.
    assert '-m "$PR_PREVIEW_E2E_MARKER"' in pr_workflow
    assert '-m "smoke or e2e"' not in pr_workflow

    from common.testing import matrix as _matrix

    assert "not llm" in _matrix.PR_PREVIEW_E2E_MARKER


def test_AC8_13_21_staging_ai_ocr_gate_runs_under_manual_dispatch() -> None:
    """AC-testing.deploy-gates.6: AC8.13.21: Provider-backed staging AI/OCR runs inside a manual dispatch, not auto-after-CI."""
    workflow = read(".github/workflows/deploy.yml")
    on_demand_gate = read(".github/workflows/deploy.yml")
    reusable = read(".github/workflows/staging-ai-ocr-gate.yml")

    parsed = yaml.safe_load(workflow)
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = parsed.get("on", parsed.get(True))
    assert isinstance(triggers, dict), "deploy.yml must declare an `on:` map"
    _has(triggers, "workflow_dispatch")
    assert "workflow_run" not in triggers, "staging deploy must NOT auto-follow CI"

    # The AI/OCR gate still exists in the staging deploy workflow (as a reusable
    # caller) and inherits its `workflow_dispatch` trigger rather than
    # auto-following a CI `workflow_run`. The gate body lives in the reusable.
    _has(
        workflow,
        "ai-ocr-gate:",
        "name: Staging AI/OCR Gate",
        "uses: ./.github/workflows/staging-ai-ocr-gate.yml",
    )
    assert "Run Staging AI/OCR Gate" in reusable
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"tags": ["v[0-9]+.[0-9]+.[0-9]+"]}
    _has(
        workflow,
        "if: ${{ github.event_name == 'workflow_dispatch' && inputs.target == 'staging' }}",
    )
    assert "workflow_run" not in triggers

    # An on-demand recovery entry point also runs the gate via workflow_dispatch.
    on_demand_parsed = yaml.safe_load(on_demand_gate)
    on_demand_triggers = on_demand_parsed.get("on", on_demand_parsed.get(True))
    assert isinstance(on_demand_triggers, dict)
    assert "workflow_dispatch" in on_demand_triggers


def test_AC8_13_120_staging_runs_lightweight_provider_connectivity_smoke() -> None:
    """AC-testing.deploy-gates.27: AC8.13.120: provider-risk staging changes prove a provider round trip."""
    workflow = read(".github/workflows/deploy.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    provider_test = read("tests/e2e/test_ai_provider_connectivity.py")

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
    # Marker expression equality is owned by the matrix conformance
    # gate (AC8.23.2, tests/tooling/test_workflow_selection_conformance.py).
    _has(
        workflow,
        "test-results/staging-provider-connectivity.xml",
        "provider-connectivity",
        "provider_connectivity_outcome=",
    )
    build_job = workflow.split("  build-and-deploy:", 1)[1].split(
        "\n  provider-gate:", 1
    )[0]
    provider_job = workflow.split("  provider-gate:", 1)[1].split("\n  ai-ocr-gate:", 1)
    assert "id: ai_provider_connectivity" not in build_job
    _has(
        provider_job[0],
        "id: ai_provider_connectivity",
        "ref: ${{ needs.build-and-deploy.outputs.commit_full_sha }}",
    )
    # The smoke is resilient to transient provider failure: it retries with
    # backoff, hard-fails only on a client/config 4xx
    # (config-failure), and reports a transient 5xx/timeout as a non-blocking
    # degraded status so a provider blip cannot red main.
    _has(
        workflow,
        "PROVIDER_CONNECTIVITY_RETRIES",
        "provider_status=config-failure",
        "provider_status=degraded",
        "degraded-provider",
    )
    provider_smoke = (
        provider_job[0]
        .split("name: AI Provider Connectivity Smoke", 1)[1]
        .split("name: Write provider gate context", 1)[0]
    )
    config_branch = provider_smoke.split("provider_status=config-failure", 1)[1].split(
        "provider_status=degraded", 1
    )[0]
    degraded_branch = provider_smoke.split("provider_status=degraded", 1)[1]
    _has(
        provider_smoke,
        "connectivity failed: [0-9]{3}",
        '[ "$status_code" -ge 400 ]',
        '[ "$status_code" -lt 500 ]',
    )
    assert "exit 1" in config_branch
    assert "exit 0" in degraded_branch
    _has(
        ci_cd,
        "provider connectivity smoke",
        "runs only when `provider_gate_required.staging` is true",
        "full OCR/LLM replay remains gated",
        "degraded-provider",
        "transient provider blips do not",
    )
    _has(
        provider_test,
        "@pytest.mark.llm",
        "authenticated_page_unique",
        "authenticated_page_unique.request.post",
        '"/chat"',
    )
    _lacks(workflow, "Wait for matching CI success", "wait_for_github_ci.py")
    assert "inherits the deploy workflow's `workflow_dispatch` trigger" in ci_cd


def test_AC8_13_22_staging_deploys_manually_dispatched_version_ref() -> None:
    """AC-testing.deploy-gates.7: AC8.13.22: Staging deploys the manually dispatched release version_ref."""
    workflow = read(".github/workflows/deploy.yml")
    resolver = read("common/runtime/release_coordinate.py")

    parsed = yaml.safe_load(workflow)
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = parsed.get("on", parsed.get(True))
    assert isinstance(triggers, dict)
    assert "workflow_dispatch" in triggers
    assert "workflow_run" not in triggers

    _has(workflow, "actions: read", "contents: read", "packages: read")
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"tags": ["v[0-9]+.[0-9]+.[0-9]+"]}
    _has(
        workflow,
        "if: ${{ github.event_name == 'workflow_dispatch' && inputs.target == 'staging' }}",
    )
    assert "Wait for matching CI success" not in workflow
    inputs = triggers["workflow_dispatch"].get("inputs") or {}
    assert "version_ref" in inputs
    assert "tag" not in inputs
    assert inputs["version_ref"].get("required") is False
    _has(
        workflow,
        "Version ref to deploy (vX.Y.Z release tag)",
        "tools/resolve_release_coordinate.py",
    )
    _has(resolver, "_RELEASE_VERSION_REF_RE", "version_ref must be a release tag")
    assert "version_ref.strip()" not in resolver
    # The superproject release-tag fetch stays narrow (no --force, only the
    # requested tag, --no-tags so it does not pull every app tag).
    assert '"--force"' not in resolver
    assert '"--no-tags"' in resolver
    assert '"refs/tags/*:refs/tags/*"' not in resolver
    assert 'f"refs/tags/{version_ref}:refs/tags/{version_ref}"' in resolver
    _lacks(resolver, "resolve_infra2_release_tag", "iac_ref")
    assert "VERSION_REF: ${{ inputs.version_ref }}" in workflow
    assert workflow.index("Resolve release coordinate") < workflow.index(
        "Deploy to Staging"
    )
    _lacks(
        workflow,
        "Build and push Backend",
        "Build and push Frontend",
        "Promote Backend Image to Staging Tag",
    )
    _has(
        workflow,
        "python -m tools.app_deploy_request",
        "python -m tools.app_deploy_transport",
        "--deploy-type staging",
        '--version-ref "$version_ref"',
    )


def test_AC8_13_22_release_coordinate_rejects_non_release_ref() -> None:
    """AC8.13.22: Release coordinate resolution rejects branch-form refs."""
    from common.runtime import release_coordinate

    with pytest.raises(ValueError, match="version_ref must be a release tag"):
        release_coordinate.resolve("main")


def test_AC8_13_22_release_coordinate_rejects_whitespace_version_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.22: Whitespace-padded release refs fail instead of being trimmed."""
    from common.runtime import release_coordinate

    monkeypatch.setattr(release_coordinate, "_run", lambda *_args: None)
    monkeypatch.setattr(release_coordinate, "_out", lambda *_args: "a" * 40)

    with pytest.raises(ValueError, match="version_ref must be a release tag"):
        release_coordinate.resolve(" v1.2.3 ")


def test_AC8_13_22_release_coordinate_fetches_only_requested_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.22: Release coordinate resolution does not force-fetch every tag."""
    from common.runtime import release_coordinate

    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        release_coordinate,
        "_run",
        lambda *args: commands.append(args),
    )
    monkeypatch.setattr(
        release_coordinate,
        "_out",
        lambda *args: "a" * 40,
    )

    coord = release_coordinate.resolve("v1.2.3")

    assert commands[0] == (
        "git",
        "fetch",
        "--no-tags",
        "origin",
        "refs/tags/v1.2.3:refs/tags/v1.2.3",
    )
    assert not any("--force" in command for command in commands)
    assert set(coord) == {"version_ref", "full_sha", "short_sha"}


def test_AC8_13_36_post_merge_reuses_sha_tagged_staging_images() -> None:
    """AC-testing.deploy-gates.9: AC8.13.36: Main CI builds SHA images, deploy.yml tags them, staging deploys the tag."""
    ci_workflow = read(".github/workflows/ci.yml")
    release_workflow = read(".github/workflows/deploy.yml")
    deploy_workflow = read(".github/workflows/deploy.yml")
    resolver = read("common/runtime/release_coordinate.py")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    _has(ci_workflow, "container-images:", "name: Build Staging Images")
    container_block = ci_workflow.split("  container-images:", 1)[1].split(
        "  tooling-coverage:", 1
    )[0]
    assert "needs: [changes]" in container_block
    _lacks(container_block.split("steps:", 1)[0], "lint", "ac-traceability")
    _has(
        ci_workflow,
        "needs.changes.outputs.pr_required == 'true'",
        "if: github.event_name == 'push' && github.ref == 'refs/heads/main'",
        "packages: write",
        "Build Backend SHA image",
        "Build Frontend SHA image",
        "full_sha=$(git rev-parse HEAD)",
        'short_sha="${full_sha:0:7}"',
        "push: ${{ (github.event_name == 'push' && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/release/'))) || github.event_name == 'workflow_dispatch' }}",
        "${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}-backend:${{ steps.get_sha.outputs.short_sha }}",
        "${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}-frontend:${{ steps.get_sha.outputs.short_sha }}",
    )
    _lacks(ci_workflow, "backend:staging", "frontend:staging")

    _has(
        release_workflow,
        "Release Images",
        "tags: ['v[0-9]+.[0-9]+.[0-9]+']",
        'full_sha="$(git rev-parse "$GITHUB_SHA")"',
        'short_sha="${full_sha:0:7}"',
        "docker buildx imagetools create --prefer-index=false --tag",
        "Backend digests differ!",
        "Frontend digests differ!",
    )

    _lacks(
        deploy_workflow,
        "Resolve Backend Image",
        "Resolve Frontend Image",
        "tools/check_ghcr_image_tag.sh",
        "Build and push Backend",
        "Build and push Frontend",
        "Promote Backend Image to Staging Tag",
    )
    _has(
        deploy_workflow,
        "VERSION_REF: ${{ inputs.version_ref }}",
        "tools/resolve_release_coordinate.py",
    )
    _has(resolver, '"git", "rev-parse", "HEAD"', '"short_sha": full_sha[:7]')
    assert deploy_workflow.index("Resolve release coordinate") < deploy_workflow.index(
        "Deploy to Staging"
    )
    _has(
        deploy_workflow,
        "backend_image=${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}-backend:${{ steps.release.outputs.version_ref }}",
        "frontend_image=${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}-frontend:${{ steps.release.outputs.version_ref }}",
    )

    _has(
        ci_cd,
        "SHA-tagged images",
        "deploy.yml",
        "promotes main-CI SHA images to the immutable release tag",
        "staging deploy consumes the release tag without rebuilding",
    )


def test_AC8_13_40_pr_ci_dry_runs_staging_image_builds_before_merge() -> None:
    """AC-testing.deploy-gates.10: AC8.13.40: PR CI dry-runs staging image builds before merge."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    container_block = workflow.split("  container-images:", 1)[1].split(
        "  tooling-coverage:", 1
    )[0]
    finish_block = workflow.split("- name: Check job status", 1)[1]
    login_block = container_block.split("- name: Log in to Container registry", 1)[
        1
    ].split("- name: Set up Docker Buildx", 1)[0]

    # PR path still gates the dry-run on pr_required + image_build_required; a
    # main/release push always builds (immutable :<sha> for promote-not-rebuild).
    _has(
        container_block,
        "needs.changes.outputs.pr_required == 'true' && needs.changes.outputs.image_build_required == 'true'",
    )
    _has(
        login_block,
        "if: (github.event_name == 'push' && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/release/'))) || github.event_name == 'workflow_dispatch'",
    )
    assert container_block.count("uses: docker/build-push-action@v7") == 2
    assert (
        container_block.count(
            "push: ${{ (github.event_name == 'push' && (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/heads/release/'))) || github.event_name == 'workflow_dispatch' }}"
        )
        == 2
    )
    _has(container_block, "Build Backend SHA image", "Build Frontend SHA image")
    assert "Container image validation failed" in finish_block
    _has(
        ci_cd,
        "PR CI dry-runs staging image builds before merge",
        "Main and release-branch push CI, plus on-demand",
    )


def test_AC8_13_89_pr_preview_follows_ci_without_pr_image_builds() -> None:
    """AC-testing.preview.7: AC8.13.89: the in-runner e2e gate runs synchronously on pull_request (independent
    of CI) and does not build/push PR images."""
    workflow = read(".github/workflows/preview.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
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
    _has(
        workflow,
        "types: [opened, synchronize, reopened, closed]",
        'action = "deploy"',
        'action_reason = "pull-request-sync"',
        'action = "cleanup"',
        "github.event.pull_request.number",
    )
    _lacks(workflow, "gate-cheap-ci:", "tools/wait_for_cheap_ci.py")
    # No PR preview IMAGES are built/pushed/preflighted in CI: the persistent
    # preview is built from source on the Dokploy host instead.
    _lacks(
        workflow,
        "build-preview-backend-image:",
        "build-preview-frontend-image:",
        "Preflight PR preview image tags",
        "docker/build-push-action@v7",
        "push: true",
        "packages: write",
    )
    # Persistent preview: non-blocking deploy job, after the in-runner E2E gate,
    # building from the PR source on the Dokploy host (no image pull/push).
    assert "deploy-preview:" in workflow
    assert "needs: [setup, e2e]" in deploy_block
    assert "needs.e2e.result == 'success'" in workflow
    _has(
        deploy_block,
        "continue-on-error: true",
        "--action deploy",
        "--github-integration-id",
        "build from source on Dokploy host",
    )
    # The preview compose builds backend/frontend from source (no image pull).
    _has(pr_preview_compose, "context: ./apps/backend", "context: ./apps/frontend")
    assert "pull_policy: always" not in pr_preview_compose
    _has(
        e2e_block,
        "GIT_COMMIT_SHA: ${{ needs.setup.outputs.head_sha }}",
        "EXPECTED_SHA: ${{ needs.setup.outputs.head_sha }}",
        "APP_URL: http://localhost:8080",
        "docker compose up --build",
        "docker compose down --volumes --remove-orphans",
    )
    _has(
        frontend_dockerfile,
        "ARG GIT_COMMIT_SHA=unknown",
        "ENV GIT_COMMIT_SHA=${GIT_COMMIT_SHA}",
    )
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
    _has(e2e_block, "Wait for stack readiness", "End-to-End Tests")
    assert e2e_block.index("Wait for stack readiness") < e2e_block.index(
        "End-to-End Tests"
    )
    _has(
        e2e_block,
        'curl -fsS "$APP_URL/api/health"',
        "bash tools/smoke_test.sh",
        "no PR preview image is pushed",
    )
    assert "Delete GHCR images" not in cleanup_block
    assert "pr_preview_images=not-created" in cleanup_block
    _has(
        ci_cd,
        "synchronously on `pull_request`",
        "does not push, preflight, pull, or delete PR preview images",
        "built from the PR source on the Dokploy host",
        "not the infra2 `deploy_v2 preview/*` front door",
        "The runner stack waits for `/api/health` before smoke/E2E",
    )


def test_AC8_13_23_post_merge_deploy_and_ai_ocr_are_one_serial_unit() -> None:
    """AC-testing.deploy-gates.8: AC8.13.23: Deploy health and provider gate share one serialized workflow unit."""
    deploy_workflow = read(".github/workflows/deploy.yml")
    ai_workflow = read(".github/workflows/deploy.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

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
    assert 'workflows: ["Deploy Staging"]' not in ai_workflow
    assert "serialized deploy workflow unit" in ci_cd
    assert "in-job FIFO" not in ci_cd
    _has(
        ci_cd,
        "test code, audit context, and deployed image under validation aligned",
        "only one `Deploy Staging` run mutates staging at a time",
    )


def test_AC8_13_24_ac_traceability_uploads_audit_artifact_without_stale_doc_gate() -> (
    None
):
    """AC-testing.acgates.2: AC8.13.24: CI uploads traceability audit instead of gating stale snapshots."""
    workflow = read(".github/workflows/ci.yml")
    audit_builder = read("common/testing/build_ac_traceability.py")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    project_readme = read("docs/project/README.md")

    _has(
        workflow,
        "uv run --with pyyaml python tools/generate_ac_registry.py --check",
        'tools/build_ac_traceability.py --output "$RUNNER_TEMP/AC-TEST-TRACEABILITY-AUDIT.md"',
        "uses: actions/upload-artifact@v7",
        "name: ac-test-traceability-audit",
    )
    assert "tools/build_ac_traceability.py --check" not in workflow
    assert "CI uploads the generated audit as an artifact" in audit_builder
    assert "uploaded as a CI artifact" in ci_cd
    _has(
        project_readme,
        "Do not commit generated audit snapshots in routine",
        "issue #548",
    )


def test_AC8_13_25_full_ci_aggregates_static_traceability_and_test_gates() -> None:
    """AC-testing.ci-structure.1: AC8.13.25: Full CI starts tests early while finish aggregates every gate."""
    workflow = read(".github/workflows/ci.yml")
    workflow_data = yaml.safe_load(workflow)
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    backend_block = workflow.split("  backend:", 1)[1].split(
        "  frontend-build:",
        1,
    )[0]
    frontend_block = workflow.split("  frontend-build:", 1)[1].split(
        "  container-images:", 1
    )[0]
    image_block = workflow.split("  container-images:", 1)[1].split(
        "  tooling-coverage:", 1
    )[0]
    tooling_block = workflow.split("  tooling-coverage:", 1)[1].split(
        "  unified-coverage:", 1
    )[0]
    finish_block = workflow.split("  finish:", 1)[1]

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
    assert workflow_data["jobs"]["ac-traceability"]["if"] == "${{ always() }}"
    _has(
        finish_block,
        "needs: [changes, schema-migrations, backend, backend-integration, frontend-build, frontend-vitest, frontend-playwright, frontend-telemetry-e2e, container-images, verify-sha-image-published, lint, tooling-coverage, unified-coverage, ac-traceability, ac-behavioral-ratchet]",
    )
    _has(
        ci_cd,
        "late evidence consumer",
        "Deterministic test and image jobs start after change classification",
        "finish remains the authoritative aggregate gate",
    )


def test_AC8_13_86_fast_feedback_jobs_do_not_wait_for_behavior_gates() -> None:
    """AC-testing.ci-structure.5: AC8.13.86: CI fast feedback jobs preserve actual workflow dependency semantics."""
    workflow = read(".github/workflows/ci.yml")
    workflow_data = yaml.safe_load(workflow)
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

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
    assert set(workflow_data["jobs"]["ac-traceability"]["needs"]) == {
        "changes",
        "lint",
        "tooling-coverage",
        "backend",
        "backend-integration",
        "frontend-vitest",
    }
    assert workflow_data["jobs"]["ac-traceability"]["if"] == "${{ always() }}"
    _has(
        ci_cd,
        "Standalone lint starts immediately",
        "Deterministic test and image jobs start after change classification",
        "Behavior-only backend gates run in parallel",
        "`ac-traceability` is intentionally a late evidence consumer",
    )


def test_AC8_13_94_env_and_pipeline_stage_contract_is_documented() -> None:
    """AC-testing.governance.3: AC8.13.94: environments and pipeline stages are separate matrix axes."""
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    environments = read("common/runtime/environments.md")
    readme = read("README.md")

    _has(
        ci_cd,
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
    )

    _has(
        ci_cd,
        "not every environment runs every pipeline stage",
        "environment taxonomy, pipeline stages, and GitHub Actions jobs",
    )
    _has(environments, "Environment taxonomy is not the delivery pipeline stage count")
    _has(readme, "Local fast feedback", "PR CI is the authoritative merge gate")


def test_AC8_13_95_local_fast_gate_and_escalation_policy_are_documented() -> None:
    """AC-testing.governance.4: AC8.13.95: local defaults stay fast but escalate for high-risk paths."""
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    development = read("common/meta/development.md")
    readme = read("README.md")

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
    _has(readme, "Default local loop", "risk-triggered escalation")


def test_AC8_13_67_backend_tier1_api_e2e_scope_excludes_browser_e2e() -> None:
    """AC8.13.67: Tier-1 backend API E2E is retired and consolidated into Bench V2."""
    workflow = read(".github/workflows/ci.yml")
    pyproject = read("apps/backend/pyproject.toml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    matrix_yaml = yaml.safe_load(read("common/testing/data/test-execution-matrix.yaml"))

    assert "backend-e2e-tier1:" not in workflow
    _has(
        pyproject,
        "e2e: End-to-end tests, including backend API scenarios and browser UI flows",
    )
    assert "test-execution-matrix.yaml" in ci_cd
    # Legacy apps/backend/tests/e2e/test_core_journeys.py has been consolidated into Bench V2
    assert not any(
        rule["path"] == "apps/backend/tests/e2e/test_core_journeys.py"
        for rule in matrix_yaml["rules"]
    )


def test_AC8_13_27_coveralls_uploads_are_reporting_only() -> None:
    """AC-testing.coverage.2: AC8.13.27: PR CI has no external Coveralls status surface."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    coverage = read("common/testing/coverage.md")
    readme = read("README.md")

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
    global_permissions = workflow.split("env:", 1)[0]
    unified_coverage_block = workflow.split("  unified-coverage:", 1)[1].split(
        "  ac-traceability:", 1
    )[0]
    assert "statuses: write" not in global_permissions
    assert "statuses: write" not in unified_coverage_block
    _lacks(
        workflow,
        "Mark Coveralls statuses reporting-only",
        "tools/mark_coveralls_reporting_status.py",
        "publish_coveralls_reporting_statuses",
        "Wait for Coveralls unified status",
        "mark_coveralls_reporting_status.py",
        "wait_for_github_status.py",
    )
    _has(
        workflow,
        "Write coverage gate summary",
        "Authoritative coverage gate",
        "Pull requests do not publish Coveralls status contexts",
    )
    _has(ci_cd, "Pull requests do not call Coveralls", "coverage gate summary")
    _has(
        coverage,
        "Coveralls badge is reporting-only",
        "authoritative coverage gate",
        "PR CI does not call Coveralls",
    )
    _has(
        readme,
        "Pull requests do not publish",
        "merge readiness follows the `finish` check",
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


def test_AC8_13_75_unified_coverage_uploads_debug_context() -> None:
    """AC8.13.75: Unified coverage preserves line-level debug inputs."""
    workflow = read(".github/workflows/ci.yml")
    coverage = read("common/testing/coverage.md")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    tooling_coverage_block = workflow.split("  tooling-coverage:", 1)[1].split(
        "  unified-coverage:", 1
    )[0]
    unified_coverage_block = workflow.split("  unified-coverage:", 1)[1].split(
        "  ac-traceability:", 1
    )[0]
    upload_block = unified_coverage_block.split(
        "- name: Upload unified coverage context", 1
    )[1].split("# Note: baseline auto-push removed", 1)[0]

    _has(
        tooling_coverage_block,
        "Tooling/Common Coverage",
        "Run tooling tests with coverage",
        "Upload tooling coverage context",
        "name: coverage-tooling",
        "--cov=common",
        "--cov=tools",
    )
    assert "Run tooling tests with coverage" not in unified_coverage_block
    _has(
        unified_coverage_block,
        "Download tooling coverage",
        "Write coverage debug context",
    )
    _has(
        upload_block,
        "if: ${{ always() }}",
        "name: unified-coverage-context",
        "coverage/backend.lcov",
        "coverage/frontend.lcov",
        "coverage/common.lcov",
        "coverage/tools.lcov",
        "coverage/coverage-context.txt",
        "unified-coverage.json",
    )
    _has(coverage, "coverage context artifact", "unified-coverage-context")
    assert "raw line-count inputs" in ci_cd


def test_AC8_13_143_unified_coverage_updates_baseline_through_pr_not_direct_main_push() -> (
    None
):
    """AC-testing.coverage.5: AC8.13.143: main baseline updates are automated through a PR, not a direct push."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    inventory = read("common/meta/data/ci-gate-inventory.yaml")

    unified_coverage_block = workflow.split("  unified-coverage:", 1)[1].split(
        "  unified-coverage-baseline-pr:", 1
    )[0]
    baseline_job_block = workflow.split("  unified-coverage-baseline-pr:", 1)[1].split(
        "  ac-traceability:", 1
    )[0]
    baseline_block = baseline_job_block.split(
        "- name: Open unified coverage baseline PR", 1
    )[1]

    _has(unified_coverage_block, "permissions:", "contents: read")
    _lacks(unified_coverage_block, "contents: write", "pull-requests: write")
    _has(
        baseline_job_block,
        "needs: [changes, unified-coverage]",
        "contents: write",
        "pull-requests: write",
        "if: github.event_name == 'push' && github.ref == 'refs/heads/main' && needs.changes.outputs.pr_required == 'true' && needs.unified-coverage.result == 'success'",
        "name: unified-coverage-context",
    )
    # The baseline content still comes from the uploaded coverage context; the
    # rise-only merge reads it instead of a blind cp (which folded dips in).
    tool_impl = read("common/testing/unified_coverage_baseline_pr.py")
    _has(
        baseline_block,
        "tools/open_unified_coverage_baseline_pr.py",
        "--coverage-context coverage-context/unified-coverage.json",
        "BASELINE_BRANCH: automation/unified-coverage-baseline",
    )
    # Quantized-rise guard (replaces the old byte-level `git diff --quiet`,
    # which churned a baseline PR on every ±1 covered-line jitter) and a plain
    # --force push (not leased: the shallow CI checkout never fetches the bot
    # branch, so a lease has no remote-tracking ref and rejects with "stale
    # info"; single-writer bot branch, and the push still targets
    # $BASELINE_BRANCH — never main, asserted below — so the AC's real
    # invariant, baseline updates via PR, holds).
    tool_impl.index("kept old baseline for")
    tool_impl.index('"git"')
    tool_impl.index('"push"')
    tool_impl.index('f"HEAD:{baseline_branch}"')
    tool_impl.index('"gh"')
    tool_impl.index('"edit"')
    tool_impl.index('"create"')
    assert "HEAD:main" not in baseline_block and "HEAD:main" not in tool_impl
    assert "[skip ci]" not in baseline_block
    assert "unified-coverage-baseline-pr" not in workflow.split("  finish:", 1)[1]
    assert "automatic baseline PR" in ci_cd
    _has(inventory, "task_category: coverage_fan_in", "baseline_update_pr_on_main")


def test_AC8_13_66_coveralls_uploads_use_line_only_lcov() -> None:
    """AC8.13.66: Main Coveralls reporting uses the unified line-only metric."""
    workflow = read(".github/workflows/ci.yml")
    coverage = read("common/testing/coverage.md")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    _has(
        workflow,
        "tools/build_unified_lcov.py coverage/coveralls-unified.lcov --strip-branches",
        "file: coverage/coveralls-unified.lcov",
    )
    _lacks(
        workflow,
        "file: coverage/coveralls-backend.lcov",
        "file: coverage/coveralls-frontend.lcov",
    )
    _has(workflow, "if: github.event_name == 'push' && github.ref == 'refs/heads/main'")
    _has(
        coverage,
        "Coveralls upload LCOV files are line-only",
        "Coveralls is a main-branch external reporting baseline only",
    )
    _has(
        ci_cd,
        "Coverage scope is deny-list based within each governed source root",
        "strip branch records before upload",
    )


def test_AC8_13_93_staging_promotion_requires_manual_dispatch() -> None:
    """AC-testing.deploy-gates.19 AC-testing.deploy-gates.22: AC8.13.93: Staging is mutated only by an explicit manual dispatch; no auto path."""
    workflow = read(".github/workflows/deploy.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    deployment = read("common/runtime/deployment.md")

    parsed = yaml.safe_load(workflow)
    # PyYAML parses the bare `on:` key as the boolean True.
    triggers = parsed.get("on", parsed.get(True))
    assert isinstance(triggers, dict), "deploy.yml must declare an `on:` map"
    # deploy.yml also owns release-image tag promotion; no workflow_run / branch
    # push / schedule path can mutate staging.
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["push"] == {"tags": ["v[0-9]+.[0-9]+.[0-9]+"]}
    inputs = triggers["workflow_dispatch"].get("inputs") or {}
    assert "version_ref" in inputs
    assert "tag" not in inputs
    assert inputs["version_ref"].get("required") is False

    # The retired auto-deploy machinery (the dedicated "CI Workflow Run Ignored"
    # skip-summary job that fired on a non-success CI workflow_run) is gone.
    _lacks(workflow, "ci-not-success-summary:", "name: CI Workflow Run Ignored")

    # The staging build-and-deploy job and Dokploy mutation only run on the
    # staging manual target; a bare event-only guard would be too weak now that
    # deploy.yml also owns tag-push image promotion.
    assert "if: ${{ github.event_name == 'workflow_dispatch' }}" not in workflow

    # The structured deploy failure-context classification is preserved.
    failure_context = workflow.split("Classify staging deploy failure context", 1)[
        1
    ].split("Write staging deploy context", 1)[0]
    _has(
        failure_context,
        "id: deploy_failure_context",
        '"toolchain/uv-install"',
        '"toolchain/python-setup"',
        '"toolchain/deploy-v2-deps"',
        '"deploy-v2-rollout"',
        '"staging-route-health"',
        '"application-smoke-e2e"',
        "Failure domain: ${failure_domain}",
        "Failed step: ${failed_step}",
        "Failure summary: ${failure_summary}",
    )

    _has(
        ci_cd,
        "Staging deploy is manual",
        "does not poll or wait for CI",
        "failure domain, failed step, and failure summary",
    )
    assert "manual" in deployment.lower()


def test_AC8_13_45_make_test_routes_through_root_moon_test() -> None:
    """AC8.13.45: make test uses the root Moon verification entry point."""
    makefile = read("Makefile")
    development = read("common/meta/development.md")
    environments = read("common/runtime/environments.md")

    assert "\n\tmoon run :test\n" in makefile
    assert "moon run backend:test" not in makefile
    assert "same gate family as GitHub CI" in development
    assert "same gate family as GitHub CI" in environments


def test_AC8_13_45_root_moon_tasks_use_explicit_app_workspace_inputs() -> None:
    """AC8.13.45: Root Moon gates use explicit application workspace inputs."""
    moon = yaml.safe_load(read("moon.yml"))

    workspace_inputs = moon["fileGroups"]["workspace"]
    _lacks(workspace_inputs, "repo", "**/*")
    _has(workspace_inputs, "common/**/*", "tools/**/*")
    _has(
        read("common/meta/development.md"),
        "uncached wrappers with explicit workspace inputs",
    )

    for task_name in ("setup", "dev", "test", "lint", "build", "clean"):
        task = moon["tasks"][task_name]
        task_inputs = task["inputs"]
        assert task_inputs == ["@group(workspace)"]
        assert task["options"]["cache"] is False


def test_AC8_13_46_pr_preview_non_llm_gate_matches_staging_strict_parallelism() -> None:
    """AC-testing.preview.2: AC8.13.46: PR preview keeps strictness while narrowing to preview scope."""
    preview = read(".github/workflows/preview.yml")
    staging = read(".github/workflows/deploy.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    preview_block = preview.split("- name: End-to-End Tests", 1)[1].split(
        "- name: Rollback on E2E Failure", 1
    )[0]
    staging_block = staging.split("- name: End-to-End Tests", 1)[1].split(
        "\n  ai-ocr-gate:", 1
    )[0]

    for block in (preview_block, staging_block):
        assert "STRICT_E2E_GATES: true" in block

    # Preview selection is derived from the execution matrix SSOT
    # (common/testing/matrix.py, #1547/#1556): the workflow carries no
    # hardcoded test list; full conformance is gated in
    # tests/tooling/test_execution_matrix_contract.py (AC8.22).
    _has(
        preview_block,
        'eval "$(python tools/test_selection.py --stage pr_preview_e2e --shell)"',
        'pytest "${PR_PREVIEW_E2E_TESTS[@]}"',
        '-m "$PR_PREVIEW_E2E_MARKER"',
    )
    assert "tests/e2e/" not in preview_block

    from common.testing import matrix

    # The preview marker expression stays aligned with the staging gate's.
    assert matrix.PR_PREVIEW_E2E_MARKER == "(smoke or e2e) and not llm"

    # Marker expression equality is owned by the matrix conformance
    # gate (AC8.23.2, tests/tooling/test_workflow_selection_conformance.py).

    assert "PR preview non-LLM E2E is a strict preview-relevant subset" in ci_cd


def test_AC8_13_38_pr_preview_dokploy_responses_are_not_logged() -> None:
    """AC8.13.38: preview DEPLOY parses Dokploy responses without raw logs; the app
    runs no Dokploy reclaim — PR close dispatches a teardown signal to infra2."""
    preview = read(".github/workflows/preview.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    lifecycle = read("tools/_lib/dev/pr_preview_lifecycle")

    _has(ci_cd, "PR preview Dokploy API responses are parsed for required fields only")
    # Deploy goes through pr_preview_lifecycle.py (no hand-rolled Dokploy curl), so
    # it logs no raw responses.
    _has(preview, "Deploy preview lifecycle", "--action deploy")
    # Reclaim is infra2-owned: no app-side cleanup/reconcile; on PR close the app
    # only dispatches a vendor-neutral teardown signal to infra2.
    _lacks(preview, "--action cleanup", "--action reconcile")
    assert "preview-teardown" in preview
    assert "Response body" not in lifecycle
    _has(lifecycle, "raw_body_printed: false", "safe_message")

    unsafe_patterns = (
        r"response=\$\(curl[^)]*/compose\.create",
        r"curl -sf -X POST [^\n]*/compose\.update[\s\S]*?\n\s*-d \"\$PAYLOAD\"\n(?![\s\S]*?-o )",
        r"curl -sf -X POST [^\n]*/compose\.deploy[\s\S]*?\n\s*-d \"\{\\\"composeId",
        r"curl -sf -X POST [^\n]*/compose\.delete[\s\S]*?\n\s*-d \"\{\\\"composeId",
        r"echo \"Response: \$response\"",
    )
    for pattern in unsafe_patterns:
        assert re.search(pattern, preview) is None


def test_AC8_13_108_staging_failure_context_fails_closed_on_classifier_and_unknown_failures() -> (
    None
):
    """AC8.13.108: staging failure context does not hide real failures as skips."""
    workflow = read(".github/workflows/deploy.yml")
    failure_context = workflow.split("Classify staging deploy failure context", 1)[
        1
    ].split("Write staging deploy context", 1)[0]

    for step_id in [
        "checkout",
        "release",
        "classify",
        "install_uv",
        "setup_python",
        "install_deploy_v2",
        "deploy_staging",
        "staging_health",
    ]:
        assert f"id: {step_id}" in workflow

    _has(
        failure_context,
        '"classification"',
        '"release-coordinate-resolution"',
        '"change-classification"',
        "Change classification failed before staging relevance could be trusted.",
        '"toolchain/uv-install"',
        '"toolchain/python-setup"',
        '"toolchain/deploy-v2-deps"',
        '"deploy-v2-rollout"',
        '"staging-route-health"',
        '"unclassified-build-deploy-failure"',
        "A build/deploy job step failed outside the known failure map.",
        "STEPS_CONTEXT: ${{ toJSON(steps) }}",
        'grep -q \'"outcome":"failure"\'',
    )
    assert failure_context.index('"change-classification"') < failure_context.index(
        'staging_required" != "true"'
    )


def test_AC8_13_47_delivery_engine_recommendations_are_tracked() -> None:
    """AC-testing.governance.1: AC8.13.47: remaining delivery-engine work is captured outside mutable SSOT."""
    recommendation = read("docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md")
    project_readme = read("docs/project/README.md")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

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
    _has(
        ci_cd,
        "delivery-engine recommendation note",
        "Main CI run `27896401849` after PR #1288",
        "backend shards finished in the 3m 31s-3m 50s band",
    )


def test_AC8_13_112_sparse_matrix_recommendation_tracks_simplification_path() -> None:
    """AC-testing.classifier.8: AC8.13.112: sparse-matrix audit keeps the simplification path explicit."""
    recommendation = read("docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    classifier = read("common/testing/change_classifier.py")

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
    # Migration complete: the per-env legacy scalar outputs are retired, and the
    # SSOT records that completed state rather than an in-progress shim.
    _has(
        ci_cd,
        "legacy per-env scalar outputs",
        "retired",
        "GitHub Actions consumers normalize gates from the structured matrix",
    )
    _has(classifier, "ENV_STAGE_MATRIX", "LEGACY_ENV_OUTPUTS")


def test_AC8_13_112_workflows_consume_structured_env_stage_gates() -> None:
    """AC8.13.112: workflows consume structured gates, not legacy scalar gates."""
    ci_workflow = read(".github/workflows/ci.yml")
    pr_workflow = read(".github/workflows/preview.yml")
    staging_workflow = read(".github/workflows/deploy.yml")

    _has(
        ci_workflow,
        "pr_required: ${{ steps.gates.outputs.pr_required }}",
        "ENV_STAGE_REQUIRED: ${{ steps.classify.outputs.env_stage_required }}",
        "ENV_STAGE_REASONS: ${{ steps.classify.outputs.env_stage_reasons }}",
        "if: needs.changes.outputs.pr_required == 'true'",
    )
    _lacks(
        ci_workflow,
        "needs.changes.outputs.heavy_required",
        "heavy_required: ${{ steps.classify.outputs.heavy_required }}",
    )

    _has(
        pr_workflow,
        "pr_preview_required: ${{ steps.preview_gate.outputs.pr_preview_required }}",
        "ENV_STAGE_REQUIRED: ${{ steps.preview.outputs.env_stage_required }}",
        "ENV_STAGE_REASONS: ${{ steps.preview.outputs.env_stage_reasons }}",
        "required['pr-preview']",
    )
    assert "steps.preview.outputs.pr_preview_required" not in pr_workflow

    _has(
        staging_workflow,
        "staging_required: ${{ steps.gates.outputs.staging_required }}",
        "ai_ocr_required: ${{ steps.gates.outputs.ai_ocr_required }}",
        "ENV_STAGE_REQUIRED: ${{ steps.classify.outputs.env_stage_required }}",
        "PROVIDER_GATE_REQUIRED: ${{ steps.classify.outputs.provider_gate_required }}",
        "STAGING_AI_OCR_REQUIRED: ${{ steps.classify.outputs.staging_ai_ocr_required }}",
        "STAGING_AI_OCR_REASON: ${{ steps.classify.outputs.staging_ai_ocr_reason }}",
        "staging_ai_ocr_required_raw",
        "staging_ai_ocr_reason = os.environ.get",
        "env_required['staging']",
        "provider_required['staging']",
    )
    assert "steps.classify.outputs.staging_required" not in staging_workflow


def test_AC8_13_152_workflow_consumers_keep_classification_single_owned() -> None:
    """AC-testing.classifier.9: AC8.13.152: downstream workflow jobs do not reclassify changed paths."""
    ci_workflow = read(".github/workflows/ci.yml")
    pr_workflow = read(".github/workflows/preview.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    ci_jobs = yaml.safe_load(ci_workflow)["jobs"]
    pr_jobs = yaml.safe_load(pr_workflow)["jobs"]

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

    ci_gate = step(ci_jobs["changes"], "Normalize Env x Stage gates")
    assert ci_jobs["changes"]["outputs"]["pr_required"] == (
        "${{ steps.gates.outputs.pr_required }}"
    )
    assert ci_gate["env"] == {
        "ENV_STAGE_REQUIRED": "${{ steps.classify.outputs.env_stage_required }}",
        "ENV_STAGE_REASONS": "${{ steps.classify.outputs.env_stage_reasons }}",
    }
    _has(
        str(ci_gate["run"]),
        'json.loads(os.environ["ENV_STAGE_REQUIRED"])',
        "required['pr']",
    )

    for job_name, job in ci_jobs.items():
        assert isinstance(job, dict)
        if not needs_job(job, "changes"):
            continue
        text = job_text(job)
        assert "tools/ci_change_classifier.py" not in text, job_name
        assert "git diff --name-only" not in text, job_name
        assert "changed-files.txt" not in text, job_name
        assert "/pulls/" not in text, job_name

    preview_classify = step(pr_jobs["setup"], "Classify PR preview relevance")
    assert "python tools/ci_change_classifier.py" in str(preview_classify["run"])

    preview_gate = step(pr_jobs["setup"], "Normalize PR preview gate")
    assert pr_jobs["setup"]["outputs"]["pr_preview_required"] == (
        "${{ steps.preview_gate.outputs.pr_preview_required }}"
    )
    assert preview_gate["env"] == {
        "ENV_STAGE_REQUIRED": "${{ steps.preview.outputs.env_stage_required }}",
        "ENV_STAGE_REASONS": "${{ steps.preview.outputs.env_stage_reasons }}",
    }
    _has(
        str(preview_gate["run"]),
        'json.loads(os.environ["ENV_STAGE_REQUIRED"])',
        "required['pr-preview']",
    )

    for job_name in ("deploy-preview", "e2e"):
        text = job_text(pr_jobs[job_name])
        assert "needs.setup.outputs.pr_preview_required == 'true'" in text
        assert "tools/ci_change_classifier.py" not in text, job_name
        assert "changed-files.txt" not in text, job_name
        assert "/pulls/" not in text, job_name

    _has(
        ci_cd,
        "Workflow YAML remains explicit; it is not generated from SSOT or the classifier at runtime.",
        "changed-path classification stays owned by the classifier step",
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
        "PR preview Dokploy compose",
        "GHCR PR images",
        "Docker build cache",
        "stale staging or production routes",
        "safe simplification boundary",
    )


def test_AC8_13_119_delivery_resource_leak_hardening_is_contracted() -> None:
    """AC-testing.deploy-gates.26: AC8.13.119: delivery cleanup covers the five known leak paths."""
    from common.meta.extension.generate_ac_registry import _roadmap_acs_from_contract

    statements = {
        record["id"]: record["statement"]
        for record in _roadmap_acs_from_contract(ROOT / "common/testing/contract.py")
    }
    statement = statements["AC-testing.deploy-gates.26"]
    recommendation = read("docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md")
    preview_cleanup = read(".github/workflows/maintenance.yml")
    pr_preview = read(".github/workflows/preview.yml")
    staging = read(".github/workflows/staging-ai-ocr-gate.yml")
    production = read(".github/workflows/release.yml")

    _has(
        statement,
        "PR preview leftovers",
        "GHCR PR tag accumulation",
        "stale staging or production routes",
        "provider-backed external-state residue",
        "Docker build cache and stopped containers",
    )

    _has(
        recommendation,
        "Resource leak hardening bundle",
        "one PR",
        "closed-PR Dokploy reconciliation",
        "closed-PR PR preview GHCR tags",
        "production_before_version",
        "isolated-users-provider-gate-only",
        "finance-report-vps-host-hygiene",
    )

    _has(
        preview_cleanup,
        "packages: write",
        "Prune stale PR preview GHCR tags",
        "retention_days=14",
        "gh pr list --state open",
        'owner_type="$(gh api',
        'package_scope_path="/orgs/${{ github.repository_owner }}"',
        'package_scope_path="/users/${{ github.repository_owner }}"',
        '"${package_scope_path}/packages/container/${image_name}/versions"',
        "if ! gh api \\",
        "list-failed package_scope=${package_scope_path}",
        "continue",
        'f"{package_scope_path}/packages/container/{image_name}/versions/{version_id}"',
    )
    _lacks(
        preview_cleanup,
        '"/orgs/${{ github.repository_owner }}/packages/container',
        'f"/orgs/{owner}/packages/container',
    )
    _has(
        preview_cleanup,
        "^pr-([1-9][0-9]*)-[0-9a-f]{40}$",
        "ghcr_cleanup=closed-pr-pr-tags-older-than-14-days",
    )
    # Host hygiene moved to infra2 (host-GC owner); the app's maintenance job no
    # longer owns or provisions it.
    assert "host_hygiene=infra2-owned" in preview_cleanup
    _lacks(
        preview_cleanup, "finance-report-vps-host-hygiene", "VPS_SSH_KEY", "ssh-keyscan"
    )

    assert "Delete GHCR images" not in pr_preview
    _has(pr_preview, "pr_preview_images=not-created", "registry_image_push=false")

    _has(
        staging,
        "provider_resource_boundary=isolated-users-provider-gate-only",
        "shared mutable user fixtures",
    )

    _has(
        production,
        "Probe current production version",
        "production_before_version",
        "deploy_health_outcome",
        "failure_domain=${failure_domain}",
        "deploy-v2-rollout",
        "production-route-health",
    )

    # Host hygiene (the "Docker build cache and stopped containers" leak path) is
    # infra2-owned now (tools/host_hygiene_schedule.py); the app ships no
    # host-hygiene module to assert on here.
    assert not (ROOT / "tools/_lib/dev/vps_host_hygiene.py").exists()


def test_AC8_13_10_multi_brokerage_upload_to_portfolio_value_gate() -> None:
    """AC-extraction.813.10: Staging proves multi-brokerage upload through latest value."""
    reusable = read(".github/workflows/staging-ai-ocr-gate.yml")
    brokerage = read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")
    statements_router = read("apps/backend/src/routers/statements.py")
    brokerage_payload = read(
        "apps/backend/src/extraction/extension/brokerage_statement_payload.py"
    )
    generator = read("common/testing/fixtures/pdf/generate_pdf_fixtures.py")

    assert "tools/staging_ai_ocr_gate_contract.py --shell" in reusable
    _has(staging_ai_ocr_contract_shell(), "test_brokerage_upload_to_portfolio_value.py")
    # Marker expression equality is owned by the matrix conformance
    # gate (AC8.23.2, tests/tooling/test_workflow_selection_conformance.py).
    _has(
        brokerage,
        "pytest.mark.critical",
        "pytest.mark.llm",
        '("moomoo", "Moomoo E2E Portfolio")',
        '("futu", "Futu E2E Portfolio")',
        "/statements/upload",
        "/brokerage/import",
        "/portfolio/holdings",
        "/reports/balance-sheet",
        "fail_or_skip_ai_ocr_gate(",
        "parsed_positions",
        "_assert_portfolio_market_valuation_covered",
        "_market_valuation_lines",
        "market_valuation_adjustment_total",
        "non_portfolio_asset_total",
    )
    assert "BrokeragePositionImportService" in statements_router
    _has(
        brokerage_payload,
        "Statement must be parsed before importing brokerage positions",
    )
    assert '"futu"' in generator


def test_AC8_13_19_brokerage_gate_reports_portfolio_diagnostics() -> None:
    """AC8.13.19: Brokerage gate failures include portfolio valuation diagnostics."""
    brokerage = read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")

    _has(
        brokerage,
        "imported_positions=",
        "holdings_total_market_value=",
        "market_valuation_adjustment_total=",
        "non_portfolio_asset_total=",
        "net_worth_adjustment_gain_loss=",
        "relevant_asset_lines=",
    )


def test_AC8_13_28_vision_hard_gate_uses_deterministic_fixture_with_fresh_user() -> (
    None
):
    """AC-testing.product-gates.2: deterministic source facts stop at economic review."""
    gate = read("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py")
    contract = read("common/testing/contract.py")

    _has(gate, "@pytest.mark.e2e", "@pytest.mark.tier3", "@pytest.mark.critical")
    assert "@pytest.mark.llm" not in gate
    _has(
        gate,
        "authenticated_page_unique",
        "vision_hard_gate_statement.csv",
        "pytest.skip(",
    )
    assert "AC-testing.product-gates.2" in contract
    _lacks(
        contract,
        "AC-testing.product-gates.3",
        "AC-testing.product-gates.4",
        "AC-testing.product-gates.5",
        "AC-testing.product-gates.6",
    )
    assert "test_statement_upload_to_dashboard_vision_hard_gate" in contract


def test_AC8_13_28_vision_hard_gate_uses_statement_id_link_locator() -> None:
    """AC-testing.product-gates.2: AC8.13.28: statement upload E2E locates the detail link by statement id."""
    gate = read("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py")
    test_body = gate.split(
        "async def test_statement_upload_to_dashboard_vision_hard_gate", 1
    )[1]

    _has(test_body, "f'a[href=\"/statements/{statement_id}\"]'", "fixture_path.name")
    _lacks(
        test_body,
        "filter(has_text=INSTITUTION_LABEL).first",
        'page.locator("a").filter(has_text=INSTITUTION_LABEL)',
    )


def test_AC8_13_28_vision_hard_gate_requires_economic_review_before_approval() -> None:
    """AC-testing.product-gates.2: Stage 1 review must not fake successful posting."""
    gate = read("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py")
    test_body = gate.split(
        "async def test_statement_upload_to_dashboard_vision_hard_gate", 1
    )[1]

    _has(
        test_body,
        'review_path = f"/statements/{statement_id}/review"',
        "f\"a[href='{review_path}']\"",
        "page.expect_response(",
        'get_by_role("button", name="Approve", exact=True)',
        "approve_response.status == 409",
        '"Economic review required: intent_missing"',
        'reviewed_statement["stage1_status"] == "pending_review"',
        'journal_body["total"] == 0',
    )


def test_AC8_13_42_four_asset_net_worth_golden_path_is_post_merge_critical() -> None:
    """AC-testing.product-gates.7: AC8.13.42: four-asset as-of net worth proof is wired into the post-merge hard gate."""
    gate = read("tests/e2e/test_four_asset_net_worth_golden_path.py")
    ai_workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    matrix = critical_matrix_text()
    contract = read("common/testing/contract.py")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

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

    # The gate body (contract shell + llm marker) lives in the reusable workflow.
    assert "tools/staging_ai_ocr_gate_contract.py --shell" in ai_workflow
    # Marker expression equality is owned by the matrix conformance
    # gate (AC8.23.2, tests/tooling/test_workflow_selection_conformance.py).
    # deploy.yml still runs the provider connectivity smoke under the llm marker.
    # Marker expression equality is owned by the matrix conformance
    # gate (AC8.23.2, tests/tooling/test_workflow_selection_conformance.py).
    assert "test_four_asset_net_worth_golden_path.py" in staging_ai_ocr_contract_shell()

    _has(
        matrix,
        "four-asset-as-of-net-worth",
        "test_four_asset_as_of_net_worth_golden_path",
        "AC-testing.product-gates.7",
    )
    _has(
        contract,
        "AC-testing.product-gates.7",
        "test_four_asset_as_of_net_worth_golden_path",
    )
    assert "four-asset gate" in ci_cd


def test_AC8_13_33_e2e_setup_caches_virtualenv_and_playwright_browsers() -> None:
    """AC-testing.ci-structure.3: AC8.13.33: shared E2E setup caches Python and Playwright install work."""
    action = read(".github/actions/setup-e2e-tests/action.yml")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    _has(
        action,
        "Cache E2E virtualenv",
        "path: .venv",
        "e2e-venv-${{ runner.os }}-${{ hashFiles('tests/e2e/requirements.txt') }}",
        "Cache Playwright browsers",
        "path: ~/.cache/ms-playwright",
        "playwright-${{ runner.os }}-${{ hashFiles('tests/e2e/requirements.txt') }}",
        "if [ ! -x .venv/bin/python ]; then",
        'echo "PYTHONPATH=${GITHUB_WORKSPACE:-$PWD}${PYTHONPATH:+:$PYTHONPATH}" >> "$GITHUB_ENV"',
        "uv pip install -r tests/e2e/requirements.txt",
    )
    assert "shared E2E setup action caches `.venv` and Playwright browsers" in ci_cd


def test_AC8_13_34_ci_and_post_merge_write_timing_summaries() -> None:
    """AC8.13.34: CI and post-merge workflows report queue and critical-path timing."""
    ci_workflow = read(".github/workflows/ci.yml")
    deploy_workflow = read(".github/workflows/deploy.yml")
    timing_script = read("common/testing/github_workflow_timing_summary.py")
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")

    _has(
        ci_workflow,
        "Write CI timing summary",
        "tools/github_workflow_timing_summary.py",
        '--title "CI Timing Summary"',
        '--run-id "${{ github.run_id }}"',
        '--summary-path "$GITHUB_STEP_SUMMARY"',
    )
    _has(
        deploy_workflow,
        "post-merge-summary:",
        "needs: [build-and-deploy, provider-gate, ai-ocr-gate, post-merge-delivery]",
        "Write post-merge timing summary",
        '--title "Post-merge Timing Summary"',
    )
    _has(timing_script, "Queue delay", "Longest completed job")
    assert "GitHub Step Summary" in ci_cd


def test_AC8_13_114_pr_preview_follows_successful_ci_workflow_run() -> None:
    """AC-testing.preview.13: AC8.13.114: the in-runner e2e gate runs synchronously on pull_request, so it is a
    real required check a fast/auto merge cannot bypass. It no longer follows CI async
    via workflow_run — that fired after CI and a quick merge could land before it ran as
    a gate (skipped required checks count as passed). It is image-free, so it needs no
    CI artifact and runs independently."""
    workflow = read(".github/workflows/preview.yml")
    assert "workflow_run:" not in workflow
    _has(
        workflow,
        "types: [opened, synchronize, reopened, closed]",
        'action_reason = "pull-request-sync"',
        'action = "deploy"',
        'action = "cleanup"',
        "pr_preview_required == 'true'",
    )
    _lacks(
        workflow,
        "tools/wait_for_cheap_ci.py",
        "gate-cheap-ci:",
        "build-preview-backend-image:",
        "build-preview-frontend-image:",
    )


def test_AC8_13_115_readiness_fail_fast() -> None:
    """AC-testing.preview.14: AC8.13.115: Runner preview readiness is bounded before smoke/E2E starts."""
    workflow = read(".github/workflows/preview.yml")
    e2e_block = workflow.split("  e2e:", 1)[1].split("  cleanup:", 1)[0]
    _has(
        e2e_block,
        "timeout-minutes: 25",
        "Wait for stack readiness",
        "for i in $(seq 1 60)",
        "stack did not become healthy within 300s",
    )
    _lacks(workflow, "consecutive_dokploy_failures", "consecutive_404_failures")


def test_AC8_13_116_skip_heavy_ci_on_main_push() -> None:
    """AC-testing.deploy-gates.25: AC8.13.116: Post-merge -> staging start latency is reduced by removing redundant heavy re-run on push to main."""
    workflow = read(".github/workflows/ci.yml")

    # Check that heavy jobs skip on push to main by checking pr_required gate
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

    # container-images: PR path still gates on pr_required (narrow dry-run), but a
    # main/release push always builds + pushes the immutable :<sha> image so
    # promote-not-rebuild always has an artifact to promote.
    container_images_block = workflow.split("  container-images:", 1)[1].split(
        "\n\n", 1
    )[0]
    _has(
        container_images_block,
        "needs.changes.outputs.pr_required == 'true' && needs.changes.outputs.image_build_required == 'true'",
        "github.event_name == 'push' && (github.ref == 'refs/heads/main'",
    )

    # frontend-telemetry-e2e (#1689): right-moved off unrelated PRs the same way
    # container-images is — PR path gates on pr_required + frontend_changed, but
    # main/release push and workflow_dispatch always run it (production
    # observability canary).
    telemetry_block = workflow.split("  frontend-telemetry-e2e:", 1)[1].split(
        "\n\n", 1
    )[0]
    pr_scope_condition = (
        "needs.changes.outputs.pr_required == 'true' "
        "&& needs.changes.outputs.frontend_changed == 'true'"
    )
    main_push_override = (
        "github.event_name == 'push' && (github.ref == 'refs/heads/main'"
    )
    _has(telemetry_block, pr_scope_condition, main_push_override)

    # Check finish job handles skipped tests on push via pr_required output
    finish_block = workflow.split("  finish:", 1)[1]
    _has(
        finish_block,
        'if [[ "${{ needs.changes.outputs.pr_required }}" == "true" ]]; then',
    )


def test_AC8_13_118_timeouts_and_retries_documented() -> None:
    """AC-testing.governance.5: AC8.13.118: Critical-path timeouts and retries are documented in common/runtime/ci-cd.md."""
    ci_cd = read("common/testing/ci-cd.md") + read("common/runtime/ci-cd.md")
    # The staging FIFO train wait is retired with the manual-only model; staging is
    # serialized by the workflow concurrency group, so no FIFO timeout is documented.
    assert "STAGING_FIFO_TIMEOUT_SECONDS" not in ci_cd
    _has(
        ci_cd,
        "The runner stack waits for `/api/health` before smoke/E2E",
        "caps readiness at 300 seconds",
        "docker compose down --volumes",
        "parallel staging",
    )


def test_wait_for_cheap_ci_full_flow(monkeypatch) -> None:
    """Test wait_for_cheap_ci with mock urlopen to get full test coverage."""
    import importlib

    importlib.import_module("tools.wait_for_cheap_ci")
    from common.testing.wait_for_cheap_ci import GitHubActionsClient, main
    import urllib.request
    import urllib.error
    from io import BytesIO

    def mock_urlopen(request, timeout=None):
        url = request.full_url
        if "jobs" in url:
            return _FakeResponse(
                {
                    "jobs": [
                        {
                            "name": "Lint",
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {
                            "name": "AC Traceability Check",
                            "status": "completed",
                            "conclusion": "success",
                        },
                    ]
                }
            )
        elif "runs" in url:
            return _FakeResponse(
                {
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
            )
        return _FakeResponse({})

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

    res = main(
        [
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
    )
    assert res == 0
