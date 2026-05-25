from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import check_toolchain_contract as contract  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]


def test_AC8_13_39_current_toolchain_contract_is_consistent() -> None:
    """AC8.13.39: Runtime and container versions are governed by one contract."""
    assert contract.run_contract(ROOT) == 0


def test_AC8_13_39_contract_fails_when_node_version_drifts(tmp_path: Path) -> None:
    """AC8.13.39: Local tool files cannot drift from toolchain.toml."""
    for relative_path in (
        "toolchain.toml",
        ".python-version",
        ".node-version",
        ".nvmrc",
        ".tool-versions",
        ".npmrc",
        "apps/frontend/package.json",
        ".github/workflows/ci.yml",
        ".github/workflows/staging-deploy.yml",
        ".github/workflows/production-release.yml",
        ".github/workflows/docs.yml",
        ".github/actions/setup-e2e-tests/action.yml",
        "apps/backend/Dockerfile",
        "apps/frontend/Dockerfile",
        "docker-compose.yml",
    ):
        source = ROOT / relative_path
        target = tmp_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    (tmp_path / ".node-version").write_text("25.9.0\n", encoding="utf-8")

    assert contract.run_contract(tmp_path) == 1


def test_AC8_13_39_contract_reports_missing_toolchain(tmp_path: Path) -> None:
    """AC8.13.39: Missing runtime SSOT fails instead of silently passing."""
    with pytest.raises(FileNotFoundError):
        contract.load_toolchain(tmp_path)
