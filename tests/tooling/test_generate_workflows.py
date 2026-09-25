"""Tests for workflow and action projection from toolchain SSOT."""

from __future__ import annotations

import runpy
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.runtime import generate_workflows  # noqa: E402


def _copy_projection_inputs(target_root: Path) -> None:
    for rel_path in (
        "toolchain.toml",
        ".github/workflows/ci.yml",
        ".github/workflows/deploy.yml",
        ".github/workflows/docs.yml",
        ".github/workflows/release.yml",
        ".github/workflows/deploy-freshness.yml",
        ".github/workflows/benchmark.yml",
        ".github/actions/setup-minio/action.yml",
        ".github/actions/setup-e2e-tests/action.yml",
        ".github/actions/setup-backend-env/action.yml",
        "docker-compose.yml",
        "docker-compose.pr-preview.yml",
        "apps/backend/Dockerfile",
        "apps/frontend/Dockerfile",
    ):
        src = ROOT / rel_path
        dst = target_root / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def test_AC_testing_toolchain_1_clean_checkout_has_zero_drift() -> None:
    """AC-testing.toolchain.1: Clean checkout matches projected toolchain exactly."""
    status, errors, _ = generate_workflows.project_all(ROOT, check_only=True)
    assert status == 0
    assert len(errors) == 0


def test_AC_testing_toolchain_1_cli_check_passes_on_clean_checkout() -> None:
    """AC-testing.toolchain.1: CLI returns 0 on clean repository."""
    code = generate_workflows.main(["--repo-root", str(ROOT), "--check"])
    assert code == 0


def test_AC_testing_toolchain_1_detects_drift_when_toolchain_runtime_changes(
    tmp_path: Path,
) -> None:
    """AC-testing.toolchain.1: toolchain.toml runtime changes are detected as drift."""
    _copy_projection_inputs(tmp_path)
    tc = generate_workflows.load_toolchain(tmp_path)
    current_uv = tc["runtime"]["uv"]
    tc_file = tmp_path / "toolchain.toml"
    tc_content = tc_file.read_text(encoding="utf-8")
    tc_file.write_text(
        tc_content.replace(f'uv = "{current_uv}"', 'uv = "0.9.99"'),
        encoding="utf-8",
    )

    status, errors, _ = generate_workflows.project_all(tmp_path, check_only=True)
    assert status == 1
    assert len(errors) > 0


def test_AC_testing_toolchain_1_detects_drift_when_workflow_env_changes(
    tmp_path: Path,
) -> None:
    """AC-testing.toolchain.1: Workflow env header drift is detected."""
    _copy_projection_inputs(tmp_path)
    tc = generate_workflows.load_toolchain(tmp_path)
    current_py = tc["runtime"]["python"]
    ci_file = tmp_path / ".github/workflows/ci.yml"
    ci_content = ci_file.read_text(encoding="utf-8")
    ci_file.write_text(
        ci_content.replace(
            f'PYTHON_VERSION: "{current_py}"', 'PYTHON_VERSION: "3.11.0"'
        ),
        encoding="utf-8",
    )

    status, errors, _ = generate_workflows.project_all(tmp_path, check_only=True)
    assert status == 1
    assert len(errors) > 0


def test_AC_testing_toolchain_1_missing_required_env_pin_fails(
    tmp_path: Path,
) -> None:
    """AC-testing.toolchain.1: Deletion of required version pin causes projection failure."""
    _copy_projection_inputs(tmp_path)
    tc = generate_workflows.load_toolchain(tmp_path)
    current_py = tc["runtime"]["python"]
    ci_file = tmp_path / ".github/workflows/ci.yml"
    ci_content = ci_file.read_text(encoding="utf-8")
    ci_file.write_text(
        ci_content.replace(f'PYTHON_VERSION: "{current_py}"\n', ""),
        encoding="utf-8",
    )

    status, errors, _ = generate_workflows.project_all(tmp_path, check_only=True)
    assert status == 1
    pin_error_needle = "missing required PYTHON_VERSION pin"
    assert any(pin_error_needle in err for err in errors)


def test_AC_testing_toolchain_1_detects_drift_when_minio_image_changes(
    tmp_path: Path,
) -> None:
    """AC-testing.toolchain.1: MinIO container image drift is detected."""
    _copy_projection_inputs(tmp_path)
    action_file = tmp_path / ".github/actions/setup-minio/action.yml"
    action_content = action_file.read_text(encoding="utf-8")
    drifted_image = "invalid.example/minio:drift"
    tc = generate_workflows.load_toolchain(tmp_path)
    action_file.write_text(
        action_content.replace(tc["images"]["minio"], drifted_image),
        encoding="utf-8",
    )

    status, errors, _ = generate_workflows.project_all(tmp_path, check_only=True)
    assert status == 1
    assert len(errors) > 0


def test_AC_testing_toolchain_1_detects_drift_when_postgres_image_changes(
    tmp_path: Path,
) -> None:
    """AC-testing.toolchain.1: Postgres service container image drift is detected."""
    _copy_projection_inputs(tmp_path)
    tc = generate_workflows.load_toolchain(tmp_path)
    current_pg = tc["images"]["postgres"]
    tc_file = tmp_path / "toolchain.toml"
    tc_content = tc_file.read_text(encoding="utf-8")
    tc_file.write_text(
        tc_content.replace(current_pg, "postgres:16-alpine"),
        encoding="utf-8",
    )

    status, errors, _ = generate_workflows.project_all(tmp_path, check_only=True)
    assert status == 1
    assert len(errors) > 0


def test_AC_testing_toolchain_1_synchronization_updates_files_cleanly(
    tmp_path: Path,
) -> None:
    """AC-testing.toolchain.1: Synchronizing writes projected changes and restores zero drift."""
    _copy_projection_inputs(tmp_path)
    tc = generate_workflows.load_toolchain(tmp_path)
    current_uv = tc["runtime"]["uv"]
    tc_file = tmp_path / "toolchain.toml"
    tc_content = tc_file.read_text(encoding="utf-8")
    new_uv_version = "0.9.99"
    tc_file.write_text(
        tc_content.replace(f'uv = "{current_uv}"', f'uv = "{new_uv_version}"'),
        encoding="utf-8",
    )

    # 1. First verify check_only reports drift
    status_before, errors_before, _ = generate_workflows.project_all(
        tmp_path, check_only=True
    )
    assert status_before == 1
    assert len(errors_before) > 0

    # 2. Run write mode
    status_write, errors_write, _ = generate_workflows.project_all(
        tmp_path, check_only=False
    )
    assert status_write == 0
    assert len(errors_write) == 0

    # 3. Verify check_only is now completely clean
    status_after, errors_after, _ = generate_workflows.project_all(
        tmp_path, check_only=True
    )
    assert status_after == 0
    assert len(errors_after) == 0

    # 4. Verify targeted file has new version
    ci_content = (tmp_path / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    expected_header = f'UV_VERSION: "{new_uv_version}"'
    assert expected_header in ci_content


def test_AC_testing_toolchain_1_missing_required_workflow_fails(
    tmp_path: Path,
) -> None:
    """AC-testing.toolchain.1: Missing required workflow file reports an error."""
    _copy_projection_inputs(tmp_path)
    ci_file = tmp_path / ".github/workflows/ci.yml"
    ci_file.unlink()

    status, errors, _ = generate_workflows.project_all(tmp_path, check_only=True)
    assert status == 1
    missing_needle = ".github/workflows/ci.yml: file not found (required)"
    assert any(missing_needle in err for err in errors)


def test_AC_testing_toolchain_1_missing_toolchain_toml_fails(
    tmp_path: Path,
) -> None:
    """AC-testing.toolchain.1: Missing toolchain.toml fails cleanly."""
    status, errors, _ = generate_workflows.project_all(tmp_path, check_only=True)
    assert status == 1
    assert len(errors) > 0


def test_AC_testing_toolchain_1_main_entrypoint_exits_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-testing.toolchain.1: Direct invocation of generate_workflows exits with 0."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_workflows.py",
            "--repo-root",
            str(ROOT),
            "--check",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(
            Path(generate_workflows.__file__).as_posix(), run_name="__main__"
        )
    assert exc_info.value.code == 0
