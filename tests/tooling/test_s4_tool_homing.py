"""S4 PR-C package-homing and thin-tool structural contracts (#1867)."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_AC_runtime_http_probes_1_runtime_checks_share_hardened_http_primitives() -> (
    None
):
    """AC-runtime.http-probes.1: runtime probes share HTTP and SHA behavior."""
    from common.runtime import http_probe, production_infra_smoke, tier2_http_e2e

    assert production_infra_smoke.HttpResponse is http_probe.HttpResponse
    assert tier2_http_e2e.HttpResponse is http_probe.HttpResponse
    assert production_infra_smoke.sha_matches is http_probe.sha_matches
    assert tier2_http_e2e.sha_matches is http_probe.sha_matches
    assert not http_probe.sha_matches("", "")
    assert http_probe.sha_matches("abc123", "abc123456789")
    assert len((ROOT / "tools/tier2_http_e2e.py").read_text().splitlines()) <= 40


def test_AC_runtime_extension_tools_1_backend_gates_share_project_root() -> None:
    """AC-runtime.extension-tools.1: backend runtime gates share root lookup."""
    from apps.backend.src.runtime.extension import (
        env_keys,
        project_root,
        schema_validation,
    )

    assert env_keys.get_project_root is project_root.get_project_root
    assert schema_validation.get_project_root is project_root.get_project_root
    assert project_root.get_project_root() == ROOT


def test_AC_testing_governance_19_ai_ocr_gate_and_data_are_package_owned() -> None:
    """AC-testing.governance.19: AI-OCR gate logic and counters leave tools/."""
    from common.testing import staging_ai_ocr_gate_contract

    data_path = ROOT / "common/testing/data/staging-ai-ocr-replay-counters.json"
    assert json.loads(data_path.read_text(encoding="utf-8")) == (
        staging_ai_ocr_gate_contract.REPLAY_COUNTERS
    )
    assert (
        len((ROOT / "tools/staging_ai_ocr_gate_contract.py").read_text().splitlines())
        <= 40
    )


def test_AC_testing_governance_20_fat_tool_ratchet_rejects_new_and_stale_debt(
    tmp_path: Path, capsys
) -> None:
    """AC-testing.governance.20: the fat-tool baseline only shrinks."""
    from common.testing import tool_shim_contract

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "thin.py").write_text("pass\n", encoding="utf-8")
    (tools_dir / "new_fat.py").write_text("pass\n" * 41, encoding="utf-8")
    baseline = {"legacy_fat_tools": ["tools/resolved.py"]}
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    new, stale = tool_shim_contract.findings(tmp_path, baseline_path)

    assert new == ["new fat tool: tools/new_fat.py (41 lines; maximum 40)"]
    assert stale == ["resolved fat tool still baselined: tools/resolved.py"]

    assert (
        tool_shim_contract.main(
            [
                "--repo-root",
                str(tmp_path),
                "--baseline",
                str(baseline_path),
            ]
        )
        == 1
    )
    assert "new fat tool" in capsys.readouterr().err

    baseline_path.write_text(
        json.dumps({"legacy_fat_tools": ["tools/new_fat.py"]}),
        encoding="utf-8",
    )
    assert (
        tool_shim_contract.main(
            [
                "--repo-root",
                str(tmp_path),
                "--baseline",
                str(baseline_path),
            ]
        )
        == 0
    )

    (tools_dir / "new_fat.py").write_text("pass\n", encoding="utf-8")
    assert (
        tool_shim_contract.main(
            [
                "--repo-root",
                str(tmp_path),
                "--baseline",
                str(baseline_path),
            ]
        )
        == 1
    )
    assert "resolved fat tool" in capsys.readouterr().err
    assert (
        tool_shim_contract.main(
            [
                "--repo-root",
                str(tmp_path),
                "--baseline",
                str(baseline_path),
                "--update",
            ]
        )
        == 0
    )
    assert json.loads(baseline_path.read_text(encoding="utf-8")) == {
        "legacy_fat_tools": []
    }


def test_AC_testing_toolchain_13_dev_commands_share_env_aware_toolchain(
    monkeypatch,
) -> None:
    """AC-testing.toolchain.13: dev commands share one toolchain implementation."""
    from tools._lib.dev import cli, dev_backend, test_lifecycle, toolchain

    assert cli.get_runtime_version is toolchain.get_runtime_version
    assert dev_backend.get_runtime_version is toolchain.get_runtime_version
    assert test_lifecycle.get_runtime_version is toolchain.get_runtime_version
    assert cli.uv_run is toolchain.uv_run
    assert dev_backend.uv_run is toolchain.uv_run
    assert test_lifecycle.uv_run is toolchain.uv_run
    assert cli.get_compose_cmd is toolchain.get_compose_cmd
    assert dev_backend.get_compose_cmd is toolchain.get_compose_cmd

    monkeypatch.setenv("CONTAINER_RUNTIME", "docker")
    monkeypatch.setattr(toolchain.shutil, "which", lambda name: f"/bin/{name}")
    assert dev_backend.get_compose_cmd() == ["docker", "compose"]

    monkeypatch.setenv("CONTAINER_RUNTIME", "invalid")
    assert toolchain.get_container_runtime() is None


def test_homed_cli_argument_errors_return_status_codes() -> None:
    """Package-owned CLI mains remain composable across argparse failures."""
    from common.runtime import tier2_http_e2e
    from common.testing import staging_ai_ocr_gate_contract

    assert tier2_http_e2e.main(["--timeout-seconds", "not-a-number"]) == 2
    assert staging_ai_ocr_gate_contract.main(["--corpus", "unknown"]) == 2
