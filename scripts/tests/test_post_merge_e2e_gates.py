from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


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
    test_body = upload.split("async def test_statement_upload_full_flow", 1)[1].split("@pytest.mark.e2e", 1)[0]

    assert "AI/OCR readiness gate" in test_body
    assert "fail_or_skip_ai_ocr_gate(" in test_body
    assert "statement=statement" in test_body
    assert '"rejected"' not in test_body.split("assert status in", 1)[1]


def test_AC8_13_11_health_check_diagnoses_staging_api_route_404() -> None:
    """AC8.13.11: Staging health 404 reports API route diagnostics."""
    health_check = read("scripts/health_check.sh")

    assert "print_404_route_diagnostics" in health_check
    assert "Traefik API route is missing or shadowed" in health_check
    assert 'probe_route "API ping" "$APP_BASE_URL/api/ping"' in health_check
    assert 'probe_route "Frontend shell" "$APP_BASE_URL/"' in health_check
    assert '[[ "$http_code" == "404" ]]' in health_check


def test_AC8_13_12_ai_ocr_gate_failure_includes_statement_context() -> None:
    """AC8.13.12: AI/OCR gate failures include statement validation context."""
    conftest = read("tests/e2e/conftest.py")
    journey = read("tests/e2e/test_statement_full_journey.py")
    upload = read("tests/e2e/test_statement_upload_e2e.py")
    brokerage = read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")

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


def test_AC8_13_13_staging_deploy_fast_fail_guardrails() -> None:
    """AC8.13.13: Staging deploy does not cancel running main validations."""
    workflow = read(".github/workflows/staging-deploy.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "group: staging-deploy" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "timeout-minutes: 30" in workflow
    assert "timeout-minutes: 22" in workflow
    assert "run_timed_phase()" in workflow
    assert "[phase:start]" in workflow
    assert "[phase:end]" in workflow
    assert "duration=%ss" in workflow
    assert 'run_timed_phase "Phase 1: Smoke Check (Shell)"' in workflow
    assert 'run_timed_phase "Phase 2: Core Flow Validation (Python)"' in workflow
    assert "does not cancel a running deploy" in ci_cd
    assert "latest pending deploy is retained" in ci_cd
    assert "30-minute job timeout" in ci_cd
    assert "22-minute E2E step timeout" in ci_cd


def test_AC8_13_14_staging_ai_ocr_gate_is_separate_workflow() -> None:
    """AC8.13.14: Provider-backed AI/OCR gate runs outside deploy health."""
    deploy_workflow = read(".github/workflows/staging-deploy.yml")
    ai_workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "name: Staging AI/OCR Gate" in ai_workflow
    assert 'workflows: ["Deploy Staging"]' in ai_workflow
    assert "github.event.workflow_run.conclusion == 'success'" in ai_workflow
    assert "workflow_dispatch:" in ai_workflow
    assert "group: staging-ai-ocr" in ai_workflow
    assert "cancel-in-progress: false" in ai_workflow
    assert "timeout-minutes: 22" in ai_workflow
    assert "STRICT_E2E_GATES: true" in ai_workflow
    assert "PARSING_TIMEOUT_MS: 480000" in ai_workflow
    assert "EXPECTED_SHA: ${{ steps.expected_sha.outputs.short_sha }}" in ai_workflow
    assert "test_version_check.py" in ai_workflow
    assert 'run_timed_phase "Staging AI/OCR Gate' in ai_workflow
    assert "Wait for matching CI success" in ai_workflow
    assert '--workflow "CI"' in ai_workflow
    assert "test_statement_full_journey.py" in ai_workflow
    assert "test_brokerage_upload_to_portfolio_value.py" in ai_workflow
    assert "test_statement_upload_e2e.py" in ai_workflow
    assert '-v -m "llm"' in ai_workflow
    assert '-v -m "llm"' not in deploy_workflow
    assert "Basic staging deploy feedback no longer waits on provider-backed OCR parsing" in ci_cd
    assert "Staging AI/OCR Gate" in ci_cd


def test_AC8_13_16_ci_change_classification_and_frontend_cache() -> None:
    """AC8.13.16: CI skips heavy jobs for lightweight changes and caches npm."""
    workflow = read(".github/workflows/ci.yml")
    classifier = read("scripts/ci_change_classifier.py")
    ci_cd = read("docs/ssot/ci-cd.md")
    environments = read("docs/ssot/environments.md")

    assert "name: Classify Changes" in workflow
    assert "heavy_required: ${{ steps.classify.outputs.heavy_required }}" in workflow
    assert "scripts/ci_change_classifier.py" in workflow
    assert "--changed-files changed-files.txt" in workflow
    assert '"docs/"' in classifier
    assert '".github/ISSUE_TEMPLATE/"' in classifier
    assert '".github/workflows/docs.yml"' in classifier
    assert "path.endswith" not in workflow
    assert "path.endswith" not in classifier
    assert "runtime-or-ci-paths-changed" in classifier
    assert "lightweight-docs-or-docs-workflow-only" in classifier
    assert "needs: [changes, lint]" in workflow
    assert "if: needs.changes.outputs.heavy_required == 'true'" in workflow
    assert "name: AC Traceability Check" in workflow
    assert "needs: [changes, backend, frontend, lint, unified-coverage, ac-traceability]" in workflow
    assert "Heavy backend/frontend/coverage jobs skipped for lightweight changes." in workflow
    assert "uses: actions/setup-node@v4" in workflow
    assert "cache: npm" in workflow
    assert "cache-dependency-path: apps/frontend/package-lock.json" in workflow
    assert "run: npm ci" in workflow
    assert "run: npm install" not in workflow
    assert "PR vs Main CI Responsibilities" in ci_cd
    assert "Lightweight changes do not repeat the heavy path" in ci_cd
    assert "Frontend dependency installation uses `actions/setup-node@v4`" in ci_cd
    assert "Markdown outside the documented lightweight trees is treated as heavy" in ci_cd
    assert "lightweight documentation" in environments.lower()


def test_AC8_13_17_ac_traceability_runs_registry_generation_check() -> None:
    """AC8.13.17: AC traceability checks registry generation before audit output."""
    workflow = read(".github/workflows/ci.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "uv run --with pyyaml python scripts/generate_ac_registry.py --check" in workflow
    assert "uv run --with pyyaml python scripts/build_ac_traceability.py --check" in workflow
    assert workflow.index("scripts/generate_ac_registry.py --check") < workflow.index(
        "scripts/build_ac_traceability.py --check"
    )
    assert "without rewriting historical registry descriptions" in ci_cd


def test_AC8_13_9_production_release_runs_prod_safe_e2e_smoke() -> None:
    """AC8.13.9: Production release runs prod-safe read-only E2E smoke."""
    workflow = read(".github/workflows/production-release.yml")
    prod_smoke = read("tests/e2e/test_production_readonly_smoke.py")

    assert "Setup E2E Tests" in workflow
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


def test_AC8_13_7_staging_runs_llm_e2e_serially_with_glm_5_1() -> None:
    """AC8.13.7: Post-merge AI/OCR E2E is a single-provider-access gate."""
    workflow = read(".github/workflows/staging-deploy.yml")
    ai_workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    pr_workflow = read(".github/workflows/pr-test.yml")
    journey = read("tests/e2e/test_statement_full_journey.py")
    brokerage = read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")
    upload = read("tests/e2e/test_statement_upload_e2e.py")
    deploy_script = read("scripts/dokploy_deploy.sh")

    assert "group: staging-deploy" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "workflow_dispatch:" in workflow
    assert "STAGING_E2E_PRIMARY_MODEL: glm-5.1" in workflow
    assert "STAGING_E2E_OCR_MODEL: glm-4.6v" in workflow
    assert "STAGING_E2E_VISION_MODEL: glm-4.6v" in workflow
    assert "DEPLOY_PRIMARY_MODEL_OVERRIDE: ${{ env.STAGING_E2E_PRIMARY_MODEL }}" in workflow
    assert "DEPLOY_OCR_MODEL_OVERRIDE: ${{ env.STAGING_E2E_OCR_MODEL }}" in workflow
    assert "DEPLOY_VISION_MODEL_OVERRIDE: ${{ env.STAGING_E2E_VISION_MODEL }}" in workflow
    assert 'update_env_var "$new_env" "PRIMARY_MODEL" "$DEPLOY_PRIMARY_MODEL_OVERRIDE"' in deploy_script
    assert 'update_env_var "$new_env" "OCR_MODEL" "$DEPLOY_OCR_MODEL_OVERRIDE"' in deploy_script
    assert 'update_env_var "$new_env" "VISION_MODEL" "$DEPLOY_VISION_MODEL_OVERRIDE"' in deploy_script
    assert 'update_env_var "$new_env" "IAC_CONFIG_HASH" "models-${IMAGE_TAG}-$(date +%s)"' in deploy_script
    assert '-m "(smoke or e2e) and not llm" -n 4' in workflow
    assert "PARSING_TIMEOUT_MS: 480000" in ai_workflow
    assert "Wait for matching CI success" in ai_workflow
    assert "test_brokerage_upload_to_portfolio_value.py" in ai_workflow
    assert '-v -m "llm"' in ai_workflow
    assert "@pytest.mark.llm" in journey
    assert "@pytest.mark.llm" in brokerage
    assert upload.count("@pytest.mark.llm") >= 2
    assert 'echo "ZAI_API_KEY="' in pr_workflow
    assert 'echo "AI_BASE_URL=https://api.z.ai/api/coding/paas/v4"' in pr_workflow
    assert 'echo "OCR_MODEL=glm-4.6v"' in pr_workflow
    assert 'echo "AI_JSON_TIMEOUT_SECONDS=360"' in pr_workflow
    assert 'echo "AI_JSON_MAX_TOKENS=8192"' in pr_workflow
    assert 'echo "AI_JSON_DISABLE_THINKING=true"' in pr_workflow
    assert "https://api.z.ai/api/coding/paas/v4" in read("docs/ssot/ci-cd.md")
    assert '-m "(smoke or e2e) and not llm"' in pr_workflow
    assert '-m "smoke or e2e"' not in pr_workflow


def test_AC8_13_10_multi_brokerage_upload_to_portfolio_value_gate() -> None:
    """AC8.13.10: Staging proves multi-brokerage upload through latest value."""
    workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    brokerage = read("tests/e2e/test_brokerage_upload_to_portfolio_value.py")
    statements_router = read("apps/backend/src/routers/statements.py")
    generator = read("scripts/pdf_fixtures/generate_pdf_fixtures.py")

    assert "test_brokerage_upload_to_portfolio_value.py" in workflow
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
    assert "Statement must be parsed before importing brokerage positions" in statements_router
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


def test_AC8_13_21_post_merge_ai_ocr_waits_for_matching_ci_success() -> None:
    """AC8.13.21: Provider-backed post-merge gate waits for same-SHA CI success."""
    workflow = read(".github/workflows/staging-ai-ocr-gate.yml")
    ci_cd = read("docs/ssot/ci-cd.md")

    assert "permissions:" in workflow
    assert "actions: read" in workflow
    assert "Wait for matching CI success" in workflow
    assert "EXPECTED_FULL_SHA: ${{ steps.expected_sha.outputs.full_sha }}" in workflow
    assert '--commit "$EXPECTED_FULL_SHA"' in workflow
    assert "--event push" in workflow
    assert "Skipping provider-backed AI/OCR gate because matching CI concluded" in workflow
    assert "before spending provider quota" in ci_cd


def test_AC8_13_22_vision_hard_gate_uses_deterministic_fixture_with_fresh_user() -> None:
    """AC8.13.22: deterministic upload-to-dashboard gate uses a critical fresh-user fixture flow."""
    gate = read("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py")
    epic = read("docs/project/EPIC-008.testing-strategy.md")

    assert "@pytest.mark.e2e" in gate
    assert "@pytest.mark.tier3" in gate
    assert "@pytest.mark.critical" in gate
    assert "@pytest.mark.llm" not in gate
    assert "authenticated_page_unique" in gate
    assert "vision_hard_gate_statement.csv" in gate
    assert "pytest.skip(" in gate
    assert "AC8.13.22" in epic
    assert "test_statement_upload_to_dashboard_vision_hard_gate" in epic


def test_AC8_13_26_vision_hard_gate_proves_trusted_reporting_totals() -> None:
    """AC8.13.26: deterministic vision gate asserts exact trusted accounting/report totals."""
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
