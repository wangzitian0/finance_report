from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_moon_ci_and_compose_contracts() -> None:
    moon_tc = yaml.safe_load((ROOT / ".moon/toolchain.yml").read_text())
    workspace = yaml.safe_load((ROOT / ".moon/workspace.yml").read_text())
    root_proj = yaml.safe_load((ROOT / "moon.yml").read_text())
    backend_proj = yaml.safe_load((ROOT / "apps/backend/moon.yml").read_text())
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text()

    assert (moon_tc["node"]["packageManager"], moon_tc["node"]["version"], moon_tc["node"]["npm"]["version"]) == ("npm", "20.19.0", "10.8.2")
    assert workspace["projects"] == ["apps/*", "."] and not (ROOT / "infra").exists()
    assert "moonrepo/setup-toolchain@v0" not in ci_workflow
    assert (root_proj["tasks"]["dev"]["command"], root_proj["tasks"]["test"]["command"], root_proj["tasks"]["lint"]["command"]) == ("python3 tools/cli.py dev", "python3 tools/cli.py test", "python3 tools/cli.py lint")
    assert (backend_proj["language"], backend_proj["layer"], backend_proj["fileGroups"]["sources"], backend_proj["fileGroups"]["tests"]) == ("python", "application", ["src/**/*.py"], ["tests/**/*.py"])

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose.get("services") or {}
    assert "postgres" in services and services["postgres"]["image"].startswith("postgres:15") and "postgres_data" in compose.get("volumes", {})
    assert any((ROOT / s["build"]["context"]).exists() for s in services.values() if "build" in s and s["build"].get("context"))
    assert services["backend"]["environment"]["S3_ENDPOINT"] == "${S3_ENDPOINT:-http://minio:9000}"
    assert "$$(seq 1 10)" in services["minio-init"]["entrypoint"] and "\\$(seq 1 10)" not in services["minio-init"]["entrypoint"]

    if (ROOT / ".github/workflows").exists() and (actionlint := shutil.which("actionlint")):
        res = subprocess.run([actionlint, "-color"], cwd=ROOT, capture_output=True, text=True)
        assert res.returncode == 0, f"GitHub Actions Lint Failed:\n{res.stdout}\n{res.stderr}"


def test_epic_001_skeleton_and_frontend_contracts() -> None:
    required = (
        "moon.yml",
        "apps/backend/moon.yml",
        "apps/frontend/moon.yml",
        "tools/smoke_test.sh",
        "common/runtime/shell/smoke_test.sh",
        "apps/backend/src/main.py",
        "apps/backend/src/database.py",
        "apps/backend/src/identity/extension/api/auth.py",
        "apps/backend/src/observability/__init__.py",
        "apps/frontend/src/app/layout.tsx",
        "apps/frontend/src/app/(main)/page.tsx",
        "apps/frontend/tailwind.config.ts",
        "apps/frontend/src/app/providers.tsx",
        ".pre-commit-config.yaml",
    )
    assert all((ROOT / p).exists() for p in required)
    assert not (ROOT / "apps/frontend/src/app/ping-pong/page.tsx").exists()
    assert "ruff" in (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    route_map = json.loads((ROOT / "apps/frontend/src/lib/route-map.json").read_text(encoding="utf-8"))
    assert all(r["path"] != "/ping-pong" for r in route_map["routes"])
    pkg = json.loads((ROOT / "apps/frontend/package.json").read_text(encoding="utf-8"))
    assert "@tanstack/react-query" in pkg.get("dependencies", {})

    if moon_bin := shutil.which("moon"):
        res = subprocess.run([moon_bin, "--cache", "off", "project", "frontend", "--json"], capture_output=True, text=True, cwd=ROOT)
        assert res.returncode == 0, res.stderr
        data, _ = json.JSONDecoder().raw_decode(res.stdout.lstrip())
        assert data.get("language") == "javascript"
    else:
        pytest.skip("moon CLI not installed")
