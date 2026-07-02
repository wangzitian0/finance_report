from __future__ import annotations

import runpy
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.runtime import check_toolchain_contract as contract  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]


def _copy_contract_inputs(target_root: Path) -> None:
    for relative_path in (
        "toolchain.toml",
        ".python-version",
        ".node-version",
        ".nvmrc",
        ".tool-versions",
        ".npmrc",
        ".moon/toolchain.yml",
        "apps/frontend/package.json",
        ".github/workflows/ci.yml",
        ".github/workflows/deploy.yml",
        ".github/workflows/deploy.yml",
        ".github/workflows/docs.yml",
        ".github/actions/setup-e2e-tests/action.yml",
        "apps/backend/Dockerfile",
        "apps/frontend/Dockerfile",
        "docker-compose.yml",
    ):
        source = ROOT / relative_path
        target = target_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def test_AC8_13_39_current_toolchain_contract_is_consistent() -> None:
    """AC8.13.39: Runtime and container versions are governed by one contract."""
    assert contract.run_contract(ROOT) == 0


def test_AC8_13_39_contract_fails_when_node_version_drifts(tmp_path: Path) -> None:
    """AC8.13.39: Local tool files cannot drift from toolchain.toml."""
    _copy_contract_inputs(tmp_path)

    (tmp_path / ".node-version").write_text("25.9.0\n", encoding="utf-8")

    assert contract.run_contract(tmp_path) == 1


def test_AC8_13_39_contract_fails_when_container_image_drifts(tmp_path: Path) -> None:
    """AC8.13.39: Container image tags cannot drift from toolchain.toml."""
    _copy_contract_inputs(tmp_path)

    dockerfile = tmp_path / "apps/backend/Dockerfile"
    dockerfile.write_text(
        dockerfile.read_text(encoding="utf-8").replace(
            "ARG PYTHON_IMAGE=python:3.12.12-slim",
            "ARG PYTHON_IMAGE=python:3.12-slim",
        ),
        encoding="utf-8",
    )

    assert contract.run_contract(tmp_path) == 1


def test_AC8_13_39_contract_fails_when_frontend_engine_drifts(tmp_path: Path) -> None:
    """AC8.13.39: Frontend package engines must match the runtime contract."""
    _copy_contract_inputs(tmp_path)

    package_json = tmp_path / "apps/frontend/package.json"
    package_json.write_text(
        package_json.read_text(encoding="utf-8").replace(
            '"node": "20.19.0"',
            '"node": ">=20"',
        ),
        encoding="utf-8",
    )

    assert contract.run_contract(tmp_path) == 1


def test_AC8_13_39_contract_fails_when_moon_toolchain_drifts(tmp_path: Path) -> None:
    """AC8.13.39: Moon's local toolchain declaration cannot drift from toolchain.toml."""
    _copy_contract_inputs(tmp_path)

    moon_toolchain = tmp_path / ".moon/toolchain.yml"
    moon_toolchain.write_text(
        moon_toolchain.read_text(encoding="utf-8").replace(
            "version: '20.19.0'",
            "version: '25.9.0'",
        ),
        encoding="utf-8",
    )

    assert contract.run_contract(tmp_path) == 1


def test_AC8_13_39_contract_reports_missing_toolchain(tmp_path: Path) -> None:
    """AC8.13.39: Missing runtime SSOT fails instead of silently passing."""
    with pytest.raises(FileNotFoundError):
        contract.load_toolchain(tmp_path)


def test_AC8_13_39_cli_accepts_explicit_repo_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.39: The CLI validates an explicit checkout root."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_toolchain_contract.py",
            "--repo-root",
            str(ROOT),
        ],
    )

    assert contract.main() == 0


def test_AC8_13_39_module_entrypoint_exits_with_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8.13.39: Direct script execution exits with the contract status."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_toolchain_contract.py",
            "--repo-root",
            str(ROOT),
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(Path(contract.__file__).as_posix(), run_name="__main__")

    assert exc_info.value.code == 0
