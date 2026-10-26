"""Application-owned deployment and environment verification contracts."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read(path: Path | str) -> str:
    path = ROOT / path if isinstance(path, str) else path
    return path.read_text(encoding="utf-8")


def test_staging_gate_exercises_health_smoke_e2e_and_storage_paths() -> None:
    """AC7.9.1 AC7.9.2 AC7.9.3 AC7.9.4 AC7.9.5: Staging validates runtime health, API, domain, and storage upload paths."""
    staging = read(".github/workflows/deploy.yml")
    smoke = read("common/runtime/shell/smoke_test.sh")
    hard_gate = read("tests/e2e/test_vision_upload_to_dashboard_hard_gate.py")

    assert "S3_BUCKET:-statements" in read("docker-compose.yml")
    assert "bash tools/smoke_test.sh" in staging
    assert (
        'eval "$(python tools/test_selection.py --stage staging_core_e2e --shell)"'
        in staging
    )
    assert (
        'pytest "${STAGING_CORE_E2E_TESTS[@]}"' in staging
        and '-m "$STAGING_CORE_E2E_MARKER"' in staging
    )

    assert 'wait_for_endpoint "API Health" "$BASE_URL/api/health"' in smoke
    assert 'wait_for_endpoint "Frontend Ready" "$BASE_URL/"' in smoke
    assert (
        'check_endpoint "DB Connectivity" "$BASE_URL/api/health" "\\"status\\":\\"healthy\\""'
        in smoke
    )
    assert 'check_endpoint "Ping API" "$BASE_URL/api/ping"' in smoke
    assert 'check_endpoint "API Docs" "$BASE_URL/api/docs"' in smoke

    assert "test_statement_upload_to_dashboard_vision_hard_gate" in hard_gate
    assert "/api/statements/upload" in hard_gate
    assert "dashboard" in hard_gate.lower()


def test_in_runner_e2e_compose_files_stay_retired() -> None:
    """Issue #839: full-stack E2E compose resources are clean and never leak."""
    assert not (ROOT / "docker-compose.ci-e2e.yml").exists()
    assert not (ROOT / "tools" / "ci" / "e2e-nginx.conf").exists()
