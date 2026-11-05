"""Tests for the npm lockfile registry hygiene gate (#2668)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from common.testing import lockfile_registry, preflight

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_lockfile(path: Path, packages: dict[str, dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": "test-fixture",
        "lockfileVersion": 3,
        "requires": True,
        "packages": packages,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def test_real_repository_lockfiles_pass_registry_check() -> None:
    """#2668: all tracked package-lock.json files in the repository use official npm registry URLs."""
    discovered = lockfile_registry.discover_lockfiles(REPO_ROOT)
    rel_paths = {p.relative_to(REPO_ROOT).as_posix() for p in discovered}
    assert "apps/frontend/package-lock.json" in rel_paths
    assert lockfile_registry.violations(REPO_ROOT) == []
    assert lockfile_registry.main(["--repo-root", str(REPO_ROOT)]) == 0


def test_clean_synthetic_lockfile_passes(tmp_path: Path) -> None:
    """#2668: packages with official registry.npmjs.org resolved URLs or no resolved URL pass."""
    lockfile = _write_lockfile(
        tmp_path / "apps" / "frontend" / "package-lock.json",
        {
            "": {"name": "frontend", "version": "0.1.0"},
            "node_modules/next": {
                "version": "15.0.0",
                "resolved": "https://registry.npmjs.org/next/-/next-15.0.0.tgz",
            },
            "node_modules/react": {
                "version": "19.0.0",
                "resolved": "https://registry.npmjs.org/react/-/react-19.0.0.tgz",
            },
        },
    )
    assert lockfile_registry.scan_lockfile(lockfile, repo_root=tmp_path) == []
    assert lockfile_registry.main(["--repo-root", str(tmp_path)]) == 0


def test_private_mirror_registry_url_fails_and_lists_package(
    tmp_path: Path, capsys
) -> None:
    """#2668: any private registry URL (e.g. npm.shopee.io or registry-NonPublic) fails closed."""
    _write_lockfile(
        tmp_path / "apps" / "frontend" / "package-lock.json",
        {
            "": {"name": "frontend", "version": "0.1.0"},
            "node_modules/clean-pkg": {
                "version": "1.0.0",
                "resolved": "https://registry.npmjs.org/clean-pkg/-/clean-pkg-1.0.0.tgz",
            },
            "node_modules/@private/mirror-pkg": {
                "version": "2.1.0",
                "resolved": "https://npm.shopee.io/@private/mirror-pkg/-/mirror-pkg-2.1.0.tgz",
            },
            "node_modules/corp-pkg": {
                "version": "3.0.0",
                "resolved": "https://registry-NonPublic.internal.example/corp-pkg/-/corp-pkg-3.0.0.tgz",
            },
        },
    )
    rc = lockfile_registry.main(["--repo-root", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "apps/frontend/package-lock.json" in err
    assert "node_modules/@private/mirror-pkg" in err
    assert "https://npm.shopee.io/@private/mirror-pkg/-/mirror-pkg-2.1.0.tgz" in err
    assert "node_modules/corp-pkg" in err
    assert (
        "https://registry-NonPublic.internal.example/corp-pkg/-/corp-pkg-3.0.0.tgz"
        in err
    )


def test_invalid_json_or_missing_lockfiles_fail_closed(tmp_path: Path) -> None:
    """#2668: missing lockfiles or malformed JSON fail closed rather than silently passing."""
    assert lockfile_registry.main(["--repo-root", str(tmp_path)]) == 1

    bad_lock = tmp_path / "package-lock.json"
    bad_lock.write_text("{not-valid-json", encoding="utf-8")
    assert lockfile_registry.main(["--repo-root", str(tmp_path)]) == 1


def test_preflight_and_ci_wire_lockfile_registry_gate() -> None:
    """#2668: preflight (--tier=static) and CI lint both run check_lockfile_registry.py."""
    for path in (
        "package-lock.json",
        "apps/frontend/package-lock.json",
        ".opencode/package-lock.json",
        "tools/check_lockfile_registry.py",
        "common/testing/lockfile_registry.py",
    ):
        names = {c.name for c in preflight.select_checks([path], tier="static")}
        assert "lockfile-registry" in names, f"{path} did not select lockfile-registry"

    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    lint_commands = "\n".join(
        str(step.get("run", "")) for step in workflow["jobs"]["lint"]["steps"]
    )
    assert "tools/check_lockfile_registry.py" in lint_commands
