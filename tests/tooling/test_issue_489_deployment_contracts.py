"""Application-owned deployment and environment verification contracts."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml


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


GIT_SHA_COMPOSE_VALUE = "${GIT_COMMIT_SHA:-}"
BACKEND_COMPOSE_KEYS_OWNED_BY_CONFIG = (
    "AI_PROVIDER",
    "AI_BASE_URL",
    "AI_CHAT_COMPLETIONS_PATH",
)


def git_sha_wiring_violations(
    compose: dict, frontend_dockerfile: str, frontend_version_route: str
) -> list[str]:
    """Return what is wrong with the deployed-version plumbing and the backend compose env."""
    violations: list[str] = []
    backend = compose["services"]["backend"]
    frontend = compose["services"]["frontend"]
    if backend.get("environment", {}).get("GIT_COMMIT_SHA") != GIT_SHA_COMPOSE_VALUE:
        violations.append("backend environment does not pass GIT_COMMIT_SHA")
    if (
        frontend.get("build", {}).get("args", {}).get("GIT_COMMIT_SHA")
        != GIT_SHA_COMPOSE_VALUE
    ):
        violations.append("frontend build args do not pass GIT_COMMIT_SHA")
    if frontend.get("environment", {}).get("GIT_COMMIT_SHA") != GIT_SHA_COMPOSE_VALUE:
        violations.append("frontend environment does not pass GIT_COMMIT_SHA")
    for needle in (
        "ARG GIT_COMMIT_SHA=unknown",
        "ENV GIT_COMMIT_SHA=${GIT_COMMIT_SHA}",
    ):
        if frontend_dockerfile.count(needle) < 2:
            violations.append(f"frontend Dockerfile lacks `{needle}` in a stage")
    if "process.env.GIT_COMMIT_SHA" not in frontend_version_route:
        violations.append("frontend-version route does not read GIT_COMMIT_SHA")
    declared = set(backend.get("environment", {})) | set(
        backend.get("build", {}).get("args", {})
    )
    for key in BACKEND_COMPOSE_KEYS_OWNED_BY_CONFIG:
        if key in declared:
            violations.append(f"backend compose declares {key}; config.py owns it")
    return violations


def _git_sha_wiring_inputs() -> tuple[dict, str, str]:
    compose = yaml.safe_load(read("docker-compose.yml"))
    return (
        compose,
        read("apps/frontend/Dockerfile"),
        read("apps/frontend/src/app/frontend-version.json/route.ts"),
    )


def test_AC_runtime_fe_deploy_1_git_sha_reaches_backend_runtime_and_frontend_build() -> (
    None
):
    """AC-runtime.fe-deploy.1: compose and the frontend Dockerfile carry GIT_COMMIT_SHA to /frontend-version.json; the backend compose keeps AI config out."""
    assert git_sha_wiring_violations(*_git_sha_wiring_inputs()) == []


def test_AC_runtime_fe_deploy_1_git_sha_wiring_fails_on_each_drift() -> None:
    """AC-runtime.fe-deploy.1: each mutation of the real files turns the wiring check red."""
    compose, dockerfile, route = _git_sha_wiring_inputs()

    # The ARG/ENV pair appears in the build stage and in the runtime stage; losing
    # either one breaks /frontend-version.json.
    no_arg = dockerfile.replace("ARG GIT_COMMIT_SHA=unknown", "", 1)
    assert no_arg != dockerfile
    assert git_sha_wiring_violations(compose, no_arg, route) == [
        "frontend Dockerfile lacks `ARG GIT_COMMIT_SHA=unknown` in a stage"
    ]
    no_env = dockerfile[::-1].replace(
        "ENV GIT_COMMIT_SHA=${GIT_COMMIT_SHA}"[::-1], "", 1
    )[::-1]
    assert no_env != dockerfile
    assert git_sha_wiring_violations(compose, no_env, route) == [
        "frontend Dockerfile lacks `ENV GIT_COMMIT_SHA=${GIT_COMMIT_SHA}` in a stage"
    ]
    assert git_sha_wiring_violations(compose, dockerfile, "no sha here") == [
        "frontend-version route does not read GIT_COMMIT_SHA"
    ]

    no_backend_sha = copy.deepcopy(compose)
    del no_backend_sha["services"]["backend"]["environment"]["GIT_COMMIT_SHA"]
    assert git_sha_wiring_violations(no_backend_sha, dockerfile, route) == [
        "backend environment does not pass GIT_COMMIT_SHA"
    ]

    no_build_arg = copy.deepcopy(compose)
    del no_build_arg["services"]["frontend"]["build"]["args"]["GIT_COMMIT_SHA"]
    assert git_sha_wiring_violations(no_build_arg, dockerfile, route) == [
        "frontend build args do not pass GIT_COMMIT_SHA"
    ]

    for key in BACKEND_COMPOSE_KEYS_OWNED_BY_CONFIG:
        drifted = copy.deepcopy(compose)
        drifted["services"]["backend"]["environment"][key] = "x"
        assert git_sha_wiring_violations(drifted, dockerfile, route) == [
            f"backend compose declares {key}; config.py owns it"
        ]
