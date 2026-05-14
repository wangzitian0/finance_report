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
    assert "pytest.skip(" not in test_body


def test_AC8_13_8_upload_readiness_gate_rejects_rejected_status() -> None:
    """AC8.13.8: Upload readiness E2E does not accept rejected statements."""
    upload = read("tests/e2e/test_statement_upload_e2e.py")
    test_body = upload.split("async def test_statement_upload_full_flow", 1)[1].split(
        "@pytest.mark.e2e", 1
    )[0]

    assert "AI/OCR readiness gate" in test_body
    assert "fail_or_skip_ai_ocr_gate(" in test_body
    assert '"rejected"' not in test_body.split("assert status in", 1)[1]


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
