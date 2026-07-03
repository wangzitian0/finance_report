"""AC10.9.5 (retired): deploy failure snapshots are infra2-owned; the app ships none.

The app-side ``tools/dokploy_failure_snapshot.py`` was an orphan — zero workflow or
script callers — duplicating infra2's ``deploy_failure_snapshot`` (which runs inside
the deploy_v2 front door, where the compose_id and platform context already live).
Per the App/Infra boundary (#876): the app must not reach the Dokploy API for
platform diagnostics; infra2 owns the failure snapshot end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_AC10_9_5_app_side_snapshot_is_retired() -> None:
    """AC10.9.5: the app ships no Dokploy failure-snapshot tool, and no code or
    CI surface (tools/, common/, apps/, tests/, .github/) references one — the
    platform-diagnostic boundary belongs to infra2. (docs/ may narrate the
    retirement and is deliberately out of scope.)"""
    assert not (ROOT / "tools" / "dokploy_failure_snapshot.py").exists()
    assert not (
        ROOT / "tests" / "tooling" / "test_dokploy_failure_snapshot.py"
    ).exists()

    this_file = Path(__file__).resolve()
    hits = []
    for base in ("tools", "common", "apps", "tests", ".github"):
        root = ROOT / base
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in (".py", ".yml", ".yaml", ".sh"):
                continue
            if (
                path.resolve() == this_file
                or "node_modules" in path.parts
                or ".venv" in path.parts
            ):
                continue
            if "dokploy_failure_snapshot" in path.read_text(
                encoding="utf-8", errors="ignore"
            ):
                hits.append(str(path.relative_to(ROOT)))
    assert hits == [], f"app still references the retired snapshot tool: {hits}"


def test_AC10_9_5_infra2_owns_deploy_failure_snapshots() -> None:
    """AC10.9.5: the capability lives in infra2 (relocation-resilient: any
    failure-snapshot module anywhere under repo/tools or repo/libs counts), so
    retiring the app copy leaves no diagnostic blind spot. Skips when the repo/
    submodule is not checked out (CI always populates it)."""
    repo = ROOT / "repo"
    if not (repo / "tools").is_dir():
        pytest.skip("infra2 submodule (repo/) not checked out in this workspace")
    candidates = [
        p
        for base in ("tools", "libs")
        for p in (repo / base).rglob("*failure_snapshot*.py")
    ]
    assert candidates, (
        "infra2 (repo/) no longer ships a deploy failure snapshot — investigate before retiring"
    )
