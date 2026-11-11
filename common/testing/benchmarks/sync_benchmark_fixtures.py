#!/usr/bin/env python3
"""Sync and verify external benchmark statement fixtures."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any, Sequence

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = (
    REPO_ROOT / "common" / "testing" / "fixtures" / "benchmarks" / "manifest.yaml"
)


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    return yaml.safe_load(manifest_path.read_text(encoding="utf-8"))


def verify_fixture(fixture: dict[str, Any], root_dir: Path) -> tuple[bool, str]:
    local_path = root_dir / fixture["local_path"]
    if not local_path.exists():
        return False, f"Missing file: {fixture['local_path']}"
    expected_sha = fixture.get("sha256")
    if not expected_sha:
        return False, f"Manifest has no sha256 for {fixture['local_path']}"
    content = local_path.read_bytes()
    actual_sha = compute_sha256(content)
    if actual_sha != expected_sha:
        return False, f"SHA-256 mismatch: expected {expected_sha}, got {actual_sha}"
    return True, f"OK ({len(content):,} bytes, SHA-256 verified)"


def download_fixture(
    client: httpx.Client,
    fixture: dict[str, Any],
    root_dir: Path,
    force: bool = False,
) -> bool:
    local_path = root_dir / fixture["local_path"]
    if local_path.exists() and not force and verify_fixture(fixture, root_dir)[0]:
        return True
    expected_sha = fixture.get("sha256")
    if not expected_sha:
        print(f"Manifest has no sha256 for {fixture['local_path']}.")
        return False
    if fixture.get("source_platform") == "local_generator":
        return verify_fixture(fixture, root_dir)[0]
    local_path.parent.mkdir(parents=True, exist_ok=True)
    resp = client.get(fixture["download_url"])
    if resp.status_code != 200 or compute_sha256(resp.content) != expected_sha:
        return False
    local_path.write_bytes(resp.content)
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args(argv)

    fixtures = load_manifest(args.manifest).get("fixtures", [])
    if args.clean:
        for f in fixtures:
            if f.get("source_platform") != "local_generator":
                (REPO_ROOT / f["local_path"]).unlink(missing_ok=True)
        return 0
    if args.verify:
        return 0 if all(verify_fixture(f, REPO_ROOT)[0] for f in fixtures) else 1

    headers = {"User-Agent": "Mozilla/5.0 (finance-report-benchmark-sync/1.0)"}
    with httpx.Client(follow_redirects=True, timeout=180.0, headers=headers) as client:
        ok = all(
            download_fixture(client, f, REPO_ROOT, force=args.force) for f in fixtures
        )
    return 0 if ok and all(verify_fixture(f, REPO_ROOT)[0] for f in fixtures) else 1


if __name__ == "__main__":
    raise SystemExit(main())
