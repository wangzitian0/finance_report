"""AC10.9.5 (retired): deploy failure snapshots are infra2-owned; the app ships none.

The app-side ``tools/dokploy_failure_snapshot.py`` was an orphan — zero workflow or
script callers — duplicating infra2's ``deploy_failure_snapshot`` (which runs inside
the deploy_v2 front door, where the compose_id and platform context already live).
Per the App/Infra boundary (#876): the app must not reach the Dokploy API for
platform diagnostics; infra2 owns the failure snapshot end to end.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_AC10_9_5_app_side_snapshot_is_retired() -> None:
    """AC10.9.5: the app ships no Dokploy failure-snapshot tool and nothing
    references one — the platform-diagnostic boundary belongs to infra2."""
    assert not (ROOT / "tools" / "dokploy_failure_snapshot.py").exists()
    assert not (ROOT / "tests" / "tooling" / "test_dokploy_failure_snapshot.py").exists()

    hits = []
    for base in ("tools", "common", ".github"):
        for path in (ROOT / base).rglob("*"):
            if path.is_file() and path.suffix in (".py", ".yml", ".yaml", ".sh"):
                if "dokploy_failure_snapshot" in path.read_text(encoding="utf-8", errors="ignore"):
                    hits.append(str(path.relative_to(ROOT)))
    assert hits == [], f"app still references the retired snapshot tool: {hits}"


def test_AC10_9_5_infra2_owns_deploy_failure_snapshots() -> None:
    """AC10.9.5: the capability lives in infra2 (relocation-resilient: any
    failure-snapshot module under repo/tools or repo/libs counts), so retiring
    the app copy leaves no diagnostic blind spot."""
    repo = ROOT / "repo"
    candidates = list(repo.glob("tools/*failure_snapshot*.py")) + list(repo.glob("libs/**/*failure_snapshot*.py"))
    assert candidates, "infra2 (repo/) no longer ships a deploy failure snapshot — investigate before retiring"
