from pathlib import Path
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def critical_post_merge_llm_proof_files() -> list[str]:
    matrix = yaml.safe_load(read("docs/ssot/critical-proof-matrix.yaml"))
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
    proof_matrix = yaml.safe_load(read("docs/ssot/critical-proof-matrix.yaml"))
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
    assert 'filter(has_text=INSTITUTION_LABEL).first' not in test_body
    assert '"parsed"' in test_body
    assert "# === AC8.13.3: Detail page shows transactions ===" in test_body
    assert "Transactions" in test_body
    assert "# === AC8.13.4: Start Review" in test_body
    assert "approved" in test_body
    assert "# === AC8.13.5: Balance sheet report loads ===" in test_body
    assert "/reports/balance-sheet" in test_body


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
    """AC8.13.13: Staging deploy does not cancel running main validations."""
    workflow = read(".github/workflows/staging-deploy.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert (
        "group: staging-post-merge-${{ github.event.workflow_run.head_branch || github.ref_name }}"
        in workflow
    )
    assert "cancel-in-progress: false" in workflow
    assert "timeout-minutes: 75" in workflow
    assert "timeout-minutes: 22" in workflow
    assert "run_timed_phase()" in workflow
    assert "[phase:start]" in workflow
    assert "[phase:end]" in workflow
    assert "duration=%ss" in workflow
    assert 'run_timed_phase "Phase 1: Smoke Check (Shell)"' in workflow
    assert 'run_timed_phase "Phase 2: Core Flow Validation (Python)"' in workflow
    assert "does not cancel a running post-merge lane" in ci_cd
    assert "latest pending post-merge run is retained" in ci_cd
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
    assert "needs: [build-and-deploy]" in deploy_workflow
    assert "name: Staging AI/OCR Gate" in deploy_workflow
    assert "commit_full_sha: ${{ steps.get_sha.outputs.full_sha }}" in deploy_workflow
    assert "ref: ${{ needs.build-and-deploy.outputs.commit_full_sha }}" in deploy_workflow
    assert "PARSING_TIMEOUT_MS: 480000" in deploy_workflow
    assert (
        "EXPECTED_SHA: ${{ needs.build-and-deploy.outputs.commit_sha }}"
        in deploy_workflow
    )
    assert 'run_timed_phase "Staging AI/OCR Gate' in deploy_workflow
    assert "tools/staging_ai_ocr_gate_contract.py --shell" in deploy_workflow
    assert 'pytest "${STAGING_AI_OCR_TESTS[@]}"' in deploy_workflow
    assert '-v -m "llm"' in deploy_workflow
    assert (
        '-v -m "llm"'
        not in deploy_workflow.split("name: End-to-End Tests", 1)[1].split(
            "ai-ocr-gate:", 1
        )[0]
    )
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
    assert "test-results/pr-preview-e2e.xml" in pr_preview
    assert "ci-context/pr-preview-context.txt" in pr_preview
    assert "deploy_outcome=${{ steps.deploy.outcome }}" in pr_preview
    assert "e2e_outcome=${{ steps.e2e_tests.outcome }}" in pr_preview

    assert "staging-deploy-test-context" in staging
    assert "test-results/staging-core-e2e.xml" in staging
    assert "ci-context/staging-deploy-context.txt" in staging
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


def test_AC8_13_51_staging_deploy_starts_after_successful_ci_workflow_run() -> None:
    """AC8.13.51: Staging deploy is triggered by successful main CI workflow_run."""
    workflow = read(".github/workflows/staging-deploy.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "workflow_run:" in workflow
    assert 'workflows: ["CI"]' in workflow
    assert "types: [completed]" in workflow
    assert "branches: [main]" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "ref: ${{ github.event.workflow_run.head_sha || github.sha }}" in workflow
    assert "Wait for matching CI success" not in workflow
    assert "wait_for_github_ci.py" not in workflow
    assert "workflow_run event after the matching main CI run succeeds" in ci_cd
    assert "does not poll or wait for CI inside the deploy job" in ci_cd


def test_AC8_13_55_post_merge_staging_is_scoped_to_deploy_relevant_paths() -> None:
    """AC8.13.55: Post-merge staging only runs for deploy-relevant changes."""
    workflow = read(".github/workflows/staging-deploy.yml")
    classifier = read("common/ci/change_classifier.py")
    classifier_tests = read("tests/tooling/test_ci_change_classifier.py")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "classify-staging:" in workflow
    assert "name: Classify Staging Relevance" in workflow
    assert "fetch-depth: 0" in workflow
    assert "git diff --name-only" in workflow
    assert "tools/ci_change_classifier.py" in workflow
    assert (
        "staging_required: ${{ steps.classify.outputs.staging_required }}" in workflow
    )
    assert "staging_reason: ${{ steps.classify.outputs.staging_reason }}" in workflow
    assert "needs: [classify-staging]" in workflow
    assert "needs.classify-staging.outputs.staging_required == 'true'" in workflow
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
    assert (
        "Automatic staging deploys are scoped to runtime app, deploy, root E2E, dependency, Dockerfile/config, staging workflow, toolchain, or infra-submodule changes"
        in ci_cd
    )
    assert (
        "App test-only changes, documentation, project archive, AC traceability, and other tooling-only changes keep CI/AC gates but do not consume the staging singleton"
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
    assert "push: false" in workflow
    assert "Production mutation skipped" in workflow
    dry_run_section = workflow.split("dry-run:", 1)[1].split("\n  deploy:", 1)[0]
    assert "environment:" not in dry_run_section
    assert "dokploy_deploy.sh" not in dry_run_section
    assert "inputs.dry_run" in workflow.split("deploy:", 1)[1].split("steps:", 1)[0]
    assert "Production release dry-run" in ci_cd
    assert "without changing Dokploy or production tags" in ci_cd


def test_AC8_13_16_ci_change_classification_and_frontend_cache() -> None:
    """AC8.13.16: CI skips heavy jobs for lightweight changes and caches npm."""
    workflow = read(".github/workflows/ci.yml")
    pr_workflow = read(".github/workflows/pr-test.yml")
    classifier = read("common/ci/change_classifier.py")
    ci_cd = read("docs/ssot/ci-cd.md")
    environments = read("docs/ssot/environments.md")

    assert "name: Classify Changes" in workflow
    assert "heavy_required: ${{ steps.classify.outputs.heavy_required }}" in workflow
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
    assert "if: needs.changes.outputs.heavy_required == 'true'" in workflow
    assert (
        "pr_preview_required: ${{ steps.preview.outputs.pr_preview_required }}"
        in pr_workflow
    )
    assert "name: Classify PR preview relevance" in pr_workflow
    assert "needs.setup.outputs.pr_preview_required == 'true'" in pr_workflow
    assert "name: AC Traceability Check" in workflow
    assert (
        "needs: [changes, backend, backend-integration, backend-e2e-tier1, frontend, container-images, lint, tooling-coverage, unified-coverage, ac-traceability]"
        in workflow
    )
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
        assert 'FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: "true"' in workflow, workflow_path.name

    ci_cd = read("docs/ssot/ci-cd.md")
    assert "FORCE_JAVASCRIPT_ACTIONS_TO_NODE24" in ci_cd
    assert "GitHub JavaScript action runtime is explicitly validated on Node 24" in ci_cd


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

    backend_build_blocks = re.findall(
        r"- name: Build Backend(?: Image Without Push)?\n(?:(?!\n      - name:).)*",
        workflow,
        flags=re.S,
    )
    assert len(backend_build_blocks) == 2
    for block in backend_build_blocks:
        assert "context: ./apps/backend" in block
        assert "build-args:" in block
        assert "GIT_COMMIT_SHA=${{ steps.version.outputs.tag }}" in block

    config_hash_update = (
        'new_env=$(update_env_var "$new_env" "IAC_CONFIG_HASH" '
        '"deploy-${IMAGE_TAG}-$(date +%s)")'
    )
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

    assert (
        "group: staging-post-merge-${{ github.event.workflow_run.head_branch || github.ref_name }}"
        in workflow
    )
    assert "cancel-in-progress: false" in workflow
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
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
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


def test_AC8_13_21_post_merge_ai_ocr_requires_successful_ci_workflow_run() -> None:
    """AC8.13.21: Provider-backed post-merge AI/OCR runs only after successful main CI."""
    workflow = read(".github/workflows/staging-deploy.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "workflow_run:" in workflow
    assert 'workflows: ["CI"]' in workflow
    assert "types: [completed]" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "ref: ${{ github.event.workflow_run.head_sha || github.sha }}" in workflow
    assert "Wait for matching CI success" not in workflow
    assert "wait_for_github_ci.py" not in workflow
    assert (
        "successful-main-CI `workflow_run` trigger before spending provider quota"
        in ci_cd
    )


def test_AC8_13_22_staging_deploy_starts_from_successful_ci_before_building() -> None:
    """AC8.13.22: Staging deploy builds only after successful main CI workflow_run."""
    workflow = read(".github/workflows/staging-deploy.yml")

    assert "actions: read" in workflow
    assert "contents: read" in workflow
    assert "packages: write" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "Wait for matching CI success" not in workflow
    assert workflow.index(
        "ref: ${{ github.event.workflow_run.head_sha || github.sha }}"
    ) < workflow.index("Build and push Backend")
    assert workflow.index(
        "ref: ${{ github.event.workflow_run.head_sha || github.sha }}"
    ) < workflow.index("Deploy to Staging")


def test_AC8_13_36_post_merge_reuses_sha_tagged_staging_images() -> None:
    """AC8.13.36: Main CI builds SHA images and staging reuses them after CI passes."""
    ci_workflow = read(".github/workflows/ci.yml")
    deploy_workflow = read(".github/workflows/staging-deploy.yml")
    check_script = read("tools/_lib/shell/check_ghcr_image_tag.sh")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "container-images:" in ci_workflow
    assert "name: Build Staging Images" in ci_workflow
    assert "needs: [changes]" in ci_workflow
    assert "needs.changes.outputs.heavy_required == 'true'" in ci_workflow
    assert (
        "if: github.event_name == 'push' && github.ref == 'refs/heads/main'"
        in ci_workflow
    )
    assert "packages: write" in ci_workflow
    assert "Build Backend SHA image" in ci_workflow
    assert "Build Frontend SHA image" in ci_workflow
    assert (
        "push: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}"
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
    assert "github.event.workflow_run.conclusion == 'success'" in deploy_workflow
    assert deploy_workflow.index(
        "ref: ${{ github.event.workflow_run.head_sha || github.sha }}"
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
    assert "retags those immutable images as `staging`" in ci_cd
    assert "falls back to building only the missing image" in ci_cd


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

    assert "if: needs.changes.outputs.heavy_required == 'true'" in container_block
    assert (
        "if: github.event_name == 'push' && github.ref == 'refs/heads/main'"
        in login_block
    )
    assert container_block.count("uses: docker/build-push-action@v5") == 2
    assert (
        container_block.count(
            "push: ${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}"
        )
        == 2
    )
    assert "Build Backend SHA image" in container_block
    assert "Build Frontend SHA image" in container_block
    assert "Container image validation failed" in finish_block
    assert "PR CI dry-runs staging image builds before merge" in ci_cd
    assert "Main push CI is the only path that pushes SHA-tagged images" in ci_cd


def test_AC8_13_89_pr_preview_builds_pr_tagged_images_before_deploy() -> None:
    """AC8.13.89: PR previews push the exact PR image tag before Dokploy deploy."""
    workflow = read(".github/workflows/pr-test.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    deploy_block = workflow.split("  deploy:", 1)[1].split("  cleanup:", 1)[0]

    assert "packages: write" in deploy_block
    assert "Log in to Container registry" in deploy_block
    assert "docker/login-action@v3" in deploy_block
    assert "Set up Docker Buildx" in deploy_block
    assert "Build and push Backend PR preview image" in deploy_block
    assert "Build and push Frontend PR preview image" in deploy_block
    assert deploy_block.index("Build and push Backend PR preview image") < deploy_block.index(
        "Deploy preview lifecycle"
    )
    assert deploy_block.index("Build and push Frontend PR preview image") < deploy_block.index(
        "Deploy preview lifecycle"
    )
    assert "push: true" in deploy_block
    assert (
        "${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}-backend:pr-${{ needs.setup.outputs.pr_number }}"
        in deploy_block
    )
    assert (
        "${{ env.REGISTRY }}/${{ env.IMAGE_PREFIX }}-frontend:pr-${{ needs.setup.outputs.pr_number }}"
        in deploy_block
    )
    assert "GIT_COMMIT_SHA=${{ github.sha }}" in deploy_block
    assert "NEXT_PUBLIC_API_URL=https://report-pr-${{ needs.setup.outputs.pr_number }}.${{ needs.setup.outputs.internal_domain }}" in deploy_block
    assert "PR preview deploy builds and pushes PR-numbered backend and frontend images before invoking Dokploy" in ci_cd


def test_AC8_13_23_post_merge_deploy_and_ai_ocr_are_one_serial_unit() -> None:
    """AC8.13.23: Deploy health and provider gate share one serialized workflow unit."""
    deploy_workflow = read(".github/workflows/staging-deploy.yml")
    ai_workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert (
        "group: staging-post-merge-${{ github.event.workflow_run.head_branch || github.ref_name }}"
        in deploy_workflow
    )
    assert "cancel-in-progress: false" in deploy_workflow
    assert "ai-ocr-gate:" in deploy_workflow
    assert "needs: [build-and-deploy]" in deploy_workflow
    assert "commit_full_sha: ${{ steps.get_sha.outputs.full_sha }}" in deploy_workflow
    assert "ref: ${{ needs.build-and-deploy.outputs.commit_full_sha }}" in deploy_workflow
    assert (
        "EXPECTED_SHA: ${{ needs.build-and-deploy.outputs.commit_sha }}"
        in deploy_workflow
    )
    assert 'workflows: ["Deploy Staging"]' not in ai_workflow
    assert "same serialized post-merge workflow unit" in ci_cd
    assert "test code, audit context, and deployed image under validation aligned" in ci_cd
    assert (
        "newer deploy cannot overwrite staging while an older automatic AI/OCR gate is running"
        in ci_cd
    )


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


def test_AC8_13_25_backend_and_traceability_do_not_wait_for_lint() -> None:
    """AC8.13.25: Independent CI jobs start without waiting for lint."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    backend_block = workflow.split("  backend:", 1)[1].split("  frontend:", 1)[0]
    traceability_block = workflow.split("  ac-traceability:", 1)[1].split(
        "  finish:", 1
    )[0]

    assert "needs: [changes]" in backend_block
    assert "needs: [changes, lint]" not in backend_block
    assert (
        "needs: [changes, backend-integration, backend-e2e-tier1, lint]"
        not in backend_block
    )
    assert "needs: [lint]" not in traceability_block
    assert "Standalone lint and AC traceability start immediately" in ci_cd
    assert "without waiting for behavior-only backend gates" in ci_cd


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

    assert "needs:" not in lint_block.split("steps:", 1)[0]
    assert "needs:" not in traceability_block.split("steps:", 1)[0]
    assert "Standalone gates start immediately" in ci_cd
    assert "Changes-dependent fast feedback jobs start after `changes` only" in ci_cd
    assert "Behavior-only backend gates run in parallel" in ci_cd


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
    )[1].split(
        "  ac-traceability:", 1
    )[0]

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
        "if: github.event_name == 'push' && github.ref == 'refs/heads/main'"
        in workflow
    )
    assert "Coveralls upload LCOV files are line-only" in coverage
    assert "Coveralls is a main-branch external reporting baseline only" in coverage
    assert "Coverage scope is deny-list based within each governed source root" in ci_cd
    assert "strip branch records before upload" in ci_cd


def test_AC8_13_43_failed_ci_workflow_run_reports_no_deploy_diagnostic() -> None:
    """AC8.13.43: Failed main CI reports staging state without deploying."""
    workflow = read(".github/workflows/staging-deploy.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "Probe current staging version" in workflow
    assert "id: staging_before" in workflow
    assert "https://report-staging.zitian.party/api/health" in workflow
    assert "Current Staging Before Deploy" in workflow
    assert "ci-not-success-summary:" in workflow
    assert "name: CI Did Not Pass" in workflow
    assert "github.event.workflow_run.conclusion != 'success'" in workflow
    assert "Staging Deploy Skipped Before VPS Changes" in workflow
    assert "main CI workflow_run did not succeed" in workflow
    assert (
        "No image promotion, Dokploy change, smoke test, or AI/OCR validation ran."
        in workflow
    )
    assert "id: wait_ci" not in workflow
    assert "wait_for_github_ci.py" not in workflow
    assert "Failed, cancelled, or timed-out main CI runs do not promote images" in ci_cd
    assert "does not poll or wait for CI inside the deploy job" in ci_cd


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
    """AC8.13.46: PR preview non-LLM E2E mirrors staging strictness and workers."""
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
        assert 'pytest tests/e2e -v -m "(smoke or e2e) and not llm" -n 4' in block

    assert "PR preview non-LLM E2E mirrors the staging non-LLM command shape" in ci_cd


def test_AC8_13_38_pr_preview_dokploy_responses_are_not_logged() -> None:
    """AC8.13.38: PR preview Dokploy API responses are captured, not logged raw."""
    preview = read(".github/workflows/pr-test.yml")
    ci_cd = read("docs/ssot/ci-cd.md")
    lifecycle = read("tools/_lib/dev/pr_preview_lifecycle.py")

    assert (
        "PR preview Dokploy API responses are parsed for required fields only" in ci_cd
    )
    assert "Deploy preview lifecycle" in preview
    assert "Cleanup preview lifecycle" in preview
    assert "Rollback on E2E Failure" in preview
    assert "--action delete" in preview
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
    """AC8.13.72: staging proof checks health git_sha, not just Dokploy trigger."""
    workflow = read(".github/workflows/staging-deploy.yml")
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
    assert '"https://report-staging.zitian.party/api/health"' in deploy_block
    assert '"$IMAGE_TAG"' in deploy_block
    assert (
        'actual_sha=$(echo "$health_response" | jq -r \'.git_sha // .version // ""\')'
        in health_check
    )
    assert "Git SHA Mismatch" in health_check
    assert "exit 1" in health_check


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


def test_AC8_13_10_multi_brokerage_upload_to_portfolio_value_gate() -> None:
    """AC8.13.10: Staging proves multi-brokerage upload through latest value."""
    workflow = read(".github/workflows/staging-deploy.yml")
    brokerage = read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")
    statements_router = read("apps/backend/src/routers/statements.py")
    generator = read("tools/_lib/pdf_fixtures/generate_pdf_fixtures.py")

    assert "tools/staging_ai_ocr_gate_contract.py --shell" in workflow
    assert "test_brokerage_upload_to_portfolio_value.py" in staging_ai_ocr_contract_shell()
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
        "/reports/cash-flow",
        '"total_income": Decimal("5600.00")',
        '"total_expenses": Decimal("5600.00")',
        '"net_income": Decimal("0.00")',
        '"No pending matches"',
        '"No pending transfers found."',
    ):
        assert token in gate
    assert "upload-to-dashboard vision hard gate" in ci_cd


def test_AC8_13_42_four_asset_net_worth_golden_path_is_post_merge_critical() -> None:
    """AC8.13.42: four-asset as-of net worth proof is wired into the post-merge hard gate."""
    gate = read("tests/e2e/test_four_asset_net_worth_golden_path.py")
    deploy_workflow = read(".github/workflows/staging-deploy.yml")
    ai_workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    matrix = read("docs/ssot/critical-proof-matrix.yaml")
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
    assert "uv pip install -r tests/e2e/requirements.txt" in action
    assert "shared E2E setup action caches `.venv` and Playwright browsers" in ci_cd


def test_AC8_13_34_ci_and_post_merge_write_timing_summaries() -> None:
    """AC8.13.34: CI and post-merge workflows report queue and critical-path timing."""
    ci_workflow = read(".github/workflows/ci.yml")
    deploy_workflow = read(".github/workflows/staging-deploy.yml")
    timing_script = read("tools/_lib/ci/github_workflow_timing_summary.py")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "Write CI timing summary" in ci_workflow
    assert "tools/github_workflow_timing_summary.py" in ci_workflow
    assert '--title "CI Timing Summary"' in ci_workflow
    assert '--run-id "${{ github.run_id }}"' in ci_workflow
    assert '--summary-path "$GITHUB_STEP_SUMMARY"' in ci_workflow
    assert "post-merge-summary:" in deploy_workflow
    assert "needs: [classify-staging, build-and-deploy, ai-ocr-gate]" in deploy_workflow
    assert "Write post-merge timing summary" in deploy_workflow
    assert '--title "Post-merge Timing Summary"' in deploy_workflow
    assert "Queue delay" in timing_script
    assert "Longest completed job" in timing_script
    assert "GitHub Step Summary" in ci_cd
